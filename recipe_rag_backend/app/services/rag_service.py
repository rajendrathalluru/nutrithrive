import logging
import math
import time
import re
import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from typing import List, Dict, Any, Optional

from app.core.config import settings
from app.services.data_loader import DataLoader
from app.services.aicr_guidelines_service import aicr_service
from app.services.intent_analyzer import IntentAnalyzer
from app.services.recipe_verifier import RecipeVerifier
from app.services.recipe_enhancer import RecipeEnhancer
from app.services.search_engine import SearchEngine
from app.services.response_generator import ResponseGenerator
from app.services.safety_service import safety_service
from app.services.conversation_scope import scope_recipe_history, matching_recipe_title
from app.services.equipment_validation import audit_equipment, equipment_usage_evidence
from app.services.digestive_comfort import audit_digestive_comfort, digestive_tolerance_cautions
from app.services.preparation_validation import audit_preparation_effort, time_candidate_rank
from app.services.recipe_follow_up import resolve_recipe_follow_up, is_more_recipes_request
from app.services.local_recipe_evidence import supports_local_matching, assess_local_recipe
from app.services.required_ingredients import missing_required_ingredients
from app.services.model_errors import RecipeModelUnavailable
from app.services.model_latency import ModelBudgetExhausted, model_deadline, final_review_limit, final_review_window
from openai.error import Timeout
from app.services.budget_service import budget_service, budget_clarification, budget_no_results, is_budget_clarification_reply
from app.services.budget_recipe_contract import UNLISTED_ADDITION_ISSUE, UNRESOLVED_INGREDIENT_ISSUE
from app.services.budget_service import declared_recipe_servings, requested_servings
from app.services.recipe_progress import report_progress, RecipeRequestCancelled
from app.services.verified_catalog import catalog_matches, local_catalog_matches, simple_timed_intent
from app.services.recipe_router import requests_catalog_source, requests_composed_dinner
from app.services.single_pass_generation import check_generated_recipe, generate_once

logger = logging.getLogger(__name__)
STREET_ADDRESS_DISCLOSURE = re.compile(
    r"\b(?:liv(?:e|ing)\s+(?:at|near|around|by)|(?:my|home|street) address\s*(?:is\b|:))\s*(?:the\s+)?\d+\b"
    r"|\b\d{1,6}\s+(?:[a-z][a-z'.-]*\s+){1,5}(?:street|st|avenue|ave|road|rd|boulevard|blvd|lane|ln|drive|dr|court|ct)\b"
    r"|\b\d{1,6}\s+(?:[nsew]\.?|north|south|east|west)\s+[a-z][a-z'-]+\b", re.I,
)
LABELED_ZIP = re.compile(r"\b(?:zip(?:\s+code)?|pin\s*code|postal\s+code)\s*(?:is\s+|[:=]\s*)?\d{5}\b(?!-\d)", re.I)
PERSONAL_LOCATION_DISCLOSURE = re.compile(
    r"\b(?:i\s+(?:am|live|reside|stay)|i['’]m|we\s+(?:are|live)|we['’]re)"
    r"\s+(?:(?:currently|living|located|based|staying)\s+)*"
    r"(?:near(?:\s+to)?|in|around|outside)\s+"
    r"(?!the\s+(?:kitchen|middle)\b|(?:need|pain|a\s+hurry|a\s+rush|town)\b)[a-z][\w'-]*",
    re.I,
)
MAX_RECIPES_PER_RESPONSE = 3
RED_MEAT_TERMS = re.compile(
    r"\b(?:beef|pork|lamb|mutton|veal|venison|goat meat|bison|red meat|bacon|ham|sausage|salami|pepperoni|prosciutto|chorizo|hot dogs?)\b",
    re.I,
)


def _requests_red_meat(query: str) -> bool:
    positive = re.sub(
        r"\b(?:without|avoid|no|instead of|rather than)\s+(?:any\s+)?"
        + RED_MEAT_TERMS.pattern + r"(?:\s*(?:,|and\b|or\b)\s*" + RED_MEAT_TERMS.pattern + r")*",
        "", query, flags=re.I,
    )
    return bool(RED_MEAT_TERMS.search(positive)
                and re.search(r"\b(?:recipes?|cook|prepare|meals?|dinner|lunch|breakfast)\b", query, re.I))


def _generated_red_meat_conflict(recipe):
    return bool(recipe.get("generated_by_llm") and any(
        RED_MEAT_TERMS.search(str(recipe.get(field) or ""))
        for field in ("name", "ingredients", "instructions", "helpful_tips", "ingredient_adaptations")
    ))


RED_MEAT_ALTERNATIVE_NOTE = (
    "Thrivewell offers alternatives to red and processed meat. Beef and pork are red meat. "
    "AICR recommends limiting red meat and eating little, if any, processed meat for cancer prevention. "
    "Beans, lentils, tofu, fish, or unprocessed poultry can be alternatives, depending on your dietary needs."
)
RED_MEAT_ALTERNATIVE_OFFER = (
    RED_MEAT_ALTERNATIVE_NOTE
    + "\n\nWould you like me to generate alternatives that keep your other requirements? "
    "Reply “yes,” or choose beans, lentils, tofu, fish, or poultry."
)

