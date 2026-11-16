import re

from app.services.equipment_validation import PATTERNS, audit_equipment, equipment_usage_evidence, normalize_equipment
from app.services.preparation_validation import declared_time_check, audit_preparation
from app.services.required_ingredients import missing_required_ingredients
from app.services.storage_guidance import extract_storage_guidance
from app.services.verified_catalog import simple_catalog_intent, _matches_catalog_labels
from app.core.config import settings


SUPPORTED_CONSTRAINTS = {
    "time_max_minutes", "time_limit_exclusive", "meal_suitability",
    "dietary_restrictions", "ingredients_must_use", "ingredients_available",
    "max_ingredients", "min_ingredients", "equipment_required",
    "avoid_red_meat", "leftover_friendly",
}
SUPPORTED_NUTRITIONAL_GOALS = {"high protein", "protein", "healthy", "nutrient-dense", "balanced"}
PROTEIN_EVIDENCE_PATTERN = re.compile(
    r"\b(?:chicken|turkey|duck|fish|salmon|tuna|cod|tilapia|halibut|trout|shrimp|prawns?|eggs?|"
    r"greek yogurt|yogurt|cottage cheese|tofu|tempeh|edamame|beans?|chickpeas?|garbanzo|lentils?|peas|quinoa)\b",
    re.I,
)
RED_MEAT_PATTERN = re.compile(
    r"\b(?:beef|pork|lamb|mutton|veal|venison|goat meat|bison|red meat|bacon|ham|sausage|salami|pepperoni|prosciutto|chorizo|hot dogs?)\b",
    re.I,
)


def active_fields(values):
    return {key: value for key, value in values.items() if value is not None and value is not False
            and value not in ("", [], {})}


def supports_local_matching(intent):
    if not settings.RECIPE_RUNTIME_EVIDENCE:
        return False
    if intent.get("query_type") != "recipe_search" or intent.get("budget_request") or intent.get("adaptation_request"):
        return False
    coverage = intent.get("requirement_coverage")
    canonical = simple_catalog_intent(intent.get("resolved_query", ""))
    if not (isinstance(coverage, dict) and coverage.get("complete") is True
            and coverage.get("unresolved") == []) and canonical != intent:
        return False
    constraints = active_fields(intent.get("constraints", {}))
    preferences = active_fields(intent.get("preferences", {}))
    if (set(constraints) - SUPPORTED_CONSTRAINTS or set(preferences) - {"meal_types", "nutritional_goals"}
            or active_fields(intent.get("cancer_patient_specific", {}))
            or intent.get("search_strategy", {}).get("must_match_criteria")):
        return False
    diets = constraints.get("dietary_restrictions", [])
    meals = preferences.get("meal_types", [])
    goals = preferences.get("nutritional_goals", [])
    if (not isinstance(diets, list) or not all(isinstance(value, str) for value in diets)
            or not {value.lower() for value in diets} <= {"vegetarian", "vegan", "avoid red meat"}
            or not isinstance(meals, list) or not all(isinstance(value, str) for value in meals)
            or not set(meals) <= {"breakfast", "lunch", "dinner"}
            or not isinstance(goals, list) or not all(isinstance(value, str) for value in goals)
            or not {value.lower() for value in goals} <= SUPPORTED_NUTRITIONAL_GOALS
            or constraints.get("meal_suitability") not in {None, "meal"}
            or constraints.get("time_limit_exclusive", False) not in (True, False)
            or constraints.get("avoid_red_meat", False) not in (True, False)
            or constraints.get("leftover_friendly", False) not in (True, False)):
        return False
    for field in ("time_max_minutes", "max_ingredients", "min_ingredients"):
        value = constraints.get(field)
        if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value <= 0):
            return False
    if (constraints.get("min_ingredients") is not None and constraints.get("max_ingredients") is not None
            and constraints["min_ingredients"] > constraints["max_ingredients"]):
        return False
    equipment = constraints.get("equipment_required", [])
    if (not isinstance(equipment, list) or not all(isinstance(item, str) and item.strip() for item in equipment)
            or not set(normalize_equipment(equipment)) <= set(PATTERNS)):
        return False
    for field in ("ingredients_must_use", "ingredients_available"):
        items = constraints.get(field, [])
        if not isinstance(items, list) or not all(isinstance(item, str) and item.strip() for item in items):
            return False
    return True


