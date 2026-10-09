import json
import unittest
from unittest.mock import Mock

from app.services.conversation_scope import scope_recipe_history, starts_new_request
from app.services.intent_analyzer import IntentAnalyzer


QUERY = "What can I make with barley, tofu and spinach?"
OLD_QUERY = "Show vegetarian meals under 20 minutes using canned ingredients only."


class ConversationScopeTests(unittest.TestCase):
    def test_self_contained_requests_start_new_tasks(self):
        for query in (QUERY, "What can we prepare with beans and rice?", "Show me Chinese dinner recipes",
                      "best breakfast that i can eat", "What foods don't change texture when reheated?",
                      "Start over, more recipes", "A recipe for paneer butter masala"):
            with self.subTest(query=query):
                self.assertTrue(starts_new_request(query))

    def test_refinements_and_references_do_not_reset(self):
        for query in ("more recipes", "What else can I make?", "Italian instead", "without onions",
                      "Can I freeze it?", "Use those ingredients", "Can you make a recipe with them?",
                      "Show vegetarian versions of those recipes", "What can I make with those ingredients?",
                      "Show recipes with the same restrictions", "Also, show recipes under 15 minutes"):
            with self.subTest(query=query):
                self.assertFalse(starts_new_request(query))

    def test_followup_uses_latest_task_even_without_client_metadata(self):
        history = [{"role": "user", "content": OLD_QUERY}, {"role": "assistant", "content": "Old wraps"},
                   {"role": "user", "content": QUERY}, {"role": "assistant", "content": "A barley bowl"}]
        selected, new_request = scope_recipe_history("More recipes", history)
        self.assertFalse(new_request)
        self.assertEqual(selected, history[2:])
        self.assertEqual(len(history), 4)
        self.assertEqual(scope_recipe_history(QUERY, history), ([], True))

    def test_saved_boundary_handles_short_named_dish_without_keyword_heuristic(self):
        history = [{"role": "user", "content": OLD_QUERY},
                   {"role": "user", "content": "Paneer butter masala"},
                   {"role": "assistant", "content": "Paneer recipe", "context_action": "new_request"}]
        self.assertEqual(scope_recipe_history("More recipes", history)[0], history[1:])

    def test_current_query_reaches_model_without_old_task_constraints(self):
        analyzer = IntentAnalyzer()
        parsed = analyzer._get_fallback_intent_data(QUERY)
        parsed["constraints"]["ingredients_must_use"] = ["barley", "tofu", "spinach"]

        def predict(prompt):
            self.assertNotIn(OLD_QUERY, prompt)
            self.assertNotIn("Old assistant claims", prompt)
            return json.dumps(parsed)

        analyzer.initialize(Mock(predict=Mock(side_effect=predict)))
        result = analyzer.understand_query_intent_with_context(QUERY, [
            {"role": "user", "content": OLD_QUERY},
            {"role": "assistant", "content": "Old assistant claims: these take 20 minutes"},
        ])
        self.assertEqual(result["context_action"], "new_request")
        self.assertEqual(result["user_request_context"], [QUERY])
        self.assertIsNone(result["constraints"]["time_max_minutes"])
        self.assertIsNone(result["constraints"]["ingredient_storage"])
        self.assertEqual(result["constraints"]["dietary_restrictions"], [])
        self.assertEqual(result["constraints"]["ingredients_must_use"], ["barley", "tofu", "spinach"])
        self.assertNotIn("context_action", analyzer.understand_query_intent(QUERY))

    def test_explicit_time_limit_survives_within_active_task(self):
        analyzer = IntentAnalyzer()
        query = "More recipes"
        parsed = analyzer._get_fallback_intent_data("More recipes with barley, tofu and spinach under 10 minutes")
        analyzer.initialize(Mock(predict=Mock(return_value=json.dumps(parsed))))
        history = [{"role": "user", "content": OLD_QUERY},
                   {"role": "user", "content": QUERY + " Keep these under 10 minutes."}]
        result = analyzer.understand_query_intent_with_context(query, history)
        prompt = analyzer.llm.predict.call_args.args[0]
        self.assertNotIn(OLD_QUERY, prompt)
        self.assertEqual(result["constraints"]["time_max_minutes"], 10)
        self.assertEqual(result["user_request_context"], [history[1]["content"], query])

    def test_semantically_detected_new_topic_is_reanalyzed_without_history(self):
        analyzer = IntentAnalyzer()
        query = "Paneer butter masala"
        contaminated = analyzer._get_fallback_intent_data(query + " under 20 minutes")
        contaminated["context_action"] = "new_request"
        contaminated["constraints"]["time_max_minutes"] = 20
        clean = analyzer._get_fallback_intent_data(query)
        analyzer.initialize(Mock(predict=Mock(side_effect=[json.dumps(contaminated), json.dumps(clean)])))
        result = analyzer.understand_query_intent_with_context(query, [{"role": "user", "content": OLD_QUERY}])
        self.assertEqual(analyzer.llm.predict.call_count, 2)
        self.assertNotIn(OLD_QUERY, analyzer.llm.predict.call_args.args[0])
        self.assertIsNone(result["constraints"]["time_max_minutes"])
        self.assertEqual(result["user_request_context"], [query])

    def test_other_chats_boundaries_and_requirements_do_not_leak(self):
        analyzer = IntentAnalyzer()
        parsed = analyzer._get_fallback_intent_data("More recipes")
        analyzer.initialize(Mock(predict=Mock(return_value=json.dumps(parsed))))
        analyzer.understand_query_intent_with_context("More recipes", [{"role": "user", "content": OLD_QUERY}])
        result = analyzer.understand_query_intent_with_context("More recipes", [{"role": "user", "content": QUERY}])
        self.assertNotIn(OLD_QUERY, analyzer.llm.predict.call_args.args[0])
        self.assertIsNone(result["constraints"]["ingredient_storage"])
