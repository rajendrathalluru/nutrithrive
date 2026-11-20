import re
from copy import deepcopy
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field, ValidationError


SIMPLIFICATION_RULES = """For simplification, adapt the selected reference rather than finding similar recipes.
Preserve the dish's core identity and the user's explicit ingredients and restrictions. Reduce real preparation
work, equipment, or nonessential ingredients: purchased pre-cut components, omitting optional garnishes,
or removing a separate sauce-making task can help when compatible. Do not add a side dish or new complexity.
Shorter wording or merging the same actions into fewer numbered steps is NOT a simpler recipe.
The reference ingredient list is not an instruction to keep every seasoning or optional component.
Keep complete quantities and safe cooking/doneness instructions; do not shorten cooking arbitrarily.
State concrete changes in the description, supported by the new ingredients and directions.
Return only an adapted version of each selected recipe, not the original plus alternatives.
"""


ADAPTATION_RULES = """Edit only the selected recipe(s), preserving their core identity and every active user restriction.
Apply the requested change in the actual ingredients AND directions, not just a tip saying it could be changed.
Keep unaffected components unless the requested change requires replacing them. Do not return similar dishes.
For texture changes, use the user's chosen final texture and describe how preparation achieves it throughout,
including seeds, nuts, vegetables, sauces, and toppings. Adding liquid alone does not remove crunchy components.
Do not infer swallowing problems or promise a medically safe texture. Do not invent nutrition equivalence.
Explain the concrete change in the description; do not add unrelated tips, sides, or new restrictions.
"""


class RecipeConversationContext(BaseModel):
    version: Literal[1] = 1
    query_type: Literal["recipe_question", "recipe_adaptation"]
    operation: Literal["modify", "simplify", "texture", "seasoning", "question"]
    selected_recipe_ids: List[str] = Field(default_factory=list, max_length=3)
    request: str = Field(default="", max_length=8000)
    waiting_for: Optional[Literal[
        "recipe", "texture", "seasoning", "seasoning_choice", "seasoning_custom", "seasoning_profile"
    ]] = None


