import json
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock

from app.services.intent_analyzer import IntentAnalyzer
from app.services.recipe_verifier import RecipeVerifier
from app.services.rag_service import RecipeRAGService
from app.services.required_ingredients import explicit_ingredient_combination, missing_required_ingredients


class RequiredIngredientTests(unittest.TestCase):
    def test_chicken_is_not_broth_flavoring_an_optional_choice_or_imitation(self):
        for line in ("1 cup chicken broth", "Low sodium chicken stock", "Chicken-flavored seasoning",
                     "1 chicken bouillon cube", "200 g plant-based chicken strips", "Chicken (optional)",
                     "200 g chicken or tofu", "Optional: add chicken", "Use pork instead of chicken"):
            with self.subTest(line=line):
                self.assertEqual(missing_required_ingredients({"ingredients": [line]}, ["chicken"]), ["chicken"])

    def test_actual_chicken_forms_and_explicit_broth_requests_are_supported(self):
        for line in ("1 pound boneless skinless chicken breasts", "1 cup cooked shredded chicken",
                     "200 g chicken breast or chicken thighs", "1 or 2 cups cooked chicken",
                     "Chicken breast simmered in chicken broth"):
            with self.subTest(line=line):
                self.assertEqual(missing_required_ingredients({"ingredients": [line]}, ["chicken"]), [])
        self.assertEqual(missing_required_ingredients({"ingredients": ["1 cup chicken broth"]}, ["chicken broth"]), [])

    def test_preparation_or_color_alternatives_still_use_the_same_food(self):
        for ingredient, line in (("broccoli", "2 cups fresh or frozen broccoli"),
                                 ("broccoli", "2 cups broccoli (fresh or frozen)"),
                                 ("rice", "1 cup brown or white rice"),
                                 ("mushrooms", "2 cups mushrooms, sliced or chopped")):
            with self.subTest(line=line):
                self.assertEqual(missing_required_ingredients({"ingredients": [line]}, [ingredient]), [])

    def test_inventory_parser_does_not_turn_a_broth_request_into_meat(self):
        analyzer = IntentAnalyzer()
        query = "I have broccoli and chicken broth. Generate a recipe using these ingredients."
        parsed = analyzer._get_fallback_intent_data(query)
        parsed["constraints"]["ingredients_available"] = ["broccoli", "chicken"]
        result = analyzer._post_process_intent(query, parsed)
        self.assertEqual(result["constraints"]["ingredients_must_use"], ["broccoli", "chicken broth"])

    def test_reported_pork_recipe_is_not_a_chicken_recipe_even_if_model_passes_it(self):
        service = RecipeRAGService()
        service.data_loader.load_data(str(Path(__file__).parents[1] / "app/data/Recipe.csv"))
        recipe = service._build_recipe_data_from_record(service.data_loader.get_recipe_record("Cashew Stir Fry with Broccoli and Pork"))
        self.assertEqual(missing_required_ingredients(recipe, ["broccoli", "chicken"]), ["chicken"])
        verifier = RecipeVerifier()
        intent = {"constraints": {"ingredients_must_use": ["broccoli", "chicken"]}}
        assessment = {"relevance": "match", "constraint_violations": [], "constraint_checks": {
            key: {"status": "pass", "evidence": "Broccoli and chicken broth are present"}
            for key in verifier._required_checks(intent)
        }}
        result = verifier._finalize_verification(assessment, recipe, intent)
        self.assertFalse(result["passes_verification"])
        self.assertEqual(result["relevance"], "adaptable")
        recipe["verification_details"] = {"relevance": "match", "passes_verification": True}
        self.assertEqual(service._get_verified_matches([recipe], intent), [])

    def test_csv_rescue_prioritizes_recipes_containing_both_actual_foods(self):
        service = RecipeRAGService()
        service.data_loader.load_data(str(Path(__file__).parents[1] / "app/data/Recipe.csv"))
        source = service.data_loader.get_recipe_record("Cashew Stir Fry with Broccoli and Pork")
        service.data_loader.df.loc[len(service.data_loader.df)] = {
            **source, "Name": "Chicken and Broccoli Test Dish", "recipe_id": "chicken-broccoli-test",
            "Ingredients": "3 cups broccoli\n1 pound chicken breast\n1 tbsp oil",
            "Directions": "Cook the chicken through and cook the broccoli until tender.",
        }
        intent = {"constraints": {"ingredients_must_use": ["broccoli", "chicken"]}, "search_strategy": {}}
        candidates = service._get_database_search_candidates("broccoli chicken cashew pork stir fry", intent, set(), 1)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["name"], "Chicken and Broccoli Test Dish")
        self.assertEqual(missing_required_ingredients(candidates[0], ["broccoli", "chicken"]), [])

    def test_user_inventory_selection_is_required_even_when_model_omits_an_item(self):
        query = "I have broccoli and chicken. Generate a recipe using these ingredients"
        for available in (["broccoli", "chicken"], ["broccoli"], [], None):
            with self.subTest(available=available):
                analyzer = IntentAnalyzer()
                parsed = analyzer._get_fallback_intent_data(query)
                parsed["constraints"]["ingredients_available"] = available
                analyzer.initialize(Mock(predict=Mock(return_value=json.dumps(parsed))))
                intent = analyzer.understand_query_intent_with_context(query)
                self.assertEqual(intent["constraints"]["ingredients_must_use"], ["broccoli", "chicken"])

    def test_inventory_wording_variants_and_single_ingredient(self):
        for query, expected in (
            ("I have broccoli and chicken; please use both.", ["broccoli", "chicken"]),
            ("I have carrots, chicken, and rice. Make a dish with these ingredients.", ["carrots", "chicken", "rice"]),
            ("I have 2 cups broccoli and 1 pound chicken. Cook with both.", ["broccoli", "chicken"]),
            ("We have tofu. Generate a recipe using it.", ["tofu"]),
        ):
            with self.subTest(query=query):
                analyzer = IntentAnalyzer()
                intent = analyzer._post_process_intent(query, analyzer._get_fallback_intent_data(query))
                self.assertEqual(intent["constraints"]["ingredients_must_use"], expected)

    def test_inventory_reference_keeps_requirements_across_more_but_honors_changes(self):
        initial = "I have broccoli and chicken. Generate a recipe using these ingredients."
        for follow_up, expected in (("More recipes", ["broccoli", "chicken"]),
                                    ("Replace chicken with tofu", ["broccoli", "tofu"]),
                                    ("Use tofu instead of chicken", ["broccoli", "tofu"]),
                                    ("Without chicken", ["broccoli"])):
            with self.subTest(follow_up=follow_up):
                analyzer = IntentAnalyzer()
                parsed = analyzer._get_fallback_intent_data(follow_up)
                parsed["constraints"]["ingredients_must_use"] = ["broccoli", "chicken"]
                result = analyzer._post_process_intent(follow_up, deepcopy(parsed), [{"role": "user", "content": initial}], follow_up)
                self.assertEqual(result["constraints"]["ingredients_must_use"], expected)

    def test_user_inventory_antecedent_not_assistant_ideas_becomes_required(self):
        analyzer = IntentAnalyzer()
        query = "Generate a recipe using these ingredients"
        for role, expected in (("user", ["broccoli", "chicken"]), ("assistant", [])):
            history = [{"role": role, "content": "I have broccoli and chicken."}]
            intent = analyzer._post_process_intent(query, analyzer._get_fallback_intent_data(query), history, query)
            self.assertEqual(intent["constraints"]["ingredients_must_use"], expected)

    def test_flexible_inventory_does_not_become_a_mandatory_combination(self):
        for query in ("I have broccoli and chicken. Any ideas?", "I have broccoli or chicken. Use these ingredients.",
                      "I have broccoli and chicken. Use either of these ingredients.",
                      "I have broccoli and chicken. Use any of these ingredients.",
                      "I have broccoli and chicken. Do not use these ingredients."):
            with self.subTest(query=query):
                analyzer = IntentAnalyzer()
                intent = analyzer._post_process_intent(query, analyzer._get_fallback_intent_data(query))
                self.assertEqual(intent["constraints"]["ingredients_must_use"], [])

    def test_new_request_does_not_inherit_the_previous_inventory(self):
        analyzer = IntentAnalyzer()
        query = "Show me lentil soup recipes"
        analyzer.initialize(Mock(predict=Mock(return_value=json.dumps(analyzer._get_fallback_intent_data(query)))))
        intent = analyzer.understand_query_intent_with_context(query, [{
            "role": "user", "content": "I have broccoli and chicken. Generate a recipe using these ingredients.",
        }])
        self.assertEqual(intent["constraints"]["ingredients_must_use"], [])
        self.assertEqual(intent["context_action"], "new_request")

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
