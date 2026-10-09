import re
from copy import deepcopy
from typing import Any, Dict, List, Optional


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


def resolve_simplification(query: str, history: List[Dict[str, Any]]) -> Optional[List[Dict[str, Any]]]:
    text = query.lower().replace("’", "'")
    if re.search(
        r"\b(?:don't|do not|never)\s+(?:simplify|make|adapt|change)\b|\b(?:why|explain|explanation|wording|summary)\b|"
        r"\beasier to (?:read|understand)\b", text,
    ):
        return None
    if not re.search(
        r"\bsimplify\b|\b(?:make|adapt|change)\b[^.!?]{0,140}\b(?:simpler|easier|fewer (?:ingredients|steps))\b|"
        r"\b(?:simpler|easier|simplified) version\b", text,
    ):
        return None
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
    ordinal = re.search(r"\b(first|second|third|last|1st|2nd|3rd) (?:one|recipe|meal)\b", text)
    if ordinal:
        position = {"first": 0, "second": 1, "third": 2, "last": -1, "1st": 0, "2nd": 1, "3rd": 2}[ordinal[1]]
        return [recent[position]] if recent and position < len(recent) else []
    if re.search(r"\b(?:them|these|those|both|all (?:of )?(?:the )?recipes)\b", text):
        return recent[:3]
    if re.search(r"\b(?:it|this|that)(?: recipe| meal| one)?\b|\bthe recipe\b", text):
        return recent if len(recent) == 1 else []
    return None


def simplification_intent(query: str, references: List[Dict[str, Any]], intent: Dict[str, Any]) -> Dict[str, Any]:
    intent = deepcopy(intent)
    intent["context_action"] = "continue_request"
    intent["referenced_recipe_ids"] = [recipe["recipe_id"] for recipe in references]
    if not references:
        intent["query_type"] = "clarification"
        intent["clarification_question"] = "Which recipe would you like me to simplify? Please use its name or position in the last recipe list."
        return intent
    intent["query_type"] = "recipe_adaptation"
    intent["adaptation_request"] = {
        "operation": "simplify",
        "request": query,
        "references": [{key: recipe.get(key) for key in ("recipe_id", "name", "ingredients", "instructions")}
                       for recipe in references],
    }
    resolved = query + " Selected recipe: " + "; ".join(recipe["name"] for recipe in references)
    intent["resolved_query"] = resolved
    intent.setdefault("search_strategy", {})["enhanced_query"] = resolved
    return intent


def unchanged_simplification(recipe: Dict[str, Any], intent: Dict[str, Any]) -> bool:
    request = intent.get("adaptation_request", {})
    if request.get("operation") != "simplify":
        return False

    def content(record, field):
        lines = [re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", str(line)) for line in record.get(field, [])]
        return re.sub(r"[^\w]+", " ", " ".join(lines).lower()).strip()

    return any(
        all(content(recipe, field) == content(reference, field) for field in ("ingredients", "instructions"))
        for reference in request.get("references", [])
    )
