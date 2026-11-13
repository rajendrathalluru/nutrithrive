import unittest
from unittest.mock import Mock, patch

from app.services.intent_analyzer import IntentAnalyzer
from app.services.recipe_verifier import RecipeVerifier
from app.services.recipe_prompt_rules import CHEWING_RULES, PREPARATION_RULES


class CompactIntentTests(unittest.TestCase):
    def test_same_contract_handles_unfamiliar_requests_without_phrase_branches(self):
        analyzer = IntentAnalyzer()
        for query in (
            "Dinner needs to be on the table inside half an hour; what could I cook?",
            "Something for an evening gathering, with Korean flavors and no peanuts",
            "My energy is low; dinner should need very little chopping",
            "Another option with the same limits, but double the portions",
        ):
            prompt = analyzer._build_intent_prompt(query)
            self.assertLess(len(prompt), 6500)
            self.assertIn(query, prompt)
            self.assertIn("must_match_criteria", prompt)
            self.assertIn("allergens_to_avoid", prompt)
            self.assertIn("current_request|active_conversation", prompt)

    def test_full_validation_rules_remain_in_recipe_review_not_extraction(self):
        prompt = IntentAnalyzer()._build_intent_prompt("An easy-to-chew no-cook meal")
        self.assertNotIn(CHEWING_RULES, prompt)
        self.assertNotIn(PREPARATION_RULES, prompt)
        review = RecipeVerifier()._build_batch_verification_prompt([], {
            "constraints": {"chewing_effort": "low", "preparation_mode": "no_heat"},
        })
        self.assertIn(CHEWING_RULES, review)
        self.assertIn(PREPARATION_RULES, review)

    def test_legacy_prompt_is_available_for_rollback(self):
        analyzer = IntentAnalyzer()
        with patch("app.services.intent_analyzer.settings.RECIPE_COMPACT_INTENT", False):
            self.assertEqual(analyzer._build_intent_prompt("Dinner"),
                             analyzer._build_legacy_intent_prompt("Dinner"))

    def test_model_telemetry_does_not_log_prompt_or_response(self):
        from app.services.model_latency import predict_with_budget
        with self.assertLogs("app.services.model_latency", level="INFO") as logs:
            result = predict_with_budget(Mock(predict=Mock(return_value="private response")),
                                         "private request", stage="intent")
        self.assertEqual(result, "private response")
        self.assertNotIn("private", str(logs.output))
        self.assertIn("stage=intent", str(logs.output))