def parse_recipe_context(value: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(value, dict):
        return None
    try:
        return RecipeConversationContext.model_validate(value).model_dump(exclude_none=True)
    except ValidationError:
        return None


def latest_recipe_context(history: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    for message in reversed(history):
        if message.get("role") == "assistant":
            return parse_recipe_context(message.get("recipe_context"))
    return None


def _simplification_requested(query: str) -> bool:
    text = query.lower().replace("’", "'")
    if re.search(
        r"\b(?:don't|do not|never)\s+(?:simplify|make|adapt|change)\b|\b(?:why|explain|explanation|wording|summary)\b|"
        r"\beasier to (?:read|understand)\b", text,
    ):
        return False
    return bool(re.search(
        r"\bsimplify\b|\b(?:make|adapt|change)\b[^.!?]{0,140}\b(?:simpler|easier|fewer (?:ingredients|steps))\b|"
        r"\b(?:simpler|easier|simplified) version\b", text,
    ))


TEXTURE = re.compile(r"\b(?:soft(?:er)?|smooth(?:er)?|creamy|creamier|crunchy|crunchier|crispy|crispier|"
                     r"firm(?:er)?|thick(?:er)?|thin(?:ner)?|coars(?:e|er)|chewy|chewier|puree(?:d)?|purée(?:d)?)\b", re.I)
SEASONING_REQUEST = re.compile(
    r"\b(?:more|extra|add|boost|enhance|increase|change|adjust|update|switch|different|new)\b[^.!?]{0,40}"
    r"\b(?:season(?:ing|ings|ed)?|flavor(?:s|ing|ings|ful)?|flavour(?:s|ing|ings|ful)?|spic(?:e|es|ier|y)|herbs?)\b|"
    r"\b(?:season|flavor|flavour)\b[^.!?]{0,60}\b(?:it|this|that|the recipe|more|better|differently|with)\b|"
    r"^\s*(?:please\s+)?(?:more|extra|better)\s+(?:seasoning|flavor|flavour|spices|herbs)[.!?]*$",
    re.I,
)
SEASONING_PROFILE = re.compile(
    r"\b(?:"
    r"italian|mediterranean|greek|mexican|latin|tex[- ]?mex|southwest(?:ern)?|indian|curry|"
    r"asian|chinese|thai|japanese|korean|vietnamese|french|provencal|provençal|"
    r"cajun|creole|moroccan|middle eastern|lebanese|turkish|persian|caribbean|jamaican|jerk|"
    r"spanish|ethiopian|scandinavian|nordic|bbq|barbecue|lemon[- ]?herb|herbaceous|herby|"
    r"garlic|garlicky|ginger|onion|shallot|scallion|chive|leek|"
    r"basil|oregano|thyme|rosemary|parsley|cilantro|coriander|dill|mint|sage|tarragon|marjoram|bay lea(?:f|ves)|chervil|lemongrass|"
    r"cumin|paprika|turmeric|cinnamon|nutmeg|clove|cardamom|allspice|anise|fennel|fenugreek|caraway|saffron|sumac|za'?atar|"
    r"chili|chile|cayenne|jalape[nñ]o|chipotle|harissa|peppercorn|black pepper|red pepper|peppery|crushed red|"
    r"garam masala|five[- ]?spice|italian seasoning|herbes de provence|old bay|ras el hanout|berbere|taj[ií]n|taco|ranch|"
    r"lemon|lime|orange zest|citrus|vinegar|balsamic|tamari|soy sauce|miso|sesame|mustard|dijon|horseradish|caper|olive|"
    r"mild(?:er)?|gentle|subtle|bright|zesty|tangy|smok(?:y|ier)|savor(?:y|ier)|umami|warm(?:er)?|earthy|sweet(?:er)?|bold(?:er)?|spic(?:y|ier)|hot(?:ter)?|kick"
    r")\b",
    re.I,
)
SEASONING_CUSTOM_CHOICE = re.compile(
    r"\b(?:specific seasonings?|my own|enter my own|own seasonings?|custom seasonings?|in mind|i know what|type my own)\b",
    re.I,
)
SEASONING_GUIDE_CHOICE = re.compile(
    r"\b(?:help me choose|choose (?:for me|from|a flavor)|flavor profiles?|you choose|suggest(?:ions?)?|show .*profiles?|recommend)\b",
    re.I,
)
VAGUE_CONFIRMATION = re.compile(
    r"^\s*(?:yes|yeah|yep|yup|sure|ok|okay|please|yes please|sure thing|sounds good|go ahead|do it|thanks?)[.!?\s]*$",
    re.I,
)
MORE_RECIPES = re.compile(
    r"\b(?:more|another|other|similar|extra|additional) (?:recipes?|meals?|options?)\b|"
    r"\bshow (?:me )?(?:more|others?)[.!?]*$|"
    r"^what else(?:[.!?]*$| can (?:i|we) (?:make|cook|prepare|eat)\b)", re.I,
)


def _strip_recipe_names(text: str, references: List[Dict[str, Any]]) -> str:
    cleaned = text
    for recipe in references:
        name = str(recipe.get("name") or "").strip()
        if name:
            cleaned = re.sub(r"(?<!\w)" + re.escape(name) + r"(?!\w)", " ", cleaned, flags=re.I)
    return " ".join(cleaned.split())


def build_recipe_selection_follow_up(recipes: List[Dict[str, Any]], operation: str) -> Dict[str, Any]:
    choices = []
    seen = set()
    for recipe in recipes[:3]:
        name = str(recipe.get("name") or "").strip()
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        choices.append({"label": name, "instruction": name})
    if len(choices) < 2:
        return {}
    choices.append({"label": "All recipes", "instruction": "All of the recipes"})
    question = (
        "Which recipe are you asking about?"
        if operation == "question"
        else "Which recipe would you like to update?"
    )
    return {"question": question, "choices": choices}


def build_seasoning_choice_follow_up(recipe_names: str) -> Dict[str, Any]:
    target = recipe_names.strip() or "this recipe"
    return {
        "question": "How would you like to customize the seasonings?",
        "choices": [
            {
                "label": "I have specific seasonings in mind",
                "instruction": f"I have specific seasonings in mind for {target}.",
            },
            {
                "label": "Help me choose a flavor profile",
                "instruction": f"Help me choose a flavor profile for {target}.",
            },
        ],
    }


def build_seasoning_follow_up(recipe_names: str) -> Dict[str, Any]:
    target = recipe_names.strip() or "this recipe"
    return {
        "question": "Choose a flavor profile or type the herbs and spices you'd like:",
        "choices": [
            {
                "label": "Italian (basil, oregano, garlic)",
                "instruction": f"Season {target} with an Italian flavor profile using basil, oregano, garlic, and rosemary.",
            },
            {
                "label": "Mediterranean (lemon, dill, thyme)",
                "instruction": f"Season {target} with a Mediterranean flavor profile using lemon, oregano, dill, and garlic.",
            },
            {
                "label": "Mexican (cumin, lime, cilantro)",
                "instruction": f"Season {target} with a Mexican flavor profile using cumin, oregano, smoked paprika, lime, and cilantro.",
            },
            {
                "label": "Indian (turmeric, cumin, ginger)",
                "instruction": f"Season {target} with an Indian flavor profile using turmeric, cumin, coriander, ginger, and garam masala.",
            },
            {
                "label": "Asian (ginger, garlic, sesame)",
                "instruction": f"Season {target} with an Asian flavor profile using ginger, garlic, scallions, and toasted sesame.",
            },
            {
                "label": "Cajun (paprika, thyme, cayenne)",
                "instruction": f"Season {target} with a Cajun flavor profile using smoked paprika, thyme, oregano, garlic, and a pinch of cayenne.",
            },
            {
                "label": "Mild & herbaceous (parsley, chives, lemon)",
                "instruction": f"Season {target} with a mild, bright herb profile using fresh parsley, chives, thyme, and lemon zest.",
            },
        ],
    }


def is_more_recipes_request(query: str) -> bool:
    return bool(MORE_RECIPES.search(" ".join(query.split())))


def _follow_up_action(query: str) -> Optional[tuple[str, str]]:
    text = query.lower().replace("’", "'")
    if is_more_recipes_request(text):
        return None
    if _simplification_requested(query):
        return "recipe_adaptation", "simplify"
    if re.search(r"\b(?:don't|do not|never)\s+(?:change|adapt|modify|replace|swap|make)\b", text):
        return None
    if re.search(r"^(?:(?:and|also|please)[, ]+)*(?:why|how|what|which|explain|can i|could i|is it|does it|will it)\b", text):
        return "recipe_question", "question"
    if re.search(r"\bcompare\b", text):
        return "recipe_question", "question"
    if re.search(r"\b(?:change|adjust|alter)\b[^.!?]*\btexture\b", text) or (
        re.search(r"\b(?:make|adapt|change|convert)\b", text) and TEXTURE.search(text)
    ):
        return "recipe_adaptation", "texture"
    if SEASONING_REQUEST.search(text):
        return "recipe_adaptation", "seasoning"
    if re.search(r"\b(?:change|modify|adapt|replace|swap|substitute|omit|remove|halve|double|scale|convert|reduce|increase|add)\b", text):
        return "recipe_adaptation", "modify"
    if re.search(r"\buse\b[^.!?]*\binstead\b", text):
        return "recipe_adaptation", "modify"
    if re.search(r"\bmake\b[^.!?]*\b(?:vegan|vegetarian|gluten[- ]free|dairy[- ]free|nut[- ]free|"
                 r"less spicy|milder|higher (?:in )?protein|for \d+|\d+ servings)\b", text):
        return "recipe_adaptation", "modify"
    return None


def resolve_recipe_references(query: str, history: List[Dict[str, Any]], implicit: bool = False) -> Optional[List[Dict[str, Any]]]:
    text = query.lower().replace("’", "'")
    recipe_lists = [
        [recipe for recipe in message.get("recipes", []) if isinstance(recipe, dict) and recipe.get("recipe_id")]
        for message in history if message.get("role") == "assistant" and message.get("recipes")
    ]
    recent = recipe_lists[-1] if recipe_lists else []
    named = {}
    for recipes in recipe_lists:
        for recipe in recipes:
            name = str(recipe.get("name", "")).strip().lower()
            if name and re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", text):
                named[name] = recipe
    if named:
        return [recipe for name, recipe in named.items() if not any(
            name != other and name in other for other in named
        )][:3]
    ordinal_words = r"first|second|third|last|1st|2nd|3rd"
    ordinal_reply = re.fullmatch(r"\s*(?:the )?(" + ordinal_words + r")(?: one| recipe)?[.!?]?\s*", text)
    ordinals = [ordinal_reply[1]] if ordinal_reply else re.findall(
        r"\b(" + ordinal_words + r")\b(?=\s+(?:ones?|recipes?|meals?|dish(?:es)?)\b|\s+and\s+(?:the )?(?:" + ordinal_words + r")\b)", text,
    )
    if ordinals:
        positions = list(dict.fromkeys({"first": 0, "second": 1, "third": 2, "last": -1, "1st": 0, "2nd": 1, "3rd": 2}[ordinal]
                                      for ordinal in ordinals))
        return [recent[position] for position in positions] if recent and all(position < len(recent) for position in positions) else []
    context = latest_recipe_context(history)
    selection = None
    if context and context.get("selected_recipe_ids"):
        by_id = {recipe["recipe_id"]: recipe for recipes in recipe_lists for recipe in recipes}
        ids = context["selected_recipe_ids"]
        selection = [by_id[recipe_id] for recipe_id in ids] if all(recipe_id in by_id for recipe_id in ids) else []
    if re.search(r"\ball (?:of )?(?:the )?(?:recipes|them|these|those)\b|^\s*all[.!?]*$", text):
        return recent[:3]
    if re.search(r"\b(?:them|these|those|both)\b", text):
        return selection if selection is not None and len(selection) != 1 else recent[:3]
    if implicit or re.search(r"\b(?:it|its)\b|\b(?:this|that) (?:recipe|dish|meal|one)\b|\bthe recipe\b|\b(?:this|that)[?.!]*$", text):
        if selection is not None:
            return selection if len(selection) == 1 else []
        return recent if len(recent) == 1 else []
    return None


def resolve_recipe_follow_up(
    query: str, history: List[Dict[str, Any]], model_intent: Optional[Dict[str, Any]] = None
) -> Optional[Dict[str, Any]]:
    if is_more_recipes_request(query):
        return None
    action = _follow_up_action(query)
    context = latest_recipe_context(history)
    pending = context if context and context.get("waiting_for") else None
    request = query
    if pending and (not action or re.fullmatch(r"(?:the )?(?:first|second|third|last)(?: one| recipe)?[.!]?", query.strip(), re.I)):
        action = (pending["query_type"], pending["operation"])
        request = pending["request"] + " User clarification: " + query
    if not action and model_intent and model_intent.get("query_type") in {"recipe_question", "recipe_adaptation"}:
        action = (model_intent["query_type"], "question" if model_intent["query_type"] == "recipe_question" else "modify")
    if not action:
        return None
    references = resolve_recipe_references(query, history)
    descriptive_reference = re.search(r"\b(?:one|recipe|dish) (?:with|without|containing|using)\b|\bthe [\w-]+ one\b", query, re.I)
    if descriptive_reference and references is None:
        if model_intent is None:
            return None
        references = []
        by_id = {recipe["recipe_id"]: recipe for message in history for recipe in (message.get("recipes") or [])
                 if isinstance(recipe, dict) and recipe.get("recipe_id")}
        ids = model_intent.get("referenced_recipe_ids") or []
        if isinstance(ids, list) and 0 < len(ids) <= 3 and all(isinstance(recipe_id, str) and recipe_id in by_id for recipe_id in ids):
            references = [by_id[recipe_id] for recipe_id in dict.fromkeys(ids)]
    if references is None:
        implicit_edit = action[0] == "recipe_adaptation" and (
            action[1] == "seasoning"
            or bool(re.search(
                r"\b(?:simplify|replace|swap|substitute|omit|remove|halve|double|scale|reduce|increase|add)\b|"
                r"\buse\b[^.!?]*\binstead\b", query, re.I,
            ))
        )
        semantic_follow_up = model_intent and model_intent.get("context_action") != "new_request" and (
            model_intent.get("query_type") in {"recipe_question", "recipe_adaptation"}
        )
        if pending or implicit_edit or semantic_follow_up:
            references = resolve_recipe_references(query, history, implicit=any(message.get("recipes") for message in history))
    if references is None:
        return None
    query_type, operation = action
    pending_wait = pending.get("waiting_for") if pending else None
    cleaned_request = _strip_recipe_names(request, references)
    cleaned_query = _strip_recipe_names(query, references)
    waiting_for = None
    if not references:
        waiting_for = "recipe"
    elif operation == "texture" and not TEXTURE.search(cleaned_request):
        waiting_for = "texture"
    elif operation == "seasoning":
        if pending_wait == "seasoning_custom":
            if SEASONING_GUIDE_CHOICE.search(cleaned_query):
                waiting_for = "seasoning_profile"
            elif VAGUE_CONFIRMATION.fullmatch(cleaned_query.strip()) or SEASONING_CUSTOM_CHOICE.search(cleaned_query):
                waiting_for = "seasoning_custom"
            else:
                waiting_for = None
        elif SEASONING_PROFILE.search(cleaned_request):
            waiting_for = None
        elif SEASONING_CUSTOM_CHOICE.search(cleaned_query):
            waiting_for = "seasoning_custom"
        elif SEASONING_GUIDE_CHOICE.search(cleaned_query):
            waiting_for = "seasoning_profile"
        elif pending_wait in {"seasoning_profile", "seasoning"}:
            waiting_for = "seasoning_profile"
        else:
            waiting_for = "seasoning_choice"
    recent_lists = [
        [recipe for recipe in message.get("recipes", []) if isinstance(recipe, dict) and recipe.get("recipe_id")]
        for message in history if message.get("role") == "assistant" and message.get("recipes")
    ]
    recent_recipes = recent_lists[-1][:3] if recent_lists else []
    return {"query_type": query_type, "operation": operation, "request": request,
            "references": references, "recent_recipes": recent_recipes, "waiting_for": waiting_for}


def apply_recipe_follow_up(resolution: Dict[str, Any], intent: Dict[str, Any]) -> Dict[str, Any]:
    intent = deepcopy(intent)
    references = resolution["references"]
    recent_recipes = resolution.get("recent_recipes") or []
    request = resolution["request"]
    operation = resolution["operation"]
    intent["context_action"] = "continue_request"
    intent["referenced_recipe_ids"] = [recipe["recipe_id"] for recipe in references]
    intent["recipe_context"] = RecipeConversationContext(
        query_type=resolution["query_type"], operation=operation, request=request,
        selected_recipe_ids=intent["referenced_recipe_ids"], waiting_for=resolution["waiting_for"],
    ).model_dump(exclude_none=True)
    if resolution["waiting_for"]:
        intent["query_type"] = "clarification"
        intent.pop("adaptation_request", None)
        names = "; ".join(recipe["name"] for recipe in references)
        if resolution["waiting_for"] == "texture":
            intent["clarification_question"] = f"What texture would you like for {names}—softer, creamier, smoother, or firmer/crunchier? I'll adapt the same recipe."
        elif resolution["waiting_for"] == "seasoning_choice":
            intent["clarification_question"] = (
                f"Would you like to enter specific seasonings or herbs you have in mind for {names}, "
                "or would you like to choose from our classic flavor profiles?"
            )
            intent["_generated_follow_up"] = build_seasoning_choice_follow_up(names)
        elif resolution["waiting_for"] == "seasoning_custom":
            intent["clarification_question"] = (
                f"Great! Tell me which herbs, spices, or seasonings you'd like for {names} "
                "(for example: garlic and rosemary, cumin and lime, or ginger and sesame), "
                "and I'll customize the recipe for you."
            )
        elif resolution["waiting_for"] in {"seasoning_profile", "seasoning"}:
            intent["clarification_question"] = (
                f"Here are classic flavor profiles you can choose from for {names}. "
                "Pick one below—or type your own herbs and spices—and I'll customize the recipe."
            )
            intent["_generated_follow_up"] = build_seasoning_follow_up(names)
        else:
            selection_follow_up = build_recipe_selection_follow_up(recent_recipes, operation)
            if selection_follow_up:
                intent["clarification_question"] = (
                    "Which recipe are you asking about? Select one below or choose All recipes."
                    if operation == "question"
                    else "Which recipe would you like to adjust? Select one below or choose All recipes."
                )
                intent["_generated_follow_up"] = selection_follow_up
            else:
                intent["clarification_question"] = "Which recipe do you mean? Please use its name or its position in the last recipe list."
        return intent
    intent["query_type"] = resolution["query_type"]
    if resolution["query_type"] == "recipe_adaptation":
        intent["adaptation_request"] = {
            "operation": operation, "request": request,
            "references": [{key: recipe.get(key) for key in ("recipe_id", "name", "ingredients", "instructions")}
                           for recipe in references],
        }
    resolved = request + " Selected recipe: " + "; ".join(recipe["name"] for recipe in references)
    intent["resolved_query"] = resolved
    intent.setdefault("search_strategy", {})["enhanced_query"] = resolved
    return intent


def unchanged_adaptation(recipe: Dict[str, Any], intent: Dict[str, Any]) -> bool:
    request = intent.get("adaptation_request", {})
    if not request.get("references"):
        return False

    def content(record, field):
        lines = [re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", str(line)) for line in record.get(field, [])]
        return re.sub(r"[^\w]+", " ", " ".join(lines).lower()).strip()

    return any(
        all(content(recipe, field) == content(reference, field) for field in ("ingredients", "instructions"))
        for reference in request.get("references", [])
    )


def audit_texture_adaptation(recipe: Dict[str, Any], intent: Dict[str, Any]) -> List[str]:
    request = intent.get("adaptation_request", {})
    if request.get("operation") != "texture":
        return []
    target = str(request.get("request", "")).lower()
    target = re.sub(r"\b(?:not|instead of|rather than) (?:soft(?:er)?|smooth(?:er)?|pureed)\b", "", target)
    if not re.search(r"\b(?:soft(?:er)?|smooth(?:er)?|pureed|puréed)\b", target):
        return []
    instructions = [str(line).lower() for line in recipe.get("instructions", [])]
    processed = re.compile(r"\b(?:finely ground|powder(?:ed)?|paste|butter|puree[ds]?|purée[ds]?|smooth)\b")
    problems = []
    for ingredient in recipe.get("ingredients", []):
        line = str(ingredient).lower()
        components = re.findall(r"\b(?:seeds?|nuts?|almonds?|walnuts?|pecans?|peanuts?|cashews?|hazelnuts?)\b", line)
        if not components or processed.search(line) or re.search(r"\b(?:oil|milk|flour)\b", line):
            continue
        evidence = [step for step in instructions if (
            any(component in step for component in components)
            or re.search(r"\b(?:all (?:the )?ingredients|entire (?:mixture|dish))\b", step)
        ) and not re.search(r"\b(?:not|never|without|don't|do not)\b", step)]
        if not any(processed.search(step) for step in evidence):
            problems.append(f"Soft/smooth texture edit retains unprocessed nuts or seeds: {ingredient}")
    return problems
