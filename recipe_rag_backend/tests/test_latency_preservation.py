import copy
import json
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch

from langchain.schema import Document
from app.services.intent_analyzer import IntentAnalyzer
from app.services.recipe_verifier import RecipeVerifier
from app.services.response_cache import ResponseCache
from app.services.budget_service import apply_budget_intent
from app.services.model_errors import RecipeModelUnavailable
from app.services.search_engine import SearchEngine
from guideline_fixtures import passing_guideline_checks


class ResponseCacheTests(unittest.TestCase):
    def test_expiry_capacity_and_mutation_isolation(self):
        now = [0.0]
        cache = ResponseCache(ttl=10, capacity=2, clock=lambda: now[0])
        value = {"ingredients": ["rice"]}
        cache.put("first", value)
        value["ingredients"].append("nuts")
        result = cache.get("first")
        self.assertEqual(result, {"ingredients": ["rice"]})
        result["ingredients"].append("milk")
        self.assertEqual(cache.get("first"), {"ingredients": ["rice"]})
        cache.put("second", {})
        cache.get("first")
        cache.put("third", {})
        self.assertIsNone(cache.get("second"))
        now[0] = 10
        self.assertIsNone(cache.get("first"))
        self.assertEqual(cache.stats()["cache_size"], 0)
        cache.clear()
        self.assertEqual(cache.stats()["cache_hits"], 0)

    def test_disabled_cache_always_misses(self):
        cache = ResponseCache(ttl=0)
        cache.put("key", {"value": True})
        self.assertIsNone(cache.get("key"))
        self.assertEqual(cache.stats()["cache_size"], 0)

    def test_concurrent_access_is_bounded_and_thread_safe(self):
        cache = ResponseCache(capacity=8)
        def work(index):
            cache.put(str(index), {"index": index})
            result = cache.get(str(index))
            if result is not None:
                self.assertEqual(result["index"], index)
        with ThreadPoolExecutor(max_workers=3) as executor:
            list(executor.map(work, range(100)))
        self.assertLessEqual(cache.stats()["cache_size"], 8)


class IntentCacheTests(unittest.TestCase):
    def setUp(self):
        self.analyzer = IntentAnalyzer()
        self.query = "more recipes"
        self.parsed = self.analyzer._get_fallback_intent_data("Show vegetarian recipes")
        self.parsed.update(query_type="recipe_search", context_action="continue_request")
        self.model = Mock(predict=Mock(return_value=json.dumps(self.parsed)))
        self.analyzer.initialize(self.model)
        self.history = [{"role": "user", "content": "Show vegetarian recipes"},
                        {"role": "assistant", "content": "Here are your recipes.", "recipes": [
                            {"recipe_id": "bowl", "name": "Bean Bowl", "ingredients": ["canned beans"], "instructions": ["Heat beans."]}
                        ]}]

    def test_identical_scoped_context_reuses_result_without_mutation_leaks(self):
        first = self.analyzer.understand_query_intent_with_context(self.query, self.history)
        expected = copy.deepcopy(first)
        first["constraints"]["ingredients_must_use"] = ["chicken"]
        second = self.analyzer.understand_query_intent_with_context(self.query, self.history)
        self.assertEqual(second, expected)
        self.assertEqual(self.model.predict.call_count, 1)
        self.assertEqual(self.analyzer.get_cache_stats()["context_response_cache"]["cache_hits"], 1)

    def test_history_recipe_changes_and_model_changes_invalidate_context_cache(self):
        self.analyzer.understand_query_intent_with_context(self.query, self.history)
        self.history[-1]["recipes"][0]["ingredients"].append("rice")
        self.analyzer.understand_query_intent_with_context(self.query, self.history)
        self.assertEqual(self.model.predict.call_count, 2)
        self.history[0]["content"] = "Show recipes without peanuts"
        self.analyzer.understand_query_intent_with_context(self.query, self.history)
        self.assertEqual(self.model.predict.call_count, 3)
        self.model.temperature = 0.25
        self.analyzer.understand_query_intent_with_context(self.query, self.history)
        self.assertEqual(self.model.predict.call_count, 4)

    def test_new_requests_remain_independent_and_cached_intent_cannot_be_mutated(self):
        query = "Show recipes using chicken and broccoli"
        first = self.analyzer.understand_query_intent_with_context(query, self.history)
        expected = copy.deepcopy(first)
        first["constraints"]["ingredients_must_use"] = ["pork"]
        second = self.analyzer.understand_query_intent_with_context(query, self.history)
        self.assertEqual(second, expected)
        self.assertEqual(second["context_action"], "new_request")
        self.assertEqual(self.model.predict.call_count, 1)


