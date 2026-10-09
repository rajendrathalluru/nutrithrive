import re
from typing import Any, Dict, List, Tuple


FOLLOW_UP = re.compile(
    r"^(?:and|also|but)\b|\b(?:more|another|other|similar) (?:recipes?|meals?|options?|ones?)\b|"
    r"\b(?:what else|follow[- ]?up|same (?:requirements?|restrictions?|ingredients?|recipes?|meals?))\b|"
    r"\b(?:those|these|that|this|previous|above) (?:ingredients?|foods?|recipes?|meals?|ones?|options?)\b|"
    r"\b(?:with|using|use) (?:those|these|them)\b|"
    r"\bversions? of (?:these|those|it|them)\b|"
    r"\b(?:make|change|adapt|modify|freeze|reheat|store) (?:it|them|that|this)\b|"
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


def starts_new_request(query: str) -> bool:
    return bool(RESET.search(query) or (DISCOVERY.search(query) and not FOLLOW_UP.search(query)))


def scope_recipe_history(query: str, history: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], bool]:
    if starts_new_request(query):
        return [], True
    start = 0
    latest_user = None
    for index, message in enumerate(history):
        if message.get("role") == "user":
            latest_user = index
            if starts_new_request(message.get("content", "")):
                start = index
        elif message.get("role") == "assistant" and message.get("context_action") == "new_request":
            if latest_user is not None:
                start = latest_user
    return history[start:], False
