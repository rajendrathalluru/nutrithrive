import re

from app.services.budget_service import apply_budget_intent, requested_servings


def requests_catalog_source(query):
    return bool(re.search(r"\b(?:database|catalog|aicr|aha|acs|source)\b", query, re.I))


def requests_composed_dinner(query):
    if apply_budget_intent({}, query).get("budget_request"):
        return False
    if requested_servings(query) is None and not re.search(
        r"\b(?:thanksgiving|christmas|holiday|celebration|party|feast|banquet)\b", query, re.I
    ):
        return False
    if requests_catalog_source(query) or re.search(r"\b(?:find|search|show)\b", query, re.I):
        return False
    if re.search(r"\b(?:this|that|those|these|same|previous|more|instead)\b|\ba\s+recipe\b", query, re.I):
        return False
    if requested_servings(query) is not None and re.search(
        r"\b(?:generate|create|invent)\s+(?:me\s+)?(?:some\s+)?recipes\b", query, re.I
    ):
        return True
    return bool(
        re.search(r"\b(?:prepare|plan|planning|make|cook|create|generate|organize)\b", query, re.I)
        and re.search(r"\b(?:dinner|menu|feast|banquet)\b", query, re.I)
        and re.search(r"\b(?:recipes|menu|thanksgiving|christmas|holiday|celebration|party|banquet|feast)\b", query, re.I)
    )
