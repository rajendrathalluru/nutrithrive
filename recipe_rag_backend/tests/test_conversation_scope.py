import json
import unittest
from pathlib import Path
from unittest.mock import Mock

from app.services.conversation_scope import scope_recipe_history, starts_new_request
from app.services.intent_analyzer import IntentAnalyzer
from app.services.data_loader import DataLoader


QUERY = "What can I make with barley, tofu and spinach?"
OLD_QUERY = "Show vegetarian meals under 20 minutes using canned ingredients only."
RECIPE_NAME = "Sheet Pan Roasted Vegetables and Beans"


class ConversationScopeTests(unittest.TestCase):
    def test_catalog_title_starts_an_independent_request(self):
        history = [{"role": "user", "content": "Show meals in at most 35 minutes"}]
        for title in (RECIPE_NAME, RECIPE_NAME.upper(), "  " + RECIPE_NAME + "  ", RECIPE_NAME + "."):
            with self.subTest(title=title):
                self.assertEqual(scope_recipe_history(title, history, [RECIPE_NAME]), ([], True))

    def test_every_loaded_catalog_title_has_no_inferred_time_limit(self):
        loader = DataLoader()
        loader.load_data(str(Path(__file__).parents[1] / "app/data/Recipe.csv"))
        analyzer = IntentAnalyzer()
        model = Mock(predict=Mock(side_effect=AssertionError("Unexpected intent inference")))
        analyzer.initialize(model, recipe_names=loader.recipe_lookup)
        history = [{"role": "user", "content": "Show recipes in at most 35 minutes"},
                   {"role": "assistant", "content": "No results", "recipes": None}]
        for record in loader.recipe_lookup.values():
            with self.subTest(title=record["Name"]):
                intent = analyzer.understand_query_intent_with_context(record["Name"], history)
                self.assertIsNone(intent["constraints"]["time_max_minutes"])
                self.assertEqual(intent["context_action"], "new_request")
                self.assertEqual(intent["user_request_context"], [record["Name"]])
        model.predict.assert_not_called()

    def test_title_from_previous_card_is_also_a_new_request(self):
        history = [{"role": "user", "content": OLD_QUERY}, {
            "role": "assistant", "content": "Try this recipe", "recipes": [{"recipe_id": "sheet-pan", "name": RECIPE_NAME}],
        }]
        self.assertEqual(scope_recipe_history(RECIPE_NAME, history), ([], True))

    def test_followup_after_title_keeps_only_the_named_recipe_task(self):
        history = [{"role": "user", "content": "Show meals in at most 35 minutes"},
                   {"role": "assistant", "content": "I couldn't verify a recipe under 35 minutes"},
                   {"role": "user", "content": RECIPE_NAME},
                   {"role": "assistant", "content": "Here is the recipe"}]
        for query in ("Can you simplify this recipe even more?", "more recipes", "Can I freeze it?"):
            with self.subTest(query=query):
                self.assertEqual(scope_recipe_history(query, history, [RECIPE_NAME]), (history[2:], False))

    def test_named_followup_is_not_reset_by_catalog_substring(self):
        history = [{"role": "user", "content": "Show meals in at most 35 minutes"}]
        for query in ("Simplify " + RECIPE_NAME, "Can I freeze " + RECIPE_NAME + "?",
                      RECIPE_NAME + " with the same restrictions", "Make it under 35 minutes"):
            with self.subTest(query=query):
                self.assertEqual(scope_recipe_history(query, history, [RECIPE_NAME]), (history, False))

    def test_title_answering_recipe_clarification_keeps_the_task(self):
        history = [{"role": "user", "content": "Show meals in at most 35 minutes"},
                   {"role": "user", "content": "Simplify this recipe"},
                   {"role": "assistant", "content": "Which recipe would you like me to simplify? Please use its name or position in the last recipe list."}]
        self.assertEqual(scope_recipe_history(RECIPE_NAME, history, [RECIPE_NAME]), (history, False))
        history.extend([{"role": "user", "content": RECIPE_NAME}, {"role": "assistant", "content": "Adapted recipe"}])
        self.assertEqual(scope_recipe_history("Can I freeze it?", history, [RECIPE_NAME]), (history, False))

    def test_literal_title_does_not_ask_model_to_invent_constraints(self):
        analyzer = IntentAnalyzer()
        model = Mock(predict=Mock(side_effect=AssertionError("A catalog title needs no inferred requirements")))
        analyzer.initialize(model, recipe_names=[RECIPE_NAME])
        history = [{"role": "user", "content": "Show meals in at most 35 minutes"},
                   {"role": "assistant", "content": "This dish takes 35-40 minutes."}]
        for previous in (history, []):
            intent = analyzer.understand_query_intent_with_context(RECIPE_NAME, previous)
            self.assertEqual(intent["context_action"], "new_request")
            self.assertEqual(intent["query_type"], "recipe_search")
            self.assertIsNone(intent["constraints"]["time_max_minutes"])
            self.assertFalse(intent["constraints"]["time_limit_exclusive"])
            self.assertEqual(intent["user_request_context"], [RECIPE_NAME])
        model.predict.assert_not_called()

    def test_explicit_limit_on_named_recipe_still_applies(self):
        analyzer = IntentAnalyzer()
        query = "A recipe for " + RECIPE_NAME + " in at most 35 minutes"
        parsed = analyzer._get_fallback_intent_data(query)
        analyzer.initialize(Mock(predict=Mock(return_value=json.dumps(parsed))), recipe_names=[RECIPE_NAME])
        intent = analyzer.understand_query_intent_with_context(query, [{"role": "user", "content": OLD_QUERY}])
        self.assertEqual(intent["constraints"]["time_max_minutes"], 35)
        self.assertEqual(intent["user_request_context"], [query])
        analyzer.llm.predict.assert_called_once()

    def test_real_followup_preserves_active_35_minute_limit(self):
        analyzer = IntentAnalyzer()
        query = "More recipes"
        parsed = analyzer._get_fallback_intent_data("More recipes in at most 35 minutes")
        parsed["constraints"]["time_max_minutes"] = 35
        analyzer.initialize(Mock(predict=Mock(return_value=json.dumps(parsed))), recipe_names=[RECIPE_NAME])
        intent = analyzer.understand_query_intent_with_context(query, [
            {"role": "user", "content": "Show meals in at most 35 minutes"},
        ])
        self.assertEqual(intent["constraints"]["time_max_minutes"], 35)
        self.assertEqual(intent["context_action"], "continue_request")

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