class RecipeRAGService:
    def __init__(self):
        self.embeddings = None
        self.llm = None
        self.vector_store = None
        self.data_loader = DataLoader()
        self.is_initialized = False
        self.initialization_error = None
        self._initialization_lock = threading.Lock()
        
        # Initialize modular services
        self.intent_analyzer = IntentAnalyzer()
        self.recipe_verifier = RecipeVerifier()
        self.recipe_enhancer = RecipeEnhancer()
        self.search_engine = SearchEngine()
        self.response_generator = ResponseGenerator()

    def _normalize_recipe_name(self, recipe_name: str) -> str:
        return " ".join(str(recipe_name).strip().lower().split())

    def _ensure_recipe_id(self, recipe: Dict[str, Any]) -> Dict[str, Any]:
        if recipe.get("recipe_id"):
            return recipe

        normalized_name = self._normalize_recipe_name(recipe.get("name", ""))
        normalized_type = self._normalize_recipe_name(recipe.get("type", ""))
        calories = str(recipe.get("calories", "")).strip()
        slug = re.sub(r"[^a-z0-9]+", "-", normalized_name).strip("-") or "recipe"
        digest = hashlib.md5(f"{normalized_name}|{normalized_type}|{calories}".encode("utf-8")).hexdigest()[:10]

        recipe_with_id = dict(recipe)
        recipe_with_id["recipe_id"] = f"{slug}-{digest}"
        return recipe_with_id

    def _get_recipe_identity(self, recipe: Dict[str, Any]) -> str:
        recipe = self._ensure_recipe_id(recipe)
        recipe_id = str(recipe.get("recipe_id", "")).strip()
        if recipe_id:
            return recipe_id
        return self._normalize_recipe_name(recipe.get("name", ""))

    def _deduplicate_recipes(self, recipes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        deduplicated: List[Dict[str, Any]] = []
        seen_identities = set()

        for recipe in recipes:
            recipe = self._ensure_recipe_id(recipe)
            identity = self._get_recipe_identity(recipe)
            if not identity or identity in seen_identities:
                continue

            seen_identities.add(identity)
            deduplicated.append(recipe)

        return deduplicated

    def _get_database_search_candidates(
        self, query: str, intent_data: Dict[str, Any], excluded_ids: set[str], limit: int,
        excluded_names: Optional[set[str]] = None
    ) -> List[Dict[str, Any]]:
        if self.data_loader.df is None:
            return []

        generic_terms = {
            "what", "some", "that", "are", "the", "and", "any", "can", "for", "give",
            "how", "make", "please", "recipe", "recipes", "show", "want", "with", "without",
            "you", "provide", "rely", "using", "need", "could", "would", "best", "good",
            "simple", "easy", "generate", "ingredients", "prepare", "eat", "help",
            "meal", "meals", "dinner", "lunch", "breakfast", "food", "foods"
        }
        search_text = " ".join([
            query,
            *intent_data.get("search_strategy", {}).get("search_keywords", []),
            *intent_data.get("preferences", {}).get("cuisine_types", [])
        ])
        terms = set(re.findall(r"[a-z0-9]+", search_text.lower())) - generic_terms
        terms = {term for term in terms if len(term) > 2}
        meal_types = intent_data.get("preferences", {}).get("meal_types", [])
        equipment = intent_data.get("constraints", {}).get("equipment_required", [])
        required_ingredients = intent_data.get("constraints", {}).get("ingredients_must_use") or []
        low_exertion = intent_data.get("constraints", {}).get("preparation_effort") == "low"
        constraints = intent_data.get("constraints", {})
        budget = intent_data.get("budget_request")
        if budget:
            terms = {term for term in terms if not term.isdigit()} - {"under", "less", "than", "dollars", "dollar", "usd", "budget", "whole", "total", "cost", "per", "serving", "groceries", "shopping"}
        ranked = []
        for _, row in self.data_loader.df.iterrows():
            record = row.to_dict()
            if record.get("recipe_id") in excluded_ids:
                continue
            if self._normalize_recipe_name(record.get("Name", "")) in (excluded_names or set()):
                continue
            title_terms = set(re.findall(r"[a-z0-9]+", str(record.get("Name", "")).lower()))
            ingredient_terms = set(re.findall(r"[a-z0-9]+", str(record.get("Ingredients", "")).lower()))
            content = self.data_loader.build_recipe_text(record)
            content_terms = set(re.findall(r"[a-z0-9]+", content.lower()))
            score = 3 * len(terms & title_terms) + 3 * len(terms & ingredient_terms) + len(terms & content_terms)
            if not terms:
                score = 1
            recipe_type = str(record.get("Type", "")).lower()
            if any(meal in {"dinner", "lunch"} for meal in meal_types):
                score += 3 * any(label in recipe_type for label in ("entree", "main dish", "one-dish"))
            elif any(meal in recipe_type for meal in meal_types):
                score += 3
            if intent_data.get("constraints", {}).get("leftover_friendly"):
                score += self.search_engine.storage_evidence_score(content)
            equipment_matches = len(equipment_usage_evidence(
                {"instructions": str(record.get("Directions", "")).splitlines()}, equipment
            )) if equipment else 0
            effort_conflicts = len(audit_preparation_effort({
                "ingredients": str(record.get("Ingredients", "")).splitlines(),
                "instructions": str(record.get("Directions", "")).splitlines(),
            })) if low_exertion else 0
            timing_rank = (
                time_candidate_rank(self._build_recipe_data_from_record(record), constraints)
                if constraints.get("time_max_minutes") is not None else 0
            )
            if score or equipment_matches or timing_rank == 2 or budget:
                ingredient_matches = len(required_ingredients) - len(missing_required_ingredients(
                    {"ingredients": str(record.get("Ingredients", "")).splitlines()}, required_ingredients,
                ))
                prefix = (ingredient_matches, -effort_conflicts, equipment_matches, timing_rank, score)
                if budget:
                    assessment = budget_service.assess(self._build_recipe_data_from_record(record), budget)
                    prefix += (int(assessment["status"] == "estimated_within_budget"),)
                ranked.append((*prefix, record))
        ranked.sort(key=lambda item: item[:-1], reverse=True)
        return [self._build_recipe_data_from_record(item[-1]) for item in ranked[:limit]]

    def _has_valid_time_limit(self, intent_data):
        limit = intent_data.get("constraints", {}).get("time_max_minutes")
        return isinstance(limit, (int, float)) and not isinstance(limit, bool) and math.isfinite(limit) and limit >= 0

    def _catalog_recipe(self, name):
        record = self.data_loader.get_recipe_record(name)
        return self._build_recipe_data_from_record(record) if record else None

    def _timing_search_candidates(self, docs, intent_data):
        if not self._has_valid_time_limit(intent_data):
            return docs
        ranked = []
        for doc in docs:
            try:
                rank = time_candidate_rank(self._build_recipe_data_from_doc(doc), intent_data["constraints"])
            except Exception:
                rank = 1
            if rank:
                ranked.append((rank, doc))
        ranked.sort(key=lambda item: item[0], reverse=True)
        return [doc for _, doc in ranked]

    def _verify_candidates(self, recipes: List[Dict[str, Any]], intent_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        required_servings = intent_data.get("constraints", {}).get("requested_servings")
        yield_rejections = []
        eligible = []
        for recipe in recipes:
            if (required_servings is not None and recipe.get("database_record_found")
                    and declared_recipe_servings(recipe) != required_servings):
                yield_rejections.append({**recipe, "verification_details": {
                    "passes_verification": False, "relevance": "adaptable",
                    "catalog_yield_mismatch": True,
                    "constraint_violations": ["Catalog recipe does not establish the requested serving count."],
                }})
            else:
                eligible.append(recipe)
        if yield_rejections:
            logger.info("Catalog serving prefilter rejected %s candidates before verification", len(yield_rejections))
        recipes = eligible
        if not recipes:
            return yield_rejections
        if recipes:
            report_progress("verifying")
        prepared = self.recipe_enhancer.prepare_recipes_for_verification(recipes, intent_data)
        timing_rejections = []
        constraints = intent_data.get("constraints", {})
        required_ingredients = constraints.get("ingredients_must_use") or []
        if isinstance(required_ingredients, str):
            required_ingredients = [required_ingredients]
        compatible = []
        for recipe in prepared:
            conflicts = []
            if _generated_red_meat_conflict(recipe):
                conflicts.append("Generated recipe conflicts with ThriveWell's red and processed meat policy.")
            if recipe.get("database_record_found") and recipe.get("ingredients") and recipe.get("instructions"):
                if missing_required_ingredients(recipe, required_ingredients):
                    conflicts.append("Catalog recipe does not contain all required ingredients.")
                conflicts.extend(audit_equipment(recipe, constraints))
            if conflicts:
                recipe["verification_details"] = {
                    "passes_verification": False, "relevance": "adaptable", "constraint_violations": conflicts,
                    "catalog_preflight_mismatch": bool(recipe.get("database_record_found")),
                }
                timing_rejections.append(recipe)
            else:
                compatible.append(recipe)
        if timing_rejections:
            logger.info("Local requirement prefilter rejected %s candidates before model review", len(timing_rejections))
        prepared = compatible
        if constraints.get("digestive_comfort") == "gentle":
            compatible = []
            for recipe in prepared:
                conflicts = audit_digestive_comfort(recipe, constraints)
                if conflicts:
                    recipe["verification_details"] = {
                        "passes_verification": False, "relevance": "adaptable", "constraint_violations": conflicts,
                    }
                    timing_rejections.append(recipe)
                else:
                    compatible.append(recipe)
            logger.info("Gentle-food prefilter: %s retained, %s conflicts rejected", len(compatible), len(timing_rejections))
            prepared = sorted(compatible, key=lambda recipe: len(digestive_tolerance_cautions(recipe)))
        if self._has_valid_time_limit(intent_data):
            eligible = []
            for recipe in prepared:
                if time_candidate_rank(recipe, constraints) == 0:
                    recipe["verification_details"] = {
                        "passes_verification": False,
                        "relevance": "adaptable",
                        "constraint_violations": ["Declared total preparation time exceeds the requested limit"],
                        "catalog_preflight_mismatch": bool(recipe.get("database_record_found")),
                    }
                    timing_rejections.append(recipe)
                else:
                    eligible.append(recipe)
            prepared = eligible
            logger.info("Timing prefilter: %s candidates retained, %s declared conflicts rejected",
                        len(prepared), len(timing_rejections))
        if intent_data.get("budget_request"):
            budget_service.prepare_prices(prepared, intent_data, generation=any(
                recipe.get("generated_by_llm") or recipe.get("dynamically_adapted")
                or recipe.get("ingredients_generated") or recipe.get("instructions_generated")
                for recipe in prepared
            ))
        if intent_data.get("constraints", {}).get("leftover_friendly"):
            prepared = [{**recipe, "storage_evidence": self._get_recipe_storage_evidence(recipe)} for recipe in prepared]
        deferred = []
        if intent_data.get("budget_request"):
            assessed = budget_service.annotate(prepared, intent_data)
            prepared = []
            for recipe in assessed:
                if recipe["budget_assessment"]["status"] == "estimated_within_budget":
                    recipe.pop("budget_verification_pending", None)
                    prepared.append(recipe)
                else:
                    recipe["budget_verification_pending"] = True
                    recipe["verification_details"].setdefault("relevance", "unreviewed")
                    deferred.append(recipe)
        verified = []
        pending = []
        for recipe in prepared:
            if intent_data.get("budget_request") and recipe.pop("_local_generation_checks", False) and recipe.get("generated_by_llm"):
                check_generated_recipe(recipe, intent_data, aicr_service)
                verified.append(recipe)
            else:
                pending.append(recipe)
        if pending:
            verified.extend(self.recipe_verifier.batch_verify_recipes(pending, intent_data, aicr_service))
        return budget_service.annotate(verified, intent_data) + deferred + timing_rejections + yield_rejections

    def _get_verified_matches(self, recipes: List[Dict[str, Any]], intent_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        matches = [
            recipe for recipe in recipes
            if recipe.get("verification_details", {}).get("passes_verification") is True
            and recipe.get("verification_details", {}).get("relevance") == "match"
        ]
        matches = self._apply_deterministic_constraints(matches, intent_data)
        if matches and intent_data.get("constraints", {}).get("digestive_comfort") == "gentle":
            least_cautions = min(len(digestive_tolerance_cautions(recipe)) for recipe in matches)
            matches = [recipe for recipe in matches if len(digestive_tolerance_cautions(recipe)) == least_cautions]
        return budget_service.rank(matches, intent_data) if intent_data.get("budget_request") else matches

    def _budget_instruction_repair_kind(self, recipe):
        if not recipe.get("generated_by_llm"):
            return None
        assessment = recipe.get("budget_assessment", {})
        issues = assessment.get("issues", [])
        violations = recipe.get("verification_details", {}).get("constraint_violations", [])
        if (any(issue.startswith(UNLISTED_ADDITION_ISSUE) for issue in issues)
                and all(issue.startswith((UNLISTED_ADDITION_ISSUE, UNRESOLVED_INGREDIENT_ISSUE)) for issue in issues)
                and budget_service.price_lookup_ready({"ingredients": recipe.get("ingredients")},
                                                     budget_service.pricing_catalog() or {"items": []})):
            return "quantity"
        if (assessment.get("status") == "estimated_within_budget" and violations
                and all(issue.startswith("Guideline food_safety:") for issue in violations)):
            return "safety"
        return None

    def _generate_verified_fallback_recipes(
        self, query: str, intent_data: Dict[str, Any], failed_recipes: List[Dict[str, Any]],
        grounding_recipes: List[Dict[str, Any]], excluded_names: set[str], *, bounded=False
    ) -> List[Dict[str, Any]]:
        stages = [grounding_recipes]
        if grounding_recipes and intent_data.get("query_type") != "recipe_adaptation" and not bounded:
            stages.append([])

        instruction_repairs = set()
        budget = bool(intent_data.get("budget_request"))
        timed_fallback = bounded and not budget and intent_data.get("query_type") == "recipe_search" and self._has_valid_time_limit(intent_data)
        generation_intent = {**intent_data, "_timed_candidate_count": 3} if timed_fallback else intent_data
        assessed = []
        alternatives = []
        timeout_recovery_attempted = False
        for stage_index, references in enumerate(stages):
            stage_name = "reference_guided" if references else "ai_only"
            stage_failures = list(failed_recipes) if stage_index == 0 or budget else []
            for attempt in range(2 if timed_fallback else 1 if bounded else 3):
                generation_query = query if attempt != 1 else (
                    f"Create complete recipes with ingredients and step-by-step instructions for: {query}"
                )
                logger.info("Recipe generation stage=%s attempt=%s", stage_name, attempt + 1)
                report_progress("generating")
                if budget:
                    intent_data["budget_price_options"] = budget_service.options()
                repair = None
                if budget and intent_data.get("query_type") != "recipe_adaptation":
                    for recipe in assessed:
                        kind = self._budget_instruction_repair_kind(recipe)
                        repair_key = (kind, tuple(sorted(recipe.get("ingredients") or [])),
                                      tuple(sorted(recipe.get("budget_assessment", {}).get("issues", []))))
                        if kind and repair_key not in instruction_repairs:
                            repair = (recipe, repair_key)
                            break
                if repair:
                    target, repair_key = repair
                    instruction_repairs.add(repair_key)
                    candidates = self.recipe_enhancer.repair_budget_instructions(target, intent_data)
                elif attempt == 2:
                    candidates = self.recipe_enhancer.generate_structured_fallback_recipe(
                        query, intent_data, grounding_recipes=references,
                        **({"failed_recipes": stage_failures} if budget else {}),
                    )
                else:
                    candidates = self.recipe_enhancer.generate_fallback_recipes(
                        generation_query, generation_intent, stage_failures, grounding_recipes=references
                    )
                candidates = self._exclude_previously_shown_recipes(candidates, excluded_names)
                review_intent = {**intent_data, "_independent_final_review": True}
                try:
                    with final_review_window():
                        assessed = self._verify_candidates(candidates, review_intent)
                except RecipeModelUnavailable as error:
                    if not isinstance(error, ModelBudgetExhausted) and not isinstance(error.__cause__, Timeout):
                        raise
                    assessed = []
                if (bounded and not budget and candidates and not assessed and not timeout_recovery_attempted
                        and intent_data.get("query_type") == "recipe_search"):
                    limit = final_review_limit.get()
                    if limit is not None and limit > time.monotonic():
                        timeout_recovery_attempted = True
                        token = model_deadline.set(limit)
                        try:
                            report_progress("generating")
                            simpler = self.recipe_enhancer.generate_fallback_recipes(
                                f"{query}\nReturn one simpler complete recipe. Prefer straightforward assembly "
                                "or simple cooking compatible with every requirement. Preserve food safety.",
                                intent_data, stage_failures, grounding_recipes=references,
                            )
                            simpler = self._exclude_previously_shown_recipes(simpler, excluded_names)
                            assessed = self._verify_candidates(simpler[:1], review_intent)
                        finally:
                            model_deadline.reset(token)
                matches = self._get_verified_matches(assessed, intent_data)
                logger.info("Generation candidates: %s assessed, %s matched, %s pending budget evidence",
                            len(assessed), len(matches), sum(bool(recipe.get("budget_verification_pending")) for recipe in assessed))
                if matches:
                    if not intent_data.get("red_meat_alternatives"):
                        return matches
                    alternatives = self._deduplicate_recipes([*alternatives, *matches])
                    if len(alternatives) >= MAX_RECIPES_PER_RESPONSE:
                        return alternatives[:MAX_RECIPES_PER_RESPONSE]
                    excluded_names = excluded_names | {self._normalize_recipe_name(recipe["name"]) for recipe in alternatives}
                stage_failures = [*assessed, *stage_failures]

            if budget:
                failed_recipes = stage_failures
            logger.warning("Recipe generation stage=%s exhausted without verified matches", stage_name)

        return alternatives

    def _complete_composed_dinner(self, query, intent_data, verified, failed):
        if len(verified) >= MAX_RECIPES_PER_RESPONSE:
            return verified[:MAX_RECIPES_PER_RESPONSE]
        existing_names = {self._normalize_recipe_name(recipe["name"]) for recipe in verified}
        report_progress("generating")
        generation_query = query + ". Return distinct recipes; do not repeat: " + ", ".join(sorted(existing_names))
        try:
            candidates = self.recipe_enhancer.generate_fallback_recipes(
                generation_query, {**intent_data, "_generation_slots": MAX_RECIPES_PER_RESPONSE - len(verified)},
                failed, grounding_recipes=[]
            )
            candidates = self._exclude_previously_shown_recipes(self._deduplicate_recipes(candidates), existing_names)
            checked = self._verify_candidates(candidates[:MAX_RECIPES_PER_RESPONSE - len(verified)], intent_data)
            return self._deduplicate_recipes(verified + self._get_verified_matches(checked, intent_data))[:MAX_RECIPES_PER_RESPONSE]
        except RecipeModelUnavailable:
            if verified:
                logger.warning("Menu completion unavailable; retaining already verified recipes")
                return verified
            raise

    def _validate_final_recipes(self, recipes: List[Dict[str, Any]], intent_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        verified = self._verify_candidates(recipes, intent_data)
        matches = self._get_verified_matches(verified, intent_data)
        accepted_ids = {self._get_recipe_identity(recipe) for recipe in matches}
        stripped_recipes = []
        for recipe in verified:
            if self._get_recipe_identity(recipe) in accepted_ids:
                continue
            if not recipe.get("guidance_generated"):
                continue
            if not (recipe.get("helpful_tips") or recipe.get("ingredient_adaptations")):
                continue
            stripped = dict(recipe)
            stripped.pop("helpful_tips", None)
            stripped.pop("ingredient_adaptations", None)
            stripped["guidance_generated"] = False
            stripped["instructions_adapted"] = False
            stripped_recipes.append(stripped)
        if stripped_recipes:
            matches.extend(self._get_verified_matches(self._verify_candidates(stripped_recipes, intent_data), intent_data))
        positions = {self._get_recipe_identity(recipe): position for position, recipe in enumerate(recipes)}
        return sorted(matches, key=lambda recipe: positions[self._get_recipe_identity(recipe)])

    def _enhance_verified_recipes(self, recipes: List[Dict[str, Any]], intent_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        baseline = deepcopy([
            self._ensure_recipe_id(recipe) for recipe in self._get_verified_matches(recipes, intent_data)
        ])
        if not baseline:
            return []
        if (intent_data.get("query_type") == "recipe_adaptation"
                or intent_data.get("constraints", {}).get("digestive_comfort") == "gentle"
                or intent_data.get("constraints", {}).get("preparation_effort") == "low"
                or intent_data.get("budget_request")
                or intent_data.get("constraints", {}).get("time_max_minutes") is not None):
            return baseline
        originals = {self._get_recipe_identity(recipe): recipe for recipe in baseline}
        report_progress("enhancing")
        try:
            enhanced = self.recipe_enhancer.batch_enhance_recipes(deepcopy(baseline), deepcopy(intent_data))
            changed = [recipe for recipe in enhanced if self._get_recipe_identity(recipe) in originals
                       and recipe != originals[self._get_recipe_identity(recipe)]]
            accepted = self._validate_final_recipes(changed, deepcopy(intent_data)) if changed else []
            replacements = {self._get_recipe_identity(recipe): recipe for recipe in accepted}
            return [replacements.get(self._get_recipe_identity(recipe), recipe) for recipe in baseline]
        except Exception as error:
            logger.warning("Optional recipe enhancement failed; keeping verified originals (%s)", type(error).__name__)
            return baseline

    def _apply_deterministic_constraints(
        self,
        recipes: List[Dict[str, Any]],
        intent_data: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        required = intent_data.get("constraints", {}).get("ingredients_must_use") or []
        if isinstance(required, str):
            required = [required]
        recipes = [recipe for recipe in recipes if not missing_required_ingredients(recipe, required)]
        recipes = [recipe for recipe in recipes if not _generated_red_meat_conflict(recipe)]
        if intent_data.get("red_meat_alternatives"):
            recipes = [recipe for recipe in recipes if not any(
                RED_MEAT_TERMS.search(str(recipe.get(field) or ""))
                for field in ("name", "description", "ingredients", "instructions", "helpful_tips", "ingredient_adaptations")
            )]
        servings = intent_data.get("constraints", {}).get("requested_servings")
        if servings is not None:
            recipes = [{**recipe, "servings": servings} for recipe in recipes if declared_recipe_servings(recipe) == servings]
        if intent_data.get("budget_request"):
            recipes = [recipe for recipe in budget_service.annotate(recipes, intent_data)
                       if recipe["budget_assessment"]["status"] == "estimated_within_budget"
                       and recipe.get("verification_details", {}).get("passes_verification") is not False]
        if not intent_data.get("constraints", {}).get("leftover_friendly"):
            return recipes

        matching_recipes = []
        for recipe in recipes:
            evidence = self._get_recipe_storage_evidence(recipe)
            if not evidence:
                continue
            recipe_with_evidence = dict(recipe)
            recipe_with_evidence["storage_evidence"] = evidence
            matching_recipes.append(recipe_with_evidence)

        return matching_recipes

    def _get_recipe_storage_evidence(self, recipe: Dict[str, Any]) -> str:
        if recipe.get("database_record_found") and self._classify_recipe_source_tier(recipe) == "database_exact":
            source_guidance = self.search_engine.extract_storage_evidence(recipe.get("content", ""))
            if source_guidance:
                return source_guidance
        for field in ("storage_instructions", "storage_evidence"):
            guidance = self.search_engine.extract_storage_evidence(recipe.get(field, ""))
            if guidance:
                return guidance

        searchable_fields = [
            recipe.get("content", ""),
            recipe.get("description", ""),
            "\n".join(str(item) for item in recipe.get("instructions", []) if item),
            "\n".join(str(item) for item in recipe.get("helpful_tips", []) if item),
        ]
        return self.search_engine.extract_storage_evidence("\n".join(map(str, searchable_fields)))

    def _normalize_recipe_request(self, query: str) -> str:
        replacements = {
            r"\bmaggie\b": "Maggi",
            r"\bbindi\b": "Bhindi",
            r"\bpanner\b": "Paneer",
            r"\baneer\b": "Paneer"
        }
        normalized_query = query
        for pattern, replacement in replacements.items():
            normalized_query = re.sub(pattern, replacement, normalized_query, flags=re.IGNORECASE)
        return normalized_query

    def _is_more_recipes_query(self, query: str) -> bool:
        return is_more_recipes_request(query)

    def _get_previous_recipe_request(
        self,
        conversation_history: Optional[List[Dict]] = None
    ) -> Optional[str]:
        for message in reversed(conversation_history or []):
            if not isinstance(message, dict) or str(message.get("role", "")).lower() != "user":
                continue

            content = str(message.get("content", "")).strip()
            if content and not self._is_more_recipes_query(content):
                return content

        return None

    def _get_previously_shown_recipe_names(
        self,
        conversation_history: Optional[List[Dict]] = None
    ) -> set[str]:
        shown_names: set[str] = set()
        marker = "previously shown recipes:"

        for message in conversation_history or []:
            if not isinstance(message, dict) or str(message.get("role", "")).lower() != "assistant":
                continue

            for recipe in message.get("recipes", []):
                if isinstance(recipe, dict) and recipe.get("name"):
                    shown_names.add(self._normalize_recipe_name(recipe["name"]))

            content = str(message.get("content", ""))
            for line in content.splitlines():
                if marker not in line.lower():
                    continue
                names = line.split(":", 1)[1].split("|")
                shown_names.update(self._normalize_recipe_name(name) for name in names if name.strip())

        return shown_names

    def _exclude_previously_shown_recipes(
        self,
        recipes: List[Dict[str, Any]],
        shown_names: set[str]
    ) -> List[Dict[str, Any]]:
        if not shown_names:
            return recipes
        return [
            recipe for recipe in recipes
            if self._normalize_recipe_name(recipe.get("name", "")) not in shown_names
        ]

    def _get_conversation_recipes(self, conversation_history: Optional[List[Dict]]) -> List[Dict[str, Any]]:
        recipes = {}
        for message in conversation_history or []:
            if not isinstance(message, dict) or message.get("role") != "assistant":
                continue
            for recipe in message.get("recipes") or []:
                if isinstance(recipe, dict) and recipe.get("recipe_id"):
                    recipes[str(recipe["recipe_id"])] = dict(recipe)
        return list(recipes.values())

    def _build_context_reply(self, query: str, mode: str, intent_data: Dict[str, Any], response: str) -> Dict[str, Any]:
        return {
            "query": query, "mode": mode, "response": response,
            "source": "recipe_follow_up", "matches_found": 0,
            "source_documents": [], "intent_analysis": intent_data,
            "conversation_context_used": True
        }

    def _build_recipe_data_from_doc(self, doc: Any) -> Dict[str, Any]:
        recipe_id = self.search_engine.safe_get_metadata(doc, "recipe_id", "")
        recipe_name = self.search_engine.safe_get_metadata(doc, "name")
        full_recipe_record = self.data_loader.get_recipe_record(recipe_name)
        if full_recipe_record:
            return self._build_recipe_data_from_record(full_recipe_record)

        recipe_content = self.data_loader.build_recipe_text(full_recipe_record) or doc.page_content
        recipe_details = self.search_engine.extract_recipe_details(recipe_content)

        return {
            "recipe_id": recipe_id,
            "name": recipe_name,
            "type": self.search_engine.safe_get_metadata(doc, "type"),
            "calories": self.search_engine.safe_get_metadata(doc, "calories", 0),
            "content": recipe_content,
            "youtube_link": self.search_engine.safe_get_metadata(doc, "youtube_link", ""),
            "recipe_link": self.search_engine.safe_get_metadata(doc, "recipe_link", ""),
            "source_name": self.search_engine.safe_get_metadata(doc, "source_name", ""),
            "database_record_found": False,
            **recipe_details
        }

    def _build_recipe_data_from_record(self, record: Dict[str, Any]) -> Dict[str, Any]:
        recipe_content = self.data_loader.build_recipe_text(record)
        recipe_details = self.search_engine.extract_recipe_details(recipe_content)
        calories = record.get("Calories", 0)
        try:
            calories = float(calories) if calories != "" else 0
        except (TypeError, ValueError):
            calories = 0

        return {
            "recipe_id": record.get("recipe_id", ""),
            "name": record.get("Name", "Unknown"),
            "type": record.get("Type", "Unknown"),
            "calories": calories,
            "content": recipe_content,
            "youtube_link": record.get("YT Link", ""),
            "recipe_link": record.get("Recipe Link", ""),
            "source_name": record.get("Source Name (AICR or ACS)", ""),
            "database_record_found": True,
            **recipe_details,
            **self.data_loader.get_source_annotations(record),
        }

    def _get_leftover_friendly_database_recipes(self, limit: int) -> List[Dict[str, Any]]:
        if self.data_loader.df is None:
            return []

        ranked_recipes = []
        for _, row in self.data_loader.df.iterrows():
            record = row.to_dict()
            recipe_content = self.data_loader.build_recipe_text(record)
            storage_evidence = self.search_engine.extract_storage_evidence(recipe_content)
            if not storage_evidence:
                continue

            recipe = self._build_recipe_data_from_record(record)
            recipe["storage_evidence"] = storage_evidence
            ranked_recipes.append((self.search_engine.storage_evidence_score(recipe_content), recipe))

        ranked_recipes.sort(
            key=lambda item: (-item[0], self._normalize_recipe_name(item[1].get("name", "")))
        )
        return [recipe for _, recipe in ranked_recipes[:limit]]
        
    def initialize(self):
        with self._initialization_lock:
            if self.is_initialized:
                return

            try:
                if not settings.OPENAI_API_KEY:
                    raise ValueError("OPENAI_API_KEY not found")
                
                from langchain.embeddings import OpenAIEmbeddings
                from langchain.vectorstores import FAISS
                from langchain.text_splitter import RecursiveCharacterTextSplitter
                from langchain.chat_models import ChatOpenAI
                
                self.embeddings = OpenAIEmbeddings(
                    model=settings.EMBEDDING_MODEL,
                    openai_api_key=settings.OPENAI_API_KEY
                )
                
                self.llm = ChatOpenAI(
                    model_name=settings.LLM_MODEL,
                    temperature=settings.LLM_TEMPERATURE,
                    max_tokens=settings.LLM_MAX_TOKENS,
                    request_timeout=settings.LLM_REQUEST_TIMEOUT_SECONDS,
                    max_retries=settings.LLM_MAX_RETRIES,
                    openai_api_key=settings.OPENAI_API_KEY
                )
                self.llm.predict("Reply with OK only.")
                
                self.data_loader.load_data()
                documents = self.data_loader.prepare_documents()
                
                text_splitter = RecursiveCharacterTextSplitter(
                    chunk_size=settings.CHUNK_SIZE,
                    chunk_overlap=settings.CHUNK_OVERLAP
                )
                split_docs = text_splitter.split_documents(documents)
                
                logger.info(f"Creating vector store with {len(split_docs)} document chunks")
                self.vector_store = FAISS.from_documents(split_docs, self.embeddings)

                self.intent_analyzer.initialize(self.llm, recipe_names=self.data_loader.recipe_lookup)
                self.recipe_verifier.initialize(self.llm)
                self.recipe_enhancer.initialize(self.llm, aicr_service)
                self.search_engine.initialize(self.vector_store, self.llm, self.embeddings)
                self.response_generator.initialize(self.llm)
                
                self.is_initialized = True
                self.initialization_error = None
                logger.info("RAG system initialized successfully")
                
            except Exception as e:
                self.is_initialized = False
                self.initialization_error = str(e)
                logger.error(f"Error initializing RAG system: {e}")
                raise

    def _classify_recipe_source_tier(self, recipe: Dict[str, Any]) -> str:
        if recipe.get("generated_by_llm"):
            return "llm_generated"

        core_completion_flags = [
            recipe.get("ingredients_generated", False),
            recipe.get("instructions_generated", False),
            recipe.get("dynamically_adapted", False)
        ]

        if any(core_completion_flags):
            return "database_completed"

        return "database_exact"

    def _annotate_recipe_source_tiers(self, recipes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        annotated_recipes = []
        for recipe in recipes:
            annotated_recipe = dict(recipe)
            source_tier = self._classify_recipe_source_tier(annotated_recipe)
            annotated_recipe["source_tier"] = source_tier
            annotated_recipe["source"] = source_tier
            annotated_recipe["source_label"] = (
                "AI Generated"
                if source_tier == "llm_generated"
                else f"Sourced from {annotated_recipe.get('source_name') or 'AICR'}"
            )
            annotated_recipes.append(annotated_recipe)
        return annotated_recipes

    def _classify_response_source(self, recipes: List[Dict[str, Any]]) -> str:
        if not recipes:
            return "database_exact"

        source_tiers = {recipe.get("source_tier") or self._classify_recipe_source_tier(recipe) for recipe in recipes}

        if source_tiers == {"database_exact"}:
            return "database_exact"
        if source_tiers.issubset({"database_exact", "database_completed"}):
            return "database_completed"
        if source_tiers == {"llm_generated"}:
            return "llm_generated"

        return "database_completed"
    "main initialization"
    def ask_question(self, query: str, mode: str = "auto", conversation_history: List[Dict] = None) -> Dict[str, Any]:
        """
        Main entry point with conversation context support
        """
        if safety_service.should_intercept(query, conversation_history):
            logger.warning("Detected self-harm crisis language; returning safety response")
            return safety_service.build_crisis_response(query, mode, conversation_history)

        if not self.is_initialized:
            raise ValueError("RAG system not initialized")

        logger.info(
            "Processing recipe query (%s characters) with %s previous messages",
            len(query),
            len(conversation_history or []),
        )
        start_time = time.time()
        
        try:
            conversation_history = [
                message for message in (conversation_history or [])
                if not (isinstance(message, dict)
                        and self._contains_phi_like_content(str(message.get("content", ""))))
            ]
            if self._contains_phi_like_content(query, conversation_history):
                logger.info("Detected PHI-like content, returning privacy redirect response")
                return self._build_phi_redirect_response(query, mode, conversation_history)
            alternative_choice = re.fullmatch(
                r"\s*(?:yes[, ]+|(?:i(?:['’]d like| prefer)|(?:please )?use|let['’]s go with)\s+)?"
                r"(yes(?:,? please)?|beans|lentils|tofu|fish|poultry)"
                r"(?:\s+(?:(?:would be|is|sounds)\s+(?:ok(?:ay)?|good|fine|great)(?:\s+for me)?"
                r"|works(?:\s+for me)?|please))?[.!]?\s*", query, re.I
            )
            confirmed_alternatives = bool(
                alternative_choice and len(conversation_history) >= 2
                and conversation_history[-1].get("role") == "assistant"
                and conversation_history[-1].get("content") == RED_MEAT_ALTERNATIVE_OFFER
                and conversation_history[-2].get("role") == "user"
            )
            if confirmed_alternatives:
                choice = alternative_choice[1].lower()
                query = str(conversation_history[-2]["content"])
                if not choice.startswith("yes"):
                    query += f" Use {choice} as the alternative protein."
            if re.search(
                r"\b(?:i\s+(?:have|have got|am having|am running)|i['’]m\s+(?:having|running)|my child has)"
                r"\s+(?:a\s+)?(?:high\s+)?fever\b", query, re.I
            ):
                return {
                    **self._build_context_reply(
                        query, mode, {},
                        "If you’re receiving cancer treatment, contact your oncology care team promptly about the fever. "
                        "Follow their instructions rather than waiting for a meal suggestion. "
                        "A recipe can’t determine what is causing the fever or whether you need urgent care.",
                    ),
                    "source": "health_safety",
                    "conversation_context_used": False,
                }
            if LABELED_ZIP.search(query) and re.search(r"\b(?:groceries|grocery|markets?|stores?)\b", query, re.I):
                return {
                    **self._build_context_reply(
                        query, mode, {},
                        "I can help make a grocery list from your recipes, but I can't check nearby store inventory here. "
                        "Tell me which recipe you’re shopping for, or share a store’s ingredient list. No street address needed.",
                    ),
                    "query": "Local grocery request",
                }

            recipe_history, _ = scope_recipe_history(
                query, self.intent_analyzer._sanitize_conversation_history(conversation_history or []),
                self.data_loader.recipe_lookup,
                semantic_current=True,
            )
            conversation_recipes = self._get_conversation_recipes(recipe_history)
            references_previous_recipe = bool(conversation_recipes) and bool(re.search(
                r"\b(it|them|those|these|that|first|second|third|one|ones)\b", query, re.IGNORECASE
            ))
            recipe_follow_up = resolve_recipe_follow_up(query, recipe_history) is not None
            catalog_recipe_name = matching_recipe_title(query, self.data_loader.recipe_lookup)
            if (not confirmed_alternatives and not is_budget_clarification_reply(query, recipe_history)
                    and self._is_small_talk_query(query, allow_heuristic=not conversation_recipes)
                    and not references_previous_recipe and not recipe_follow_up and not catalog_recipe_name):
                logger.info("Detected small-talk query, returning conversational response")
                return self._build_small_talk_response(query, mode, conversation_history)

            is_more_request = self._is_more_recipes_query(query)
            previous_recipe_request = self._get_previous_recipe_request(recipe_history)
            recipe_request_query = previous_recipe_request if is_more_request and previous_recipe_request else query
            previously_shown_names = self._get_previously_shown_recipe_names(recipe_history)
            excluded_names = previously_shown_names if is_more_request else set()
            intent_history = recipe_history
            if is_more_request:
                intent_history = [
                    ({**message, "content": "Previously shown recipe reference data.", "recipes": [
                        {key: recipe.get(key) for key in ("recipe_id", "name", "type")}
                        for recipe in message["recipes"] if isinstance(recipe, dict)
                    ]}
                     if message.get("role") == "assistant" and message.get("recipes") else message)
                    for message in recipe_history
                    if isinstance(message, dict)
                    and message.get("role") in {"user", "assistant"}
                ]

            # Step 1: Enhanced intent understanding with conversation context
            report_progress("understanding")
            meat_request = recipe_request_query
            redirect_red_meat = _requests_red_meat(meat_request)
            redirect_red_meat = redirect_red_meat or confirmed_alternatives
            if redirect_red_meat and not confirmed_alternatives and not (is_more_request and conversation_recipes):
                return self._build_context_reply(query, mode, {}, RED_MEAT_ALTERNATIVE_OFFER)
            intent_query = query
            if redirect_red_meat:
                intent_query = (
                    RED_MEAT_TERMS.sub("alternative protein", meat_request)
                    + "\nGenerate three distinct recipes using suitable alternative proteins, with no red or processed meat. "
                    "Preserve all other requirements; do not assume the alternatives are already available."
                )
            intent_data, combined_candidates = None, []
            composed_dinner = (
                not redirect_red_meat and not intent_history and not catalog_recipe_name
                and not is_more_request and not references_previous_recipe and not recipe_follow_up
                and requests_composed_dinner(query)
            )
            single_pass_dinner = composed_dinner and settings.RECIPE_SINGLE_PASS_DINNER
            if single_pass_dinner:
                intent_data = self.intent_analyzer._post_process_intent(
                    query, self.intent_analyzer._get_fallback_intent_data(query)
                )
                intent_data.update(query_type="recipe_search", context_action="new_request", recipe_request=query,
                                   resolved_query=query, user_request_context=[query], referenced_recipe_ids=[],
                                   generation_recipe_count=3, generation_mode="single_pass")
                intent_data["constraints"]["requested_servings"] = requested_servings(query)
                report_progress("generating")
                combined_candidates = generate_once(self.llm or self.intent_analyzer.llm, query, intent_data,
                                                    self.recipe_verifier, aicr_service)
            elif (not redirect_red_meat and not intent_history and not catalog_recipe_name and not is_more_request
                    and (composed_dinner or re.search(r"\b(?:generate|create|invent)\s+(?:me\s+)?an?\s+(?:original\s+)?recipe\b", query, re.I))):
                report_progress("generating")
                intent_data, combined_candidates = self.intent_analyzer.interpret_and_generate(
                    query, aicr_service.get_guidelines(), **({"recipe_count": 3} if composed_dinner else {})
                )
            if intent_data is None:
                intent_data = self.intent_analyzer.understand_query_intent_with_context(intent_query, intent_history)
            required_foods = intent_data.get("constraints", {}).get("ingredients_must_use") or []
            if (not redirect_red_meat and intent_data.get("query_type") == "recipe_search"
                    and isinstance(required_foods, list)
                    and any(RED_MEAT_TERMS.search(str(food)) for food in required_foods)):
                redirect_red_meat = True
                combined_candidates = []
                intent_query = RED_MEAT_TERMS.sub("alternative protein", intent_data.get("resolved_query") or query)
                intent_query += "\nUse suitable alternatives without red or processed meat. Preserve all other requirements."
            if (not is_more_request and previous_recipe_request and intent_data.get("context_action") == "continue_request"
                    and intent_data.get("query_type") == "recipe_search" and intent_data.get("more_recipes") is True):
                is_more_request = True
                excluded_names = previously_shown_names
                if _requests_red_meat(previous_recipe_request):
                    redirect_red_meat = True
                    intent_query = RED_MEAT_TERMS.sub("alternative protein", previous_recipe_request) + (
                        "\nGenerate distinct alternatives without red or processed meat. Preserve the original budget and requirements."
                    )
            if redirect_red_meat:
                if not confirmed_alternatives and not (is_more_request and conversation_recipes):
                    return self._build_context_reply(query, mode, {}, RED_MEAT_ALTERNATIVE_OFFER)
                intent_data["red_meat_alternatives"] = True
                intent_data.setdefault("constraints", {})["avoid_red_meat"] = True
                for field in ("ingredients_must_use", "ingredients_available"):
                    foods = intent_data["constraints"].get(field)
                    if isinstance(foods, list):
                        intent_data["constraints"][field] = [
                            food for food in foods if not RED_MEAT_TERMS.search(str(food))
                        ]
                if confirmed_alternatives and not choice.startswith("yes"):
                    required = intent_data["constraints"].get("ingredients_must_use") or []
                    if isinstance(required, list) and choice not in required:
                        intent_data["constraints"]["ingredients_must_use"] = [*required, choice]
                strategy = intent_data.setdefault("search_strategy", {})
                if isinstance(strategy.get("must_match_criteria"), list):
                    strategy["must_match_criteria"] = [
                        RED_MEAT_TERMS.sub("alternative protein", criterion)
                        for criterion in strategy["must_match_criteria"] if isinstance(criterion, str)
                    ]
                intent_data["user_request_context"] = [intent_query]
                intent_data["resolved_query"] = intent_query
            if intent_data.get("context_resolution_failed"):
                return self._build_context_reply(
                    query, mode, intent_data,
                    "I couldn't reliably interpret this follow-up. Please try again so I can keep your earlier requirements."
                )
            recipe_request_query = str(intent_data.get("resolved_query") or recipe_request_query)
            intent_data = {**intent_data, "recipe_request": self._normalize_recipe_request(recipe_request_query)}
            serving_context = [query] if intent_data.get("context_action") == "new_request" else [
                *(message["content"] for message in intent_history if message.get("role") == "user"), query
            ]
            servings = next((count for message in reversed(serving_context)
                             if (count := requested_servings(message)) is not None), None)
            if servings is not None and not intent_data.get("budget_request"):
                intent_data.setdefault("constraints", {})["requested_servings"] = servings
            context_used = bool(recipe_history) and intent_data.get("context_action") != "new_request"
            query_type = intent_data.get("query_type")
            normalized_request = intent_data.get("normalized_request")
            semantic_creation = intent_data.get("recipe_action") == "create"
            corrected_creation = isinstance(normalized_request, str) and requests_composed_dinner(normalized_request)
            if (not composed_dinner and settings.RECIPE_SINGLE_PASS_DINNER
                    and intent_data.get("context_action") == "new_request" and query_type == "recipe_search"
                    and not redirect_red_meat and not catalog_recipe_name and not is_more_request
                    and not references_previous_recipe and not recipe_follow_up
                    and not requests_catalog_source(query) and not requests_catalog_source(recipe_request_query)
                    and not (isinstance(normalized_request, str) and requests_catalog_source(normalized_request))
                    and not intent_data.get("budget_request")
                    and intent_data.get("constraints", {}).get("preparation_effort") != "low"
                    and intent_data.get("constraints", {}).get("digestive_comfort") != "gentle"
                    and (semantic_creation or corrected_creation)):
                composed_dinner = single_pass_dinner = True
                intent_data.update(generation_recipe_count=3, generation_mode="single_pass")
                report_progress("generating")
                combined_candidates = generate_once(self.llm or self.intent_analyzer.llm, query, intent_data,
                                                    self.recipe_verifier, aicr_service)
            composed_dinner = bool(composed_dinner and intent_data.get("context_action") == "new_request"
                                   and query_type == "recipe_search" and not intent_data.get("budget_request"))
            if composed_dinner:
                intent_data["generation_recipe_count"] = 3
            ai_estimates = (
                settings.RECIPE_AI_COST_ESTIMATES
                and query_type in {"recipe_search", "recipe_adaptation"}
                and bool(intent_data.get("budget_request"))
            )
            if (redirect_red_meat and query_type == "recipe_search" and settings.RECIPE_SINGLE_PASS_DINNER
                    and not ai_estimates and not intent_data.get("budget_request")
                    and not intent_data.get("constraints", {}).get("health_conditions")
                    and not intent_data.get("constraints", {}).get("allergens_to_avoid")
                    and intent_data.get("constraints", {}).get("digestive_comfort") != "gentle"
                    and not any(intent_data.get("cancer_patient_specific", {}).values())):
                single_pass_dinner = True
                intent_data.update(generation_recipe_count=3, generation_mode="single_pass")
                if confirmed_alternatives:
                    intent_data["_confirmed_alternative_count"] = 1
                intent_data["exclude_dish_names"] = sorted(excluded_names)[:20]
                report_progress("generating")
                combined_candidates = generate_once(self.llm or self.intent_analyzer.llm, intent_query,
                                                    intent_data, self.recipe_verifier, aicr_service)
            if intent_data.get("budget_request") and query_type != "recipe_question" and not ai_estimates:
                clarification = budget_clarification(intent_data)
                if clarification:
                    intent_data["query_type"] = "clarification"
                    return self._build_context_reply(query, mode, intent_data, clarification)
                intent_data["budget_price_options"] = budget_service.options()
                intent_data["budget_request"]["_price_lookup_batches"] = 0
                intent_data["budget_request"]["_retrieval_price_lookup_batches"] = 0
                intent_data.pop("budget_previous_recipes", None)
                if is_more_request:
                    intent_data["budget_previous_recipes"] = [
                        {key: recipe.get(key) for key in ("name", "ingredients", "instructions")}
                        for recipe in conversation_recipes
                    ]
            reference_ids = intent_data.get("referenced_recipe_ids") or []
            referenced_recipes = [recipe for recipe in conversation_recipes if recipe["recipe_id"] in reference_ids]
            if query_type == "clarification" or (
                query_type in {"recipe_question", "recipe_adaptation"}
                and (not referenced_recipes or len(referenced_recipes) != len(set(reference_ids)))
            ):
                return self._build_context_reply(
                    query, mode, intent_data,
                    intent_data.get("clarification_question") or
                    "Which recipe do you mean? Please use its name or its position in the last recipe list."
                )
            if query_type == "recipe_question":
                return self._build_context_reply(
                    query, mode, intent_data,
                    self.response_generator.answer_recipe_question(recipe_request_query, referenced_recipes, intent_data)
                )
            if ai_estimates:
                estimate_intent = deepcopy(intent_data)
                estimate_intent["ai_cost_estimates"] = True
                if servings is not None:
                    estimate_intent.setdefault("constraints", {})["requested_servings"] = servings
                if context_used:
                    estimate_intent["previous_dishes"] = [
                        {key: recipe.get(key) for key in ("recipe_id", "name", "ingredients", "instructions", "servings", "ai_cost_estimate")}
                        for recipe in (referenced_recipes or conversation_recipes)[-6:]
                    ]
                estimate_intent["exclude_dish_names"] = sorted(excluded_names)[:20]
                report_progress("generating")
                candidates = generate_once(self.llm or self.intent_analyzer.llm, query, estimate_intent,
                                           self.recipe_verifier, aicr_service)
                local_intent = {key: value for key, value in estimate_intent.items() if key != "budget_request"}
                matches = self._get_verified_matches(candidates, local_intent)
                matches = self._exclude_previously_shown_recipes(self._deduplicate_recipes(matches), excluded_names)
                matches = self._annotate_recipe_source_tiers(matches[:MAX_RECIPES_PER_RESPONSE])
                if matches:
                    response = "Here are recipe ideas based on your request. Any prices shown are rough AI estimates, not verified store prices or a guarantee that the recipe fits your budget."
                    if redirect_red_meat:
                        response = RED_MEAT_ALTERNATIVE_NOTE + "\n\n" + response
                else:
                    response = self._recipe_shortage_message(intent_data, additional=is_more_request)
                follow_up = estimate_intent.get("_generated_follow_up")
                return {
                    **self._build_context_reply(query, mode, intent_data, response),
                    "source": "llm_generated" if matches else "no_results",
                    "source_documents": matches, "matches_found": len(matches),
                    "conversation_context_used": context_used,
                    **({"follow_up": follow_up} if matches and follow_up else {}),
                }
            if query_type == "food_guidance":
                response = self.response_generator.answer_food_guidance(
                    recipe_request_query, intent_data,
                    aicr_service.get_prompt_context(focus_areas=aicr_service.extract_focus_areas_from_intent(intent_data)),
                )
                return {
                    **self._build_context_reply(query, mode, intent_data, response),
                    "source": "food_guidance",
                    "conversation_context_used": context_used,
                }
            is_recipe_adaptation = query_type == "recipe_adaptation"
            lookup_name = catalog_recipe_name if intent_data.get("context_action") == "new_request" else None
            lookup_record = self.data_loader.get_recipe_record(lookup_name) if lookup_name else None
            previous_results = next((message.get("recipes", []) for message in reversed(recipe_history)
                                     if message.get("role") == "assistant" and message.get("recipes")), [])
            sparse_follow_up = bool(
                is_more_request and 0 < len(previous_results) < MAX_RECIPES_PER_RESPONSE
                and query_type == "recipe_search" and not is_recipe_adaptation
                and not intent_data.get("budget_request")
                and not requests_catalog_source(query) and not requests_catalog_source(recipe_request_query)
            )
            generate_first = sparse_follow_up or composed_dinner or redirect_red_meat or bool(combined_candidates) or (
                intent_data.get("context_action") == "new_request"
                and not lookup_record and not is_recipe_adaptation and not is_more_request
                and not references_previous_recipe and not recipe_follow_up
                and bool(re.match(
                    r"^\s*(?:please\s+)?(?:create|generate|invent)\s+(?:an?\s+)?original\s+recipe\b",
                    query, re.IGNORECASE,
                ) or (servings is not None and re.search(r"\bgenerate\s+(?:me\s+)?a\s+recipe\b", query, re.I)))
            )
            if generate_first:
                logger.info("Recipe route: %s", "additional recipes after sparse results" if sparse_follow_up else
                            "composed dinner; skip catalog candidate verification" if composed_dinner else "explicit original generation")
            logger.info("%s: %.2fs", "Intent + initial generation" if composed_dinner else "Intent analysis",
                        time.time() - start_time)
            effective_query = intent_data.get("search_strategy", {}).get("enhanced_query") or recipe_request_query
            catalog_recipes = catalog_matches(intent_data, self._catalog_recipe, self.recipe_verifier, aicr_service)
            local_matches = []
            if len(catalog_recipes) < MAX_RECIPES_PER_RESPONSE and not settings.RECIPE_OPTIONAL_ENHANCEMENT:
                local_matches = local_catalog_matches(
                    intent_data, self.data_loader.recipe_lookup.values(), self._build_recipe_data_from_record,
                    aicr_service, MAX_RECIPES_PER_RESPONSE,
                )
            catalog_recipes = self._get_verified_matches(catalog_recipes, intent_data)
            if len(catalog_recipes) < MAX_RECIPES_PER_RESPONSE or settings.RECIPE_OPTIONAL_ENHANCEMENT:
                catalog_recipes = self._get_verified_matches(local_matches, intent_data)
                if catalog_recipes:
                    logger.info("Catalog criteria route: %s results, no remote search or verification", len(catalog_recipes))
            if catalog_recipes:
                report_progress("verifying")
                logger.info("Recipe route: prevalidated catalog; no retrieval or verification model calls")

            runtime_evidence_route = bool(not catalog_recipes and self.data_loader.recipe_lookup
                                          and not generate_first and not lookup_record and not is_recipe_adaptation
                                          and supports_local_matching(intent_data))
            if runtime_evidence_route:
                matches = []
                for record in self.data_loader.recipe_lookup.values():
                    recipe = self._build_recipe_data_from_record(record)
                    if self._normalize_recipe_name(recipe.get("name", "")) in excluded_names:
                        continue
                    if assess_local_recipe(recipe, intent_data)["status"] != "pass":
                        continue
                    compliance = aicr_service.validate_recipe_compliance(recipe)
                    if compliance.get("overall_compliant") is True:
                        matches.append(recipe)
                matches = self._deduplicate_recipes(matches)[:MAX_RECIPES_PER_RESPONSE]
                catalog_recipes = self._get_verified_matches(
                    self.recipe_verifier.batch_verify_recipes(matches, intent_data, aicr_service), intent_data
                ) if matches else []
                if not catalog_recipes:
                    generate_first = True
                logger.info("Runtime evidence route: %s source matches; %s", len(catalog_recipes),
                            "local checks only" if catalog_recipes else "generate without speculative catalog reviews")
            
            # Step 2: Multi-query search
            should_search = not (is_recipe_adaptation or lookup_record or generate_first or catalog_recipes)
            bounded_gentle_search = bool(
                should_search and query_type == "recipe_search" and not intent_data.get("budget_request")
                and intent_data.get("constraints", {}).get("digestive_comfort") == "gentle"
            )
            normalized_recipe_request = self._normalize_recipe_request(recipe_request_query)
            local_candidates = []
            docs = []
            if should_search:
                report_progress("searching")
                if bounded_gentle_search and settings.RECIPE_IO_WORKERS > 1:
                    with ThreadPoolExecutor(max_workers=2) as executor:
                        shortlist = executor.submit(
                            self._get_database_search_candidates, normalized_recipe_request, intent_data, set(),
                            settings.SEARCH_K, excluded_names=excluded_names
                        )
                        docs = self.search_engine.multi_query_search(effective_query, intent_data, k=settings.SEARCH_K * 2)
                        local_candidates = shortlist.result()
                else:
                    docs = self.search_engine.multi_query_search(effective_query, intent_data, k=settings.SEARCH_K * 2)
                    if bounded_gentle_search:
                        local_candidates = self._get_database_search_candidates(
                            normalized_recipe_request, intent_data, set(), settings.SEARCH_K, excluded_names=excluded_names
                        )
            logger.info(f"Search complete: {time.time() - start_time:.2f}s, found {len(docs)} docs")
            
            # Step 3: Reranking
            if docs:
                report_progress("ranking")
            ranking_candidates = self._timing_search_candidates(docs, intent_data)
            reranked_docs = [] if not ranking_candidates else self.search_engine.rerank_with_constraint_filtering(ranking_candidates, effective_query, intent_data, top_k=settings.SEARCH_K)
            logger.info(f"Reranking complete: {time.time() - start_time:.2f}s, {len(reranked_docs)} docs")
            
            # Step 4: Extract recipe details
            candidate_recipes = [self._build_recipe_data_from_record(lookup_record)] if lookup_record else combined_candidates
            if catalog_recipes:
                candidate_recipes = catalog_recipes[:MAX_RECIPES_PER_RESPONSE]
            for doc in reranked_docs:
                try:
                    candidate_recipes.append(self._build_recipe_data_from_doc(doc))
                except Exception as e:
                    logger.error(f"Error extracting recipe: {e}")
                    continue

            candidate_recipes = self._deduplicate_recipes(candidate_recipes)
            if intent_data.get("constraints", {}).get("time_max_minutes") is not None:
                candidate_recipes.sort(
                    key=lambda recipe: time_candidate_rank(recipe, intent_data["constraints"]), reverse=True
                )
            if is_more_request:
                candidate_recipes = self._exclude_previously_shown_recipes(candidate_recipes, previously_shown_names)
            logger.info(f"Extraction complete: {time.time() - start_time:.2f}s")
            if bounded_gentle_search:
                constraints = intent_data["constraints"]
                pool = self._deduplicate_recipes(candidate_recipes + local_candidates)
                pool = self._exclude_previously_shown_recipes(pool, excluded_names)
                pool = [recipe for recipe in pool if not audit_digestive_comfort(recipe, constraints)]
                pool.sort(key=lambda recipe: len(digestive_tolerance_cautions(recipe)))
                candidate_recipes = pool[:MAX_RECIPES_PER_RESPONSE]
                logger.info("Gentle recipe route: reviewing %s of %s locally shortlisted candidates",
                            len(candidate_recipes), len(pool))

            shared_fit_route = bool(
                query_type == "recipe_search" and not is_recipe_adaptation and not lookup_record
                and not catalog_recipes and not single_pass_dinner and not generate_first
                and not intent_data.get("budget_request")
                and isinstance(intent_data.get("requirement_coverage"), dict)
            )
            # Step 4.5: Fill missing ingredients/instructions before verification
            if catalog_recipes or single_pass_dinner:
                pass
            elif shared_fit_route and not requests_catalog_source(recipe_request_query):
                candidate_recipes = []
                logger.info("No established local match; routing directly to verified generation")
            elif shared_fit_route:
                deadline = model_deadline.get()
                fit_deadline = time.monotonic() + 6
                token = model_deadline.set(min(deadline, fit_deadline) if deadline is not None else fit_deadline)
                try:
                    candidate_recipes = self._verify_candidates(
                        candidate_recipes[:4], {**intent_data, "_shared_fit_batch": True}
                    )
                except RecipeModelUnavailable as error:
                    if not isinstance(error, ModelBudgetExhausted) and not isinstance(error.__cause__, Timeout):
                        raise
                    candidate_recipes = []
                    logger.info("Candidate fit review timed out; reserving remaining request time for generation")
                finally:
                    model_deadline.reset(token)
                logger.info("Shared candidate fit: %s accepted; no second catalog review round",
                            len(self._get_verified_matches(candidate_recipes, intent_data)))
            elif (len(candidate_recipes) >= MAX_RECIPES_PER_RESPONSE
                    and settings.RECIPE_IO_WORKERS >= MAX_RECIPES_PER_RESPONSE
                    and not self._has_valid_time_limit(intent_data)
                    and not intent_data.get("budget_request") and not is_recipe_adaptation
                    and intent_data.get("constraints", {}).get("digestive_comfort") != "gentle"
                    and all(recipe.get("database_record_found") and recipe.get("ingredients")
                            and recipe.get("instructions") and not self.recipe_verifier._requires_guideline_review(recipe)
                            for recipe in candidate_recipes)):
                first = self._verify_candidates(
                    candidate_recipes[:MAX_RECIPES_PER_RESPONSE], {**intent_data, "_parallel_catalog_verification": True}
                )
                if len(self._get_verified_matches(first, intent_data)) < MAX_RECIPES_PER_RESPONSE:
                    first.extend(self._verify_candidates(candidate_recipes[MAX_RECIPES_PER_RESPONSE:], intent_data))
                candidate_recipes = first
            else:
                candidate_recipes = self._verify_candidates(candidate_recipes, intent_data)
            logger.info("%s: %.2fs", "Local checks complete" if single_pass_dinner else "Batch verification complete",
                        time.time() - start_time)

            verified_recipes = self._get_verified_matches(candidate_recipes, intent_data)
            if not verified_recipes and not is_recipe_adaptation and not lookup_record and not generate_first and not bounded_gentle_search and not shared_fit_route:
                report_progress("searching_more")
                seen_ids = {self._get_recipe_identity(recipe) for recipe in candidate_recipes}
                additional = self._get_database_search_candidates(
                    normalized_recipe_request, intent_data, seen_ids, settings.SEARCH_K,
                    excluded_names=excluded_names
                )
                for doc in docs:
                    try:
                        recipe = self._build_recipe_data_from_doc(doc)
                        if self._get_recipe_identity(recipe) not in seen_ids:
                            additional.append(recipe)
                    except Exception as error:
                        logger.warning("Skipping invalid retrieval candidate: %s", error)
                additional = self._deduplicate_recipes(additional)
                if is_more_request:
                    additional = self._exclude_previously_shown_recipes(additional, previously_shown_names)
                candidate_recipes.extend(self._verify_candidates(additional[:settings.SEARCH_K], intent_data))
                candidate_recipes = self._deduplicate_recipes(candidate_recipes)
                verified_recipes = self._get_verified_matches(candidate_recipes, intent_data)
            
            # Separate passed/failed
            failed_recipes = [r for r in candidate_recipes if not r.get("verification_details", {}).get("passes_verification")]
            all_catalog_mismatches = all(
                recipe.get("verification_details", {}).get("catalog_yield_mismatch")
                or recipe.get("verification_details", {}).get("catalog_preflight_mismatch")
                for recipe in candidate_recipes
            )
            if (not verified_recipes and not generate_first and not lookup_record and not is_recipe_adaptation
                    and query_type == "recipe_search" and (candidate_recipes or servings is not None)
                    and not intent_data.get("budget_request") and settings.RECIPE_SINGLE_PASS_DINNER
                    and not intent_data.get("constraints", {}).get("health_conditions")
                    and not intent_data.get("constraints", {}).get("allergens_to_avoid")
                    and intent_data.get("constraints", {}).get("digestive_comfort") != "gentle"
                    and not any(intent_data.get("cancer_patient_specific", {}).values())
                    and all_catalog_mismatches):
                logger.info("Recipe route: catalog candidates failed concrete requirements; generating directly")
                report_progress("generating")
                intent_data.update(generation_recipe_count=3, generation_mode="single_pass")
                intent_data["exclude_dish_names"] = sorted(excluded_names)[:20]
                generated = generate_once(self.llm or self.intent_analyzer.llm, normalized_recipe_request,
                                          intent_data, self.recipe_verifier, aicr_service)
                verified_recipes = self._get_verified_matches(self._deduplicate_recipes(generated), intent_data)
                single_pass_dinner = composed_dinner = generate_first = True
            
            logger.info(f"Verification: {len(verified_recipes)} passed, {len(failed_recipes)} failed")
            
            # Step 6: Generate fallback if needed with AICR guidelines
            source_docs = verified_recipes
            if (shared_fit_route and 0 < len(source_docs) < MAX_RECIPES_PER_RESPONSE
                    and not requests_catalog_source(recipe_request_query)):
                source_docs = self._complete_composed_dinner(
                    normalized_recipe_request, intent_data, source_docs, failed_recipes
                )
            if (not catalog_recipes and 0 < len(source_docs) < MAX_RECIPES_PER_RESPONSE
                    and intent_data == simple_timed_intent(intent_data.get("resolved_query", ""))):
                report_progress("generating")
                existing_names = {self._normalize_recipe_name(recipe["name"]) for recipe in source_docs}
                missing = MAX_RECIPES_PER_RESPONSE - len(source_docs)
                additions = self.recipe_enhancer.generate_fallback_recipes(
                    f"{normalized_recipe_request}. Create {missing} additional distinct recipes, excluding: "
                    + ", ".join(recipe["name"] for recipe in source_docs),
                    intent_data, failed_recipes, grounding_recipes=source_docs,
                )
                additions = self._exclude_previously_shown_recipes(additions, existing_names)
                additions = self._deduplicate_recipes(additions)[:missing]
                source_docs = source_docs + self._get_verified_matches(self._verify_candidates(additions, intent_data), intent_data)
            
            if not verified_recipes or composed_dinner:
                grounding_recipes = referenced_recipes if is_recipe_adaptation else [
                    recipe for recipe in candidate_recipes
                    if recipe.get("database_record_found")
                    and (recipe.get("verification_details", {}).get("relevance") in {"match", "adaptable"}
                         or recipe.get("budget_verification_pending"))
                ][:3]
                if single_pass_dinner:
                    logger.info("Single-pass result: %s locally accepted recipes; no further model calls", len(verified_recipes))
                else:
                    logger.info("Generating recipes with %s database references", len(grounding_recipes))
                generation_query = normalized_recipe_request
                if is_more_request and previously_shown_names:
                    generation_query += (
                        ". Generate different recipes and do not repeat: "
                        + ", ".join(sorted(previously_shown_names))
                    )
                generated_recipes = verified_recipes if single_pass_dinner else self._complete_composed_dinner(
                    generation_query, intent_data, verified_recipes, failed_recipes
                ) if composed_dinner else self._generate_verified_fallback_recipes(
                    generation_query,
                    intent_data,
                    failed_recipes,
                    grounding_recipes=grounding_recipes,
                    excluded_names=excluded_names,
                    bounded=bounded_gentle_search or sparse_follow_up or runtime_evidence_route or shared_fit_route,
                )
                
                if generated_recipes:
                    source_docs = generated_recipes
                else:
                    return {
                        "query": query,
                        "response": (
                            self._recipe_shortage_message(intent_data, additional=True)
                            if is_more_request else
                            (self._recipe_shortage_message(intent_data) if single_pass_dinner or redirect_red_meat or intent_data.get("budget_request") else
                             self.response_generator.generate_helpful_no_results_message(effective_query, intent_data))
                        ),
                        "source": "no_results",
                        "matches_found": 0,
                        "mode": mode,
                        "intent_analysis": intent_data,
                        "source_documents": []
                    }
            
            recipe_limit = min(MAX_RECIPES_PER_RESPONSE, len(referenced_recipes)) if is_recipe_adaptation else MAX_RECIPES_PER_RESPONSE
            if not redirect_red_meat and (lookup_record or (servings is not None and re.search(r"\ba\s+recipe\b", query, re.I))):
                recipe_limit = 1
            if generate_first or not settings.RECIPE_OPTIONAL_ENHANCEMENT:
                source_docs = [self._ensure_recipe_id(recipe) for recipe in source_docs[:recipe_limit]]
            else:
                source_docs = self._enhance_verified_recipes(source_docs[:recipe_limit], intent_data)
            report_progress("finalizing")
            source_docs = self._deduplicate_recipes(source_docs)
            source_docs = self._apply_deterministic_constraints(source_docs, intent_data)
            source_docs = self._annotate_recipe_source_tiers(source_docs)
            if is_more_request:
                source_docs = self._exclude_previously_shown_recipes(source_docs, previously_shown_names)
            source_docs = source_docs[:MAX_RECIPES_PER_RESPONSE]
            logger.info(f"Enhancement complete: {time.time() - start_time:.2f}s")

            if not source_docs:
                return {
                    "query": query,
                    "response": (
                        self._recipe_shortage_message(intent_data, additional=True)
                        if is_more_request else
                        (self._recipe_shortage_message(intent_data) if intent_data.get("budget_request") else
                         "I couldn't verify a recipe that meets your requirements right now. Please try again.")
                    ),
                    "source": "no_results",
                    "matches_found": 0,
                    "mode": mode,
                    "intent_analysis": intent_data,
                    "source_documents": []
                }
            
            # Step 8: Generate response
            if is_recipe_adaptation and intent_data.get("recipe_context"):
                intent_data["recipe_context"] = {
                    **intent_data["recipe_context"],
                    "selected_recipe_ids": [recipe["recipe_id"] for recipe in source_docs],
                    "waiting_for": None,
                }
            report_progress("summarizing")
            response_text = self.response_generator.generate_personalized_response(effective_query, source_docs, intent_data)
            if redirect_red_meat:
                shortage = (f" I could {'return' if single_pass_dinner else 'verify'} {len(source_docs)} of the three alternatives."
                            if len(source_docs) < MAX_RECIPES_PER_RESPONSE and not confirmed_alternatives else "")
                response_text = f"{RED_MEAT_ALTERNATIVE_NOTE}{shortage}\n\n{response_text}"
            
            total_time = time.time() - start_time
            logger.info(f"TOTAL TIME: {total_time:.2f}s")
            follow_up = intent_data.pop("_generated_follow_up", None)
            
            return {
                "query": query,
                "response": response_text,
                "source": self._classify_response_source(source_docs),
                "matches_found": len(source_docs),
                "mode": mode,
                "source_documents": source_docs,
                **({"follow_up": follow_up} if follow_up else {}),
                "intent_analysis": intent_data,
                "dynamically_adapted": any(doc.get("dynamically_adapted", False) for doc in source_docs),
                "instructions_generated": any(doc.get("instructions_generated", False) for doc in source_docs),
                "aicr_compliant": all(doc.get("aicr_compliance", {}).get("overall_compliant", False) for doc in source_docs),
                "verification_details": {
                    "total_candidates": len(candidate_recipes),
                    "passed_verification": len(verified_recipes),
                    "failed_verification": len(failed_recipes),
                    "llm_generated": len([doc for doc in source_docs if doc.get("source_tier") == "llm_generated"]),
                    "database_exact": len([doc for doc in source_docs if doc.get("source_tier") == "database_exact"]),
                    "database_completed": len([doc for doc in source_docs if doc.get("source_tier") == "database_completed"])
                },
                "performance": {
                    "total_time_seconds": round(total_time, 2)
                },
                "conversation_context_used": context_used,
                "previous_messages_considered": len(recipe_history) if context_used else 0
            }
            
        except RecipeRequestCancelled:
            raise
        except RecipeModelUnavailable as error:
            logger.error("Recipe model unavailable (configured model: %s)", settings.LLM_MODEL)
            timed_out = isinstance(error, ModelBudgetExhausted) or isinstance(error.__cause__, Timeout)
            return {
                "query": query,
                "response": (
                    "The recipe check didn’t finish, so I’m not showing an unchecked recipe. "
                    "If you share one ingredient you already have, I can look for a simpler option under the same requirements."
                    if timed_out else
                    "The recipe service is temporarily unavailable, so I couldn't complete recipe verification. Please try again later."
                ),
                "source": "error", "matches_found": 0, "mode": mode, "source_documents": [],
            }
        except Exception as e:
            logger.error(f"Error processing query: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {
                "query": query,
                "response": "I apologize for the error. Please try rephrasing your question.",
                "source": "error",
                "matches_found": 0,
                "mode": mode,
                "source_documents": []
            }

    def _recipe_shortage_message(self, intent_data, additional=False):
        budget = intent_data.get("budget_request")
        redirect = intent_data.get("red_meat_alternatives")
        prefix = RED_MEAT_ALTERNATIVE_NOTE + "\n\n" if redirect else ""
        if budget:
            continuation = "I excluded recipes already shown. " if additional else ""
            suggestion = "Tell me which ingredients and quantities you already have, and I can check a different meal without raising your budget."
            if redirect:
                suggestion = "If you're open to unprocessed poultry or fish, tell me which you prefer and what you already have. I can check another option at the same budget."
            return prefix + budget_no_results(intent_data) + " " + continuation + suggestion
        subject = "an additional recipe" if additional else "a matching recipe"
        return prefix + (
            f"I couldn't confirm {subject} that meets all your requirements. "
            "Tell me one ingredient you'd like to use, or which preference is flexible, and I can suggest a different option without dropping your restrictions."
        )

    def _contains_phi_like_content(self, query: str, conversation_history: Optional[List[Dict]] = None) -> bool:
        normalized = query.lower()
        if STREET_ADDRESS_DISCLOSURE.search(normalized) or PERSONAL_LOCATION_DISCLOSURE.search(normalized):
            return True
        if re.search(r"\b(?:groceries|grocery|markets?|stores?)\b", normalized):
            normalized = LABELED_ZIP.sub("", normalized)

        strong_identifier_patterns = [
            r"\b(?:my (?:full |legal )?name is|name\s*:|i go by)\s+[a-z][a-z'’-]*\b",
            r"\b\d{3}-\d{2}-\d{4}\b",  # SSN
            r"\b(?:mrn|medical record number|member id|insurance id|policy number|claim number|patient identifier|patient id|unique patient identifier|account number|license number|certificate number|device identifier|vehicle identifier)\b",
            r"\b(?:date of birth|dob|born on|my birthday)\b",
            r"\b[\w\.-]+@[\w\.-]+\.\w+\b",  # email
            r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b",  # phone
            r"\b[a-z]{1,6}-?\d{4,}\b",  # PT-00077891, MRN12345, ID998877
            r"\b\d{5,}\b"  # long unique numeric identifiers
        ]

        health_context_terms = {
            "diet",
            "recipe",
            "meal",
            "nutrition",
            "symptom",
            "symptoms",
            "treatment",
            "diagnosis",
            "condition",
            "cancer",
            "nausea",
            "allergy",
            "doctor",
            "hospital",
            "insurance",
            "medication",
            "patient",
            "health"
        }

        direct_personal_patterns = [
            r"\bmy name is\s+[a-z]+(?:\s+[a-z]+)?\b",
            r"\bfor my\s+(?:mother|father|mom|dad|son|daughter|wife|husband|brother|sister|friend|patient)\b",
            r"\bpatient\s+[a-z]+(?:\s+[a-z]+){0,2}\b",
            r"\bmember\s+[a-z]+(?:\s+[a-z]+){0,2}\b",
            r"\blive at\b",
            r"\bmy address is\b",
            r"\bmy phone number is\b",
            r"\bmy email is\b"
        ]

        identifier_value_patterns = [
            r"\b(?:patient identifier|patient id|member id|medical record number|mrn|insurance id|policy number|claim number|account number|device identifier|vehicle identifier)\s*[:#-]?\s*[a-z0-9-]{4,}\b",
            r"\b(?:identifier|id)\s*[:#-]?\s*[a-z]{0,4}-?\d{4,}\b"
        ]

        has_health_context = any(term in normalized for term in health_context_terms)
        has_strong_identifier = any(re.search(pattern, normalized) for pattern in strong_identifier_patterns)
        has_direct_personal_info = any(re.search(pattern, normalized) for pattern in direct_personal_patterns)
        has_identifier_value = any(re.search(pattern, normalized) for pattern in identifier_value_patterns)
        has_name_like_reference = self._has_name_like_reference(normalized)
        has_explicit_identity_phrase = bool(
            re.search(r"\b(?:my name is|patient\s+[a-z]+|member\s+[a-z]+|for my\s+(?:mother|father|mom|dad|son|daughter|wife|husband|brother|sister|friend|patient))\b", normalized)
        )

        return (
            has_strong_identifier or
            has_identifier_value or
            (has_direct_personal_info and has_health_context and has_explicit_identity_phrase) or
            (has_name_like_reference and has_health_context)
        )

    def _has_name_like_reference(self, normalized_query: str) -> bool:
        name_reference_matches = re.finditer(r"\b(?:patient|member)\s+([a-z]+(?:\s+[a-z]+){0,2})\b", normalized_query)
        excluded_terms = {
            "breakfast", "lunch", "dinner", "snack", "dessert", "meal", "meals", "recipe", "recipes",
            "diet", "diets", "nutrition", "healthy", "nutritious", "vegetarian", "vegan", "protein",
            "chinese", "indian", "mexican", "italian", "mediterranean", "thai", "japanese", "korean",
            "more", "other", "another", "missing", "these", "those", "them", "options", "ideas",
            "today", "tonight", "week", "weekend", "runner", "running", "muscle", "cramps",
            "me", "myself", "us", "ourselves", "you", "yourself", "someone", "anyone"
        }

        for match in name_reference_matches:
            candidate = match.group(1).strip()
            candidate_tokens = [token for token in candidate.split() if token]
            if candidate_tokens and all(token not in excluded_terms for token in candidate_tokens):
                return True

        return False

    def _build_phi_redirect_response(
        self,
        query: str,
        mode: str,
        conversation_history: Optional[List[Dict]] = None
    ) -> Dict[str, Any]:
        response_text = (
            "Please don’t share personal or identifying health information here, such as names, where you live, "
            "contact details, dates of birth, or medical record numbers. "
            "You can ask for recipes or nutrition guidance without those details."
        )

        return {
            "query": "[Personal information omitted]",
            "response": response_text,
            "source": "privacy_redirect",
            "matches_found": 0,
            "mode": mode,
            "source_documents": [],
            "intent_analysis": {
                "query_type": "privacy_redirect",
                "constraints": {},
                "preferences": {},
                "cancer_patient_specific": {},
                "search_strategy": {
                    "primary_focus": "privacy_redirect",
                    "search_keywords": [],
                    "must_match_criteria": [],
                    "enhanced_query": query
                }
            },
            "dynamically_adapted": False,
            "instructions_generated": False,
            "aicr_compliant": False,
            "verification_details": {
                "total_candidates": 0,
                "passed_verification": 0,
                "failed_verification": 0,
                "llm_generated": 0
            },
            "performance": {
                "total_time_seconds": 0
            },
            "conversation_context_used": conversation_history is not None and len(conversation_history) > 0,
            "previous_messages_considered": len(conversation_history) if conversation_history else 0
        }

    def _is_small_talk_query(self, query: str, allow_heuristic: bool = True) -> bool:
        normalized = re.sub(r"\s+", " ", query.lower()).strip()
        normalized = re.sub(r"[^\w\s]", "", normalized)

        if not normalized:
            return True

        small_talk_patterns = {
            "hi",
            "hello",
            "hey",
            "good morning",
            "good afternoon",
            "good evening",
            "how are you",
            "whats up",
            "what is up",
            "howdy",
            "yo",
            "sup",
            "thanks",
            "thank you",
            "ok",
            "okay"
        }

        conversational_patterns = [
            r"^hi(?:\s+there)?$",
            r"^hello(?:\s+there)?$",
            r"^hey(?:\s+there)?$",
            r"^how are you(?: doing)?(?: today)?$",
            r"^hows it going(?: today)?$",
            r"^what are you doing(?: today)?$",
            r"^whats up(?: today)?$",
            r"^can you help me$",
            r"^who are you$",
            r"^what can you do$",
            r"^thanks(?: you)?$"
        ]

        recipe_keywords = {
            "recipe",
            "recipes",
            "meal",
            "meals",
            "diet",
            "dietary",
            "eat",
            "eating",
            "food",
            "foods",
            "cook",
            "cooking",
            "ingredients",
            "nutrition",
            "nutritious",
            "healthy",
            "symptom",
            "symptoms",
            "side",
            "effect",
            "effects",
            "protein",
            "calories",
            "microwave",
            "breakfast",
            "lunch",
            "dinner",
            "snack",
            "vegetarian",
            "vegan",
            "nausea",
            "fever",
            "swallow",
            "appetite"
        }

        recipe_request_patterns = [
            r"\bbreakfasts?\b",
            r"\blunch(?:es)?\b",
            r"\bdinners?\b",
            r"\bsnacks?\b",
            r"\bmeal(?:s)?\b",
            r"\brecipe(?:s)?\b",
            r"\bmeal ideas?\b",
            r"\bbreakfast ideas?\b",
            r"\blunch ideas?\b",
            r"\bdinner ideas?\b",
            r"\bsnack ideas?\b",
            r"\bcould you provide me some\b",
            r"\bshow me some\b",
            r"\bgive me some\b",
            r"\bfind me some\b",
            r"\bsheet pan\b",
            r"\broasted vegetables?\b",
            r"\bvegetables and beans\b"
        ]

        if any(keyword in normalized.split() for keyword in recipe_keywords):
            return False

        if any(re.search(pattern, normalized) for pattern in recipe_request_patterns):
            return False

        if normalized in small_talk_patterns:
            return True

        if any(re.fullmatch(pattern, normalized) for pattern in conversational_patterns):
            return True

        if not allow_heuristic:
            return False

        # Short noun-phrase prompts are often recipe lookups rather than small talk.
        if len(normalized.split()) >= 2:
            conversational_verbs = {
                "are", "am", "is", "was", "were", "do", "does", "did",
                "can", "could", "would", "should", "who", "what", "why", "how",
                "thanks", "thank", "hello", "hi", "hey"
            }
            words = normalized.split()
            if not any(word in conversational_verbs for word in words):
                return False

        # Short, non-domain prompts are treated as conversation instead of recipe requests.
        if len(normalized.split()) <= 6:
            return True

        return False

    def _build_small_talk_response(
        self,
        query: str,
        mode: str,
        conversation_history: Optional[List[Dict]] = None
    ) -> Dict[str, Any]:
        normalized = re.sub(r"\s+", " ", query.lower()).strip()

        if normalized in {"thanks", "thank you"}:
            response_text = (
                "Thanks for reaching out. Please ask me about diet-based, nutrition, or recipe-related questions and I’ll be happy to help."
            )
        elif normalized in {"how are you", "how are you doing today", "whats up", "what is up"}:
            response_text = (
                "Thanks for reaching out. Please ask me about diet-based recipe-related questions, meal ideas, symptoms, or ingredients you want to work with."
            )
        else:
            response_text = (
                "Thanks for reaching out. Please ask me about diet-based recipe-related questions, nutrition-friendly meals, symptom-aware food suggestions, or cooking with ingredients you already have."
            )

        return {
            "query": query,
            "response": response_text,
            "source": "conversation",
            "matches_found": 0,
            "mode": mode,
            "source_documents": [],
            "intent_analysis": {
                "query_type": "small_talk",
                "constraints": {},
                "preferences": {},
                "cancer_patient_specific": {},
                "search_strategy": {
                    "primary_focus": "conversation",
                    "search_keywords": [],
                    "must_match_criteria": [],
                    "enhanced_query": query
                }
            },
            "dynamically_adapted": False,
            "instructions_generated": False,
            "aicr_compliant": False,
            "verification_details": {
                "total_candidates": 0,
                "passed_verification": 0,
                "failed_verification": 0,
                "llm_generated": 0
            },
            "performance": {
                "total_time_seconds": 0
            },
            "conversation_context_used": conversation_history is not None and len(conversation_history) > 0,
            "previous_messages_considered": len(conversation_history) if conversation_history else 0
        }
    
    def search_recipes(self, query: str, k: int = None) -> List[Dict[str, Any]]:
        """Search for recipes"""
        if not self.is_initialized:
            raise ValueError("RAG system not initialized")
        
        k = k or settings.SEARCH_K
        intent_data = self.intent_analyzer.understand_query_intent(query)
        docs = self.search_engine.multi_query_search(query, intent_data, k=k)
        reranked_docs = self.search_engine.rerank_with_constraint_filtering(docs, query, intent_data, top_k=k)
        
        recipes = []
        for doc in reranked_docs:
            try:
                recipe = self._build_recipe_data_from_doc(doc)
                
                # Add AICR validation to search results
                aicr_compliance = aicr_service.validate_recipe_compliance(recipe)
                recipe["aicr_compliance"] = aicr_compliance
                
                recipes.append(recipe)
            except Exception as e:
                logger.error(f"Error processing document: {e}")
                continue

        recipes = self._deduplicate_recipes(recipes)
        recipes = self._apply_deterministic_constraints(recipes, intent_data)
        return self._annotate_recipe_source_tiers(recipes)[:MAX_RECIPES_PER_RESPONSE]
    
    def get_system_info(self) -> Dict[str, Any]:
        """Get system information"""
        aicr_guidelines = aicr_service.get_guidelines()
        return {
            "initialized": self.is_initialized,
            "initialization_error": self.initialization_error,
            "recipes_loaded": self.data_loader.recipes_count if self.data_loader else 0,
            "vector_store_ready": self.vector_store is not None,
            "supports_dynamic_adaptation": True,
            "supports_constraint_based_search": True,
            "supports_recipe_verification": True,
            "supports_llm_generation": True,
            "supports_aicr_guidelines": True,
            "supports_conversation_context": True,
            "optimizations": {
                "batch_verification": True,
                "parallel_enhancement": True,
                "combined_enhancement": True,
                "token_reduction": True,
                "advanced_caching": True,
                "aicr_validation": True,
                "conversation_context": True
            },
            "cache_statistics": self.get_combined_cache_stats(),
            "aicr_guidelines": {
                "loaded": aicr_service._initialized,
                "source": aicr_guidelines["metadata"]["source"],
                "version": aicr_guidelines["metadata"]["version"]
            }
        }
    
    def get_combined_cache_stats(self) -> Dict[str, Any]:
        """Combine cache stats from all services"""
        return {
            "intent_analyzer": self.intent_analyzer.get_cache_stats(),
            "recipe_verifier": self.recipe_verifier.get_cache_stats(),
            "recipe_enhancer": self.recipe_enhancer.get_cache_stats()
        }
    
    def clear_caches(self):
        """Clear all caches"""
        self.intent_analyzer.clear_caches()
        self.recipe_verifier.clear_caches()
        self.recipe_enhancer.clear_caches()
        logger.info("All caches cleared")

# Global instance
rag_service = RecipeRAGService()
