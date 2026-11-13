import hashlib
import json
import logging
import re
import time
from copy import deepcopy
from functools import lru_cache
from pathlib import Path

from app.core.config import settings
from app.services.preparation_validation import audit_preparation, declared_time_check

logger = logging.getLogger(__name__)
CATALOG_VERSION = 1


def normalize_request_framing(query):
    text = " ".join(query.lower().strip().rstrip(".?!").split())
    text = re.sub(r"^(?:please\s+)?(?:(?:can|could|would) you\s+)?"
                  r"help me (?:to )?(?:get|find|choose|select|generate)\s+", "show ", text)
    return text


def simple_timed_intent(query):
    text = normalize_request_framing(query)
    match = re.fullmatch(
        r"(?:please )?(?:show|give)(?: me)? (?P<kind>recipes|meals|dinners|lunches|breakfasts) that take "
        r"(?:(?P<under>under|less than) )?(?P<minutes>\d{1,3}) minutes"
        r"(?P<inclusive> or less)?(?: for (?P<meal>dinner|lunch|breakfast))?", text
    )
    if not match or bool(match["under"]) == bool(match["inclusive"]):
        return None
    minutes = int(match["minutes"])
    if not 1 <= minutes <= 180:
        return None
    exclusive = bool(match["under"])
    implied_meal = {"dinners": "dinner", "lunches": "lunch", "breakfasts": "breakfast"}.get(match["kind"])
    if implied_meal and match["meal"] and implied_meal != match["meal"]:
        return None
    meal = match["meal"] or implied_meal
    kind = "recipes" if implied_meal else match["kind"]
    canonical = f"Show {kind} that take {'less than ' if exclusive else ''}{minutes} minutes"
    canonical += "" if exclusive else " or less"
    if meal:
        canonical += f" for {meal}"
    constraints = {"time_max_minutes": minutes, "time_limit_exclusive": exclusive}
    if meal or kind == "meals":
        constraints["meal_suitability"] = "meal"
    return {
        "query_type": "recipe_search", "context_action": "new_request",
        "resolved_query": canonical, "recipe_request": canonical, "user_request_context": [canonical],
        "referenced_recipe_ids": [], "constraints": constraints,
        "preferences": {"meal_types": [meal] if meal else []},
        "cancer_patient_specific": {},
        "search_strategy": {"primary_focus": canonical, "enhanced_query": canonical,
                            "search_keywords": [canonical], "must_match_criteria": []},
    }


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def simple_catalog_intent(query):
    timed = simple_timed_intent(query)
    if timed:
        return timed
    text = normalize_request_framing(query)
    match = re.fullmatch(
        r"(?:please )?(?:show|give|suggest|find|recommend)(?: me)? (?:some )?"
        r"(?P<diet>vegetarian|vegan)(?: (?P<meal>dinner|lunch|breakfast))? recipes"
        r"(?: (?P<comparison>under|within|in) (?P<minutes>[1-9]\d{0,2}) minutes(?P<inclusive> or less)?)?", text,
    )
    if not match or match["minutes"] and int(match["minutes"]) > 180:
        return None
    meal, diet = match["meal"], match["diet"]
    canonical = f"Show {diet}{' ' + meal if meal else ''} recipes"
    constraints = {"dietary_restrictions": [diet]}
    if meal:
        constraints["meal_suitability"] = "meal"
    if match["minutes"]:
        exclusive = match["comparison"] == "under" and not match["inclusive"]
        constraints.update(time_max_minutes=int(match["minutes"]), time_limit_exclusive=exclusive)
        canonical += f" {'under' if exclusive else 'within'} {match['minutes']} minutes"
    return {
        "query_type": "recipe_search", "context_action": "new_request", "resolved_query": canonical,
        "recipe_request": canonical, "user_request_context": [canonical], "referenced_recipe_ids": [],
        "constraints": constraints, "preferences": {"meal_types": [meal] if meal else []},
        "cancer_patient_specific": {},
        "search_strategy": {"primary_focus": canonical, "enhanced_query": canonical,
                            "search_keywords": [canonical], "must_match_criteria": []},
    }


