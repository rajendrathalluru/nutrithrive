import json
import unittest
from unittest.mock import Mock, patch

from app.services.rag_service import RecipeRAGService
from app.services.single_pass_generation import generate_once, ingredient_cost_estimate, response_format
from app.services.recipe_verifier import RecipeVerifier
from app.services.intent_analyzer import IntentAnalyzer
from app.services.aicr_guidelines_service import aicr_service
from guideline_fixtures import passing_guideline_checks


QUERY = "can you help me to prepare a thanksgiving dinner for 6 people majorly chinese recipes"


class SinglePassGenerationTests(unittest.TestCase):
    def test_ingredient_ranges_are_summed_only_with_complete_unique_coverage(self):
        recipe = {"ingredients": ["1 can beans", "1 cup rice"]}
        costs = [{"ingredient_index": 1, "low": 1, "high": 2},
                 {"ingredient_index": 0, "low": 2, "high": 3}]
        estimate = ingredient_cost_estimate(recipe, costs, {"currency": "USD", "basis": "recipe"})
        self.assertEqual((estimate["low"], estimate["high"]), (3, 5))
        self.assertEqual([item["ingredient"] for item in estimate["line_items"]], recipe["ingredients"])
        self.assertIsNone(ingredient_cost_estimate(recipe, costs[:1], {}))
        self.assertIsNone(ingredient_cost_estimate(recipe, [costs[0], costs[0]], {}))

    def test_real_client_copy_preserves_transport_without_retries(self):
        from langchain.chat_models import ChatOpenAI

        model = ChatOpenAI(openai_api_key="test", max_retries=2)
        response = {"choices": [{"message": {"role": "assistant", "content": '{"recipes": []}'}}]}
        with patch.object(model.client, "create", return_value=response) as create:
            generate_once(model, QUERY, {"constraints": {}}, RecipeVerifier(), aicr_service)
        create.assert_called_once()
        self.assertEqual(model.max_retries, 2)

    def setUp(self):
        self.service = RecipeRAGService()
        self.service.is_initialized = True
        self.model = Mock(predict=Mock(side_effect=self.reply))
        self.service.llm = self.model
        self.service.intent_analyzer.initialize(self.model)
        self.service.recipe_verifier.initialize(self.model)
        self.service.response_generator.initialize(self.model)
        self.service.search_engine.multi_query_search = Mock(side_effect=AssertionError("Unexpected search"))
        self.service.recipe_verifier.batch_verify_recipes = Mock(side_effect=AssertionError("Unexpected model verification"))
        self.service.recipe_enhancer.generate_fallback_recipes = Mock(side_effect=AssertionError("Unexpected repair"))
        self.mutate = lambda recipes: recipes

    def reply(self, prompt, **kwargs):
        intent = json.JSONDecoder().raw_decode(prompt.split("ACTIVE REQUIREMENTS: ", 1)[1])[0]
        recipes = [{
            "name": f"Chinese Bean Dinner {index}", "type": "Main Dish", "description": "Chinese-inspired dinner.",
            "servings": 6, "ingredients": ["6 cups cooked beans", "6 cups cooked brown rice"],
            "instructions": ["Heat beans thoroughly and serve with the rice."],
            "total_time": "10 minutes", "storage_instructions": "Refrigerate leftovers promptly.",
            "assessment": {
                "relevance": "match", "constraint_violations": [],
                "constraint_checks": {key: {"status": "pass", "evidence": "Fixture recipe evidence"}
                                      for key in self.service.recipe_verifier._required_checks(intent)},
                "guideline_checks": passing_guideline_checks(),
                "portion_adequacy_check": {"status": "pass", "evidence": "Six cups each of beans and rice for six people."},
            },
        } for index in range(3)]
        return json.dumps({"recipes": self.mutate(recipes), "follow_up": {
            "question": "Would a make-ahead side help?",
            "choices": [
                {"label": "Make ahead", "instruction": "Suggest a side I can make ahead."},
                {"label": "Quick side", "instruction": "Suggest a quick side."},
            ],
        }})

    def ask(self):
        with patch("app.services.rag_service.settings.RECIPE_SINGLE_PASS_DINNER", True), \
                patch("app.services.rag_service.safety_service.should_intercept", return_value=False):
            result = self.service.ask_question(QUERY, conversation_history=[
                {"role": "user", "content": "Show recipes under 30 minutes"},
                {"role": "assistant", "content": "Here are quick recipes."},
            ])
        self.model.predict.assert_called_once()
        self.service.recipe_verifier.batch_verify_recipes.assert_not_called()
        self.service.search_engine.multi_query_search.assert_not_called()
        self.service.recipe_enhancer.generate_fallback_recipes.assert_not_called()
        return result

    def test_one_call_returns_three_with_honest_review_provenance(self):
        result = self.ask()
        self.assertEqual(result["matches_found"], 3, result)
        self.assertEqual(result["follow_up"]["question"], "Would a make-ahead side help?")
        self.assertNotIn("independently verified", result["response"])
        self.assertIn("not independently AI-reviewed", result["response"])
        self.assertTrue(all(recipe["source_label"] == "AI Generated" for recipe in result["source_documents"]))
        self.assertTrue(all(recipe["verification_details"]["independent_model_review"] is False
                            for recipe in result["source_documents"]))
        self.assertIsNone(result["intent_analysis"]["constraints"]["time_max_minutes"])
        self.assertEqual(self.model.predict.call_args.kwargs["response_format"]["type"], "json_schema")

    def test_wrong_yield_is_rejected_without_repair(self):
        def wrong_yield(recipes):
            recipes[0]["servings"] = 2
            return recipes
        self.mutate = wrong_yield
        self.assertEqual(self.ask()["matches_found"], 2)

    def test_missing_instructions_are_not_accepted(self):
        def fail_checks(recipes):
            recipes[0]["instructions"] = []
            return recipes
        self.mutate = fail_checks
        self.assertEqual(self.ask()["matches_found"], 2)

    def test_missing_checks_and_malformed_json_do_not_trigger_more_calls(self):
        for response in ('not json', '{"recipes": []}', '{"recipes": [{"name": "Incomplete"}]}'):
            with self.subTest(response=response):
                self.model.predict.reset_mock(side_effect=True)
                self.model.predict.return_value = response
                result = self.ask()
                self.assertEqual(result["matches_found"], 0)

    def test_schema_closes_all_objects_and_requires_all_declared_fields(self):
        analyzer = IntentAnalyzer()
        intent = analyzer._post_process_intent(QUERY, analyzer._get_fallback_intent_data(QUERY))
        schema = response_format(RecipeVerifier(), intent)["json_schema"]["schema"]
        def check(node):
            if node.get("type") == "object":
                self.assertFalse(node["additionalProperties"])
                self.assertEqual(set(node["required"]), set(node["properties"]))
                for child in node["properties"].values():
                    check(child)
            elif node.get("type") == "array":
                check(node["items"])
        check(schema)

    def test_missing_specialized_checks_never_call_completion_model(self):
        intent = {"constraints": {"ingredient_storage": "canned_only"}}
        verifier = RecipeVerifier()
        model = Mock(predict=Mock(return_value=json.dumps({"recipes": [{
            "name": "Beans", "servings": 6, "ingredients": ["1 can beans"], "instructions": ["Serve"],
            "assessment": {"constraint_checks": {}, "relevance": "match", "constraint_violations": []},
        }]})))
        verifier.initialize(model)
        result = generate_once(model, QUERY, intent, verifier, aicr_service)
        model.predict.assert_called_once()
        self.assertFalse(result[0]["verification_details"]["passes_verification"])
