import logging
import json
import re
import hashlib
from typing import List, Dict, Any
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

class RecipeEnhancer:
    def __init__(self):
        self.llm = None
        self.aicr_service = None
        self.enhancement_cache = {}
        self.cache_hits = 0
        self.cache_misses = 0
        
    def initialize(self, llm, aicr_service):
        self.llm = llm
        self.aicr_service = aicr_service

    def _get_constraints_hash(self, intent_data: Dict[str, Any]) -> str:
        """Create a stable hash of constraints for cache keys"""
        constraints = intent_data.get("constraints", {})
        constraint_str = json.dumps(constraints, sort_keys=True)
        return hashlib.md5(constraint_str.encode()).hexdigest()[:16]
    
    def batch_enhance_recipes(self, recipes: List[Dict[str, Any]], intent_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Batch enhancement of recipes"""
        if not recipes:
            return []
        
        recipes_to_enhance = recipes[:3]
        
        with ThreadPoolExecutor(max_workers=3) as executor:
            future_to_recipe = {
                executor.submit(self.enhance_single_recipe, recipe, intent_data): recipe
                for recipe in recipes_to_enhance
            }
            
            enhanced_recipes = []
            for future in as_completed(future_to_recipe):
                try:
                    enhanced_recipe = future.result()
                    enhanced_recipes.append(enhanced_recipe)
                except Exception as e:
                    original_recipe = future_to_recipe[future]
                    logger.error(f"Error enhancing recipe {original_recipe.get('name')}: {e}")
                    enhanced_recipes.append(original_recipe)
        
        recipe_map = {r.get("name"): r for r in enhanced_recipes}
        ordered_enhanced = [recipe_map.get(r.get("name"), r) for r in recipes_to_enhance]
        
        return ordered_enhanced + recipes[3:]
    
    def enhance_single_recipe(self, recipe_data: Dict[str, Any], intent_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        CACHED: Combines instruction generation + adaptation into ONE LLM call.
        """
        recipe_name = recipe_data.get("name", "Unknown")
        
        constraints_hash = self._get_constraints_hash(intent_data)
        cache_key = f"{recipe_name}_{constraints_hash}_enhanced"
        
        if cache_key in self.enhancement_cache:
            self.cache_hits += 1
            logger.info(f"Enhancement cache HIT for '{recipe_name}'")
            return self.enhancement_cache[cache_key]
        
        self.cache_misses += 1
        
        enhanced_recipe = recipe_data.copy()
        
        constraints = intent_data.get("constraints", {})
        preferences = intent_data.get("preferences", {})
        cancer_specific = intent_data.get("cancer_patient_specific", {})
        
        needs_instructions = enhanced_recipe.get("needs_instruction_generation") and enhanced_recipe.get("ingredients")
        needs_adaptation = any([constraints.values(), preferences.values(), cancer_specific.values()])
        
        if not (needs_instructions or needs_adaptation):
            return enhanced_recipe
        
        try:
            # Get AICR context for enhancement
            focus_areas = self.aicr_service.extract_focus_areas_from_intent(intent_data)
            aicr_context = self.aicr_service.get_prompt_context(focus_areas=focus_areas)
            
            context_lines = [
                f"Recipe: {enhanced_recipe.get('name', 'Recipe')}",
                f"Type: {enhanced_recipe.get('type', 'General')}",
                f"Ingredients: {', '.join(enhanced_recipe.get('ingredients', [])[:10])}"
            ]
            
            combined_prompt = f"""Generate COMPLETE recipe enhancement for nutritious recipes following AICR guidelines.

{chr(10).join(context_lines)}

{aicr_context}

USER REQUIREMENTS:
{json.dumps(intent_data, indent=2)}

YOUR TASK - Generate ALL of the following in ONE response:

1. COOKING_INSTRUCTIONS:
[Numbered steps 1., 2., 3., etc. - Include cooking temperatures for food safety, clear practical instructions]

2. INGREDIENT_MODIFICATIONS:
[Any nutrition-appropriate substitutions/changes needed - one per line starting with "-"]

3. HELPFUL_TIPS:
[2-3 nutrition-focused tips (e.g., for easy digestion, texture, protein) - one per line starting with "-"]

Generate all three sections. Be specific, nutrition-appropriate, and AICR-compliant.
"""

            response = self.llm.predict(combined_prompt)
            
            # Parse all sections from one response
            if "COOKING_INSTRUCTIONS:" in response:
                section = response.split("COOKING_INSTRUCTIONS:")[1]
                if "INGREDIENT_MODIFICATIONS:" in section:
                    section = section.split("INGREDIENT_MODIFICATIONS:")[0]
                
                instructions = []
                for line in section.split('\n'):
                    cleaned = line.strip()
                    if cleaned and len(cleaned) > 15:
                        cleaned = re.sub(r'^\d+[\.\)]\s*', '', cleaned)
                        if cleaned:
                            instructions.append(cleaned)
                
                if instructions:
                    enhanced_recipe["instructions"] = [f"{i+1}. {inst}" for i, inst in enumerate(instructions[:8])]
                    enhanced_recipe["instructions_generated"] = True
            
            if "INGREDIENT_MODIFICATIONS:" in response:
                section = response.split("INGREDIENT_MODIFICATIONS:")[1]
                if "HELPFUL_TIPS:" in section:
                    section = section.split("HELPFUL_TIPS:")[0]
                
                mods = [line.strip().lstrip('-•*').strip() 
                       for line in section.split('\n') 
                       if line.strip() and line.strip().startswith(('-', '•', '*'))]
                
                if mods:
                    enhanced_recipe["ingredient_adaptations"] = mods[:5]
                    enhanced_recipe["instructions_adapted"] = True
            
            if "HELPFUL_TIPS:" in response:
                section = response.split("HELPFUL_TIPS:")[1]
                tips = [line.strip().lstrip('-•*').strip() 
                       for line in section.split('\n') 
                       if line.strip() and line.strip().startswith(('-', '•', '*'))]
                
                if tips:
                    enhanced_recipe["helpful_tips"] = tips[:3]
            
            enhanced_recipe["dynamically_adapted"] = True
            logger.info(f"Enhanced '{enhanced_recipe.get('name')}' with AICR compliance")
            
        except Exception as e:
            logger.error(f"Error in combined enhancement: {e}")
        
        self.enhancement_cache[cache_key] = enhanced_recipe
        return enhanced_recipe
    
    def generate_fallback_recipes(self, query: str, intent_data: Dict[str, Any], failed_recipes: List[Dict]) -> List[Dict[str, Any]]:
        """
        Universal recipe generation with AICR guidelines.
        """
        try:
            # STEP 1: Get AICR Context
            focus_areas = self.aicr_service.extract_focus_areas_from_intent(intent_data)
            aicr_context = self.aicr_service.get_prompt_context(focus_areas=focus_areas)
            
            logger.info(f"Generating recipes with AICR guidelines, focus areas: {focus_areas}")
            
            # STEP 2: Build Failure Context
            failure_context = ""
            if failed_recipes:
                failures = [{
                    "name": r.get("name"), 
                    "violations": r.get("verification_details", {}).get("constraint_violations", [])
                } for r in failed_recipes[:2]]
                failure_context = f"\n\nPrevious Failed Recipes:\n{json.dumps(failures, indent=2)}"

            preferences = intent_data.get("preferences", {})
            constraints = intent_data.get("constraints", {})
            cuisine_preferences = preferences.get("cuisine_types", [])
            nutritional_goals = preferences.get("nutritional_goals", [])

            explicit_rules = []
            if cuisine_preferences:
                explicit_rules.append(
                    f"- Cuisine preference is REQUIRED: recipes must stay within {', '.join(cuisine_preferences)} cuisine style."
                )
            if constraints.get("avoid_red_meat"):
                explicit_rules.append(
                    "- Do NOT use beef, pork, lamb, bacon, sausage, ham, salami, pepperoni, or other red/processed meats."
                )
            if nutritional_goals:
                explicit_rules.append(
                    f"- Nutritional focus to preserve: {', '.join(nutritional_goals)}."
                )
            if not explicit_rules:
                explicit_rules.append("- Preserve the user's stated intent closely.")
            
            # STEP 3: Generate with AICR Guidelines
            generation_prompt = f"""You are a nutrition specialist creating recipes using AICR guidelines.

{aicr_context}

USER QUERY: "{query}"

USER REQUIREMENTS:
{json.dumps(intent_data, indent=2)}
{failure_context}

YOUR TASK:
1. Read ALL user requirements from intent_data
2. Apply AICR guidelines above (especially protein, food safety, easy digestion)
3. Generate 2-3 recipes that satisfy BOTH user constraints AND AICR guidelines

RECIPE REQUIREMENTS:
- Include protein source (see AICR protein sources above - aim for 20-30g)
- Follow food safety rules (fully cooked, safe ingredients, cooking temperatures)
- Address digestive comfort if mentioned (see AICR guidelines above)
- Avoid foods to limit (processed meats, high sodium)
- Meet all user constraints (max/min ingredients, dietary restrictions, equipment, etc.)

CONSTRAINT COMPLIANCE:
- If max_ingredients exists → recipes MUST have ≤ that number
- If min_ingredients exists → recipes MUST have ≥ that number  
- If dietary_restrictions exist → full compliance required
- If equipment_only exists → use only that equipment

IMPORTANT FOLLOW-UP RULES:
{chr(10).join(explicit_rules)}

OUTPUT FORMAT (valid JSON only):
[
    {{
        "name": "Nutrition-Optimized Recipe Name",
        "type": "Main Dish|Side Dish|Soup|Smoothie|Breakfast|Snack",
        "calories": estimated_number,
        "protein_grams": estimated_grams (aim for 20-30g),
        "ingredients": [
            "1 cup ingredient one",
            "4 oz ingredient two",
            "..."
        ],
        "instructions": [
            "1. First step with specific details and cooking temp",
            "2. Cook chicken to 165°F internal temperature",
            "3. Final step"
        ],
        "description": "Why this recipe meets user needs and AICR guidelines",
        "nutrition_benefits": "Specific benefits (high protein 25g, easy to digest, nourishing)",
        "generated_by_llm": true,
        "meets_requirements": true
    }}
]

Generate practical, safe, nutrition-optimized recipes that meet ALL constraints and AICR guidelines.
"""

            response = self.llm.predict(generation_prompt)
            
            # STEP 4: Parse Response
            response = response.strip()
            generated_recipes = self._parse_generated_recipe_response(response)
            
            if not generated_recipes:
                logger.error("LLM returned empty recipe array")
                return []
            
            # STEP 5: Validate with AICR Service
            formatted_recipes = []
            for i, recipe in enumerate(generated_recipes[:3]):
                
                # Validate against AICR guidelines
                aicr_compliance = self.aicr_service.validate_recipe_compliance(recipe)
                
                formatted_recipe = {
                    "name": recipe.get("name", f"Nutrition-Optimized Recipe {i+1}"),
                    "type": recipe.get("type", "CUSTOM"),
                    "calories": recipe.get("calories", 0),
                    "protein_grams": recipe.get("protein_grams", 0),
                    "ingredients": recipe.get("ingredients", []),
                    "instructions": recipe.get("instructions", []),
                    "description": recipe.get("description", "Custom generated recipe for optimal nutrition"),
                    "nutrition_benefits": recipe.get("nutrition_benefits", ""),
                    "aicr_compliance": aicr_compliance,
                    "generated_by_llm": True,
                    "meets_requirements": aicr_compliance["overall_compliant"],
                    "verification_details": {
                        "passes_verification": aicr_compliance["overall_compliant"],
                        "verification_score": aicr_compliance["score"],
                        "reasoning": f"Generated with AICR guidelines. Compliance score: {aicr_compliance['score']}/100",
                        "constraint_violations": aicr_compliance["warnings"]
                    }
                }
                
                if aicr_compliance["overall_compliant"]:
                    formatted_recipes.append(formatted_recipe)
                    logger.info(f"✓ Recipe '{formatted_recipe['name']}' AICR validated - Score: {aicr_compliance['score']}")
                else:
                    logger.warning(f"✗ Recipe '{formatted_recipe['name']}' failed AICR validation - Score: {aicr_compliance['score']}")
            
            logger.info(f"Generated {len(formatted_recipes)} AICR-compliant recipes")
            return formatted_recipes
            
        except json.JSONDecodeError as e:
            logger.error(f"JSON parsing error: {e}")
            logger.error(f"Response was: {response if 'response' in locals() else 'No response'}")
            return []
        except Exception as e:
            logger.error(f"Error generating recipes: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return []

    def _parse_generated_recipe_response(self, response: str) -> List[Dict[str, Any]]:
        cleaned = response.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        elif cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            match = re.search(r"\[\s*\{.*\}\s*\]", cleaned, re.DOTALL)
            if match:
                return json.loads(match.group(0))
            raise

    def generate_helpful_no_results_message(self, query: str, intent_data: Dict[str, Any]) -> str:
        """Generate a helpful message when no recipes can be found or generated"""
        constraints = intent_data.get("constraints", {})
        
        constraint_summary = []
        if constraints.get("max_ingredients"):
            constraint_summary.append(f"maximum {constraints['max_ingredients']} ingredients")
        if constraints.get("min_ingredients"):
            constraint_summary.append(f"at least {constraints['min_ingredients']} ingredients")
        if constraints.get("dietary_restrictions"):
            constraint_summary.append(f"{', '.join(constraints['dietary_restrictions'])} diet")
        if constraints.get("equipment_only"):
            constraint_summary.append(f"using only {', '.join(constraints['equipment_only'])}")
        
        if constraint_summary:
            return f"I couldn't find or generate AICR-compliant recipes that meet all your requirements ({', '.join(constraint_summary)}). This combination might be too specific. Could you try:\n\n• Relaxing some constraints\n• Changing ingredient count requirements\n• Asking about different types of recipes\n• Being more flexible with dietary restrictions"
        else:
            return "I couldn't find recipes matching your query. Could you try rephrasing or providing more details about what you're looking for?"

    def enhance_multiple_recipes_parallel(self, recipes: List[Dict[str, Any]], intent_data: Dict[str, Any], max_workers: int = 3) -> List[Dict[str, Any]]:
        """
        Enhance multiple recipes in parallel using ThreadPoolExecutor
        Alternative to batch_enhance_recipes for more control
        """
        if not recipes:
            return []
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_recipe = {
                executor.submit(self.enhance_single_recipe, recipe, intent_data): recipe
                for recipe in recipes
            }
            
            enhanced_recipes = []
            for future in as_completed(future_to_recipe):
                try:
                    enhanced_recipe = future.result()
                    enhanced_recipes.append(enhanced_recipe)
                except Exception as e:
                    original_recipe = future_to_recipe[future]
                    logger.error(f"Error enhancing recipe {original_recipe.get('name')}: {e}")
                    enhanced_recipes.append(original_recipe)
        
        return enhanced_recipes

    def get_enhancement_summary(self, recipes: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Get summary of enhancement results"""
        total = len(recipes)
        enhanced = sum(1 for r in recipes if r.get("dynamically_adapted", False))
        instructions_generated = sum(1 for r in recipes if r.get("instructions_generated", False))
        ingredients_adapted = sum(1 for r in recipes if r.get("instructions_adapted", False))
        
        enhancement_types = {
            "instructions_generated": instructions_generated,
            "ingredients_adapted": ingredients_adapted,
            "helpful_tips_added": sum(1 for r in recipes if r.get("helpful_tips") and len(r.get("helpful_tips", [])) > 0)
        }
        
        return {
            "total_recipes": total,
            "enhanced_recipes": enhanced,
            "enhancement_rate": round((enhanced / total) * 100, 2) if total > 0 else 0,
            "enhancement_types": enhancement_types
        }

    def clear_recipe_enhancement(self, recipe: Dict[str, Any]):
        """Clear enhancement data from a recipe (useful for re-enhancement)"""
        keys_to_remove = [
            "instructions_generated", "instructions_adapted", "dynamically_adapted",
            "ingredient_adaptations", "helpful_tips"
        ]
        for key in keys_to_remove:
            recipe.pop(key, None)
        
        # Only clear instructions if they were generated
        if recipe.get("instructions_generated_backup"):
            recipe["instructions"] = recipe["instructions_generated_backup"]
            recipe.pop("instructions_generated_backup", None)

    def force_reenhance_recipe(self, recipe: Dict[str, Any], intent_data: Dict[str, Any]) -> Dict[str, Any]:
        """Force re-enhancement of a recipe, bypassing cache"""
        self.clear_recipe_enhancement(recipe)
        return self.enhance_single_recipe(recipe, intent_data)

    def get_cache_stats(self) -> Dict[str, Any]:
        return {
            "cache_size": len(self.enhancement_cache),
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "hit_rate": f"{round(self.cache_hits / max(self.cache_hits + self.cache_misses, 1) * 100, 1)}%"
        }

    def clear_caches(self):
        self.enhancement_cache.clear()
        self.cache_hits = 0
        self.cache_misses = 0
        logger.info("Enhancement caches cleared")

    def get_detailed_cache_info(self) -> Dict[str, Any]:
        """Get detailed cache information"""
        cache_keys = list(self.enhancement_cache.keys())
        sample_keys = cache_keys[:5] if len(cache_keys) > 5 else cache_keys
        
        return {
            "total_cached_recipes": len(self.enhancement_cache),
            "sample_cached_items": sample_keys,
            "cache_memory_estimate_mb": len(json.dumps(self.enhancement_cache).encode('utf-8')) / (1024 * 1024),
            "performance_metrics": {
                "cache_hit_rate": round(self.cache_hits / max(self.cache_hits + self.cache_misses, 1) * 100, 2),
                "total_enhancements": self.cache_hits + self.cache_misses,
                "cache_efficiency": "HIGH" if (self.cache_hits / max(self.cache_hits + self.cache_misses, 1)) > 0.7 else "LOW"
            }
        }
