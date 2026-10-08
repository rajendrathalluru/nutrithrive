import copy
import json
import unittest
from unittest.mock import Mock

from app.services.aicr_guidelines_service import aicr_service
from app.services.intent_analyzer import IntentAnalyzer
from app.services.pantry_validation import explicit_canned_requirement
from app.services.rag_service import RecipeRAGService
from app.services.recipe_enhancer import RecipeEnhancer
from app.services.recipe_verifier import RecipeVerifier
from app.services.response_generator import ResponseGenerator


QUERIES = (
    "Show recipes that use canned ingredients only.",
    "help me to prepare some recipes that have only canned ingredients",
)
REPORTED_RECIPE = {
    "name": "Show Recipes That Use Canned Ingredients Only.", "type": "CUSTOM", "generated_by_llm": True,
    "ingredients": ["1 (15 oz) can black beans, drained and rinsed", "1 (15 oz) can diced tomatoes",
                    "1 (15 oz) can corn, drained", "1 cup quinoa", "1 tsp chili powder", "1/2 tsp cumin",
                    "Salt and pepper to taste", "Fresh cilantro, chopped (optional, for garnish)"],
    "instructions": ["Combine quinoa with 2 cups of water, bring to a boil and simmer for 15-20 minutes.",
                     "Combine beans, tomatoes and corn. Stir in chili powder, cumin, salt and pepper.",
                     "Serve the bean mixture over quinoa. Garnish with fresh cilantro if desired."],
    "helpful_tips": ["Add a side of grilled chicken or tofu.", "Serve with steamed vegetables or a green salad.",
                     "Squeeze fresh lime juice over the dish."],
}


def canned_recipe():
    return {
        "name": "Three-Can Bean and Corn Bowl", "type": "Main Dish", "generated_by_llm": True,
        "ingredients": ["1 can no-salt-added black beans, drained", "1 can diced tomatoes", "1 can corn, drained"],
        "instructions": ["Mix the canned black beans, tomatoes, and corn in a bowl.", "Divide into bowls and serve."],
    }


