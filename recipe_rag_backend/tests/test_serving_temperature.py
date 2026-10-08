import copy
import json
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app.services.data_loader import DataLoader
from app.services.intent_analyzer import IntentAnalyzer
from app.services.rag_service import RecipeRAGService
from app.services.recipe_enhancer import RecipeEnhancer
from app.services.recipe_prompt_rules import SERVING_TEMPERATURE_RULES
from app.services.recipe_verifier import RecipeVerifier
from app.services.response_generator import ResponseGenerator
from app.services.serving_temperature import audit_serving_temperature, explicit_serving_temperature


class ServingTemperatureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.loader = DataLoader()
        cls.loader.load_data(Path(__file__).parents[1] / "app/data/Recipe.csv")

    def setUp(self):
        self.intent = {"constraints": {"serving_temperature": "warm_not_hot"}, "preferences": {}}
        self.recipe = {"name": "Lentil Soup", "ingredients": ["1 can lentils", "1 cup vegetable broth"],
                       "instructions": ["Simmer the lentils in broth.", "Serve warm."]}

    def assessment(self, recipe=None, quote=None, field="instructions", index=None):
        recipe = recipe or self.recipe
        index = len(recipe["instructions"]) - 1 if index is None else index
        return {
            "id": 0, "relevance": "match", "constraint_violations": [],
            "constraint_checks": {"constraints.serving_temperature": {"status": "pass", "evidence": "Model claims warm serving."}},
            "serving_temperature_check": {
                "evidence": [{"field": field, "index": index, "quote": quote or recipe["instructions"][index]}],
                "conflicting_guidance": [], "food_safety_concerns": [],
            },
        }

    def verify(self, recipe=None, assessment=None, batch=False):
        recipe = recipe or self.recipe
        assessment = assessment or self.assessment(recipe)
        verifier = RecipeVerifier()
        verifier.initialize(Mock(predict=Mock(return_value=json.dumps([assessment] if batch else assessment))))
        if batch:
            guidelines = Mock(validate_recipe_compliance=Mock(return_value={"overall_compliant": True}))
            return verifier.batch_verify_recipes([copy.deepcopy(recipe)], self.intent, guidelines)[0]["verification_details"]
        return verifier.verify_recipe_against_constraints(recipe, self.intent)

    def test_category_request_is_guidance_not_no_heat_or_a_recipe_search(self):
        query = "Show foods that taste good warm but not hot"
        analyzer = IntentAnalyzer()
        for route in ("general", "recipe_search", "food_guidance"):
            intent = analyzer._get_fallback_intent_data(query)
            intent["query_type"] = route
            result = analyzer._post_process_intent(query, intent)
            self.assertEqual(result["query_type"], "food_guidance")
            self.assertEqual(result["constraints"]["serving_temperature"], "warm_not_hot")
            self.assertIsNone(result["constraints"]["preparation_mode"])
            self.assertIsNone(result["constraints"]["chewing_effort"])
            self.assertEqual(result["cancer_patient_specific"]["symptoms"], [])

    def test_explicit_recipe_requests_keep_search_and_temperature(self):
        query = "Show recipes that taste good warm but not hot"
        analyzer = IntentAnalyzer()
        intent = analyzer._get_fallback_intent_data(query)
        intent["query_type"] = "food_guidance"
        result = analyzer._post_process_intent(query, intent)
        self.assertEqual(result["query_type"], "recipe_search")
        self.assertIn("serve warm", result["search_strategy"]["search_keywords"])

    def test_guidance_to_recipe_followup_preserves_user_constraints(self):
        analyzer = IntentAnalyzer()
        intent = analyzer._get_fallback_intent_data("more")
        intent["query_type"] = "food_guidance"
        intent["constraints"]["dietary_restrictions"] = ["vegan"]
        result = analyzer._post_process_intent("Vegan foods that taste good warm but not hot", intent, current_query="Give me recipes for those")
        self.assertEqual(result["query_type"], "recipe_search")
        self.assertEqual(result["constraints"]["serving_temperature"], "warm_not_hot")
        self.assertEqual(result["constraints"]["dietary_restrictions"], ["vegan"])

    def test_user_temperature_survives_model_omission_but_does_not_leak_between_chats(self):
        analyzer = IntentAnalyzer()
        analyzer.initialize(Mock(predict=Mock(side_effect=lambda prompt: json.dumps(analyzer._get_fallback_intent_data("More recipes")))))
        history = [
            {"role": "user", "content": "Show foods that taste good warm but not hot"},
            {"role": "assistant", "content": "A salad can be served cold."},
        ]
        result = analyzer.understand_query_intent_with_context("More recipes", history)
        self.assertEqual(result["constraints"]["serving_temperature"], "warm_not_hot")
        reset = analyzer.understand_query_intent_with_context("Start over, Chinese dinner recipes", history)
        self.assertIsNone(reset["constraints"]["serving_temperature"])
        independent = analyzer.understand_query_intent_with_context("Chinese dinner recipes", [])
        self.assertIsNone(independent["constraints"]["serving_temperature"])

    def test_latest_temperature_overrides_and_can_be_removed(self):
        analyzer = IntentAnalyzer()
        for current, expected in (("Serve them cold instead", "cold"), ("Any serving temperature is fine", None)):
            intent = analyzer._get_fallback_intent_data(current)
            result = analyzer._post_process_intent("Recipes served warm but not hot", intent, current_query=current)
            self.assertEqual(result["constraints"]["serving_temperature"], expected)
        self.assertEqual(explicit_serving_temperature("Warm but not hot was my preference; serve cold instead"), "cold")
        self.assertEqual(explicit_serving_temperature("Comfortably warm foods"), "warm_not_hot")
        intent = analyzer._get_fallback_intent_data("warm")
        reset = analyzer._post_process_intent("Foods served warm but not hot", intent, current_query="Start over, Chinese recipes")
        self.assertIsNone(reset["constraints"]["serving_temperature"])

    def test_spice_heat_negations_and_no_heat_are_not_serving_temperatures(self):
        for query in ("Use hot sauce", "No-heat recipes", "Avoid warm foods", "Don't show warm foods", "Do not serve hot"):
            self.assertIsNone(explicit_serving_temperature(query), query)
        analyzer = IntentAnalyzer()
        intent = analyzer._post_process_intent("No-heat recipes served cold", analyzer._get_fallback_intent_data("cold"))
        self.assertEqual(intent["constraints"]["serving_temperature"], "cold")
        self.assertEqual(intent["constraints"]["preparation_mode"], "no_heat")

    def test_reported_salads_fail_even_with_positive_model_assessment(self):
        service = RecipeRAGService()
        service.data_loader = self.loader
        for name in ("White Bean and Tomato Bruschetta Salad", "Edamame Salad with Orange-Balsamic Dressing"):
            recipe = service._build_recipe_data_from_record(self.loader.get_recipe_record(name))
            for batch in (False, True):
                with self.subTest(name=name, batch=batch):
                    result = self.verify(recipe, batch=batch)
                    self.assertFalse(result["passes_verification"])
                    self.assertEqual(result["relevance"], "adaptable")

    def test_warm_soup_and_warm_salad_are_not_rejected_by_category(self):
        for name in ("Lentil Soup", "Warm Grain Salad"):
            self.recipe["name"] = name
            for source in ("database_exact", "llm_generated"):
                self.recipe["source"] = source
                self.assertTrue(self.verify()["passes_verification"])

    def test_cooking_heat_title_and_warm_component_are_not_serving_evidence(self):
        for step in ("Heat the broth.", "Serve immediately.", "Add warm beans to chilled salad greens."):
            self.recipe["instructions"] = [step]
            self.recipe["name"] = "Warm Salad"
            self.assertFalse(self.verify()["passes_verification"])

    def test_fabricated_wrong_field_and_negation_omitting_citations_fail(self):
        assessments = [self.assessment(quote="Serve comfortably warm."), self.assessment(field="description", quote="Serve warm.")]
        self.recipe["description"] = "Serve warm."
        for assessment in assessments:
            self.assertFalse(self.verify(assessment=assessment)["passes_verification"])
        self.recipe["instructions"] = ["Do not serve warm."]
        self.assertFalse(self.verify(assessment=self.assessment(quote="serve warm"))["passes_verification"])

    def test_missing_or_adverse_temperature_contract_fails_closed(self):
        for check in (None, {}, {"evidence": [], "conflicting_guidance": [], "food_safety_concerns": []}):
            assessment = self.assessment()
            assessment["serving_temperature_check"] = check
            self.assertFalse(self.verify(assessment=assessment)["passes_verification"])
        assessment = self.assessment()
        assessment["serving_temperature_check"]["food_safety_concerns"] = ["Unsafe lukewarm holding"]
        self.assertFalse(self.verify(assessment=assessment)["passes_verification"])

    def test_cold_and_hot_guidance_cannot_override_warm_request(self):
        for field in ("instructions", "helpful_tips", "ingredient_adaptations", "source_notes"):
            for line in ("Serve chilled.", "Serve at room temperature.", "Serve piping hot."):
                recipe = copy.deepcopy(self.recipe)
                recipe[field] = [*recipe.get(field, []), line] if field != "source_notes" else line
                self.assertFalse(self.verify(recipe, self.assessment())["passes_verification"])

    def test_warm_option_is_valid_but_contradictory_later_sentence_is_not(self):
        for step in ("Serve warm or cold.", "Serve warm. Alternatively, serve cold.",
                     "Let the serving cool until comfortably warm, then eat promptly."):
            self.recipe["instructions"] = [step]
            self.assertTrue(self.verify()["passes_verification"])
        self.recipe["instructions"] = ["Serve warm. Chill and serve cold."]
        self.assertFalse(self.verify()["passes_verification"])

    def test_other_requests_do_not_acquire_a_temperature_requirement(self):
        self.assertEqual(audit_serving_temperature(self.recipe, None, None), [])
        analyzer = IntentAnalyzer()
        result = analyzer._post_process_intent("Chinese dinner recipes", analyzer._get_fallback_intent_data("Chinese dinner recipes"))
        self.assertIsNone(result["constraints"]["serving_temperature"])

    def test_shared_rules_reach_intent_verification_and_repair(self):
        self.assertIn(SERVING_TEMPERATURE_RULES, IntentAnalyzer()._build_intent_prompt("warm"))
        verifier = RecipeVerifier()
        self.assertIn(SERVING_TEMPERATURE_RULES, verifier._build_individual_verification_prompt(self.recipe, self.intent))
        self.assertIn(SERVING_TEMPERATURE_RULES, verifier._build_batch_verification_prompt([], self.intent))
        self.assertIn(SERVING_TEMPERATURE_RULES, RecipeEnhancer()._build_repair_prompt("warm", self.intent, self.recipe, "Guidelines"))


