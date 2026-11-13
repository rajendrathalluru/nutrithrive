import json
import tempfile
import time
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock, patch

from app.services.intent_analyzer import IntentAnalyzer
from app.services.rag_service import RecipeRAGService
from app.services.recipe_verifier import RecipeVerifier
from app.services.verified_catalog import catalog_matches, fingerprint, policy_identity, simple_timed_intent


QUERY = "Show recipes that take 30 minutes or less for dinner"


class VerifiedCatalogTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "catalog.json"
        self.intent = simple_timed_intent(QUERY)
        self.verifier = RecipeVerifier()
        self.verifier.initialize(Mock(predict=Mock(side_effect=AssertionError("No model call allowed"))))
        self.guidelines = Mock(validate_recipe_compliance=Mock(return_value={"overall_compliant": True}))
        self.recipes = [{
            "recipe_id": f"beans-{index}", "name": f"Bean Meal {index}", "type": "Main Dishes",
            "database_record_found": True, "ingredients": ["1 can cooked beans"],
            "instructions": ["Open and drain the beans for 2 minutes.", "Serve for 1 minute."],
            "total_time": "3 minutes",
        } for index in range(3)]
        self.catalog = {"created_at": time.time(), "policy": policy_identity(), "profiles": {
            fingerprint(self.intent): [{
                "name": recipe["name"], "recipe_hash": fingerprint(recipe),
                "assessment": {
                    "relevance": "match", "constraint_violations": [],
                    "constraint_checks": {key: {"status": "pass", "evidence": "Fixture meal and timing evidence"}
                                          for key in self.verifier._required_checks(self.intent)},
                    "time_check": {"total_minutes": 3, "evidence": [{"field": "total_time", "quote": "3 minutes"}]},
                },
            } for recipe in self.recipes]
        }}
        self.write_catalog()

    def write_catalog(self):
        self.path.write_text(json.dumps(self.catalog))

    def build(self, name):
        return deepcopy(next(recipe for recipe in self.recipes if recipe["name"] == name))

    def matches(self, intent=None):
        return catalog_matches(intent or self.intent, self.build, self.verifier, self.guidelines, self.path)

    def test_rechecks_evidence_and_guidelines_without_model(self):
        self.assertEqual(len(self.matches()), 3)
        self.verifier.llm.predict.assert_not_called()
        self.assertEqual(self.guidelines.validate_recipe_compliance.call_count, 3)

    def test_recipe_changes_invalidate_only_affected_entries(self):
        self.recipes[0]["ingredients"].append("new ingredient")
        self.assertEqual(len(self.matches()), 2)

    def test_additional_requirements_cannot_reuse_generic_profile(self):
        changed = deepcopy(self.intent)
        changed["constraints"]["allergens_to_avoid"] = ["peanuts"]
        self.assertEqual(self.matches(changed), [])

    def test_policy_expiry_corruption_and_model_change_fail_closed(self):
        with patch("app.services.verified_catalog.settings.LLM_MODEL", "different-model"):
            self.assertEqual(self.matches(), [])
        self.catalog["created_at"] = 0
        self.write_catalog()
        self.assertEqual(self.matches(), [])
        self.catalog["created_at"] = time.time()
        self.catalog["policy"]["code"] = "stale"
        self.write_catalog()
        self.assertEqual(self.matches(), [])
        self.path.write_text("not json")
        self.assertEqual(self.matches(), [])

    def test_cached_pass_never_overrides_current_guidelines(self):
        self.guidelines.validate_recipe_compliance.return_value = {"overall_compliant": False}
        self.assertEqual(self.matches(), [])

    def test_missing_evidence_fails_and_duplicates_do_not_fill_slots(self):
        entries = self.catalog["profiles"][fingerprint(self.intent)]
        entries[0]["assessment"]["constraint_checks"] = {}
        entries[1:] = [deepcopy(entries[0]), deepcopy(entries[0])]
        self.write_catalog()
        self.assertEqual(self.matches(), [])

    def test_full_pipeline_returns_three_without_remote_calls(self):
        service = RecipeRAGService()
        service.is_initialized = True
        service._catalog_recipe = self.build
        service.llm = self.verifier.llm
        service.recipe_verifier = self.verifier
        service.search_engine.multi_query_search = Mock(side_effect=AssertionError("No search expected"))
        service.recipe_enhancer.generate_fallback_recipes = Mock(side_effect=AssertionError("No generation expected"))
        with patch("app.services.rag_service.settings.RECIPE_OPTIONAL_ENHANCEMENT", False), \
                patch("app.services.verified_catalog.settings.RECIPE_VERIFIED_CATALOG_PATH", str(self.path)), \
                patch("app.services.rag_service.aicr_service", self.guidelines), \
                patch("app.services.rag_service.safety_service.should_intercept", return_value=False):
            result = service.ask_question(QUERY)
        self.assertEqual(result["matches_found"], 3, result)
        self.assertEqual(result["source"], "database_exact")
        service.search_engine.multi_query_search.assert_not_called()
        self.verifier.llm.predict.assert_not_called()


