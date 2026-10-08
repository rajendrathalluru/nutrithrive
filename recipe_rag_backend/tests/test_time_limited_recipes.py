import copy
import json
import unittest
from pathlib import Path
from unittest.mock import Mock

from app.services.aicr_guidelines_service import aicr_service
from app.services.data_loader import DataLoader
from app.services.intent_analyzer import IntentAnalyzer
from app.services.preparation_validation import declared_time_check
from app.services.rag_service import RecipeRAGService
from app.services.recipe_enhancer import RecipeEnhancer
from app.services.recipe_verifier import RecipeVerifier
from app.services.response_generator import ResponseGenerator


QUERIES = (
    "Show recipes that take less than 5 minutes  to make",
    "Help me to prepare recipes that take less than 5 minutes",
)


def timed_recipe(minutes=3):
    return {
        "name": "Yogurt and Banana Bowl", "type": "Breakfast", "calories": 240,
        "ingredients": ["1 cup pasteurized plain Greek yogurt", "1 banana", "1 tbsp smooth peanut butter"],
        "instructions": [
            "Open and measure the yogurt and peanut butter into a bowl: 1 minute.",
            "Peel and slice the banana: 1 minute.",
            "Stir the peanut butter into the yogurt, top with banana and serve: 1 minute.",
        ],
        "total_time": f"Estimated total time: {minutes} minutes", "generated_by_llm": True,
    }


