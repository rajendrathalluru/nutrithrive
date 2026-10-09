import copy
import json
import unittest
from unittest.mock import Mock

from app.services.aicr_guidelines_service import aicr_service
from app.services.intent_analyzer import IntentAnalyzer
from app.services.recipe_enhancer import RecipeEnhancer
from app.services.recipe_prompt_rules import (
    CHEWING_RULES, COOKING_ATTENTION_RULES, FROZEN_INGREDIENT_RULES, INGREDIENT_STORAGE_RULES,
    MEAL_PORTION_RULES, PREPARATION_RULES, REQUEST_MEANING_RULES, SERVING_TEMPERATURE_RULES, active_recipe_rules,
)
from app.services.recipe_verifier import RecipeVerifier
from app.services.rag_service import RecipeRAGService
from app.services.response_generator import ResponseGenerator


QUERY = "What meals use frozen ingredients from start to finish?"


def frozen_bowl():
    return {
        "name": "Frozen Edamame, Rice and Vegetable Bowl", "type": "Main Dish",
        "ingredients": [
            "1 cup purchased frozen cooked brown rice in a microwave pouch requiring no added ingredients",
            "1 cup frozen shelled edamame in a steam-in-bag pack requiring no added ingredients",
            "1 cup frozen mixed vegetables in a steam-in-bag pack requiring no added ingredients",
        ],
        "instructions": [
            "Microwave the frozen cooked rice following its package heating directions without adding ingredients.",
            "Cook the edamame and mixed vegetables in their steam bags following their package directions, without adding ingredients.",
            "Carefully open the hot packs away from your face, combine in a bowl, and serve hot.",
        ],
        "generated_by_llm": True,
    }