def assess_local_recipe(recipe, intent):
    if not supports_local_matching(intent):
        return {"status": "unknown", "evidence": "Requirements need semantic or safety review."}
    if (not recipe.get("database_record_found") or recipe.get("source_name") not in {"ACS", "AICR", "AHA"}
            or any(recipe.get(field) for field in ("generated_by_llm", "ingredients_generated",
                                                  "instructions_generated", "guidance_generated", "dynamically_adapted"))
            or any(not isinstance(recipe.get(field), list) or not recipe[field]
                   or not all(isinstance(line, str) and line.strip() for line in recipe[field])
                   for field in ("ingredients", "instructions"))):
        return {"status": "unknown", "evidence": "Complete, unmodified source recipe required."}
    constraints = intent.get("constraints", {})
    preferences = intent.get("preferences", {})
    evidence = []
    timing = None
    if constraints.get("time_max_minutes") is not None:
        timing = declared_time_check(recipe)
        if not timing:
            return {"status": "unknown", "evidence": "No source-listed total preparation time."}
        if audit_preparation(recipe, constraints, {"time_check": timing}):
            return {"status": "fail", "evidence": "Source total time conflicts with the requested limit."}
        evidence.append(f"Source total time: {timing['total_minutes']} minutes")
    ingredient_count = len(recipe["ingredients"])
    if constraints.get("max_ingredients") is not None:
        if ingredient_count > constraints["max_ingredients"]:
            return {"status": "fail", "evidence": f"Recipe has {ingredient_count} ingredients, exceeding maximum {constraints['max_ingredients']}."}
        evidence.append(f"Ingredient count: {ingredient_count} (within max {constraints['max_ingredients']})")
    if constraints.get("min_ingredients") is not None:
        if ingredient_count < constraints["min_ingredients"]:
            return {"status": "fail", "evidence": f"Recipe has {ingredient_count} ingredients, below minimum {constraints['min_ingredients']}."}
        evidence.append(f"Ingredient count: {ingredient_count} (meets min {constraints['min_ingredients']})")
    diets = [str(d).lower() for d in constraints.get("dietary_restrictions", []) if isinstance(d, str)]
    if constraints.get("avoid_red_meat") or "avoid red meat" in diets:
        if RED_MEAT_PATTERN.search(" ".join(recipe["ingredients"] + recipe["instructions"])):
            return {"status": "fail", "evidence": "Recipe contains red or processed meat."}
        evidence.append("No red or processed meat in ingredients or instructions")
    if constraints.get("equipment_required"):
        eq_problems = audit_equipment(recipe, constraints)
        if eq_problems:
            return {"status": "fail", "evidence": "; ".join(eq_problems)}
        eq_evidence = equipment_usage_evidence(recipe, constraints["equipment_required"])
        evidence.append("Equipment preparation evidence: " + "; ".join(
            f"{name}: {item['quote']}" for name, item in eq_evidence.items()
        ))
    if constraints.get("leftover_friendly"):
        storage_text = "\n".join(str(recipe.get(field) or "") for field in (
            "content", "storage_evidence", "storage_instructions", "source_notes",
        ))
        storage = extract_storage_guidance(storage_text)
        if not storage:
            return {"status": "unknown", "evidence": "No source-listed leftover storage guidance."}
        evidence.append(f"Source storage guidance: {storage}")
    meals = preferences.get("meal_types", [])
    catalog_diets = [d for d in diets if d in {"vegetarian", "vegan"}]
    if constraints.get("meal_suitability") == "meal" and not meals:
        meals = ["lunch"]
    for diet in catalog_diets or [None]:
        for meal in meals or [None]:
            if not _matches_catalog_labels(recipe, diet, meal):
                return {"status": "unknown", "evidence": "Source labels do not establish the requested diet or meal."}
    if catalog_diets or meals:
        evidence.append(f"Source category: {recipe.get('type', '')}; dietary ingredient checks applied")
    if preferences.get("nutritional_goals"):
        if not PROTEIN_EVIDENCE_PATTERN.search(" ".join(recipe["ingredients"])):
            return {"status": "fail", "evidence": "Recipe does not include a primary protein source for nutritional goal."}
        evidence.append("Includes primary protein source supporting nutritional goal")
    missing = missing_required_ingredients(recipe, constraints.get("ingredients_must_use", []))
    if missing:
        return {"status": "fail", "evidence": "Missing required ingredients: " + ", ".join(missing)}
    available = constraints.get("ingredients_available", [])
    if available and not constraints.get("ingredients_must_use"):
        if all(missing_required_ingredients(recipe, [item]) for item in available):
            return {"status": "fail", "evidence": "Recipe does not use any of the available ingredients."}
        evidence.append("Uses requested available ingredient option")
    evidence.append("Complete source ingredients and instructions; all supported requirements checked")
    return {"status": "pass", "evidence": "; ".join(evidence), "time_check": timing}
