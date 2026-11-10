import math
import re
from decimal import Decimal

from app.services.required_ingredients import ingredient_present


UNLISTED_ADDITION_ISSUE = "Unlisted food addition needs an explicit priced quantity: "
UNRESOLVED_INGREDIENT_ISSUE = "Unresolved ingredient price, form or quantity: "
BUDGET_EGG_COOKING_RULE = (
    "For egg-based batter or other egg dishes without meat or poultry, cook the center to at least 160°F (71°C) "
    "as measured with a food thermometer; browning or elapsed time alone is not an endpoint. "
    "Follow any higher applicable safety endpoint."
)


def budget_recipe_response_format(options=None):
    ingredient = {
        "type": "object",
        "properties": {
            "food": {"type": "string", "description": "Purchased food identity and form, without quantity, unit, chopping instructions or garnish labels."},
            "quantity": {"type": "number", "description": "Positive amount used in the whole recipe, before draining canned foods."},
            "unit": {"type": "string", "enum": ["g", "ml", "count"],
                     "description": "g for solids including spices and produce; ml for liquids; count only for individually sold items such as eggs."},
        },
        "required": ["food", "quantity", "unit"],
        "additionalProperties": False,
    }
    references = [item["name"] for item in options or []]
    if references:
        ingredient = {"anyOf": [
            {"type": "object", "properties": {
                "price_reference": {"type": "string", "enum": references},
                "quantity": {"type": "number", "description": "Positive quantity in the reference item's specified unit, for the whole recipe."},
            }, "required": ["price_reference", "quantity"], "additionalProperties": False},
            ingredient,
        ]}
    fields = {"culinary_basis": {"type": "string", "description":
        "Identify the requested dish/cuisine, its defining ingredients and cooking method BEFORE choosing price references. "
        "Use new foods when needed; never replace a defining ingredient with an incompatible cached food."}}
    fields.update({key: {"type": "string"} for key in (
        "name", "type", "description", "total_time", "nutrition_benefits", "storage_instructions"
    )})
    fields.update({
        "servings": {"type": "integer"},
        "calories": {"type": "number"},
        "protein_grams": {"type": "number"},
        "ingredients": {"type": "array", "items": ingredient},
        "instructions": {"type": "array", "items": {"type": "string"}},
    })
    recipe = {"type": "object", "properties": fields, "required": list(fields), "additionalProperties": False}
    return {"type": "json_schema", "json_schema": {
        "name": "budget_recipes", "strict": True,
        "schema": {"type": "object", "properties": {"recipes": {"type": "array", "items": recipe}},
                   "required": ["recipes"], "additionalProperties": False},
    }}


def normalize_budget_recipe(recipe, options=None):
    ingredients = recipe.get("ingredients")
    if not isinstance(ingredients, list) or not ingredients:
        raise ValueError("Budget recipe ingredients are missing")
    normalized = []
    for ingredient in ingredients:
        if isinstance(ingredient, str):
            normalized.append(ingredient)
            continue
        if not isinstance(ingredient, dict):
            raise ValueError("Invalid budget ingredient")
        if "price_reference" in ingredient:
            reference = next((item for item in options or [] if item["name"] == ingredient["price_reference"]), None)
            if not reference:
                raise ValueError("Unknown ingredient price reference")
            ingredient = {"food": reference["name"], "quantity": ingredient.get("quantity"), "unit": reference["unit"]}
        food, quantity, unit = (ingredient.get(key) for key in ("food", "quantity", "unit"))
        if (not isinstance(food, str) or not food.strip() or not food.strip()[0].isalpha()
                or not isinstance(quantity, (float, int)) or isinstance(quantity, bool)
                or not math.isfinite(quantity) or not 0 < quantity <= 100000 or unit not in {"g", "ml", "count"}):
            raise ValueError("Budget ingredient needs a food, positive numeric quantity and supported unit")
        normalized.append(f"{format(Decimal(str(quantity)), 'f')} {unit} {food.strip()}")
    return {**recipe, "ingredients": normalized}


def unlisted_small_additions(recipe):
    ingredients = recipe.get("ingredients") or []
    missing = set()
    pattern = re.compile(
        r"\b(?:(?:pinch|dash|drizzle|splash|handful)\s+of\s+"
        r"|(?:add|adding|use|using|pour)\s+(?:a little|some|extra|additional|more)\s+)([a-z][a-z -]*?)"
        r"(?=[,.;]|\s+(?:and|then|to|before|until|as|if)\b|$)", re.I,
    )
    for field in ("instructions", "helpful_tips", "ingredient_adaptations"):
        lines = recipe.get(field) or []
        for line in [lines] if isinstance(lines, str) else lines:
            if re.search(r"\bwith (?:a )?(?:dipping sauce|sauce|garnish|topping) of (?:your )?choice\b", str(line), re.I):
                missing.add("unspecified serving addition")
            for match in pattern.finditer(str(line)):
                clause = re.split(r"[,.;]", str(line)[:match.start()])[-1]
                if re.search(r"\b(?:no|not|never|without|avoid|omit)\b", clause, re.I):
                    continue
                food = match[1].strip().lower()
                extra = bool(re.search(r"\b(?:extra|additional|more)\b", match[0], re.I))
                if food not in {"water", "tap water"} and (extra or not ingredient_present(food, ingredients)):
                    missing.add(food)
    return sorted(missing)


def overallocated_measured_oils(recipe):
    totals = {}
    for ingredient in recipe.get("ingredients") or []:
        match = re.fullmatch(r"(\d+(?:\.\d+)?)\s+ml\s+([a-z -]*\boil)", str(ingredient).strip(), re.I)
        if match:
            food = match[2].lower()
            totals[food] = totals.get(food, Decimal(0)) + Decimal(match[1])
    steps = recipe.get("instructions") or []
    text = steps if isinstance(steps, str) else "\n".join(map(str, steps))
    overallocated = []
    for food, total in totals.items():
        uses = re.finditer(rf"\b(?:add|heat|pour|use|using)\s+(?:the\s+)?(?:remaining\s+)?"
                           rf"(\d+(?:\.\d+)?)\s+ml\s+(?:of\s+)?{re.escape(food)}\b(?!\s+(?:total|in total)\b)", text, re.I)
        if sum((Decimal(use[1]) for use in uses), Decimal(0)) > total:
            overallocated.append(f"{food} allocated above its listed {total} ml total")
    return overallocated


def budget_preparation_issues(recipe):
    pasta = r"(?:pasta|penne|spaghetti|macaroni|rotini|fusilli|linguine|fettuccine)"
    dry_pasta = rf"\b(?:dry|uncooked)\b[^.;]{{0,48}}\b{pasta}\b"
    ingredients = recipe.get("ingredients") or []
    steps = recipe.get("instructions") or []
    if isinstance(steps, str):
        steps = [steps]
    if not any(re.search(dry_pasta, line, re.I) for line in ingredients if isinstance(line, str)):
        return []
    text = " ".join([str(recipe.get("name", "")), *map(str, steps)])
    if re.search(r"\b(?:batter|pancakes?|fritters?)\b", text, re.I) and any(
        re.search(rf"\b(?:add|fold|stir|mix|combine)\b[^.;]{{0,100}}{dry_pasta}", str(step), re.I)
        for step in steps
    ):
        return ["Do not add dry pasta directly to pancake or fritter batter. Use suitable flour for batter, or cook pasta separately before using it in a dish designed for cooked pasta."]
    return []
