import re
from typing import Any, Dict, List


PRODUCE = re.compile(
    r"\b(?:carrots?|celery|onions?|scallions?|garlic|bell peppers?|jalape[nñ]os?|"
    r"tomatoes|tomato|spinach|kale|cucumbers?|zucchini|broccoli|cauliflower|"
    r"lettuce|avocados?|mushrooms?|cilantro|parsley|berries|strawberries|"
    r"blueberries|lemons?|limes?)\b"
)
REFRIGERATED = re.compile(
    r"\b(?:chicken|turkey|beef|pork|fish|salmon|tuna|shrimp|eggs?|tofu|"
    r"yogurt|yoghurt|cheese|milk|cream|butter)\b"
)
AMBIGUOUS_FORM = re.compile(r"\b(?:corn|peas|broth|stock|juice)\b")
PANTRY_FORM = re.compile(
    r"\b(?:canned|cans?|tinned|dried|dry|dehydrated|powder(?:ed)?|granulated|"
    r"shelf[ -]stable|aseptic|uht|bouillon)\b"
)
NON_PANTRY_FORM = re.compile(r"\b(?:fresh|frozen|refrigerated|raw)\b")
OPTIONAL = re.compile(r"\b(?:optional|if desired|if using|if you (?:wish|like))\b")
CANNED_FORM = re.compile(r"\b(?:canned|cans?|tinned|tins?)\b", re.I)


def explicit_canned_requirement(query: str) -> str | None:
    text = query.lower().replace("’", "'")
    if re.search(r"\b(?:remove|drop) (?:the )?canned[- ]only (?:requirement|restriction)\b|"
                 r"\b(?:don't|do not|no longer) (?:need|require|want) (?:only canned|canned[- ]only)\b|"
                 r"\b(?:fresh|non-canned|other) ingredients (?:are )?(?:fine|allowed|okay|ok)\b", text):
        return "unrestricted"
    if re.search(r"\b(?:only|exclusively)\s+(?:(?:use|using|with)\s+)?(?:canned|tinned) (?:ingredients|foods?)\b|"
                 r"\b(?:canned|tinned) (?:ingredients|foods?) (?:only|exclusively)\b|\bcanned[- ]only\b", text):
        return "canned_only"
    return None


def explicit_ingredient_storage(query: str) -> str | None:
    canned = explicit_canned_requirement(query)
    if canned:
        return canned
    text = query.lower()
    if re.search(r"\b(?:(?:only|all) frozen (?:foods?|ingredients?)|frozen ingredients (?:only|from start to finish))\b", text):
        return "frozen_only"
    if re.search(r"\b(?:only shelf[- ]stable|shelf[- ]stable (?:foods?|ingredients?) only|no refrigerator ingredients)\b", text):
        return "shelf_stable_only"
    if re.search(r"\b(?:pantry|shelf[- ]stable)\b", text):
        return "pantry_based"
    return None


def audit_canned_recipe(recipe: Dict[str, Any], assessment: Any) -> List[str]:
    problems = []
    if not isinstance(assessment, dict):
        assessment = {}
    for field in ("non_canned_ingredients", "unspecified_forms", "conflicting_guidance"):
        if not isinstance(assessment.get(field), list) or assessment[field]:
            problems.append(f"Canned-only assessment has missing or conflicting {field}")
    ingredients = recipe.get("ingredients", [])
    if not isinstance(ingredients, list) or not ingredients:
        return [*problems, "Missing ingredients for canned-only verification"]
    if not any(str(ingredient).strip() and not str(ingredient).strip().endswith(":") for ingredient in ingredients):
        problems.append("No food ingredients supplied for canned-only verification")
    declared_foods = " ".join(str(ingredient).lower() for ingredient in ingredients)
    for ingredient in ingredients:
        text = str(ingredient).strip()
        if text.endswith(":"):
            continue
        clauses = re.split(r";|\+|(?:,\s*|\b(?:and|or|with)\s+)(?=\d|fresh\b|frozen\b|dried\b|raw\b|salt\b|pepper\b|quinoa\b|pasta\b|rice\b)", text, flags=re.I)
        if any(not CANNED_FORM.search(clause) or NON_PANTRY_FORM.search(clause.lower())
               or re.search(r"\b(?:not|non)[- ]canned\b", clause, re.I) for clause in clauses if clause.strip()):
            problems.append(f"Ingredient is not exclusively specified in canned form: {text}")
    food_pattern = re.compile(
        r"\b(?:quinoa|pasta|rice|grains|chicken|tofu|vegetables|green salad|side salad|cilantro|parsley|lime(?: juice)?|lemon(?: juice)?|"
        r"chili powder|cumin|salt|pepper|oil|water)\b", re.I,
    )
    for field in ("instructions", "helpful_tips", "ingredient_adaptations", "source_notes", "storage_instructions"):
        value = recipe.get(field, [])
        lines = value if isinstance(value, list) else str(value or "").splitlines()
        for line in lines:
            text = str(line).lower()
            for food in food_pattern.finditer(text):
                prefix = text[max(0, food.start() - 45):food.start()]
                if food[0] == "salt" and re.search(r"\bno[- ]$", prefix) and re.match(r"[- ]added\b", text[food.end():]):
                    continue
                if re.search(r"\b(?:do not|don't|avoid|omit|skip)\s+(?:(?:add|adding|use|using|any)\s+)?$", prefix):
                    continue
                if food[0] == "water" and re.search(r"\b(?:rinse|wash)\b", text) and not re.search(r"\b(?:add|cook|boil|mix)\b", text):
                    continue
                if re.search(r"\b(?:(?:canned|tinned)\s+(?:(?:low-sodium|no-salt-added|diced|chopped|cooked)\s+){0,3}|(?:can|tin) of\s+)$", prefix):
                    continue
                if food[0] not in declared_foods or re.search(r"\b(?:fresh|frozen|raw)\s*$", prefix):
                    problems.append(f"Unverified canned form in {field}: {line}")
                    break
    return list(dict.fromkeys(problems))


