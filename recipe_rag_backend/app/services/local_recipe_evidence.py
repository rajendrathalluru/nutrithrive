from app.services.preparation_validation import declared_time_check, audit_preparation
from app.services.required_ingredients import missing_required_ingredients
from app.services.verified_catalog import simple_catalog_intent, _matches_catalog_labels
from app.core.config import settings


SUPPORTED_CONSTRAINTS = {
    "time_max_minutes", "time_limit_exclusive", "meal_suitability",
    "dietary_restrictions", "ingredients_must_use",
}


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
    if (set(constraints) - SUPPORTED_CONSTRAINTS or set(preferences) - {"meal_types"}
            or active_fields(intent.get("cancer_patient_specific", {}))
            or intent.get("search_strategy", {}).get("must_match_criteria")):
        return False
    diets = constraints.get("dietary_restrictions", [])
    meals = preferences.get("meal_types", [])
    if (not isinstance(diets, list) or not all(isinstance(value, str) for value in diets)
            or not set(diets) <= {"vegetarian", "vegan"}
            or not isinstance(meals, list) or not all(isinstance(value, str) for value in meals)
            or not set(meals) <= {"breakfast", "lunch", "dinner"}
            or constraints.get("meal_suitability") not in {None, "meal"}
            or constraints.get("time_limit_exclusive", False) not in (True, False)):
        return False
    for field in ("time_max_minutes", "max_ingredients", "min_ingredients"):
        value = constraints.get(field)
        if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value <= 0):
            return False
    required = constraints.get("ingredients_must_use", [])
    return isinstance(required, list) and all(isinstance(item, str) and item.strip() for item in required)


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
    evidence = []
    timing = None
    if constraints.get("time_max_minutes") is not None:
        timing = declared_time_check(recipe)
        if not timing:
            return {"status": "unknown", "evidence": "No source-listed total preparation time."}
        if audit_preparation(recipe, constraints, {"time_check": timing}):
            return {"status": "fail", "evidence": "Source total time conflicts with the requested limit."}
        evidence.append(f"Source total time: {timing['total_minutes']} minutes")
    meals = intent.get("preferences", {}).get("meal_types", [])
    diets = constraints.get("dietary_restrictions", [])
    if constraints.get("meal_suitability") == "meal" and not meals:
        meals = ["lunch"]
    for diet in diets or [None]:
        for meal in meals or [None]:
            if not _matches_catalog_labels(recipe, diet, meal):
                return {"status": "unknown", "evidence": "Source labels do not establish the requested diet or meal."}
    if diets or meals:
        evidence.append(f"Source category: {recipe.get('type', '')}; dietary ingredient checks applied")
    missing = missing_required_ingredients(recipe, constraints.get("ingredients_must_use", []))
    if missing:
        return {"status": "fail", "evidence": "Missing required ingredients: " + ", ".join(missing)}
    evidence.append("Complete source ingredients and instructions; all supported requirements checked")
    return {"status": "pass", "evidence": "; ".join(evidence), "time_check": timing}
