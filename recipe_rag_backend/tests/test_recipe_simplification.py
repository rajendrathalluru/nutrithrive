import copy
import json
import unittest
from pathlib import Path
from unittest.mock import Mock

from app.services.intent_analyzer import IntentAnalyzer
from app.services.rag_service import RecipeRAGService
from app.services.recipe_verifier import RecipeVerifier
from app.services.recipe_enhancer import RecipeEnhancer
from app.services.recipe_prompt_rules import active_recipe_rules
from app.services.response_generator import ResponseGenerator


class RecipeSimplificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        service = RecipeRAGService()
        service.data_loader.load_data(str(Path(__file__).parents[1] / "app/data/Recipe.csv"))
        cls.original = service._build_recipe_data_from_record(
            service.data_loader.get_recipe_record("Sheet Pan Roasted Vegetables and Beans")
        )

    def setUp(self):
        self.analyzer = IntentAnalyzer()
        self.query = "Can you simplify this recipe even more?"
        self.history = [
            {"role": "user", "content": "heet Pan Roasted Vegetables and Beans"},
            {"role": "assistant", "content": "Here is the recipe.", "recipes": [copy.deepcopy(self.original)]},
        ]
        self.model_intent = self.analyzer._get_fallback_intent_data("Sheet Pan Roasted Vegetables and Beans")
        self.model_intent["query_type"] = "recipe_search"
        self.analyzer.initialize(Mock(predict=Mock(side_effect=lambda prompt: json.dumps(self.model_intent))))

    def analyze(self, query=None, history=None):
        return self.analyzer.understand_query_intent_with_context(query or self.query, self.history if history is None else history)

    def test_exact_report_is_bound_to_shown_recipe_despite_model_search_route(self):
        intent = self.analyze()
        self.assertEqual(intent["query_type"], "recipe_adaptation")
        self.assertEqual(intent["referenced_recipe_ids"], [self.original["recipe_id"]])
        self.assertIn("simplify", intent["resolved_query"].lower())
        reference = intent["adaptation_request"]["references"][0]
        self.assertEqual(reference["instructions"], self.original["instructions"])

    def test_explicit_reference_cannot_be_reclassified_as_new_task(self):
        self.model_intent["context_action"] = "new_request"
        intent = self.analyze()
        self.assertEqual(intent["query_type"], "recipe_adaptation")
        self.assertEqual(intent["context_action"], "continue_request")
        self.assertEqual(self.analyzer.llm.predict.call_count, 1)

    def test_multiple_cards_need_clarification_not_all_recipes(self):
        self.history[-1]["recipes"].append({**self.original, "recipe_id": "other", "name": "Walnut Bowl"})
        intent = self.analyze()
        self.assertEqual(intent["query_type"], "clarification")
        self.analyzer.llm.predict.assert_not_called()

    def test_missing_recipe_needs_clarification(self):
        self.assertEqual(self.analyze(history=[])["query_type"], "clarification")

    def test_ordinal_and_name_select_only_requested_card(self):
        second = {**self.original, "recipe_id": "other", "name": "Walnut Bowl"}
        self.history[-1]["recipes"].append(second)
        for query in ("Simplify the second one", "Make Walnut Bowl easier to prepare"):
            with self.subTest(query=query):
                self.assertEqual(self.analyze(query)["referenced_recipe_ids"], ["other"])

    def test_next_simplification_uses_latest_adapted_version(self):
        latest = {**self.original, "recipe_id": "simplified", "name": "Simplified Sheet Pan Vegetables and Beans"}
        self.history.extend([
            {"role": "user", "content": self.query},
            {"role": "assistant", "content": "Simplified version", "recipes": [latest]},
        ])
        intent = self.analyze("Can you make it even simpler?")
        self.assertEqual(intent["referenced_recipe_ids"], ["simplified"])

    def test_full_adapted_name_does_not_also_select_original_substring(self):
        latest = {**self.original, "recipe_id": "simplified", "name": "Simplified " + self.original["name"]}
        self.history.append({"role": "assistant", "content": "Simplified version", "recipes": [latest]})
        self.assertEqual(self.analyze("Simplify " + latest["name"])["referenced_recipe_ids"], ["simplified"])

    def test_keep_explicit_active_constraints(self):
        self.history[0]["content"] = "Show vegetarian meals without nuts"
        self.model_intent["constraints"].update({"dietary_restrictions": ["vegetarian"], "allergens_to_avoid": ["nuts"]})
        intent = self.analyze()
        self.assertEqual(intent["constraints"]["allergens_to_avoid"], ["nuts"])
        self.assertEqual(intent["constraints"]["dietary_restrictions"], ["vegetarian"])

    def test_unrelated_or_explanatory_requests_do_not_trigger_simplification(self):
        for query in (
            "Show simpler recipes for breakfast", "What can I make with barley, tofu and spinach?",
            "Why is this recipe simpler?", "Explain how to simplify this recipe",
            "Don't simplify this recipe", "Can you simplify the explanation?",
            "Don't make it simpler", "Can you make this recipe easier to understand?",
        ):
            with self.subTest(query=query):
                self.assertNotIn("adaptation_request", self.analyze(query))

    def test_unchanged_recipe_cannot_pass_by_claiming_simplification(self):
        intent = self.analyze()
        verifier = RecipeVerifier()
        assessment = {
            "relevance": "match", "constraint_violations": [],
            "constraint_checks": {key: {"status": "pass", "evidence": "Made simpler."}
                                  for key in verifier._required_checks(intent)},
        }
        result = verifier._finalize_verification(assessment, copy.deepcopy(self.original), intent)
        self.assertFalse(result["passes_verification"])
        self.assertTrue(any("unchanged" in problem.lower() for problem in result["constraint_violations"]))

    def test_verification_requires_comparison_to_original_not_just_shorter_text(self):
        intent = self.analyze()
        prompt = RecipeVerifier()._build_batch_verification_prompt([], intent)
        self.assertIn("adaptation_request", prompt)
        self.assertIn(self.original["instructions"][0], prompt)
        self.assertIn("shorter wording", prompt)

    def test_missing_comparison_fails_but_supported_simplification_can_pass(self):
        intent = self.analyze()
        verifier = RecipeVerifier()
        changed = {**self.original,
                   "ingredients": ["4 cups purchased pre-cut vegetables", "1 can white beans", "1 tbsp olive oil"],
                   "instructions": ["Toss on a sheet pan and roast at 400 F until tender, 35-40 minutes."]}
        assessment = {
            "relevance": "match", "constraint_violations": [],
            "constraint_checks": {key: {"status": "pass", "evidence": "Purchased pre-cut vegetables replace chopping; toss directly rather than making vinaigrette."}
                                  for key in verifier._required_checks(intent)},
        }
        self.assertTrue(verifier._finalize_verification(copy.deepcopy(assessment), changed, intent)["passes_verification"])
        del assessment["constraint_checks"]["adaptation_request"]
        self.assertFalse(verifier._finalize_verification(assessment, changed, intent)["passes_verification"])

    def test_rewording_without_reduced_work_fails_semantic_comparison(self):
        intent = self.analyze()
        verifier = RecipeVerifier()
        unchanged_work = {**self.original, "instructions": ["Do all the same chopping, vinaigrette preparation and roasting."]}
        assessment = {
            "relevance": "match", "constraint_violations": [],
            "constraint_checks": {key: {"status": "pass", "evidence": "Recipe evidence"}
                                  for key in verifier._required_checks(intent)},
        }
        assessment["constraint_checks"]["adaptation_request"] = {"status": "fail", "evidence": "Same work, only fewer words."}
        self.assertFalse(verifier._finalize_verification(assessment, unchanged_work, intent)["passes_verification"])

    def test_generation_and_repair_keep_reference_and_simplification_goal(self):
        intent = self.analyze()
        enhancer = RecipeEnhancer()
        guidelines = Mock()
        guidelines.extract_focus_areas_from_intent.return_value = []
        guidelines.get_prompt_context.return_value = "Nutrition guidelines"
        guidelines.validate_recipe_compliance.return_value = {"overall_compliant": True, "score": 100, "warnings": []}
        generated = {"name": "Simplified vegetables and beans", "type": "Entree",
                     "ingredients": ["1 can white beans", "4 cups pre-cut vegetables"],
                     "instructions": ["Roast until tender."], "generated_by_llm": True}
        model = Mock(predict=Mock(return_value=json.dumps([generated, {**generated, "name": "Unrequested alternative"}])))
        enhancer.initialize(model, guidelines)
        result = enhancer.generate_fallback_recipes(self.query, intent, [], [self.original])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["generation_basis"], "database_guided")
        self.assertEqual(result[0]["reference_sources"][0]["recipe_id"], self.original["recipe_id"])
        self.assertIn("exactly 1 complete adapted recipe", model.predict.call_args.args[0])
        self.assertIn("specific hands-on work", model.predict.call_args.args[0])
        self.assertIn("never objects", model.predict.call_args.args[0])
        repair = enhancer._build_repair_prompt(self.query, intent, generated, "Nutrition guidelines")
        self.assertIn(self.original["instructions"][0], repair)
        self.assertIn("Shorter wording", repair)
        self.assertNotIn("For simplification", active_recipe_rules({"constraints": {}}))

    def test_summary_describes_adaptation_not_another_search(self):
        generator = ResponseGenerator()
        generator.initialize(Mock())
        response = generator.generate_personalized_response(self.query, [{
            "name": "Simplified Sheet Pan Vegetables and Beans",
            "description": "Use purchased pre-cut vegetables and toss on the pan instead of preparing a separate vinaigrette.",
        }], self.analyze())
        self.assertIn("pre-cut vegetables", response)
        self.assertIn("AI-generated adaptation", response)
        self.assertNotIn("I found", response)
        generator.llm.predict.assert_not_called()


if __name__ == "__main__":
    unittest.main()
