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
    operation: Literal["modify", "simplify", "texture", "question"]
    selected_recipe_ids: List[str] = Field(default_factory=list, max_length=3)
    request: str = Field(default="", max_length=8000)
    waiting_for: Optional[Literal["recipe", "texture"]] = None


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
MORE_RECIPES = re.compile(
    r"\b(?:more|another|other|similar) (?:recipes?|meals?|options?)\b|"
    r"\bshow (?:me )?(?:more|others?)[.!?]*$|"
    r"^what else(?:[.!?]*$| can (?:i|we) (?:make|cook|prepare|eat)\b)", re.I,
)


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
    if re.search(r"\ball (?:of )?(?:the )?recipes\b", text):
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
        implicit_edit = action[0] == "recipe_adaptation" and bool(re.search(
            r"\b(?:simplify|replace|swap|substitute|omit|remove|halve|double|scale|reduce|increase|add)\b|"
            r"\buse\b[^.!?]*\binstead\b", query, re.I,
        ))
        semantic_follow_up = model_intent and model_intent.get("context_action") != "new_request" and (
            model_intent.get("query_type") in {"recipe_question", "recipe_adaptation"}
        )
        if pending or implicit_edit or semantic_follow_up:
            references = resolve_recipe_references(query, history, implicit=any(message.get("recipes") for message in history))
    if references is None:
        return None
    query_type, operation = action
    waiting_for = "recipe" if not references else "texture" if operation == "texture" and not TEXTURE.search(request) else None
    return {"query_type": query_type, "operation": operation, "request": request,
            "references": references, "waiting_for": waiting_for}


def apply_recipe_follow_up(resolution: Dict[str, Any], intent: Dict[str, Any]) -> Dict[str, Any]:
    intent = deepcopy(intent)
    references = resolution["references"]
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
        if resolution["waiting_for"] == "texture":
            names = "; ".join(recipe["name"] for recipe in references)
            intent["clarification_question"] = f"What texture would you like for {names}—softer, creamier, smoother, or firmer/crunchier? I'll adapt the same recipe."
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
