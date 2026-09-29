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
        for clause in re.split(r",|;|\+|\b(?:and|or)\b", normalized):
            clause = re.sub(r"\b(?:peanut|almond|cashew|seed|nut) butter\b", "nut spread", clause)
            clause = re.sub(r"\b(?:cream of tartar|coconut milk|coconut cream|garlic salt)\b", "pantry staple", clause)
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
