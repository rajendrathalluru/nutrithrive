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