class BudgetLatencyTests(unittest.TestCase):
    def setUp(self):
        self.query = "Mexican recipes under $10"
        self.intent = {"search_strategy": {"enhanced_query": self.query, "search_keywords": ["Mexican", "dinner"]},
                       "preferences": {"cuisine_types": ["Mexican"]}, "constraints": {"allergens_to_avoid": ["peanuts"]}}
        apply_budget_intent(self.intent, self.query)
        self.engine = SearchEngine()
        self.embeddings = Mock(embed_documents=Mock(return_value=[[1.0], [2.0], [3.0]]))
        self.store = Mock()
        self.engine.initialize(self.store, Mock(), self.embeddings)

    def test_batch_preserves_all_queries_ranked_candidates_and_deduplication(self):
        first = Document(page_content="Black bean soup")
        second = Document(page_content="Vegetable migas")
        third = Document(page_content="Chicken and pepper skillet")
        matches = [[first, second], [second, third], [first]]
        queries = [self.query, "Mexican dinner", "Mexican"]
        self.store.similarity_search_by_vector.side_effect = lambda vector, k: matches[int(vector[0]) - 1]
        self.store.similarity_search.side_effect = lambda query, k: matches[queries.index(query)]
        intent = {key: value for key, value in self.intent.items() if key != "budget_request"}
        batched = self.engine.multi_query_search(self.query, intent, 8)
        self.embeddings.embed_documents.assert_called_once_with(queries)
        self.store.similarity_search.assert_not_called()
        self.assertEqual(self.store.similarity_search_by_vector.call_count, 3)
        with patch.object(self.engine, "embeddings", None):
            baseline = self.engine.multi_query_search(self.query, intent, 8)
        self.assertEqual(batched, baseline)
        self.assertEqual(batched, [first, second, third])
        self.assertEqual(self.embeddings.embed_documents.call_count, 1)

    def test_batch_failure_uses_existing_individual_searches(self):
        self.embeddings.embed_documents.side_effect = RuntimeError("Batch failed")
        self.store.similarity_search.return_value = [Document(page_content="Mexican dinner")]
        self.assertEqual(len(self.engine.multi_query_search(self.query, self.intent, 8)), 1)
        self.assertEqual(self.store.similarity_search.call_count, 3)
        self.store.similarity_search_by_vector.assert_not_called()

