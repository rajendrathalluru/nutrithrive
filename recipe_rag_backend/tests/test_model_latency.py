import unittest
from unittest.mock import Mock, patch

from app.services.model_latency import ModelBudgetExhausted, model_deadline, predict_with_budget


class ModelLatencyTests(unittest.TestCase):
    def test_final_review_has_reserved_time_but_never_extends_hard_limit(self):
        from app.services.model_latency import final_review_window, final_review_limit
        deadline_token = model_deadline.set(25)
        limit_token = final_review_limit.set(37)
        self.addCleanup(model_deadline.reset, deadline_token)
        self.addCleanup(final_review_limit.reset, limit_token)
        with patch("app.services.model_latency.monotonic", return_value=17), \
                patch("app.services.model_latency.settings.RECIPE_FINAL_REVIEW_SECONDS", 12):
            with final_review_window():
                self.assertEqual(model_deadline.get(), 29)
        self.assertEqual(model_deadline.get(), 25)
        with patch("app.services.model_latency.monotonic", return_value=35):
            with final_review_window():
                self.assertEqual(model_deadline.get(), 37)
        self.assertEqual(model_deadline.get(), 25)

    def test_final_review_does_not_invent_extra_budget_outside_request_lifecycle(self):
        from app.services.model_latency import final_review_window
        token = model_deadline.set(25)
        self.addCleanup(model_deadline.reset, token)
        with patch("app.services.model_latency.monotonic", return_value=24):
            with final_review_window():
                self.assertEqual(model_deadline.get(), 25)

    def test_remaining_budget_caps_timeout_and_blocks_later_calls(self):
        model = Mock()
        token = model_deadline.set(25)
        self.addCleanup(model_deadline.reset, token)
        with patch("app.services.model_latency.monotonic", side_effect=[22, 26]):
            predict_with_budget(model, "intent")
            with self.assertRaises(ModelBudgetExhausted):
                predict_with_budget(model, "repair")
        model.predict.assert_called_once_with("intent", request_timeout=3)