def _matches_catalog_labels(recipe, diet, meal):
    labels = {label.strip() for label in re.split(r"[,|;/]", str(recipe.get("type", "")).lower())}
    if diet and diet not in labels and not (diet == "vegetarian" and "vegan" in labels):
        return False
    if meal == "breakfast" and "breakfast" not in labels:
        return False
    if meal in {"dinner", "lunch"} and not labels.intersection(
        {meal, "entree", "entrée", "main dish", "main dishes", "one-dish meal", "one-dish meals"}
    ):
        return False
    if diet:
        content = " ".join(recipe["ingredients"] + recipe["instructions"]).lower()
        if re.search(r"\b(?:beef|pork|lamb|chicken|turkey|duck|bacon|ham|sausage|fish|salmon|tuna|shrimp|"
                     r"anchov(?:y|ies)|gelatin|worcestershire|lard|oyster|parmesan|rennet)\b", content):
            return False
        if any(re.search(r"\b(?:broth|stock|bouillon)\b", line, re.I)
               and not re.search(r"\b(?:vegetable|vegetarian|vegan|mushroom)\b", line, re.I)
               for line in recipe["ingredients"]):
            return False
        if diet == "vegan" and re.search(r"\b(?:eggs?|milk|butter|cheese|cream|yogurt|honey|whey)\b", content):
            return False
    return True


@lru_cache(maxsize=1)
def policy_code_hash():
    digest = hashlib.sha256()
    for path in sorted(Path(__file__).parent.glob("*.py")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def policy_identity():
    return {"version": CATALOG_VERSION, "code": policy_code_hash(), "model": settings.LLM_MODEL,
            "temperature": settings.LLM_TEMPERATURE, "max_tokens": settings.LLM_MAX_TOKENS}


def local_catalog_matches(intent, records, build_recipe, guidelines, limit):
    expected = simple_catalog_intent(intent.get("resolved_query", ""))
    if expected is None or intent != expected:
        return []
    constraints = intent["constraints"]
    diet = next(iter(constraints.get("dietary_restrictions", [])), None)
    meal = next(iter(intent["preferences"]["meal_types"]), None)
    if constraints.get("meal_suitability") and not diet:
        return []
    matches = []
    seen = set()
    for record in records:
        recipe = build_recipe(record)
        identity = recipe.get("recipe_id")
        if (not identity or identity in seen or not recipe.get("database_record_found")
                or recipe.get("source_name") not in {"AHA", "AICR", "ACS"}
                or not recipe.get("ingredients") or not recipe.get("instructions")):
            continue
        if not _matches_catalog_labels(recipe, diet, meal):
            continue
        timing = None
        if constraints.get("time_max_minutes") is not None:
            timing = declared_time_check(recipe)
            if not timing or timing["total_minutes"] <= 0 or audit_preparation(recipe, constraints, {"time_check": timing}):
                continue
        compliance = guidelines.validate_recipe_compliance(recipe)
        if not compliance.get("overall_compliant"):
            continue
        recipe.update(
            verification_details={"passes_verification": True, "relevance": "match", "time_check": timing,
                                  "method": "catalog_label_local_checks" if diet else "catalog_declared_time_local_checks",
                                  "independent_model_review": False},
            aicr_compliance=compliance,
        )
        seen.add(identity)
        matches.append(recipe)
        if len(matches) >= limit:
            break
    return matches


def catalog_matches(intent, build_recipe, verifier, guidelines, path=None):
    expected = simple_timed_intent(intent.get("resolved_query", ""))
    if expected is None or intent != expected:
        return []
    path = Path(path or settings.RECIPE_VERIFIED_CATALOG_PATH)
    if not path.is_file():
        return []
    try:
        catalog = json.loads(path.read_text())
        age = time.time() - catalog["created_at"]
        if catalog["policy"] != policy_identity() or not 0 <= age <= settings.RECIPE_VERIFIED_CATALOG_TTL_SECONDS:
            return []
        entries = catalog["profiles"].get(fingerprint(intent), [])
        matches = []
        seen = set()
        for entry in entries:
            recipe = build_recipe(entry["name"])
            if not recipe or fingerprint(recipe) != entry["recipe_hash"] or recipe["recipe_id"] in seen:
                continue
            if not recipe.get("database_record_found") or verifier._requires_guideline_review(recipe):
                continue
            assessment = verifier._finalize_verification(deepcopy(entry["assessment"]), recipe, intent)
            if not assessment.get("passes_verification") or assessment.get("relevance") != "match":
                continue
            compliance = guidelines.validate_recipe_compliance(recipe)
            if not compliance["overall_compliant"]:
                continue
            recipe.update(verification_details=assessment, aicr_compliance=compliance)
            seen.add(recipe["recipe_id"])
            matches.append(recipe)
        logger.info("Prevalidated catalog: %s matching recipes rechecked locally", len(matches))
        return matches
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
        logger.warning("Prevalidated catalog unavailable (%s); using normal verification", type(error).__name__)
        return []
