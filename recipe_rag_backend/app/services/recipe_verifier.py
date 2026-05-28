import logging
import json
import time
import hashlib
import re
from typing import List, Dict, Any
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

class RecipeVerifier:
    def __init__(self):
        self.llm = None
        self.verification_cache = {}
        self.cache_hits = 0
        self.cache_misses = 0
        
    def initialize(self, llm):
        self.llm = llm

    def _get_constraints_hash(self, intent_data: Dict[str, Any]) -> str:
        """Create a stable hash of constraints for cache keys"""
        constraints = intent_data.get("constraints", {})
        constraint_str = json.dumps(constraints, sort_keys=True)
        return hashlib.md5(constraint_str.encode()).hexdigest()[:16]
    
    def batch_verify_recipes(self, recipes: List[Dict[str, Any]], intent_data: Dict[str, Any], aicr_service) -> List[Dict[str, Any]]:
        """Batch verification with AICR validation"""
        if not recipes:
            return []
        
        try:
            recipes_for_verification = []
            for i, recipe in enumerate(recipes):
                recipes_for_verification.append({
                    "id": i,
                    "name": recipe.get("name", "Unknown"),
                    "type": recipe.get("type", "Unknown"),
                    "ingredients": recipe.get("ingredients", [])[:15],
                    "ingredient_count": len(recipe.get("ingredients", []))
                })
            
            batch_prompt = self._build_batch_verification_prompt(recipes_for_verification, intent_data)
            
            start_time = time.time()
            response = self.llm.predict(batch_prompt)
            logger.info(f"Batch verification took {time.time() - start_time:.2f}s for {len(recipes)} recipes")
            
            verification_results = self._parse_verification_response(response)
            results_map = {r["id"]: r for r in verification_results}
            
            for i, recipe in enumerate(recipes):
                if i in results_map:
                    verification = results_map[i]
                    recipe["verification_details"] = {
                        "passes_verification": verification.get("passes_verification", False),
                        "verification_score": verification.get("verification_score", 0),
                        "reasoning": verification.get("reasoning", ""),
                        "constraint_violations": verification.get("constraint_violations", []),
                        "meets_preferences": True
                    }
                    
                    # AICR validation layer
                    if recipe["verification_details"]["passes_verification"]:
                        aicr_compliance = aicr_service.validate_recipe_compliance(recipe)
                        recipe["aicr_compliance"] = aicr_compliance
                        
                        if not aicr_compliance["overall_compliant"]:
                            recipe["verification_details"]["passes_verification"] = False
                            recipe["verification_details"]["constraint_violations"].extend(
                                aicr_compliance["warnings"]
                            )
                            logger.warning(f"Recipe '{recipe.get('name')}' failed AICR validation (score: {aicr_compliance['score']})")
                    
                    status = "PASSED" if recipe["verification_details"]["passes_verification"] else "FAILED"
                    logger.info(f"Recipe '{recipe.get('name')}' - {status}")
                else:
                    recipe["verification_details"] = {
                        "passes_verification": False,
                        "verification_score": 0,
                        "reasoning": "Not included in batch verification results",
                        "constraint_violations": ["Verification failed"],
                        "meets_preferences": False
                    }
            
            return recipes
            
        except Exception as e:
            logger.error(f"Error in batch verification: {e}")
            logger.warning("Batch verification failed, falling back to individual verification")
            return self._fallback_individual_verification(recipes, intent_data, aicr_service)

    def _build_batch_verification_prompt(self, recipes_for_verification: List[Dict], intent_data: Dict[str, Any]) -> str:
        """Build batch verification prompt"""
        return f"""You are a STRICT recipe verification system for nutrition-focused recipes. Verify ALL these recipes against user requirements IN ONE RESPONSE.

RECIPES TO VERIFY:
{json.dumps(recipes_for_verification, indent=2)}

USER REQUIREMENTS:
{json.dumps(intent_data, indent=2)}

YOUR TASK:
Verify EACH recipe (by id) against ALL constraints in "constraints" section.
- Understand constraints semantically
- Count/measure as needed
- Enforce numeric constraints strictly
- ANY constraint violation = FAIL for that recipe

Return ONLY valid JSON array with results for EACH recipe:
[
    {{
        "id": 0,
        "passes_verification": true/false,
        "verification_score": 0-100,
        "reasoning": "Brief explanation",
        "constraint_violations": ["violation"] or []
    }},
    ...
]

Verify ALL {len(recipes_for_verification)} recipes.
"""

    def _parse_verification_response(self, response: str) -> List[Dict[str, Any]]:
        """Parse verification response from LLM"""
        response = response.strip()
        if response.startswith("```json"):
            response = response[7:]
        elif response.startswith("```"):
            response = response[3:]
        if response.endswith("```"):
            response = response[:-3]
        response = response.strip()
        
        return json.loads(response)

    def _fallback_individual_verification(self, recipes: List[Dict[str, Any]], intent_data: Dict[str, Any], aicr_service) -> List[Dict[str, Any]]:
        """Fallback: verify recipes individually if batch fails"""
        for recipe in recipes:
            verification_result = self.verify_recipe_against_constraints(recipe, intent_data)
            recipe["verification_details"] = verification_result
            
            # Add AICR validation
            if verification_result.get("passes_verification"):
                aicr_compliance = aicr_service.validate_recipe_compliance(recipe)
                recipe["aicr_compliance"] = aicr_compliance
                if not aicr_compliance["overall_compliant"]:
                    recipe["verification_details"]["passes_verification"] = False
        return recipes

    def verify_recipe_against_constraints(self, recipe_data: Dict[str, Any], intent_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        CACHED: Universal LLM verification - completely dynamic for ANY constraint.
        """
        recipe_name = recipe_data.get("name", "Unknown")
        
        constraints_hash = self._get_constraints_hash(intent_data)
        cache_key = f"{recipe_name}_{constraints_hash}"
        
        if cache_key in self.verification_cache:
            self.cache_hits += 1
            logger.info(f"Verification cache HIT for '{recipe_name}'")
            return self.verification_cache[cache_key]
        
        self.cache_misses += 1
        
        try:
            ingredients = recipe_data.get("ingredients", [])
            recipe_name = recipe_data.get("name", "Unknown")
            constraints = intent_data.get("constraints", {})
            recipe_text = " ".join([
                recipe_name,
                recipe_data.get("type", ""),
                recipe_data.get("description", ""),
                recipe_data.get("content", ""),
                " ".join(ingredients)
            ]).lower()
            
            if not ingredients and any(constraints.values()):
                logger.warning(f"Recipe '{recipe_name}' has no ingredient data but constraints exist")
                return {
                    "passes_verification": False,
                    "verification_score": 0,
                    "reasoning": "Recipe lacks ingredient data needed for verification",
                    "constraint_violations": ["Missing ingredient data"],
                    "meets_preferences": False
                }

            if self._should_avoid_red_meat(constraints) and self._contains_red_meat(recipe_text):
                return {
                    "passes_verification": False,
                    "verification_score": 0,
                    "reasoning": "Recipe contains red meat or pork, which conflicts with the conversation dietary preference.",
                    "constraint_violations": ["Contains red meat or pork"],
                    "meets_preferences": False
                }
            
            verification_prompt = self._build_individual_verification_prompt(recipe_data, intent_data)
            response = self.llm.predict(verification_prompt)
            
            verification_result = self._parse_individual_verification_response(response)
            
            status = "PASSED" if verification_result.get('passes_verification') else "FAILED"
            score = verification_result.get('verification_score', 0)
            logger.info(f"Verification: {recipe_name} - {status} (score: {score})")
            
            self.verification_cache[cache_key] = verification_result
            return verification_result
            
        except Exception as e:
            logger.error(f"Error in verification: {e}")
            return {
                "passes_verification": False,
                "verification_score": 0,
                "reasoning": f"Verification system error: {str(e)}",
                "constraint_violations": ["System error during verification"],
                "verification_error": str(e)
            }

    def _should_avoid_red_meat(self, constraints: Dict[str, Any]) -> bool:
        if constraints.get("avoid_red_meat"):
            return True

        dietary_restrictions = [str(item).lower() for item in constraints.get("dietary_restrictions", [])]
        return any(
            phrase in restriction
            for restriction in dietary_restrictions
            for phrase in ("red meat", "no pork", "avoid pork")
        )

    def _contains_red_meat(self, recipe_text: str) -> bool:
        red_meat_keywords = [
            "beef",
            "pork",
            "lamb",
            "ham",
            "bacon",
            "sausage",
            "prosciutto",
            "pepperoni",
            "salami"
        ]
        return any(keyword in recipe_text for keyword in red_meat_keywords)

    def _build_individual_verification_prompt(self, recipe_data: Dict[str, Any], intent_data: Dict[str, Any]) -> str:
        """Build individual verification prompt"""
        return f"""You are a STRICT recipe verification system. Verify if this recipe meets the user's requirements.

RECIPE:
{json.dumps({
    "name": recipe_data.get("name", "Unknown"),
    "type": recipe_data.get("type", "Unknown"),
    "description": recipe_data.get("description", ""),
    "ingredients": recipe_data.get("ingredients", []),
    "content": recipe_data.get("content", "")[:500]
}, indent=2)}

USER REQUIREMENTS:
{json.dumps(intent_data, indent=2)}

YOUR TASK:
Read the entire intent data structure. The "constraints" section contains HARD requirements that MUST be met exactly.

Evaluate this recipe against ALL constraints intelligently:
- Understand what each constraint means semantically
- Count/measure/assess as needed
- For numeric constraints: enforce them strictly
- For categorical constraints: check compliance
- ANY constraint violation = FAIL

Return ONLY valid JSON:
{{
    "passes_verification": true/false,
    "verification_score": 0-100,
    "reasoning": "Clear explanation of decision",
    "constraint_violations": ["specific violation"] or [],
    "meets_preferences": true/false
}}
"""

    def _parse_individual_verification_response(self, response: str) -> Dict[str, Any]:
        """Parse individual verification response"""
        response = response.strip()
        if response.startswith("```json"):
            response = response[7:]
        elif response.startswith("```"):
            response = response[3:]
        if response.endswith("```"):
            response = response[:-3]
        response = response.strip()
        
        return json.loads(response)

    def verify_multiple_recipes_parallel(self, recipes: List[Dict[str, Any]], intent_data: Dict[str, Any], aicr_service, max_workers: int = 3) -> List[Dict[str, Any]]:
        """
        Verify multiple recipes in parallel using ThreadPoolExecutor
        Useful when batch verification fails and we need faster individual verification
        """
        if not recipes:
            return []
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_recipe = {
                executor.submit(self.verify_recipe_against_constraints, recipe, intent_data): recipe
                for recipe in recipes
            }
            
            verified_recipes = []
            for future in as_completed(future_to_recipe):
                try:
                    recipe = future_to_recipe[future]
                    verification_result = future.result()
                    recipe["verification_details"] = verification_result
                    
                    # Add AICR validation
                    if verification_result.get("passes_verification"):
                        aicr_compliance = aicr_service.validate_recipe_compliance(recipe)
                        recipe["aicr_compliance"] = aicr_compliance
                        if not aicr_compliance["overall_compliant"]:
                            recipe["verification_details"]["passes_verification"] = False
                    
                    verified_recipes.append(recipe)
                except Exception as e:
                    recipe = future_to_recipe[future]
                    logger.error(f"Error verifying recipe {recipe.get('name')}: {e}")
                    recipe["verification_details"] = {
                        "passes_verification": False,
                        "verification_score": 0,
                        "reasoning": f"Verification error: {str(e)}",
                        "constraint_violations": ["System error during verification"]
                    }
                    verified_recipes.append(recipe)
        
        return verified_recipes

    def get_verification_summary(self, recipes: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Get summary of verification results"""
        total = len(recipes)
        passed = sum(1 for r in recipes if r.get("verification_details", {}).get("passes_verification", False))
        failed = total - passed
        
        avg_score = 0
        if total > 0:
            scores = [r.get("verification_details", {}).get("verification_score", 0) for r in recipes]
            avg_score = sum(scores) / len(scores)
        
        common_violations = {}
        for recipe in recipes:
            violations = recipe.get("verification_details", {}).get("constraint_violations", [])
            for violation in violations:
                common_violations[violation] = common_violations.get(violation, 0) + 1
        
        return {
            "total_recipes": total,
            "passed_verification": passed,
            "failed_verification": failed,
            "success_rate": round((passed / total) * 100, 2) if total > 0 else 0,
            "average_score": round(avg_score, 2),
            "common_violations": dict(sorted(common_violations.items(), key=lambda x: x[1], reverse=True)[:5])
        }

    def clear_recipe_verification(self, recipe: Dict[str, Any]):
        """Clear verification data from a recipe (useful for re-verification)"""
        keys_to_remove = ["verification_details", "aicr_compliance"]
        for key in keys_to_remove:
            recipe.pop(key, None)

    def force_reverify_recipe(self, recipe: Dict[str, Any], intent_data: Dict[str, Any], aicr_service) -> Dict[str, Any]:
        """Force re-verification of a recipe, bypassing cache"""
        self.clear_recipe_verification(recipe)
        return self.verify_recipe_against_constraints(recipe, intent_data)

    def get_cache_stats(self) -> Dict[str, Any]:
        return {
            "cache_size": len(self.verification_cache),
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "hit_rate": f"{round(self.cache_hits / max(self.cache_hits + self.cache_misses, 1) * 100, 1)}%"
        }

    def clear_caches(self):
        self.verification_cache.clear()
        self.cache_hits = 0
        self.cache_misses = 0
        logger.info("Verification caches cleared")

    def get_detailed_cache_info(self) -> Dict[str, Any]:
        """Get detailed cache information"""
        cache_keys = list(self.verification_cache.keys())
        sample_keys = cache_keys[:5] if len(cache_keys) > 5 else cache_keys
        
        return {
            "total_cached_recipes": len(self.verification_cache),
            "sample_cached_items": sample_keys,
            "cache_memory_estimate_mb": len(json.dumps(self.verification_cache).encode('utf-8')) / (1024 * 1024),
            "performance_metrics": {
                "cache_hit_rate": round(self.cache_hits / max(self.cache_hits + self.cache_misses, 1) * 100, 2),
                "total_verifications": self.cache_hits + self.cache_misses,
                "cache_efficiency": "HIGH" if (self.cache_hits / max(self.cache_hits + self.cache_misses, 1)) > 0.7 else "LOW"
            }
        }
