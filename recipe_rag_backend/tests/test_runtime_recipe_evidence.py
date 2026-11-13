import json
import unittest
from copy import deepcopy
from unittest.mock import Mock, patch

from app.services.intent_analyzer import IntentAnalyzer
from app.services.local_recipe_evidence import assess_local_recipe, supports_local_matching
from app.services.rag_service import RecipeRAGService
from app.services.recipe_verifier import RecipeVerifier


class RuntimeEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.intent = {
            "query_type": "recipe_search", "context_action": "new_request",
            "resolved_query": "I need a lunch ready within half an hour",
            "recipe_request": "I need a lunch ready within half an hour",
            "requirement_coverage": {"complete": True, "unresolved": []},
            "constraints": {"time_max_minutes": 30, "meal_suitability": "meal"},
            "preferences": {"meal_types": ["lunch"]}, "search_strategy": {},
        }
        self.recipe = {
            "recipe_id": "beans", "name": "Bean Lunch", "type": "Main Dishes",
            "source_name": "AHA", "database_record_found": True,
            "ingredients": ["1 can cooked beans"], "instructions": ["Drain beans and serve."],
            "total_time": "10 minutes",
        }
        self.guidelines = Mock(validate_recipe_compliance=Mock(return_value={"overall_compliant": True}))

    def test_semantic_requirements_match_without_exact_prompt_grammar(self):
        self.assertTrue(supports_local_matching(self.intent))
        self.assertEqual(assess_local_recipe(self.recipe, self.intent)["status"], "pass")

    def test_missing_evidence_is_unknown_and_conflicting_time_fails(self):
        self.recipe.pop("total_time")
        self.assertEqual(assess_local_recipe(self.recipe, self.intent)["status"], "unknown")
        self.recipe["total_time"] = "45 minutes"
        self.assertEqual(assess_local_recipe(self.recipe, self.intent)["status"], "fail")

    def test_unresolved_safety_cuisine_and_other_requirements_never_pass_locally(self):
        for section, field, value in [
            ("constraints", "digestive_comfort", "gentle"),
            ("constraints", "allergens_to_avoid", ["milk"]),
            ("constraints", "requested_servings", 6),
            ("preferences", "cuisine_types", ["Chinese"]),
            ("search_strategy", "must_match_criteria", ["Thanksgiving menu"]),
            ("requirement_coverage", "unresolved", ["soft texture"]),
        ]:
            with self.subTest(field=field):
                intent = deepcopy(self.intent)
                intent[section][field] = value
                self.assertEqual(assess_local_recipe(self.recipe, intent)["status"], "unknown")

    def test_generated_recipes_and_unsupported_labels_require_review(self):
        for change in ({"generated_by_llm": True}, {"dynamically_adapted": True}, {"type": "Side Dishes"}):
            self.assertEqual(assess_local_recipe({**self.recipe, **change}, self.intent)["status"], "unknown")

    def test_local_pass_still_runs_final_checks_and_policy(self):
        verifier = RecipeVerifier()
        verifier.initialize(Mock(predict=Mock(side_effect=AssertionError("No model call expected"))))
        result = verifier.batch_verify_recipes([deepcopy(self.recipe)], self.intent, self.guidelines)
        self.assertTrue(result[0]["verification_details"]["passes_verification"])
        self.assertFalse(result[0]["verification_details"]["independent_model_review"])
        self.guidelines.validate_recipe_compliance.assert_called_once()

    def test_runtime_routing_uses_current_records_without_snapshot_or_search(self):
        service = RecipeRAGService()
        service.is_initialized = True
        service.intent_analyzer.understand_query_intent_with_context = Mock(return_value=deepcopy(self.intent))
        service.data_loader.recipe_lookup = {"beans": deepcopy(self.recipe)}
        service._build_recipe_data_from_record = deepcopy
        service.search_engine.multi_query_search = Mock(side_effect=AssertionError("No retrieval needed"))
        service.recipe_verifier.initialize(Mock(predict=Mock(side_effect=AssertionError("No review needed"))))
        with patch("app.services.rag_service.aicr_service", self.guidelines), \
                patch("app.services.rag_service.safety_service.should_intercept", return_value=False):
            result = service.ask_question(self.intent["recipe_request"])
        self.assertEqual(result["matches_found"], 1, result)
        self.assertEqual(result["source_documents"][0]["name"], "Bean Lunch")

    def test_poor_runtime_coverage_routes_to_verified_generation(self):
        service = RecipeRAGService()
        service.is_initialized = True
        service.intent_analyzer.understand_query_intent_with_context = Mock(return_value=deepcopy(self.intent))
        service.data_loader.recipe_lookup = {"beans": {**self.recipe, "total_time": "60 minutes"}}
        service._build_recipe_data_from_record = deepcopy
        service.search_engine.multi_query_search = Mock(side_effect=AssertionError("No speculative search"))
        with patch.object(service, "_generate_verified_fallback_recipes", return_value=[]) as generate, \
                patch("app.services.rag_service.safety_service.should_intercept", return_value=False):
            service.ask_question(self.intent["recipe_request"])
        generate.assert_called_once()
        self.assertTrue(generate.call_args.kwargs["bounded"])

    def test_compact_intent_defaults_are_restored(self):
        analyzer = IntentAnalyzer()
        parsed = analyzer._parse_intent_response(json.dumps({"query_type": "recipe_search", "constraints": {"time_max_minutes": 30}}))
        self.assertEqual(parsed["constraints"]["time_max_minutes"], 30)
        self.assertEqual(parsed["constraints"]["allergens_to_avoid"], [])
        self.assertIn("meal_types", parsed["preferences"])

    def test_complete_new_request_interpretation_does_not_make_a_second_call(self):
        analyzer = IntentAnalyzer()
        intent = deepcopy(self.intent)
        intent["requirement_coverage"]["scope"] = "current_request"
        analyzer.initialize(Mock(predict=Mock(return_value=json.dumps(intent))))
        result = analyzer.understand_query_intent_with_context("A lunch please", [
            {"role": "user", "content": "Previously I wanted a vegan breakfast"},
        ])
        self.assertEqual(analyzer.llm.predict.call_count, 1)
        self.assertEqual(result["user_request_context"], ["A lunch please"])
        self.assertEqual(result["constraints"]["dietary_restrictions"], [])

    def test_easy_preparation_does_not_pass_by_local_heuristic(self):
        intent = deepcopy(self.intent)
        intent["constraints"]["skill_level"] = "beginner"
        self.assertEqual(assess_local_recipe(self.recipe, intent)["status"], "unknown")

    def test_rollback_flag_disables_local_acceptance(self):
        with patch("app.services.local_recipe_evidence.settings.RECIPE_RUNTIME_EVIDENCE", False):
            self.assertFalse(supports_local_matching(self.intent))

    def test_live_csv_lunch_time_request_needs_no_remote_calls(self):
        service = RecipeRAGService()
        service.is_initialized = True
        service.data_loader.load_data()
        model = Mock(predict=Mock(side_effect=AssertionError("Unexpected model call")))
        service.intent_analyzer.initialize(model)
        service.recipe_verifier.initialize(model)
        service.response_generator.initialize(model)
        service.search_engine.multi_query_search = Mock(side_effect=AssertionError("Unexpected retrieval"))
        with patch("app.services.rag_service.catalog_matches", return_value=[]), \
                patch("app.services.rag_service.safety_service.should_intercept", return_value=False):
            result = service.ask_question("Show recipes that take 30 minutes or less for lunch")
        self.assertEqual(result["matches_found"], 3, result)
        for recipe in result["source_documents"]:
            self.assertLessEqual(recipe["verification_details"]["time_check"]["total_minutes"], 30)
            self.assertEqual(recipe["verification_details"]["method"], "runtime_source_evidence")
        model.predict.assert_not_called()

    def test_reported_help_me_dinner_request_with_welcome_avoids_all_model_calls(self):
        service = RecipeRAGService()
        service.is_initialized = True
        service.data_loader.load_data()
        model = Mock(predict=Mock(side_effect=AssertionError("No model expected")))
        service.intent_analyzer.initialize(model)
        service.recipe_verifier.initialize(model)
        service.response_generator.initialize(model)
        service.search_engine.multi_query_search = Mock(side_effect=AssertionError("No retrieval expected"))
        result = service.ask_question(
            "help me get recipes that take 30 minutes or less for dinner",
            conversation_history=[{"role": "assistant", "content": "Welcome! Ask for recipes."}],
        )
        self.assertEqual(result["matches_found"], 3, result)
        model.predict.assert_not_called()

        lunch = service.ask_question("help me to generate recipes that take 20 minutes or less for lunch")
        self.assertGreater(lunch["matches_found"], 0, lunch)
        for recipe in lunch["source_documents"]:
            self.assertLessEqual(recipe["verification_details"]["time_check"]["total_minutes"], 20)
        model.predict.assert_not_called()

    def test_request_framing_never_strips_additional_requirements(self):
        from app.services.verified_catalog import simple_catalog_intent
        self.assertIsNone(simple_catalog_intent(
            "help me get recipes that take 30 minutes or less for dinner without peanuts"
        ))
