import copy
import json
import unittest
from unittest.mock import Mock, patch

from app.services.aicr_guidelines_service import aicr_service
from app.services.budget_recipe_contract import budget_recipe_response_format, normalize_budget_recipe
from app.services.recipe_enhancer import RecipeEnhancer
import test_budget_service as fixtures


class BudgetRecipeContractTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.BudgetTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.service = self.fixture.service

    def test_budget_generation_uses_api_schema_and_renders_ingredients_for_existing_cards(self):
        candidate = {**fixtures.recipe(generated=True), "ingredients": [
            {"food": "dry rice", "quantity": 100, "unit": "g"},
            {"food": "canned beans", "quantity": 425, "unit": "g"},
        ]}
        model = Mock(predict=Mock(return_value=json.dumps({"recipes": [candidate]})))
        enhancer = RecipeEnhancer()
        enhancer.initialize(model, aicr_service)
        result = enhancer.generate_fallback_recipes("Mexican meal under $10", self.fixture.intent(), [])
        self.assertEqual(model.predict.call_args.kwargs["response_format"], budget_recipe_response_format())
        self.assertEqual(result[0]["ingredients"], ["100 g dry rice", "425 g canned beans"])
        self.assertEqual(result[0]["servings"], 2)
        self.assertTrue(result[0]["generated_by_llm"])
        ingredient = budget_recipe_response_format()["json_schema"]["schema"]["properties"]["recipes"]["items"]["properties"]["ingredients"]["items"]
        self.assertEqual(ingredient["properties"]["unit"]["enum"], ["g", "ml", "count"])
        self.assertFalse(ingredient["additionalProperties"])

    def test_quantities_are_not_guessed_or_rounded_and_food_forms_are_preserved(self):
        result = normalize_budget_recipe({"ingredients": [
            {"food": "frozen spinach", "quantity": 123.456789, "unit": "g"},
            {"food": "cooked brown rice", "quantity": 150, "unit": "g"},
        ]})
        self.assertEqual(result["ingredients"], ["123.456789 g frozen spinach", "150 g cooked brown rice"])

    def test_explicit_reference_preserves_product_qualifiers_without_blocking_new_foods(self):
        options = [{"name": "raw frozen chicken breast with added salt solution", "unit": "g"}]
        candidate = {"ingredients": [
            {"price_reference": options[0]["name"], "quantity": 300},
            {"food": "fresh asparagus", "quantity": 200, "unit": "g"},
        ]}
        result = normalize_budget_recipe(candidate, options)
        self.assertEqual(result["ingredients"], ["300 g raw frozen chicken breast with added salt solution", "200 g fresh asparagus"])
        schema = budget_recipe_response_format(options)["json_schema"]["schema"]
        choices = schema["properties"]["recipes"]["items"]["properties"]["ingredients"]["items"]["anyOf"]
        self.assertIn("food", choices[1]["properties"])
        with self.assertRaises(ValueError):
            normalize_budget_recipe({"ingredients": [{"price_reference": "invented cheap food", "quantity": 1}]}, options)

    def test_known_weight_based_package_is_not_looked_up_as_an_unmeasured_count(self):
        catalog = self.service.catalog()
        self.assertFalse(self.service.price_lookup_ready({"ingredients": ["1 count canned beans"]}, catalog))
        self.assertTrue(self.service.price_lookup_ready({"ingredients": ["425 g canned beans"]}, catalog))

    def test_budget_repair_receives_failing_steps_and_must_fix_safe_endpoint(self):
        rejected = {**fixtures.recipe(generated=True), "instructions": ["Brown the raw egg batter briefly."],
                    "verification_details": {"passes_verification": False, "constraint_violations": ["Egg center not cooked through"]}}
        prompt = RecipeEnhancer()._build_budget_generation_prompt("Korean dinner under $10", self.fixture.intent(), "Policy", [], [rejected])
        self.assertIn("Brown the raw egg batter briefly.", prompt)
        self.assertIn("center must be fully cooked/set", prompt)
        self.assertIn("New foods remain allowed", prompt)

    def test_invalid_structured_amounts_fail_instead_of_becoming_free(self):
        for changes in [{"quantity": 0}, {"quantity": -1}, {"quantity": True}, {"quantity": float("nan")},
                        {"quantity": "to taste"}, {"unit": "tsp"}, {"food": ""}]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                normalize_budget_recipe({"ingredients": [{"food": "salt", "quantity": 1, "unit": "g", **changes}]})

    def test_nonbudget_generation_does_not_receive_response_format(self):
        model = Mock(predict=Mock(return_value=json.dumps([fixtures.recipe(generated=True)])))
        enhancer = RecipeEnhancer()
        enhancer.initialize(model, aicr_service)
        enhancer.generate_fallback_recipes("Mexican dinner", self.fixture.intent("Mexican dinner"), [])
        self.assertEqual(model.predict.call_args.kwargs, {})

    def test_unpriceable_measurements_do_not_spend_lookup_or_verification_calls(self):
        intent = self.fixture.intent("Mexican recipe under $10")
        candidate = {**fixtures.recipe(), "ingredients": ["2 teaspoons ground cumin", "salt to taste"]}
        provider = Mock(enabled=True, lookup_batches=2, retrieval_lookup_batches=1, items=Mock(return_value=[]))
        self.service.provider = provider
        pipeline = self.fixture.configure_pipeline(intent, [], [])
        with patch("app.services.rag_service.budget_service", self.service):
            checked = pipeline._verify_candidates([candidate], intent)
        provider.resolve.assert_not_called()
        pipeline.recipe_verifier.batch_verify_recipes.assert_not_called()
        self.assertTrue(checked[0]["budget_verification_pending"])
        self.assertFalse(checked[0]["verification_details"]["passes_verification"])
        self.assertEqual(checked[0]["budget_assessment"]["status"], "uncertain")
        self.assertEqual(intent["budget_request"].get("_price_lookup_batches", 0), 0)

    def test_fully_priced_database_recipe_still_wins_before_generation(self):
        intent = self.fixture.intent()
        pipeline = self.fixture.configure_pipeline(intent, [fixtures.recipe()], [])
        result = self.fixture.ask(pipeline)
        self.assertEqual(result["matches_found"], 1)
        pipeline.recipe_enhancer.generate_fallback_recipes.assert_not_called()
        pipeline.recipe_verifier.batch_verify_recipes.assert_called_once()

    def test_unpriced_reference_can_guide_generation_but_is_never_returned(self):
        intent = self.fixture.intent("Mexican dinner under $10")
        reference = {**fixtures.recipe("Reference Mexican Bowl"), "ingredients": ["salt to taste"]}
        pipeline = self.fixture.configure_pipeline(intent, [reference], [fixtures.recipe("Adapted Mexican Bowl", True)])
        result = self.fixture.ask(pipeline)
        self.assertEqual([recipe["name"] for recipe in result["source_documents"]], ["Adapted Mexican Bowl"])
        references = pipeline.recipe_enhancer.generate_fallback_recipes.call_args.kwargs["grounding_recipes"]
        self.assertEqual(references[0]["name"], "Reference Mexican Bowl")
        self.assertFalse(references[0]["verification_details"]["passes_verification"])
        checked_names = [item["name"] for call in pipeline.recipe_verifier.batch_verify_recipes.call_args_list for item in call.args[0]]
        self.assertEqual(checked_names, ["Adapted Mexican Bowl"])

    def test_low_cost_does_not_override_failed_safety_or_required_ingredient(self):
        for unsafe, required in [(True, []), (False, ["chicken"])]:
            with self.subTest(unsafe=unsafe, required=required):
                intent = self.fixture.intent()
                intent["constraints"]["ingredients_must_use"] = required
                candidate = {**fixtures.recipe(generated=True), "unsafe": unsafe}
                pipeline = self.fixture.configure_pipeline(intent, [], [candidate])
                result = self.fixture.ask(pipeline)
                self.assertEqual(result["matches_found"], 0)
                self.assertTrue(pipeline.recipe_verifier.batch_verify_recipes.called)

    def test_repeated_budget_annotation_does_not_duplicate_repair_errors(self):
        intent = self.fixture.intent()
        candidate = {**fixtures.recipe(), "ingredients": ["salt to taste"]}
        first = self.service.annotate([candidate], intent)
        repeated = self.service.annotate(copy.deepcopy(first), intent)
        self.assertEqual(first[0]["verification_details"]["constraint_violations"], repeated[0]["verification_details"]["constraint_violations"])

    def test_hidden_pinch_is_not_covered_by_no_salt_added_ingredient_label(self):
        candidate = {**fixtures.recipe(), "instructions": ["Heat the beans and add a pinch of salt."]}
        candidate["ingredients"] = ["100 g dry rice", "425 g no-salt-added canned beans"]
        assessed = self.service.assess(candidate, self.fixture.intent()["budget_request"])
        self.assertIn("Unlisted food addition needs an explicit priced quantity: salt", assessed["issues"])

    def test_hidden_additions_are_generic_and_negated_advice_is_not_an_addition(self):
        for text, missing in [("Finish with a drizzle of honey.", True),
                              ("Do not add a drizzle of honey.", False),
                              ("Heat a pan and add a little oil to coat the bottom.", True),
                              ("Repeat, adding more canola oil as needed.", True),
                              ("Add a splash of water.", False)]:
            candidate = {**fixtures.recipe(), "instructions": [text]}
            assessed = self.service.assess(candidate, self.fixture.intent()["budget_request"])
            self.assertEqual(any("Unlisted food addition" in issue for issue in assessed["issues"]), missing)