def _ingredient_clauses(ingredient: str) -> List[str]:
    normalized = ingredient.lower()
    normalized = re.sub(r"\b(?:canola|corn|olive)(?:,?\s+(?:or\s+)?(?:canola|corn|olive))+\s+oil\b", "oil", normalized)
    normalized = re.sub(r"\b(?:peanut|almond|cashew|seed|nut) butter\b", "nut spread", normalized)
    normalized = re.sub(
        r"\b(?:cream of tartar|garlic salt|tomato paste|tomato sauce|corn oil|corn starch|cornstarch)\b",
        "pantry staple", normalized,
    )
    normalized = re.sub(r"\b(?:chicken|beef|fish) (broth|stock)\b", r"\1", normalized)
    clauses = []
    for fragment in re.split(r",|;|\+|\b(?:and|or)\b", normalized):
        has_food = any(pattern.search(fragment) for pattern in (PRODUCE, REFRIGERATED, AMBIGUOUS_FORM))
        previous_has_food = clauses and any(
            pattern.search(clauses[-1]) for pattern in (PRODUCE, REFRIGERATED, AMBIGUOUS_FORM)
        )
        if clauses and (not has_food or not previous_has_food or fragment.strip().startswith("with ")):
            clauses[-1] += " " + fragment
        else:
            clauses.append(fragment)
    return clauses


def audit_pantry_ingredients(recipe: Dict[str, Any], storage: str) -> Dict[str, List[str]]:
    """Catch known ingredient-form contradictions independently of model judgments."""
    findings = {
        "required_non_pantry_ingredients": [],
        "unspecified_ingredient_forms": [],
    }
    ingredients = recipe.get("ingredients", [])
    if not isinstance(ingredients, list) or not ingredients:
        findings["unspecified_ingredient_forms"].append("Missing structured ingredient list")
        return findings

    instructions = recipe.get("instructions", [])
    if isinstance(instructions, str):
        instructions = [instructions]
    for ingredient in ingredients:
        if not isinstance(ingredient, str) or not ingredient.strip():
            findings["unspecified_ingredient_forms"].append("Invalid ingredient line")
            continue
        normalized = ingredient.lower()
        for clause in _ingredient_clauses(normalized):
            produce = PRODUCE.search(clause)
            refrigerated = REFRIGERATED.search(clause)
            ambiguous = AMBIGUOUS_FORM.search(clause)
            if not (produce or refrigerated or ambiguous):
                continue
            if NON_PANTRY_FORM.search(clause):
                field = "required_non_pantry_ingredients"
            elif PANTRY_FORM.search(clause):
                continue
            elif produce or refrigerated:
                field = "required_non_pantry_ingredients"
            else:
                field = "unspecified_ingredient_forms"

            if storage == "pantry_based" and OPTIONAL.search(normalized):
                food = (produce or refrigerated or ambiguous).group()
                directions = [str(step).lower() for step in instructions if food in str(step).lower()]
                if directions and all(OPTIONAL.search(step) for step in directions):
                    continue
            if ingredient not in findings[field]:
                findings[field].append(ingredient)
    return findings