class CannedOnlyTests(unittest.TestCase):
    def intent(self, query=QUERIES[0]):
        analyzer = IntentAnalyzer()
        parsed = analyzer._get_fallback_intent_data(query)
        parsed["query_type"] = "food_guidance"
        parsed["constraints"]["ingredient_storage"] = "pantry_based"
        return analyzer._post_process_intent(query, parsed)

    def assessment(self, intent=None):
        return {
            "id": 0, "relevance": "match", "constraint_violations": [],
            "constraint_checks": {key: {"status": "pass", "evidence": "Model claims canned ingredients."}
                                  for key in RecipeVerifier()._required_checks(intent or self.intent())},
            "canned_ingredient_check": {"non_canned_ingredients": [], "unspecified_forms": [], "conflicting_guidance": []},
        }

    def verify(self, recipe, batch=True, assessment=None):
        assessment = assessment if assessment is not None else self.assessment()
        verifier = RecipeVerifier()
        verifier.initialize(Mock(predict=Mock(return_value=json.dumps([assessment] if batch else assessment))))
        if batch:
            return verifier.batch_verify_recipes([copy.deepcopy(recipe)], self.intent(), aicr_service)[0]["verification_details"]
        return verifier.verify_recipe_against_constraints(recipe, self.intent())

    def test_both_reported_phrasings_are_recipe_search_with_strict_canned_form(self):
        for query in QUERIES:
            result = self.intent(query)
            self.assertEqual(result["query_type"], "recipe_search")
            self.assertEqual(result["constraints"]["ingredient_storage"], "canned_only")
            self.assertIsNone(result["constraints"]["preparation_mode"])
            self.assertNotIn("dried lentils", result["search_strategy"]["search_keywords"])

    def test_canned_vegetables_and_pantry_are_not_all_canned(self):
        for query in ("Show meals using canned beans", "Only canned vegetables", "Show pantry meals", "Shelf-stable ingredients only"):
            self.assertIsNone(explicit_canned_requirement(query))

    def test_canned_constraint_is_preserved_in_user_followups_and_can_be_removed(self):
        analyzer = IntentAnalyzer()
        analyzer.initialize(Mock(predict=Mock(side_effect=lambda prompt: json.dumps(analyzer._get_fallback_intent_data("More recipes")))))
        history = [{"role": "user", "content": QUERIES[0]}]
        result = analyzer.understand_query_intent_with_context("More recipes", history)
        self.assertEqual(result["constraints"]["ingredient_storage"], "canned_only")
        for query in ("Remove the canned-only restriction", "Start over: dinner recipes"):
            self.assertIsNone(analyzer.understand_query_intent_with_context(query, history)["constraints"]["ingredient_storage"])
        for query, expected in (("Use pantry staples instead", "pantry_based"),
                                ("Use shelf-stable ingredients only", "shelf_stable_only"),
                                ("Start over: frozen ingredients only", "frozen_only")):
            self.assertEqual(analyzer.understand_query_intent_with_context(query, history)["constraints"]["ingredient_storage"], expected)
        self.assertIsNone(analyzer.understand_query_intent("Dinner recipes")["constraints"]["ingredient_storage"])

    def test_reported_recipe_fails_both_verification_paths_and_both_sources(self):
        for batch in (False, True):
            for generated in (False, True):
                recipe = copy.deepcopy(REPORTED_RECIPE)
                recipe["generated_by_llm"] = generated
                details = self.verify(recipe, batch)
                self.assertFalse(details["passes_verification"])
                self.assertEqual(details["relevance"], "adaptable")
                self.assertTrue(any("quinoa" in reason for reason in details["constraint_violations"]))

    def test_all_food_ingredients_must_be_canned_even_optional_garnishes(self):
        for line in ("1 cup quinoa", "1 tsp cumin", "Salt and pepper", "1 tsp olive oil", "2 cups cooking water",
                     "Fresh cilantro (optional)", "1 cup frozen corn", "1 carton shelf-stable broth",
                     "1 can tomatoes and 1 cup dry rice", "1 can beans and salt"):
            recipe = canned_recipe()
            recipe["ingredients"].append(line)
            self.assertFalse(self.verify(recipe)["passes_verification"], line)

    def test_valid_canned_forms_and_processing_water_pass(self):
        recipe = canned_recipe()
        recipe["instructions"].insert(0, "Rinse the canned beans with water and drain.")
        recipe["ingredient_adaptations"] = ["Use no-salt-added canned beans and canned vegetables."]
        self.assertTrue(self.verify(recipe)["passes_verification"])
        recipe["instructions"].extend(["Toss the salad gently.", "Enjoy the bean salad."])
        self.assertTrue(self.verify(recipe)["passes_verification"])
        recipe["ingredients"].append("1 tin peas and carrots")
        self.assertTrue(self.verify(recipe)["passes_verification"])

    def test_hidden_non_canned_additions_in_tips_and_instructions_fail(self):
        for field in ("instructions", "helpful_tips", "ingredient_adaptations", "source_notes"):
            for line in ("Add grilled chicken or tofu.", "Serve over quinoa.", "Squeeze fresh lime juice over the dish.",
                         "Stir in canned beans and quinoa.", "Add 2 cups water and boil."):
                recipe = canned_recipe()
                recipe[field] = [line] if field != "source_notes" else line
                self.assertFalse(self.verify(recipe)["passes_verification"], (field, line))

    def test_missing_or_nonempty_semantic_assessments_fail_closed(self):
        for check in (None, {}, {"non_canned_ingredients": [], "unspecified_forms": ["Ambiguous ingredient"], "conflicting_guidance": []}):
            assessment = self.assessment()
            assessment["canned_ingredient_check"] = check
            self.assertFalse(self.verify(canned_recipe(), assessment=assessment)["passes_verification"])

    def test_missing_assessment_is_completed_once_without_weakening_ingredient_checks(self):
        for recipe, expected in ((canned_recipe(), True), (REPORTED_RECIPE, False)):
            initial = self.assessment()
            initial.pop("canned_ingredient_check")
            completion = {"canned_ingredient_check": self.assessment()["canned_ingredient_check"]}
            verifier = RecipeVerifier()
            model = Mock(predict=Mock(side_effect=[json.dumps([initial]), json.dumps(completion)]))
            verifier.initialize(model)
            result = verifier.batch_verify_recipes([copy.deepcopy(recipe)], self.intent(), aicr_service)[0]
            self.assertEqual(result["verification_details"]["passes_verification"], expected)
            self.assertEqual(model.predict.call_count, 2)

    def test_assessment_completion_preserves_existing_failures(self):
        for conflict in (["Unsupported ingredient form"], "Unsupported ingredient form"):
            initial = self.assessment()
            initial["canned_ingredient_check"] = {"non_canned_ingredients": conflict}
            completion = {"canned_ingredient_check": self.assessment()["canned_ingredient_check"]}
            verifier = RecipeVerifier()
            model = Mock(predict=Mock(side_effect=[json.dumps([initial]), json.dumps(completion)]))
            verifier.initialize(model)
            result = verifier.batch_verify_recipes([canned_recipe()], self.intent(), aicr_service)[0]
            self.assertFalse(result["verification_details"]["passes_verification"])
            self.assertEqual(result["verification_details"]["canned_ingredient_check"]["non_canned_ingredients"], conflict)

    def test_invalid_completion_stays_failed_and_does_not_loop(self):
        initial = self.assessment()
        initial.pop("canned_ingredient_check")
        verifier = RecipeVerifier()
        model = Mock(predict=Mock(side_effect=[json.dumps([initial]), "not JSON"]))
        verifier.initialize(model)
        result = verifier.batch_verify_recipes([canned_recipe()], self.intent(), aicr_service)[0]
        self.assertFalse(result["verification_details"]["passes_verification"])
        self.assertEqual(model.predict.call_count, 2)

    def test_canned_only_does_not_prohibit_heating(self):
        recipe = canned_recipe()
        recipe["ingredients"].append("1 can vegetable broth")
        recipe["instructions"] = ["Simmer the canned beans, tomatoes, corn, and broth until hot."]
        self.assertTrue(self.verify(recipe)["passes_verification"])

    def test_canned_check_does_not_change_general_pantry_eligibility(self):
        recipe = canned_recipe()
        recipe["ingredients"].extend(["1 cup dry quinoa", "1 tsp cumin"])
        assessment = self.assessment({"constraints": {"ingredient_storage": "pantry_based"}})
        assessment["ingredient_storage_check"] = {
            "required_non_pantry_ingredients": [], "unspecified_ingredient_forms": [], "conflicting_guidance": [],
        }
        verifier = RecipeVerifier()
        verifier.initialize(Mock(predict=Mock(return_value=json.dumps(assessment))))
        self.assertTrue(verifier.verify_recipe_against_constraints(recipe, {"constraints": {"ingredient_storage": "pantry_based"}})["passes_verification"])

    def test_structured_fallback_requires_real_title_and_category(self):
        body = """INGREDIENTS:
- 1 can black beans
- 1 can tomatoes
COOKING_INSTRUCTIONS:
1. Mix the canned black beans and tomatoes in a bowl.
INGREDIENT_MODIFICATIONS:
HELPFUL_TIPS:
"""
        for heading, count in (("", 0), ("RECIPE_NAME: Show Recipes That Use Canned Ingredients Only.\nRECIPE_TYPE: Main Dish\n", 0),
                               ("RECIPE_NAME: Bean and Tomato Bowl\nRECIPE_TYPE: CUSTOM\n", 0),
                               ("RECIPE_NAME: Bean and Tomato Bowl\nRECIPE_TYPE: Main Dish\n", 1)):
            enhancer = RecipeEnhancer()
            enhancer.initialize(Mock(predict=Mock(return_value=heading + body)), aicr_service)
            recipes = enhancer.generate_structured_fallback_recipe(QUERIES[0], self.intent())
            self.assertEqual(len(recipes), count)
            if recipes:
                self.assertEqual(recipes[0]["name"], "Bean and Tomato Bowl")
                self.assertNotIn(QUERIES[0], recipes[0]["description"])
                self.assertTrue(self.verify(recipes[0])["passes_verification"])

    def test_repair_receives_valid_canned_components_and_full_failure_feedback(self):
        enhancer = RecipeEnhancer()
        model = Mock(predict=Mock(return_value=json.dumps([canned_recipe()])))
        enhancer.initialize(model, aicr_service)
        rejected = copy.deepcopy(REPORTED_RECIPE)
        rejected["verification_details"] = self.verify(rejected)
        enhancer.generate_fallback_recipes(QUERIES[0], self.intent(), [rejected])
        prompt = model.predict.call_args.args[0]
        self.assertIn("CANNED-ONLY REPAIR:", prompt)
        retained = prompt.split("already-canned components when sufficient: ", 1)[1].split(". Remove non-canned", 1)[0]
        self.assertEqual(json.loads(retained), REPORTED_RECIPE["ingredients"][:3])
        self.assertIn("Do not replace them with dry spices", prompt)

    def test_summary_does_not_invent_pantry_exceptions_or_a_no_cook_rule(self):
        generator = ResponseGenerator()
        generator.initialize(Mock())
        summary = generator.generate_personalized_response(QUERIES[0], [canned_recipe()], self.intent())
        self.assertIn("only explicitly canned", summary)
        self.assertNotIn("dried grains", summary)
        self.assertIn("does not necessarily mean no cooking", summary)
        generator.llm.predict.assert_not_called()

    def test_full_route_retries_bad_generation_and_never_uses_food_guidance(self):
        service = RecipeRAGService()
        service.is_initialized = True
        service._contains_phi_like_content = Mock(return_value=False)
        intent = self.intent(QUERIES[1])
        service.intent_analyzer.understand_query_intent_with_context = Mock(return_value=intent)
        service.search_engine.multi_query_search = Mock(return_value=[])
        service.search_engine.rerank_with_constraint_filtering = Mock(return_value=[])
        service._get_database_search_candidates = Mock(return_value=[])
        service.recipe_enhancer.prepare_recipes_for_verification = Mock(side_effect=lambda recipes, intent: recipes)
        service.recipe_enhancer.batch_enhance_recipes = Mock(side_effect=lambda recipes, intent: recipes)
        service.recipe_enhancer.generate_fallback_recipes = Mock(side_effect=[[copy.deepcopy(REPORTED_RECIPE)], [canned_recipe()]])
        service.recipe_verifier.initialize(Mock(predict=Mock(return_value=json.dumps([self.assessment(intent)]))))
        service.response_generator.answer_food_guidance = Mock(side_effect=AssertionError("Expected recipe cards"))
        result = service.ask_question(QUERIES[1])
        self.assertEqual(result["matches_found"], 1)
        self.assertEqual(result["source_documents"][0]["name"], canned_recipe()["name"])
        self.assertEqual(result["source_documents"][0]["source_label"], "AI Generated")
        self.assertEqual(service.recipe_enhancer.generate_fallback_recipes.call_count, 2)


if __name__ == "__main__":
    unittest.main()
