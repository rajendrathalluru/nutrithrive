import json
import runpy
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from openai.error import APIConnectionError, AuthenticationError, InvalidRequestError, RateLimitError, Timeout

from app.services.aicr_guidelines_service import aicr_service
from app.services.intent_analyzer import IntentAnalyzer
from app.services.model_errors import RecipeModelUnavailable, raise_if_model_unavailable
from app.services.rag_service import RecipeRAGService
from app.services.recipe_enhancer import RecipeEnhancer
from app.services.recipe_verifier import RecipeVerifier


class ModelAvailabilityTests(unittest.TestCase):
    def test_provider_errors_are_distinct_from_bad_model_json(self):
        for error in (InvalidRequestError("Model unavailable", "model"), AuthenticationError("Rejected"),
                      RateLimitError("Limit"), APIConnectionError("Offline"), Timeout("Timed out")):
            with self.subTest(error=type(error).__name__):
                with self.assertRaises(RecipeModelUnavailable):
                    raise_if_model_unavailable(error)
        raise_if_model_unavailable(json.JSONDecodeError("Invalid JSON", "", 0))

    def test_provider_failure_does_not_become_no_matching_recipes(self):
        service = RecipeRAGService()
        service.is_initialized = True
        model = Mock(predict=Mock(side_effect=InvalidRequestError("Deprecated model, private diagnostic", "model")))
        service.intent_analyzer.initialize(model)
        service.search_engine.multi_query_search = Mock()
        service.recipe_enhancer.generate_fallback_recipes = Mock()
        result = service.ask_question("show recipes that take 30 minutes or less")
        self.assertEqual(result["source"], "error")
        self.assertIn("temporarily unavailable", result["response"])
        self.assertNotIn("private diagnostic", result["response"])
        self.assertNotIn("rephras", result["response"])
        model.predict.assert_called_once()
        service.search_engine.multi_query_search.assert_not_called()
        service.recipe_enhancer.generate_fallback_recipes.assert_not_called()

    def test_generation_and_verification_do_not_swallow_provider_failure(self):
        model = Mock(predict=Mock(side_effect=RateLimitError("Unavailable")))
        enhancer = RecipeEnhancer()
        enhancer.initialize(model, aicr_service)
        verifier = RecipeVerifier()
        verifier.initialize(model)
        recipe = {"name": "Bean Salad", "ingredients": ["1 can beans"], "instructions": ["Mix and serve."]}
        for operation in (
            lambda: enhancer.generate_fallback_recipes("Quick recipes", {}, []),
            lambda: enhancer.generate_structured_fallback_recipe("Quick recipes", {}),
            lambda: verifier.batch_verify_recipes([recipe], {}, aicr_service),
            lambda: verifier.verify_recipe_against_constraints(recipe, {}),
        ):
            with self.assertRaises(RecipeModelUnavailable):
                operation()

    def test_invalid_intent_json_still_uses_local_constraint_parsing(self):
        analyzer = IntentAnalyzer()
        analyzer.initialize(Mock(predict=Mock(return_value="not JSON")))
        intent = analyzer.understand_query_intent("30 minutes or less")
        self.assertEqual(intent["constraints"]["time_max_minutes"], 30)

    def test_configurable_model_and_environment_precedence(self):
        for configured, expected in ((None, "gpt-4o-mini"), ("custom-deployment", "custom-deployment"), (" ", "gpt-4o-mini")):
            environment = {} if configured is None else {"LLM_MODEL": configured}
            with patch.dict("os.environ", environment, clear=True), patch("dotenv.load_dotenv") as dotenv:
                settings = runpy.run_path(str(Path(__file__).parents[1] / "app/core/config.py"))["settings"]
                self.assertEqual(settings.LLM_MODEL, expected)
                dotenv.assert_called_once_with(override=False)

    def test_startup_does_not_report_ready_when_model_is_unavailable(self):
        service = RecipeRAGService()
        service.data_loader.load_data = Mock()
        with patch("app.services.rag_service.settings.OPENAI_API_KEY", "test-key"), \
                patch("langchain.embeddings.OpenAIEmbeddings"), patch("langchain.chat_models.ChatOpenAI") as model_class:
            model_class.return_value.predict.side_effect = InvalidRequestError("Model unavailable", "model")
            with self.assertRaises(InvalidRequestError):
                service.initialize()
        self.assertFalse(service.is_initialized)
        service.data_loader.load_data.assert_not_called()

    def test_empty_ingredients_do_not_pass_guideline_precheck(self):
        self.assertFalse(aicr_service.validate_recipe_compliance({})["overall_compliant"])


if __name__ == "__main__":
    unittest.main()
