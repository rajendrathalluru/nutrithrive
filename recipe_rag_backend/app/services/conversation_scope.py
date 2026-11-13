import re
from typing import Any, Dict, Iterable, List, Optional, Tuple
from app.services.recipe_follow_up import is_more_recipes_request, parse_recipe_context
from app.services.recipe_router import requests_composed_dinner
from app.services.budget_service import is_budget_revision


FOLLOW_UP = re.compile(
    r"^(?:and|also|but)\b|\b(?:more|another|other|similar) (?:recipes?|meals?|options?|ones?)\b|"
    r"\b(?:what else|follow[- ]?up|same (?:requirements?|restrictions?|ingredients?|recipes?|meals?))\b|"
    r"\b(?:those|these|that|this|previous|above) (?:ingredients?|foods?|recipes?|meals?|dinners?|lunch(?:es)?|breakfasts?|ones?|options?)\b|"
    r"\b(?:with|using|use) (?:those|these|them)\b|"
    r"\bversions? of (?:these|those|it|them)\b|"
    r"\b(?:make|change|adapt|modify|freeze|reheat|store) (?:it|them|that|this)\b"
    r"(?!\s+(?:don['’]?t|do not|doesn['’]?t|does not|require|needs?)\b)|"
    r"\b(?:the )?(?:first|second|third|last) (?:one|recipe|meal)\b|"
    r"\b(?:instead(?! of\b)|again|as before)\b",
    re.I,
)
RESET = re.compile(r"\b(?:start over|new (?:search|request|topic)|forget (?:the )?previous)\b", re.I)
DISCOVERY = re.compile(
    r"\b(?:what|which)\s+(?:(?:are|would be)\s+)?(?:some\s+)?(?:(?:kinds?|types?) of\s+)?"
    r"(?:foods?|recipes?|meals?|dishes?|dinners?|lunch(?:es)?|breakfasts?)\b|"
    r"\bwhat (?:can|could|should) (?:i|we) (?:make|cook|prepare|eat|assemble)\b|"
    r"\bwhat (?:is|would be) safe to (?:cook|make|prepare|eat)\b|"
    r"\b(?:show|give|find|suggest|recommend|provide|generate|list)\b[^.!?]{0,60}"
    r"\b(?:recipes?|meals?|dishes?|dinners?|lunch(?:es)?|breakfasts?|foods?)\b|"
    r"\bhelp me (?:to )?(?:prepare|make|cook|assemble)\b|"
    r"\b(?:best|simple|easy|quick) (?:breakfast|lunch|dinner|recipes?|meals?)\b|"
    r"\brecipes? (?:for|with|using)\b",
    re.I,
)


def recipe_titles_from_history(history: List[Dict[str, Any]]) -> List[str]:
    return [
        recipe["name"] for message in history if message.get("role") == "assistant"
        for recipe in (message.get("recipes") or [])
        if isinstance(recipe, dict) and isinstance(recipe.get("name"), str) and recipe["name"].strip()
    ]


def matching_recipe_title(query: str, recipe_names: Iterable[str]) -> Optional[str]:
    def normalize(value):
        return " ".join(value.casefold().split()).strip(' .!?"\'“”‘’*')

    normalized_query = normalize(query)
    return next((name for name in recipe_names if normalized_query and normalize(name) == normalized_query), None)


def starts_new_request(query: str, recipe_names: Iterable[str] = ()) -> bool:
    return bool(matching_recipe_title(query, recipe_names) or RESET.search(query)
                or (DISCOVERY.search(query) and not (FOLLOW_UP.search(query) or is_more_recipes_request(query))))


def _awaits_recipe_selection(history: List[Dict[str, Any]]) -> bool:
    if not history or history[-1].get("role") != "assistant" or history[-1].get("recipes"):
        return False
    context = parse_recipe_context(history[-1].get("recipe_context"))
    if context and context.get("waiting_for") == "recipe":
        return True
    return bool(re.match(
        r"\s*(?:please (?:tell me |specify )?)?which (?:recipe|one|of (?:these|those|the) recipes)\b",
        history[-1].get("content", ""), re.I,
    ))


def scope_recipe_history(
    query: str, history: List[Dict[str, Any]], recipe_names: Iterable[str] = (), *, semantic_current: bool = False
) -> Tuple[List[Dict[str, Any]], bool]:
    names = [*recipe_names, *recipe_titles_from_history(history)]

    def begins_task(content, previous):
        if is_budget_revision(content) and any(message.get("role") == "user" for message in previous):
            return False
        if matching_recipe_title(content, names) and _awaits_recipe_selection(previous):
            return False
        return starts_new_request(content, names)

    if begins_task(query, history) and (
        not semantic_current or not any(message.get("role") == "user" for message in history)
        or matching_recipe_title(query, names) or RESET.search(query)
        or requests_composed_dinner(query)
        or not re.match(r"^\s*(?:please\s+)?(?:can|could|would|will)\s+you\b", query, re.I)
    ):
        return [], True
    start = 0
    latest_user = None
    for index, message in enumerate(history):
        if message.get("role") == "user":
            latest_user = index
            if begins_task(message.get("content", ""), history[:index]):
                start = index
        elif message.get("role") == "assistant" and message.get("context_action") == "new_request":
            if latest_user is not None and not is_budget_revision(history[latest_user].get("content", "")):
                start = latest_user
    return history[start:], False