class SimpleTimedIntentTests(unittest.TestCase):
    def test_vegetarian_dinner_uses_catalog_without_model_calls_to_fill_empty_slots(self):
        service = RecipeRAGService()
        service.is_initialized = True
        service.data_loader.load_data()
        model = Mock(predict=Mock(side_effect=AssertionError("Unexpected model call")))
        service.intent_analyzer.initialize(model)
        service.recipe_verifier.initialize(model)
        service.response_generator.initialize(model)
        service.search_engine.multi_query_search = Mock(side_effect=AssertionError("Unexpected remote search"))
        with patch("app.services.rag_service.settings.RECIPE_OPTIONAL_ENHANCEMENT", False):
            result = service.ask_question("Show me some vegetarian dinner recipes")
        self.assertGreater(result["matches_found"], 0, result)
        self.assertTrue(all(recipe["verification_details"]["method"] == "catalog_label_local_checks"
                            for recipe in result["source_documents"]))
        model.predict.assert_not_called()
        service.search_engine.multi_query_search.assert_not_called()

    def test_plain_time_request_uses_live_catalog_rows_without_snapshot_or_model(self):
        service = RecipeRAGService()
        service.is_initialized = True
        service.data_loader.load_data()
        model = Mock(predict=Mock(side_effect=AssertionError("Unexpected model call")))
        service.intent_analyzer.initialize(model)
        service.recipe_verifier.initialize(model)
        service.response_generator.initialize(model)
        service.search_engine.multi_query_search = Mock(side_effect=AssertionError("Unexpected remote search"))
        with patch("app.services.rag_service.catalog_matches", return_value=[]), \
                patch("app.services.rag_service.settings.RECIPE_OPTIONAL_ENHANCEMENT", False), \
                patch("app.services.rag_service.safety_service.should_intercept", return_value=False):
            result = service.ask_question("Show recipes that take 30 minutes or less")
        self.assertEqual(result["matches_found"], 3, result)
        self.assertIn("source-listed total times", result["response"])
        for recipe in result["source_documents"]:
            self.assertLessEqual(recipe["verification_details"]["time_check"]["total_minutes"], 30)
            self.assertEqual(recipe["verification_details"]["method"], "catalog_declared_time_local_checks")
        model.predict.assert_not_called()
        service.search_engine.multi_query_search.assert_not_called()

    def test_exact_request_avoids_model_and_preserves_boundary(self):
        analyzer = IntentAnalyzer()
        analyzer.initialize(Mock(predict=Mock(side_effect=AssertionError("No model call expected"))))
        result = analyzer.understand_query_intent_with_context(QUERY)
        self.assertEqual(result, simple_timed_intent(QUERY))
        self.assertFalse(result["constraints"]["time_limit_exclusive"])
        self.assertTrue(simple_timed_intent("Show recipes that take under 30 minutes")["constraints"]["time_limit_exclusive"])

    def test_extra_requirements_and_followups_do_not_use_grammar(self):
        for query in (QUERY + " without nuts", QUERY + " for six people", "more recipes", "same but under 30 minutes",
                      "Show recipes that take 30 minutes", "Show recipes that take under 30 minutes or less"):
            self.assertIsNone(simple_timed_intent(query), query)

    def test_canonicalization_preserves_meal_requirement(self):
        intent = simple_timed_intent("Please give me meals that take 30 minutes or less")
        self.assertEqual(intent["constraints"]["meal_suitability"], "meal")
        self.assertEqual(simple_timed_intent(intent["resolved_query"]), intent)
