import json
import unittest
from unittest.mock import Mock, patch

from app.services.intent_analyzer import IntentAnalyzer
from app.services.recipe_router import requests_composed_dinner
from app.services.recipe_verifier import RecipeVerifier
from app.services.response_generator import ResponseGenerator
import test_recipe_routing as routing
from test_recipe_routing import recipe_record
from guideline_fixtures import passing_guideline_checks


QUERY = "can you help me to prepare a thanksgiving dinner for 6 people majorly chinese recipes"


class DinnerRoutingTests(unittest.TestCase):
    def test_composition_not_specific_holiday_or_cuisine(self):
        for query in (QUERY, "Plan a Christmas dinner for 8 people using Italian recipes",
                      "Prepare a dinner menu for six people",
                      "want to make some korean dishes for my christmas dinner party",
                      "I am an african american and hostinf dinnewr for 6 people can you help me to generate recipes",
                      "I am an african american and hostinf dinnewr for 10 people can you help me to generate recipes"):
            self.assertTrue(requests_composed_dinner(query), query)
        for query in ("Show Chinese recipes for 6 people", "Prepare this dinner menu for 6 people",
                      "Generate a recipe for dinner for 6 people", QUERY + " under $10",
                      "Find AICR holiday dinner recipes for 6 people", "more recipes",
                      "I want to make Korean recipes for dinner"):
            self.assertFalse(requests_composed_dinner(query), query)

    def test_summary_does_not_call_model_or_claim_certification(self):
        generator = ResponseGenerator()
        generator.initialize(Mock())
        response = generator.generate_personalized_response(QUERY, [{"name": "Dinner", "servings": 6}],
                                                           {"generation_recipe_count": 3})
        generator.llm.predict.assert_not_called()
        self.assertIn("AI-generated", response)
        self.assertIn("fewer than three", response.lower())

    def test_wrong_yield_is_a_verification_failure_not_silent_final_filter(self):
        verifier = RecipeVerifier()
        intent = {"constraints": {"requested_servings": 6}}
        assessment = {
            "relevance": "match", "constraint_violations": [], "guideline_checks": passing_guideline_checks(),
            "constraint_checks": {"constraints.requested_servings": {"status": "pass", "evidence": "Model claim"}},
            "portion_adequacy_check": {"status": "pass", "evidence": "Model claim"},
        }
        recipe = {**recipe_record("Small Dinner", generated=True), "servings": 2}
        result = verifier._finalize_verification(assessment, recipe, intent)
        self.assertFalse(result["passes_verification"])
        self.assertTrue(any("yield" in violation for violation in result["constraint_violations"]))

    def test_yield_label_without_quantity_assessment_cannot_pass(self):
        verifier = RecipeVerifier()
        intent = {"constraints": {"requested_servings": 6}}
        assessment = {
            "relevance": "match", "constraint_violations": [], "guideline_checks": passing_guideline_checks(),
            "constraint_checks": {"constraints.requested_servings": {"status": "pass", "evidence": "Serves six"}},
        }
        result = verifier._finalize_verification(assessment, {**recipe_record("Dinner", generated=True), "servings": 6}, intent)
        self.assertFalse(result["passes_verification"])

    def test_sparse_combined_intent_is_normalized_without_second_model_call(self):
        analyzer = IntentAnalyzer()
        payload = {"intent": {"query_type": "recipe_search", "constraints": {"requested_servings": 6},
                              "preferences": {"cuisine_types": ["Chinese"]}},
                   "recipes": [{**recipe_record("Dinner", generated=True), "servings": 6}]}
        model = Mock(predict=Mock(return_value=json.dumps(payload)))
        analyzer.initialize(model)
        intent, recipes = analyzer.interpret_and_generate(QUERY, {}, recipe_count=3)
        self.assertEqual(len(recipes), 1)
        self.assertEqual(intent["constraints"]["requested_servings"], 6)
        self.assertEqual({cuisine.lower() for cuisine in intent["preferences"]["cuisine_types"]}, {"chinese"})
        model.predict.assert_called_once()


class ComposedDinnerPipelineTests(unittest.TestCase):
    def setUp(self):
        routing.RecipeRoutingTests.setUp(self)
        rollback = patch("app.services.rag_service.settings.RECIPE_SINGLE_PASS_DINNER", False)
        rollback.start()
        self.addCleanup(rollback.stop)
    verify = routing.RecipeRoutingTests.verify
    ask = routing.RecipeRoutingTests.ask

    def prepare_menu(self, recipes):
        analyzer = IntentAnalyzer()
        intent = analyzer._get_fallback_intent_data(QUERY)
        intent["query_type"] = "recipe_search"
        intent["constraints"]["requested_servings"] = 6
        intent["preferences"]["cuisine_types"] = ["Chinese"]
        model = Mock(predict=Mock(return_value=json.dumps({"intent": intent, "recipes": recipes})))
        analyzer.initialize(model)
        self.service.intent_analyzer = analyzer
        self.service.recipe_verifier.batch_verify_recipes.side_effect = lambda candidates, *_: self.verify(
            [{**recipe, "test_relevance": "match"} for recipe in candidates], {}, None
        )
        return model

    def test_three_six_person_recipes_skip_retrieval_and_separate_intent_call(self):
        recipes = [{**recipe_record(f"Chinese Dinner {index}", generated=True), "servings": 6} for index in range(3)]
        model = self.prepare_menu(recipes)
        history = [{"role": "user", "content": "Show recipes under 30 minutes"},
                   {"role": "assistant", "content": "Here are quick recipes."}]
        result = self.ask(QUERY, history)
        self.assertEqual(result["matches_found"], 3, result)
        self.assertEqual([recipe["servings"] for recipe in result["source_documents"]], [6, 6, 6])
        self.assertIsNone(result["intent_analysis"]["constraints"].get("time_max_minutes"))
        model.predict.assert_called_once()
        self.service.search_engine.multi_query_search.assert_not_called()
        self.service._get_database_search_candidates.assert_not_called()
        self.service.recipe_enhancer.generate_fallback_recipes.assert_not_called()
        self.service.recipe_verifier.batch_verify_recipes.assert_called_once()

    def test_partial_menu_retains_verified_recipe_and_has_only_one_topup(self):
        self.prepare_menu([{**recipe_record("First Dinner", generated=True), "servings": 6}])
        self.service.recipe_enhancer.generate_fallback_recipes.return_value = [
            {**recipe_record("Second Dinner", generated=True), "servings": 6},
            {**recipe_record("Third Dinner", generated=True), "servings": 6},
        ]
        result = self.ask(QUERY)
        self.assertEqual(result["matches_found"], 3, result)
        self.service.recipe_enhancer.generate_fallback_recipes.assert_called_once()
        self.assertEqual(self.service.recipe_enhancer.generate_fallback_recipes.call_args.args[1]["_generation_slots"], 2)
        self.service.recipe_enhancer.generate_structured_fallback_recipe.assert_not_called()
        self.service.search_engine.multi_query_search.assert_not_called()