class FrozenRecipeGenerationTests(unittest.TestCase):
    def setUp(self):
        analyzer = IntentAnalyzer()
        self.intent = analyzer._post_process_intent(QUERY, analyzer._get_fallback_intent_data(QUERY))
        self.intent["recipe_request"] = QUERY

    def assessment(self, intent=None):
        return {
            "id": 0, "relevance": "match", "constraint_violations": [],
            "constraint_checks": {key: {"status": "pass", "evidence": "Model claims every constraint is satisfied"}
                                  for key in RecipeVerifier()._required_checks(intent or self.intent)},
            "frozen_ingredient_check": {"non_frozen_ingredients": [], "unspecified_forms": [], "conflicting_guidance": []},
            "preparation_check": {"conflicting_steps": [], "unresolved_dependencies": [], "conflicting_guidance": []},
        }

    def verify(self, recipe, intent=None, batch=True):
        intent = intent or self.intent
        assessment = self.assessment(intent)
        verifier = RecipeVerifier()
        verifier.initialize(Mock(predict=Mock(return_value=json.dumps([assessment] if batch else assessment))))
        if batch:
            return verifier.batch_verify_recipes([copy.deepcopy(recipe)], intent, aicr_service)[0]["verification_details"]
        return verifier.verify_recipe_against_constraints(recipe, intent)

    def test_only_active_rule_families_are_selected(self):
        rules = active_recipe_rules(self.intent)
        self.assertIn(FROZEN_INGREDIENT_RULES, rules)
        self.assertIn(MEAL_PORTION_RULES, rules)
        for unrelated in (INGREDIENT_STORAGE_RULES, PREPARATION_RULES, CHEWING_RULES, COOKING_ATTENTION_RULES, SERVING_TEMPERATURE_RULES):
            self.assertNotIn(unrelated, rules)
        self.assertEqual(active_recipe_rules({}), REQUEST_MEANING_RULES)

    def test_combined_requirements_keep_all_relevant_rules(self):
        intent = {"constraints": {
            "ingredient_storage": "frozen_only", "attention_level": "low", "chewing_effort": "low",
            "meal_suitability": "meal", "preparation_mode": "no_heat", "serving_temperature": "cold",
        }}
        for rule in (FROZEN_INGREDIENT_RULES, COOKING_ATTENTION_RULES, CHEWING_RULES, MEAL_PORTION_RULES,
                     PREPARATION_RULES, SERVING_TEMPERATURE_RULES):
            self.assertIn(rule, active_recipe_rules(intent))
        for storage in ("canned_only", "pantry_based", "shelf_stable_only"):
            rules = active_recipe_rules({"constraints": {"ingredient_storage": storage}})
            self.assertIn(INGREDIENT_STORAGE_RULES, rules)
            self.assertNotIn(FROZEN_INGREDIENT_RULES, rules)
        self.assertIn(PREPARATION_RULES, active_recipe_rules({"constraints": {"time_max_minutes": 0}}))

    def test_frozen_rules_reach_generation_enhancement_repair_and_verification(self):
        model = Mock(predict=Mock(return_value=json.dumps([frozen_bowl(), frozen_bowl()])))
        enhancer = RecipeEnhancer()
        enhancer.initialize(model, aicr_service)
        generated = enhancer.generate_fallback_recipes(QUERY, self.intent, [])
        self.assertEqual(len(generated), 1)
        generation_prompt = model.predict.call_args.args[0]
        self.assertIn("exactly ONE complete recipe", generation_prompt)
        enhancer.enhance_single_recipe(frozen_bowl(), self.intent)
        enhancement_prompt = model.predict.call_args.args[0]
        verifier = RecipeVerifier()
        prompts = [generation_prompt, enhancement_prompt,
                   enhancer._build_repair_prompt(QUERY, self.intent, frozen_bowl(), "Guidelines"),
                   verifier._build_batch_verification_prompt([], self.intent),
                   verifier._build_individual_verification_prompt(frozen_bowl(), self.intent)]
        for prompt in prompts:
            self.assertIn(FROZEN_INGREDIENT_RULES, prompt)
            self.assertNotIn(INGREDIENT_STORAGE_RULES, prompt)
            self.assertNotIn("For pantry meals, examples of repairs", prompt)

    def test_actual_live_model_failures_are_rejected_despite_positive_model_verdict(self):
        for ingredients in (
            ["1 cup frozen berries", "1/2 banana, frozen", "1/2 cup Greek yogurt", "1/2 cup almond milk", "1 tbsp chia seeds"],
            ["1 cup frozen mixed vegetables", "2 tbsp soy sauce", "1 tbsp sesame oil", "1 tsp garlic powder", "2 cups cooked brown rice"],
        ):
            recipe = frozen_bowl()
            recipe["ingredients"] = ingredients
            for batch in (False, True):
                self.assertFalse(self.verify(recipe, batch=batch)["passes_verification"])

    def test_supplied_frozen_components_with_complete_heating_steps_pass(self):
        for generated in (False, True):
            recipe = frozen_bowl()
            recipe["generated_by_llm"] = generated
            self.assertTrue(self.verify(recipe)["passes_verification"])

    def test_reported_live_generation_must_not_serve_still_frozen_rice(self):
        for field in ("instructions", "helpful_tips", "ingredient_adaptations", "storage_instructions", "source_notes"):
            recipe = frozen_bowl()
            recipe[field] = ["Serve the stir-fry over the frozen cooked brown rice."] if field in {
                "instructions", "helpful_tips", "ingredient_adaptations"
            } else "Serve the stir-fry over the frozen cooked brown rice."
            self.assertFalse(self.verify(recipe)["passes_verification"], field)
        recipe = frozen_bowl()
        recipe["instructions"].append("Serve over the heated, previously frozen cooked brown rice.")
        self.assertTrue(self.verify(recipe)["passes_verification"])

    def test_frozen_does_not_override_no_heat(self):
        intent = copy.deepcopy(self.intent)
        intent["constraints"]["preparation_mode"] = "no_heat"
        self.assertFalse(self.verify(frozen_bowl(), intent)["passes_verification"])

    def test_non_frozen_extras_in_directions_and_optional_guidance_are_rejected(self):
        for field in ("instructions", "helpful_tips", "ingredient_adaptations", "source_notes", "storage_instructions"):
            for line in ("Sprinkle sesame seeds or chopped nuts on top before serving.", "Add soy sauce and sesame oil.",
                         "Serve with a side of fresh fruit.", "Mix in Greek yogurt.", "Add salt and pepper to taste."):
                recipe = frozen_bowl()
                recipe[field] = [line] if field in {"instructions", "helpful_tips", "ingredient_adaptations"} else line
                self.assertFalse(self.verify(recipe)["passes_verification"], (field, line))

    def test_declared_frozen_food_references_and_frozen_alternatives_pass(self):
        recipe = frozen_bowl()
        recipe["helpful_tips"] = [
            "Mix the rice, edamame, and vegetables thoroughly.",
            "Cook frozen cauliflower rice according to its package directions as an alternative.",
            "Do not add oil. No salt required.",
        ]
        self.assertTrue(self.verify(recipe)["passes_verification"])

    def test_final_validation_removes_live_model_tip_without_discarding_good_core(self):
        recipe = frozen_bowl()
        recipe["helpful_tips"] = ["For added protein, consider adding a sprinkle of sesame seeds or chopped nuts on top before serving."]
        recipe["guidance_generated"] = True
        service = RecipeRAGService()
        service.recipe_verifier.initialize(Mock(predict=Mock(return_value=json.dumps([self.assessment()]))))
        accepted = service._validate_final_recipes([recipe], self.intent)
        self.assertEqual(len(accepted), 1)
        self.assertEqual(accepted[0]["ingredients"], recipe["ingredients"])
        self.assertNotIn("helpful_tips", accepted[0])
        self.assertFalse(accepted[0]["guidance_generated"])

    def test_single_recipe_missing_id_is_unambiguous_but_still_verified(self):
        assessment = self.assessment()
        assessment.pop("id")
        for response in (assessment, [assessment]):
            for extra in (None, "1 tbsp olive oil"):
                recipe = frozen_bowl()
                if extra:
                    recipe["ingredients"].append(extra)
                model = Mock(predict=Mock(return_value=json.dumps(response)))
                verifier = RecipeVerifier()
                verifier.initialize(model)
                result = verifier.batch_verify_recipes([recipe], self.intent, aicr_service)[0]
                self.assertEqual(result["verification_details"]["passes_verification"], extra is None)
                self.assertEqual(model.predict.call_count, 1)

    def test_single_recipe_explicitly_wrong_id_is_not_reassigned(self):
        assessment = self.assessment()
        assessment["id"] = 7
        verifier = RecipeVerifier()
        verifier.initialize(Mock(predict=Mock(return_value=json.dumps([assessment]))))
        result = verifier.batch_verify_recipes([frozen_bowl()], self.intent, aicr_service)[0]
        self.assertFalse(result["verification_details"]["passes_verification"])

    def test_missing_ids_for_multiple_recipes_are_not_guessed(self):
        assessment = {"relevance": "match", "constraint_checks": {}, "constraint_violations": []}
        verifier = RecipeVerifier()
        verifier.initialize(Mock(predict=Mock(return_value=json.dumps([assessment, assessment]))))
        verifier._fallback_individual_verification = Mock(return_value=[])
        recipes = [frozen_bowl(), frozen_bowl()]
        self.assertEqual(verifier.batch_verify_recipes(recipes, {}, aicr_service), [])
        verifier._fallback_individual_verification.assert_called_once()

    def test_new_breakfast_request_drops_frozen_requirement_unless_explicit_followup(self):
        analyzer = IntentAnalyzer()
        breakfast = "best breakfast that i can eat"
        analyzer.initialize(Mock(predict=Mock(side_effect=lambda prompt: json.dumps(analyzer._get_fallback_intent_data(breakfast)))))
        history = [{"role": "user", "content": QUERY}]
        self.assertIsNone(analyzer.understand_query_intent_with_context(breakfast, history)["constraints"]["ingredient_storage"])
        self.assertEqual(analyzer.understand_query_intent_with_context("More breakfast recipes using those ingredients", history)["constraints"]["ingredient_storage"], "frozen_only")
        self.assertIsNone(analyzer.understand_query_intent(breakfast)["constraints"]["ingredient_storage"])
        self.assertIsNone(analyzer.understand_query_intent_with_context("Start over: " + breakfast, history)["constraints"]["ingredient_storage"])

    def test_frozen_summary_and_failure_do_not_invent_foods_or_blame_query(self):
        generator = ResponseGenerator()
        generator.initialize(Mock())
        summary = generator.generate_personalized_response(QUERY, [frozen_bowl()], self.intent)
        self.assertIn("Frozen Edamame", summary)
        self.assertIn("cooking or reheating", summary)
        generator.llm.predict.assert_not_called()
        failure = generator.generate_helpful_no_results_message(QUERY, self.intent)
        self.assertIn("frozen-only", failure)
        self.assertNotIn("rephras", failure)


if __name__ == "__main__":
    unittest.main()