class VerificationLatencyTests(unittest.TestCase):
    def setUp(self):
        self.intent = {"recipe_request": "Show bean bowls", "constraints": {}}
        self.recipe = {"name": "Bean Bowl", "type": "Main Dish", "ingredients": ["1 can beans"],
                       "instructions": ["Heat the beans thoroughly."], "generated_by_llm": True}
        self.verifier = RecipeVerifier()
        self.model = Mock(predict=Mock(side_effect=self.response))
        self.verifier.initialize(self.model)
        self.guidelines = Mock(validate_recipe_compliance=Mock(return_value={"overall_compliant": True, "score": 100, "warnings": []}))

    def response(self, prompt):
        candidates = json.JSONDecoder().raw_decode(prompt.split("RECIPES TO VERIFY:\n", 1)[1])[0]
        return json.dumps([{
            "id": candidate["id"], "relevance": "match", "constraint_violations": [],
            "constraint_checks": {key: {"status": "pass", "evidence": "Mock assessment of actual recipe content."}
                                  for key in self.verifier._required_checks(self.intent)},
            "guideline_checks": passing_guideline_checks(),
            "ingredient_completeness_check": {"status": "pass", "evidence": "Mock assessment of listed food quantities."},
            "portion_adequacy_check": {"status": "pass", "evidence": "Mock assessment of realistic servings."},
        } for candidate in candidates])

    def verify(self, recipes=None):
        return self.verifier.batch_verify_recipes(copy.deepcopy(recipes or [self.recipe]), self.intent, self.guidelines)

    def test_same_assessment_reused_but_all_final_checks_run_again(self):
        with patch.object(self.verifier, "_finalize_verification", wraps=self.verifier._finalize_verification) as finalize:
            first = self.verify()
            expected = copy.deepcopy(first)
            first[0]["verification_details"]["passes_verification"] = False
            self.assertEqual(self.verify(), expected)
            self.assertEqual(self.model.predict.call_count, 1)
            self.assertEqual(finalize.call_count, 2)
            self.assertEqual(self.guidelines.validate_recipe_compliance.call_count, 2)
            self.assertTrue(expected[0]["verification_details"]["passes_verification"])

    def test_assessment_reused_when_batch_membership_changes(self):
        second = {**self.recipe, "name": "Another Bowl"}
        self.verify([self.recipe, second])
        calls = self.model.predict.call_count
        self.verify([second])
        self.assertEqual(self.model.predict.call_count, calls)

    def test_generated_review_keeps_pass_when_other_candidate_times_out(self):
        from openai.error import Timeout

        def review(prompt):
            if "Slow Candidate" in prompt:
                raise Timeout("Simulated review timeout")
            return self.response(prompt)

        self.model.predict.side_effect = review
        self.intent["_independent_final_review"] = True
        recipes = [self.recipe, {**self.recipe, "name": "Slow Candidate"}]
        with patch("app.services.recipe_verifier.settings.RECIPE_IO_WORKERS", 2):
            result = self.verify(recipes)
        self.assertEqual([recipe["name"] for recipe in result], [self.recipe["name"]])
        self.assertTrue(result[0]["verification_details"]["passes_verification"])
        self.assertEqual(self.model.predict.call_count, 2)

    def test_shared_fit_reviews_four_candidates_in_one_call(self):
        self.intent["_shared_fit_batch"] = True
        recipes = [{**self.recipe, "name": f"Meal {index}"} for index in range(4)]
        result = self.verify(recipes)
        self.assertEqual(len(result), 4)
        self.assertTrue(all(recipe["verification_details"]["passes_verification"] for recipe in result))
        self.assertEqual(self.model.predict.call_count, 1)

    def test_shared_fit_malformed_response_does_not_retry_each_recipe(self):
        self.intent["_shared_fit_batch"] = True
        self.model.predict.side_effect = None
        self.model.predict.return_value = "invalid json"
        self.assertEqual(self.verify(), [])
        self.assertEqual(self.model.predict.call_count, 1)

    def test_complete_negative_assessment_is_reused_without_retry(self):
        def rejected(prompt):
            results = json.loads(self.response(prompt))
            for result in results:
                result["relevance"] = "unrelated"
                result["constraint_checks"]["recipe_request"] = {"status": "fail", "evidence": "Different requested dish"}
            return json.dumps(results)
        self.model.predict.side_effect = rejected
        self.assertFalse(self.verify()[0]["verification_details"]["passes_verification"])
        self.assertFalse(self.verify()[0]["verification_details"]["passes_verification"])
        self.assertEqual(self.model.predict.call_count, 1)

    def test_scheduling_flag_does_not_invalidate_identical_assessment(self):
        expected = self.verify()
        self.intent["_parallel_catalog_verification"] = True
        self.assertEqual(self.verify(), expected)
        self.assertEqual(self.model.predict.call_count, 1)
        self.assertEqual(self.guidelines.validate_recipe_compliance.call_count, 2)

    def test_changed_recipe_intent_and_guideline_policy_require_new_model_assessments(self):
        self.verify()
        for field, value in [("ingredients", ["1 can beans", "peanuts"]), ("instructions", ["Serve cold."]),
                             ("helpful_tips", ["Add rice."]), ("ingredient_adaptations", ["Substitute lentils."])]:
            self.recipe[field] = value
            self.verify()
        self.assertEqual(self.model.predict.call_count, 5)
        self.intent["constraints"]["allergens_to_avoid"] = ["milk"]
        self.verify()
        self.assertEqual(self.model.predict.call_count, 6)
        with patch.object(self.verifier, "_guideline_contract", return_value="Updated policy"):
            self.verify()
        self.assertEqual(self.model.predict.call_count, 7)

    def test_cached_pass_cannot_override_current_guideline_failure(self):
        self.assertTrue(self.verify()[0]["verification_details"]["passes_verification"])
        self.guidelines.validate_recipe_compliance.return_value = {"overall_compliant": False, "score": 0, "warnings": ["Changed safety policy"]}
        result = self.verify()[0]
        self.assertFalse(result["verification_details"]["passes_verification"])
        self.assertEqual(self.model.predict.call_count, 1)
        self.assertEqual(self.verifier.batch_response_cache.stats()["cache_size"], 0)
        self.verify()
        self.assertEqual(self.model.predict.call_count, 2)

    def test_cached_pass_cannot_override_a_failed_deterministic_check(self):
        self.verify()
        with patch.object(self.verifier, "_finalize_verification", return_value={
            "passes_verification": False, "relevance": "match", "constraint_violations": ["Unsafe preparation"],
        }):
            self.assertFalse(self.verify()[0]["verification_details"]["passes_verification"])
        self.assertEqual(self.model.predict.call_count, 1)
        self.assertEqual(self.verifier.batch_response_cache.stats()["cache_size"], 0)

    def test_failed_or_malformed_assessments_are_not_cached(self):
        self.model.predict.side_effect = None
        for response in ('not json', '[{"id": 0, "relevance": "match", "constraint_violations": []}]'):
            self.model.predict.return_value = response
            self.verifier.clear_caches()
            self.assertFalse(self.verify()[0]["verification_details"]["passes_verification"])
            self.assertEqual(self.verifier.batch_response_cache.stats()["cache_size"], 0)

    def test_budget_prices_and_patient_requirements_are_not_hidden_by_cache(self):
        apply_budget_intent(self.intent, "Show meals under $10 for the whole recipe")
        self.intent["budget_price_options"] = [{"name": "beans", "package_price": "1"}]
        self.verify()
        self.verify()
        self.assertEqual(self.model.predict.call_count, 1)
        self.intent["budget_price_options"][0]["package_price"] = "20"
        self.verify()
        self.assertEqual(self.model.predict.call_count, 2)
        self.intent["cancer_patient_specific"] = {"symptoms": ["nausea"]}
        self.verify()
        self.assertEqual(self.model.predict.call_count, 3)

    def test_initialization_and_clear_expire_model_assessments(self):
        self.verify()
        self.verifier.clear_caches()
        self.verify()
        self.assertEqual(self.model.predict.call_count, 2)
        self.verifier.initialize(self.model)
        self.verify()
        self.assertEqual(self.model.predict.call_count, 3)

    def test_expired_assessment_requires_fresh_model_verification(self):
        now = [0.0]
        self.verifier.batch_response_cache = ResponseCache(ttl=10, clock=lambda: now[0])
        self.verify()
        now[0] = 10
        self.verify()
        self.assertEqual(self.model.predict.call_count, 2)

    def test_independent_batches_overlap_and_keep_original_order(self):
        barrier = threading.Barrier(3)
        original = self.response
        def response(prompt):
            barrier.wait(timeout=3)
            return original(prompt)
        self.model.predict.side_effect = response
        recipes = [{**copy.deepcopy(self.recipe), "name": f"Bowl {index}"} for index in range(8)]
        with patch("app.services.recipe_verifier.settings.RECIPE_IO_WORKERS", 3):
            results = self.verify(recipes)
        self.assertEqual([recipe["name"] for recipe in results], [recipe["name"] for recipe in recipes])
        self.assertTrue(all(recipe["verification_details"]["passes_verification"] for recipe in results))
        self.assertEqual(self.model.predict.call_count, 3)

    def test_serial_and_parallel_batches_keep_identical_verified_results(self):
        recipes = [{**copy.deepcopy(self.recipe), "name": f"Bowl {index}"} for index in range(8)]
        self.verifier.batch_response_cache.ttl = 0
        with patch("app.services.recipe_verifier.settings.RECIPE_IO_WORKERS", 1):
            serial = self.verify(recipes)
        with patch("app.services.recipe_verifier.settings.RECIPE_IO_WORKERS", 3):
            parallel = self.verify(recipes)
        self.assertEqual(serial, parallel)

    def test_serial_mode_stops_immediately_when_model_is_unavailable(self):
        self.model.predict.side_effect = RecipeModelUnavailable("Model unavailable")
        recipes = [{**copy.deepcopy(self.recipe), "name": f"Bowl {index}"} for index in range(8)]
        with patch("app.services.recipe_verifier.settings.RECIPE_IO_WORKERS", 1):
            with self.assertRaises(RecipeModelUnavailable):
                self.verify(recipes)
        self.assertEqual(self.model.predict.call_count, 1)
