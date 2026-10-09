import json
import unittest
from unittest.mock import Mock

from app.services.intent_analyzer import IntentAnalyzer
from app.services.recipe_verifier import RecipeVerifier
from app.services.required_ingredients import explicit_ingredient_combination, missing_required_ingredients


class RequiredIngredientTests(unittest.TestCase):
    def test_missing_ingredient_cannot_be_supplied_by_title_tips_or_description(self):
        recipe = {
            "name": "Barley Bowl", "ingredients": ["1 cup tofu", "2 cups spinach"],
            "description": "Serve with barley.", "helpful_tips": ["Add barley."],
        }
        self.assertEqual(missing_required_ingredients(recipe, ["barley", "tofu", "spinach"]), ["barley"])

    def test_normalizes_common_names_forms_and_plurals_without_partial_word_matches(self):
        recipe = {"ingredients": ["1 cup cooked pearl barley", "200 g firm bean curd", "2 cups baby spinach",
                                  "1 can garbanzo beans", "2 large potatoes", "1 aubergine"]}
        self.assertEqual(missing_required_ingredients(recipe, ["cooked barley", "tofu", "spinach", "chickpeas", "potato", "eggplant"]), [])
        self.assertEqual(missing_required_ingredients(recipe, ["egg"]), ["egg"])

    def test_negated_ingredient_does_not_count(self):
        recipe = {"ingredients": ["Barley-free grain mix", "No tofu", "Rice without spinach"]}
        self.assertEqual(missing_required_ingredients(recipe, ["barley", "tofu", "spinach"]), ["barley", "tofu", "spinach"])

    def test_unspecified_required_ingredients_do_not_add_a_restriction(self):
        verifier = RecipeVerifier()
        assessment = {"relevance": "match", "constraint_violations": [], "constraint_checks": {}}
        result = verifier._finalize_verification(assessment, {"constraints": {"ingredients_must_use": None}}, {})
        self.assertTrue(result["passes_verification"])
        self.assertEqual(missing_required_ingredients({"ingredients": None}, ["barley"]), ["barley"])

    def test_explicit_combinations_differ_from_flexible_inventory(self):
        ingredients = ["barley", "tofu", "spinach"]
        self.assertTrue(explicit_ingredient_combination("What can I make with barley, tofu and spinach?", ingredients))
        for query in ("I have barley, tofu and spinach. Any ideas?", "Use barley, tofu or spinach",
                      "Make a recipe with any of barley, tofu and spinach", "Make a recipe with those ingredients"):
            self.assertFalse(explicit_ingredient_combination(query, ingredients), query)

    def test_more_preserves_user_required_combination_even_if_model_calls_it_a_pool(self):
        analyzer = IntentAnalyzer()
        query = "What can I make with barley, tofu and spinach?"
        parsed = analyzer._get_fallback_intent_data(query)
        parsed["constraints"]["ingredients_available"] = ["barley", "tofu", "spinach"]
        analyzer.initialize(Mock(predict=Mock(return_value=json.dumps(parsed))))
        result = analyzer.understand_query_intent_with_context("More recipes", [{"role": "user", "content": query}])
        self.assertEqual(result["constraints"]["ingredients_must_use"], ["barley", "tofu", "spinach"])

    def test_contradictory_model_pass_cannot_approve_missing_barley(self):
        verifier = RecipeVerifier()
        intent = {"constraints": {"ingredients_must_use": ["barley", "tofu", "spinach"]}}
        assessment = {
            "relevance": "match", "constraint_violations": [],
            "constraint_checks": {key: {"status": "pass", "evidence": "All required ingredients are present."}
                                  for key in verifier._required_checks(intent)},
        }
        verifier.initialize(Mock(predict=Mock(return_value=json.dumps(assessment))))
        recipe = {"name": "Tofu Scramble", "ingredients": ["1 cup tofu", "1 cup spinach"], "instructions": ["Cook together."]}
        result = verifier.verify_recipe_against_constraints(recipe, intent)
        self.assertFalse(result["passes_verification"])
        self.assertEqual(result["relevance"], "adaptable")
        self.assertIn("Required ingredient missing from ingredient list: barley", result["constraint_violations"])

    def test_all_requested_ingredients_still_accept_clean_model_assessment(self):
        verifier = RecipeVerifier()
        intent = {"constraints": {"ingredients_must_use": ["barley", "tofu", "spinach"]}}
        assessment = {"relevance": "match", "constraint_violations": [], "constraint_checks": {
            key: {"status": "pass", "evidence": "Declared in the ingredient list."} for key in verifier._required_checks(intent)
        }}
        verifier.initialize(Mock(predict=Mock(return_value=json.dumps(assessment))))
        recipe = {"name": "Barley Bowl", "ingredients": ["1 cup barley", "1 cup tofu", "2 cups spinach"],
                  "instructions": ["Cook barley until tender, then stir in tofu and spinach and heat through."]}
        self.assertTrue(verifier.verify_recipe_against_constraints(recipe, intent)["passes_verification"])
