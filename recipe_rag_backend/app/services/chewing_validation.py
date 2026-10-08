import re
from typing import Any, Dict, List, Optional


FIRM_COMPONENTS = re.compile(
    r"\b(?:nuts?|walnuts?|almonds?|peanuts?|cashews?|pecans?|seeds?|raisins?|"
    r"dried (?:fruit|cranberries|apricots?)|shrimp|prawns?|pineapple|water chestnuts?|"
    r"lettuce|celery|granola)\b"
)
SOFTEN_COMPONENTS = re.compile(
    r"\b(?:oats?|bran flakes|broccoli|snap peas|bell pepper|mushrooms?|carrots?|"
    r"zucchini|onions?|tomatoes|tomato|chicken|turkey|meatballs?)\b"
)
SMOOTH_PREPARATION = re.compile(r"\b(?:puree[ds]?|purée[ds]?|pureeing|puréeing|smooth|finely ground|powder(?:ed)?)\b")
SOFT_PREPARATION = re.compile(r"\b(?:soft|softened|mushy|mashed|mashable|porridge)\b")
NEGATED_PREPARATION = re.compile(r"\b(?:not|never|don't|do not|without|avoid)\b")


def explicit_chewing_requirement(query: str) -> Optional[str]:
    normalized = query.lower().replace("’", "'")
    if re.search(
        r"\b(?:no longer|don't|do not) (?:need|want|require) (?:soft|easy[- ]to[- ]chew|low[- ]chewing)\b"
        r"|\b(?:normal|regular) textures? (?:is|are) (?:fine|okay|ok)\b"
        r"|\b(?:no|don't have|do not have) (?:trouble|difficulty|problems?) (?:with )?chewing\b"
        r"|\bno chewing (?:problems?|difficulties)\b",
        normalized,
    ):
        return "unrestricted"
    if re.search(
        r"\b(?:little|less|minimal|low|no) (?:effort (?:for|when) )?chewing\b"
        r"|\b(?:don'?t|do not|doesn'?t|does not|without) (?:require |need |much |a lot of )*chewing\b"
        r"|\b(?:easy|easier)[ -]to[ -]chew\b"
        r"|\b(?:trouble|difficulty) (?:with )?chewing\b"
        r"|\b(?:soft|soft[- ]textured) (?:foods?|meals?|recipes?|diet)\b",
        normalized,
    ):
        return "low"
    return None


def _grounded_evidence(evidence: Any, recipe: Dict[str, Any], fields: set) -> List[str]:
    if not isinstance(evidence, list) or not evidence:
        return []
    lines = []
    for citation in evidence:
        if not isinstance(citation, dict) or citation.get("field") not in fields:
            return []
        values = recipe.get(citation["field"])
        index = citation.get("index")
        quote = citation.get("quote")
        if (
            not isinstance(values, list) or type(index) is not int or not 0 <= index < len(values)
            or not isinstance(values[index], str) or not isinstance(quote, str) or not quote.strip()
            or quote not in values[index]
        ):
            return []
        lines.append(values[index])
    return lines


def _component_conflict(ingredient: str, evidence: List[str]) -> bool:
    normalized = ingredient.lower()
    normalized = re.sub(
        r"\b(?:almond|peanut|cashew|walnut|sunflower seed|sesame seed|coconut) "
        r"(?:milk|flour|powder|butter|oil)\b", "soft ingredient", normalized,
    )
    normalized = re.sub(r"\b(?:chicken|turkey) (?:broth|stock)\b", "broth", normalized)
    firm = list(FIRM_COMPONENTS.finditer(normalized))
    soften = list(SOFTEN_COMPONENTS.finditer(normalized))
    for match in firm + soften:
        preparation = SMOOTH_PREPARATION if match in firm else re.compile(
            f"{SMOOTH_PREPARATION.pattern}|{SOFT_PREPARATION.pattern}"
        )
        supported = False
        for line in [normalized, *[value.lower() for value in evidence]]:
            if NEGATED_PREPARATION.search(line):
                continue
            component_named = match.group() in line
            collective = re.search(r"\b(?:all (?:the )?ingredients|entire (?:mixture|soup)|soup|mixture)\b", line)
            vegetables = not firm and re.search(r"\b(?:all (?:the )?)?vegetables\b", line)
            if (component_named or collective or vegetables) and preparation.search(line):
                supported = True
                break
        if not supported:
            return True
    return False


def audit_chewing_assessment(recipe: Dict[str, Any], assessment: Any) -> List[str]:
    """Require grounded component evidence, plus bounded checks for common texture conflicts."""
    if not isinstance(assessment, dict):
        return ["Missing low-chewing texture assessment"]
    problems = []
    ingredients = recipe.get("ingredients")
    if not isinstance(ingredients, list) or not ingredients:
        return ["Missing ingredients for low-chewing verification"]
    serving = _grounded_evidence(assessment.get("serving_evidence"), recipe, {"instructions"})
    if not serving:
        problems.append("Missing grounded finished-texture preparation evidence")
    conflicts = assessment.get("conflicting_guidance")
    if not isinstance(conflicts, list):
        problems.append("Missing low-chewing guidance assessment")
    elif conflicts:
        problems.extend(f"Conflicting low-chewing guidance: {value}" for value in conflicts)
    components = assessment.get("components")
    if not isinstance(components, list):
        return [*problems, "Missing per-ingredient texture assessments"]
    indexed = {}
    for component in components:
        index = component.get("ingredient_index") if isinstance(component, dict) else None
        if type(index) is not int or not 0 <= index < len(ingredients) or index in indexed:
            problems.append("Invalid or duplicate ingredient texture assessment")
            continue
        indexed[index] = component
    for index, ingredient in enumerate(ingredients):
        component = indexed.get(index, {})
        evidence = _grounded_evidence(component.get("evidence"), recipe, {"ingredients", "instructions"})
        if not isinstance(ingredient, str) or not ingredient.strip():
            problems.append(f"Invalid ingredient at index {index}")
        elif component.get("status") != "pass" or not evidence:
            problems.append(f"Unverified low-chewing component: {ingredient}")
        elif any(
            citation["field"] == "ingredients" and citation["index"] != index
            for citation in component["evidence"]
        ):
            problems.append(f"Texture evidence cites a different ingredient: {ingredient}")
        elif _component_conflict(ingredient, evidence):
            problems.append(f"No sufficient softening or smoothing preparation for: {ingredient}")
    for field in ("instructions", "helpful_tips", "ingredient_adaptations"):
        values = recipe.get(field, [])
        if isinstance(values, str):
            values = [values]
        for value in values or []:
            line = str(value).lower()
            if NEGATED_PREPARATION.search(line):
                continue
            crunchy = re.search(r"\b(?:crunchy|crispy|crisp[- ]tender|crunch)\b", line)
            actions = r"\b(?:top|garnish|sprinkle)\b" if field == "instructions" else r"\b(?:top|garnish|sprinkle|add|mix in)\b"
            topping = re.search(actions, line) and FIRM_COMPONENTS.search(line)
            if crunchy or (topping and not SMOOTH_PREPARATION.search(line)):
                problems.append(f"Potential chewing conflict in {field}: {value}")
    return list(dict.fromkeys(problems))