class TimeLimitedRecipeTests(unittest.TestCase):
    def intent(self, query=QUERIES[0]):
        analyzer = IntentAnalyzer()
        return analyzer._post_process_intent(query, analyzer._get_fallback_intent_data(query))

    def assessment(self, intent):
        return {
            "id": 0, "relevance": "match", "constraint_violations": [],
            "constraint_checks": {
                key: {"status": "pass", "evidence": "The stated total and complete steps fit the request."}
                for key in RecipeVerifier()._required_checks(intent)
            },
        }

    def verify(self, recipe, intent=None, assessment=None):
        intent = intent or self.intent()
        assessment = assessment if assessment is not None else self.assessment(intent)
        verifier = RecipeVerifier()
        verifier.initialize(Mock(predict=Mock(return_value=json.dumps([assessment]))))
        return verifier.batch_verify_recipes([copy.deepcopy(recipe)], intent, aicr_service)[0]

    def test_reported_phrasings_keep_the_same_strict_boundary(self):
        for query in QUERIES:
            intent = self.intent(query)
            self.assertEqual(intent["constraints"]["time_max_minutes"], 5)
            self.assertTrue(intent["constraints"]["time_limit_exclusive"])

    def test_explicit_total_provides_real_citation_when_model_omits_time_check(self):
        recipe = self.verify(timed_recipe())
        details = recipe["verification_details"]
        self.assertTrue(details["passes_verification"])
        self.assertEqual(details["time_check"], {
            "total_minutes": 3,
            "evidence": [{"field": "total_time", "quote": "Estimated total time: 3 minutes"}],
        })

    def test_exactly_five_minutes_is_rejected_even_with_positive_model_checks(self):
        result = self.verify(timed_recipe(5))["verification_details"]
        self.assertFalse(result["passes_verification"])
        self.assertEqual(result["relevance"], "adaptable")
        self.assertTrue(any("requested limit" in reason for reason in result["constraint_violations"]))

    def test_inclusive_boundary_allows_five_minutes(self):
        result = self.verify(timed_recipe(5), self.intent("5 minutes or less"))
        self.assertTrue(result["verification_details"]["passes_verification"])

    def test_declared_totals_support_seconds_ranges_and_compound_units(self):
        for text, expected in (("180 seconds", 3), ("3-4 minutes", 4), ("4 minutes 30 seconds", 4.5),
                               ("Total time: 1 hour and 5 minutes", 65), ("Estimated total time: 3 minutes", 3)):
            with self.subTest(text=text):
                self.assertEqual(declared_time_check({"total_time": text})["total_minutes"], expected)

    def test_ambiguous_totals_and_partial_cooking_times_are_not_invented(self):
        for text in ("quick", "about five", "5", "3 minutes per batch", "3 minutes plus chilling", "-3 minutes"):
            self.assertIsNone(declared_time_check({"total_time": text}))
        recipe = timed_recipe()
        recipe.pop("total_time")
        recipe["instructions"] = ["Blend for 1 minute."]
        recipe["description"] = "Quick and easy!"
        self.assertFalse(self.verify(recipe)["verification_details"]["passes_verification"])

    def test_source_total_is_preserved_and_cannot_be_lowered_by_ai_assessment(self):
        recipe = timed_recipe()
        recipe["source_notes"] = "Servings 2 | Total Time 5 min | A source tip"
        result = self.verify(recipe)["verification_details"]
        self.assertEqual(result["time_check"]["total_minutes"], 5)
        self.assertFalse(result["passes_verification"])

    def test_explicit_model_contradiction_is_not_replaced_with_optimistic_metadata(self):
        assessment = self.assessment(self.intent())
        assessment["time_check"] = {"total_minutes": 6, "evidence": []}
        self.assertFalse(self.verify(timed_recipe(), assessment=assessment)["verification_details"]["passes_verification"])
        assessment["time_check"] = {"total_minutes": None, "evidence": []}
        self.assertFalse(self.verify(timed_recipe(), assessment=assessment)["verification_details"]["passes_verification"])

    def test_independent_total_check_rejects_citing_only_a_short_step(self):
        assessment = self.assessment(self.intent())
        recipe = timed_recipe(6)
        assessment["time_check"] = {
            "total_minutes": 3, "evidence": [{"field": "instructions", "index": 0, "quote": "1 minute"}],
        }
        self.assertFalse(self.verify(recipe, assessment=assessment)["verification_details"]["passes_verification"])

    def test_backend_cites_exact_metadata_instead_of_requiring_model_to_copy_its_format(self):
        recipe = timed_recipe(4)
        recipe["total_time"] = "4 minutes"
        assessment = self.assessment(self.intent())
        assessment["time_check"] = {
            "total_minutes": 4,
            "evidence": [{"field": "total_time", "index": None, "quote": "Total time: 4 minutes"}],
        }
        details = self.verify(recipe, assessment=assessment)["verification_details"]
        self.assertTrue(details["passes_verification"])
        self.assertEqual(details["time_check"]["evidence"], [{"field": "total_time", "quote": "4 minutes"}])

    def test_missing_recipe_timing_cannot_be_repaired_from_a_model_only_claim(self):
        recipe = timed_recipe(4)
        recipe.pop("total_time")
        assessment = self.assessment(self.intent())
        assessment["time_check"] = {
            "total_minutes": 4, "evidence": [{"field": "total_time", "quote": "4 minutes"}],
        }
        self.assertFalse(self.verify(recipe, assessment=assessment)["verification_details"]["passes_verification"])

    def test_total_does_not_override_long_steps_or_failed_dietary_checks(self):
        recipe = timed_recipe()
        recipe["instructions"].append("Chill for 20 minutes before serving.")
        self.assertFalse(self.verify(recipe)["verification_details"]["passes_verification"])
        intent = self.intent()
        intent["constraints"]["allergens_to_avoid"] = ["peanuts"]
        assessment = self.assessment(intent)
        assessment["constraint_checks"]["constraints.allergens_to_avoid"] = {
            "status": "fail", "evidence": "Contains peanut butter.",
        }
        self.assertFalse(self.verify(timed_recipe(), intent, assessment)["verification_details"]["passes_verification"])

    def test_generation_keeps_one_complete_timed_recipe_and_explicit_budget(self):
        model = Mock(predict=Mock(return_value=json.dumps([timed_recipe(), timed_recipe(4)])))
        enhancer = RecipeEnhancer()
        enhancer.initialize(model, aicr_service)
        recipes = enhancer.generate_fallback_recipes(QUERIES[0], self.intent(), [])
        self.assertEqual(len(recipes), 1)
        self.assertEqual(recipes[0]["total_time"], timed_recipe()["total_time"])
        prompt = model.predict.call_args.args[0]
        self.assertIn("strictly less than 5 minutes (300 seconds)", prompt)
        self.assertIn("Exactly 5 minutes does NOT qualify", prompt)
        self.assertIn("exactly ONE complete recipe", prompt)
        self.assertIn("do not merely relabel a slower recipe", prompt)

    def test_repair_prompt_includes_original_time_and_strict_budget(self):
        rejected = timed_recipe(5)
        rejected["verification_details"] = {"passes_verification": False, "constraint_violations": ["Time limit exceeded"]}
        model = Mock(predict=Mock(return_value=json.dumps([timed_recipe()])))
        enhancer = RecipeEnhancer()
        enhancer.initialize(model, aicr_service)
        enhancer.generate_fallback_recipes(QUERIES[0], self.intent(), [rejected])
        prompt = model.predict.call_args.args[0]
        self.assertIn("Repair ONE rejected recipe", prompt)
        self.assertIn("Estimated total time: 5 minutes", prompt)
        self.assertIn("Exactly 5 minutes does NOT qualify", prompt)

    def test_unrestricted_generation_keeps_existing_batch_size(self):
        enhancer = RecipeEnhancer()
        enhancer.initialize(Mock(predict=Mock(return_value=json.dumps([timed_recipe()] * 3))), aicr_service)
        self.assertEqual(len(enhancer.generate_fallback_recipes("Breakfast recipes", {}, [])), 3)

    def test_structured_fallback_preserves_timing_as_metadata_not_a_cooking_step(self):
        response = """RECIPE_NAME: Yogurt and Banana Bowl
RECIPE_TYPE: Breakfast
INGREDIENTS:
- 1 cup pasteurized Greek yogurt
- 1 banana
COOKING_INSTRUCTIONS:
Estimated total time: 3 minutes
1. Open and measure yogurt into a bowl: 1 minute.
2. Peel and slice the banana: 1 minute.
3. Top yogurt with banana and serve: 1 minute.
INGREDIENT_MODIFICATIONS:
HELPFUL_TIPS:
"""
        enhancer = RecipeEnhancer()
        enhancer.initialize(Mock(predict=Mock(return_value=response)), aicr_service)
        recipes = enhancer.generate_structured_fallback_recipe(QUERIES[0], self.intent())
        self.assertEqual(recipes[0]["total_time"], "Estimated total time: 3 minutes")
        self.assertEqual(len(recipes[0]["instructions"]), 3)
        self.assertTrue(self.verify(recipes[0])["verification_details"]["passes_verification"])

    def test_guidance_does_not_rewrite_existing_database_timing(self):
        recipe = timed_recipe(5)
        recipe["generated_by_llm"] = False
        enhancer = RecipeEnhancer()
        enhancer.initialize(Mock(predict=Mock(return_value="""COOKING_INSTRUCTIONS:
Estimated total time: 3 minutes
1. Mix ingredients for 3 minutes.
INGREDIENT_MODIFICATIONS:
HELPFUL_TIPS:
""")), aicr_service)
        enhanced = enhancer.enhance_single_recipe(recipe, self.intent())
        self.assertEqual(enhanced["total_time"], recipe["total_time"])
        self.assertEqual(enhanced["instructions"], recipe["instructions"])

    def routing_service(self, query, database_recipes, generated_recipes):
        service = RecipeRAGService()
        service.is_initialized = True
        service._contains_phi_like_content = Mock(return_value=False)
        intent = self.intent(query)
        intent["recipe_request"] = query
        service.intent_analyzer.understand_query_intent_with_context = Mock(return_value=intent)
        service.search_engine.multi_query_search = Mock(return_value=database_recipes)
        service.search_engine.rerank_with_constraint_filtering = Mock(side_effect=lambda recipes, *args, **kwargs: recipes)
        service._build_recipe_data_from_doc = Mock(side_effect=copy.deepcopy)
        service._get_database_search_candidates = Mock(return_value=[])
        generations = iter(generated_recipes)

        def response(prompt):
            if prompt.startswith("Generate COMPLETE recipe enhancement"):
                return "INGREDIENTS:\nCOOKING_INSTRUCTIONS:\nINGREDIENT_MODIFICATIONS:\nHELPFUL_TIPS:"
            return json.dumps(next(generations))

        service.recipe_enhancer.initialize(Mock(predict=Mock(side_effect=response)), aicr_service)
        service.recipe_verifier.initialize(Mock(predict=Mock(return_value=json.dumps([self.assessment(intent)]))))
        return service

    def test_pipeline_returns_verified_ai_recipe_when_no_database_match_exists(self):
        for query in QUERIES:
            service = self.routing_service(query, [], [[timed_recipe()]])
            result = service.ask_question(query)
            self.assertEqual(result["matches_found"], 1)
            self.assertEqual(result["source_documents"][0]["source_label"], "AI Generated")
            self.assertEqual(result["source_documents"][0]["generation_basis"], "ai_only")
            self.assertIn("approximately 3 minutes total", result["response"])

    def test_pipeline_repairs_excluded_boundary_using_database_context(self):
        loader = DataLoader()
        loader.load_data(Path(__file__).parents[1] / "app/data/Recipe.csv")
        database_recipe = RecipeRAGService()._build_recipe_data_from_record(loader.get_recipe_record("Hummus"))
        service = self.routing_service(QUERIES[0], [database_recipe], [[timed_recipe(5)], [timed_recipe()]])
        result = service.ask_question(QUERIES[0])
        self.assertEqual(result["matches_found"], 1)
        recipe = result["source_documents"][0]
        self.assertEqual(recipe["source_label"], "AI Generated")
        self.assertEqual(recipe["generation_basis"], "database_guided")
        self.assertEqual(recipe["reference_sources"][0]["name"], "Hummus")
        self.assertTrue(any("Repair ONE" in call.args[0] for call in service.recipe_enhancer.llm.predict.call_args_list))

    def test_source_recipe_remains_first_choice_when_inclusive_time_allows_it(self):
        loader = DataLoader()
        loader.load_data(Path(__file__).parents[1] / "app/data/Recipe.csv")
        database_recipe = RecipeRAGService()._build_recipe_data_from_record(loader.get_recipe_record("Hummus"))
        service = self.routing_service("5 minutes or less", [database_recipe], [])
        service.recipe_enhancer.generate_fallback_recipes = Mock(side_effect=AssertionError("Database match must take priority"))
        result = service.ask_question("5 minutes or less")
        self.assertEqual([recipe["name"] for recipe in result["source_documents"]], ["Hummus"])
        self.assertEqual(result["source_documents"][0]["source_label"], "Sourced from AHA")
        self.assertTrue(result["source_documents"][0]["recipe_link"])

    def test_timing_summary_uses_verified_duration_without_another_model_call(self):
        recipe = self.verify(timed_recipe())
        generator = ResponseGenerator()
        generator.initialize(Mock())
        response = generator.generate_personalized_response(QUERIES[0], [recipe], self.intent())
        self.assertIn("approximately 3 minutes total", response)
        generator.llm.predict.assert_not_called()

    def test_no_results_explains_verification_instead_of_blame_on_phrasing(self):
        response = ResponseGenerator().generate_helpful_no_results_message(QUERIES[0], self.intent())
        self.assertIn("less than 5 minutes", response)
        self.assertIn("Your request is clear", response)
        self.assertNotIn("rephras", response)


if __name__ == "__main__":
    unittest.main()