class FoodGuidanceRoutingTests(unittest.TestCase):
    def setUp(self):
        self.service = RecipeRAGService()
        self.service.is_initialized = True
        self.service._contains_phi_like_content = Mock(return_value=False)
        self.intent = {"query_type": "food_guidance", "constraints": {"serving_temperature": "warm_not_hot"}}
        self.service.intent_analyzer.understand_query_intent_with_context = Mock(return_value=self.intent)
        self.service.search_engine.multi_query_search = Mock()
        self.service.recipe_enhancer.generate_fallback_recipes = Mock()
        self.service.response_generator.answer_food_guidance = Mock(return_value="Porridge and soups can be enjoyed warm. Would you like recipes?")

    def test_food_guidance_does_not_retrieve_or_fabricate_recipe_cards(self):
        result = self.service.ask_question("Show foods that taste good warm but not hot")
        self.assertEqual(result["source"], "food_guidance")
        self.assertEqual(result["source_documents"], [])
        self.assertEqual(result["matches_found"], 0)
        self.assertFalse(result["conversation_context_used"])
        self.service.search_engine.multi_query_search.assert_not_called()
        self.service.recipe_enhancer.generate_fallback_recipes.assert_not_called()

    def test_safety_and_privacy_still_precede_guidance(self):
        with patch("app.services.rag_service.safety_service.should_intercept", return_value=True), patch(
            "app.services.rag_service.safety_service.build_crisis_response", return_value={"source": "safety"}
        ):
            self.assertEqual(self.service.ask_question("crisis")["source"], "safety")
        self.service.response_generator.answer_food_guidance.assert_not_called()
        self.service._contains_phi_like_content.return_value = True
        self.service._build_phi_redirect_response = Mock(return_value={"source": "privacy"})
        self.assertEqual(self.service.ask_question("food question")["source"], "privacy")
        self.service.response_generator.answer_food_guidance.assert_not_called()

    def test_guidance_prompt_preserves_constraints_and_does_not_claim_retrieved_recipes(self):
        generator = ResponseGenerator()
        generator.initialize(Mock(predict=Mock(return_value="Try porridge made with water, served comfortably warm.")))
        intent = copy.deepcopy(self.intent)
        intent["constraints"]["dietary_restrictions"] = ["dairy-free"]
        response = generator.answer_food_guidance("What foods?", intent, "Guidelines")
        self.assertTrue(response)
        prompt = generator.llm.predict.call_args.args[0]
        for phrase in ("dairy-free", "warm_not_hot", "without recipe cards", "Do not say 'I found recipes'", "lukewarm", "fda.gov"):
            self.assertIn(phrase, prompt)
        self.assertIn(SERVING_TEMPERATURE_RULES, prompt)

    def test_guidance_failure_is_not_reported_as_no_matching_recipes(self):
        generator = ResponseGenerator()
        generator.initialize(Mock(predict=Mock(side_effect=ValueError("unavailable"))))
        response = generator.answer_food_guidance("What foods?", self.intent, "Guidelines")
        self.assertIn("couldn't answer", response)
        self.assertNotIn("matching recipes", response)


if __name__ == "__main__":
    unittest.main()
