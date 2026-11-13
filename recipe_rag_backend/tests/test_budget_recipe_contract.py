import copy
import json
import unittest
from unittest.mock import Mock, patch

from app.services.aicr_guidelines_service import aicr_service
from app.services.budget_recipe_contract import budget_preparation_issues, budget_recipe_response_format, normalize_budget_recipe
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
        self.assertTrue(result[0]["_local_generation_checks"])
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

    def test_dry_pasta_added_to_pancake_batter_is_not_a_valid_priceable_recipe(self):
        candidate = {**fixtures.recipe("Vegetable Pancakes", True), "ingredients": ["150 g dry whole wheat penne"],
                     "instructions": ["Add the dry whole wheat penne to the egg mixture.", "Fry the batter."]}
        self.assertTrue(budget_preparation_issues(candidate))
        self.assertFalse(self.service.price_lookup_ready(candidate, self.service.catalog()))
        self.assertIn("dry pasta directly", " ".join(self.service.assess(candidate, self.fixture.intent()["budget_request"])["issues"]))
        candidate["instructions"] = ["Boil the dry whole wheat penne according to its package directions.",
                                     "Drain and fold the cooked penne into the batter."]
        self.assertFalse(budget_preparation_issues(candidate))
        candidate.update(name="Penne Soup", instructions=["Add the dry penne to the simmering soup and cook until tender."])
        self.assertFalse(budget_preparation_issues(candidate))

    def test_oil_used_across_batches_cannot_exceed_the_priced_total(self):
        candidate = {**fixtures.recipe(generated=True), "ingredients": [*fixtures.recipe()["ingredients"], "30 ml canola oil"],
                     "instructions": ["Heat a skillet and add 30 ml of canola oil.",
                                      "Repeat with remaining batter, using the remaining 30 ml of canola oil.",
                                      "Serve hot, optionally with a dipping sauce of your choice."]}
        request = self.fixture.intent("Korean recipe under $10")["budget_request"]
        checked = self.service.assess(candidate, request)
        self.assertEqual(checked["status"], "uncertain")
        self.assertIn("canola oil allocated above its listed 30 ml total", " ".join(checked["issues"]))
        self.assertIn("unspecified serving addition", " ".join(checked["issues"]))
        candidate["instructions"] = ["Use 30 ml canola oil in total.", "Heat 15 ml canola oil for the first batch.",
                                     "Cook the next batch using the remaining 15 ml of canola oil."]
        self.assertEqual(self.service.assess(candidate, request)["status"], "estimated_within_budget")

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
        self.assertIn("160°F (71°C)", prompt)
        self.assertIn("New foods remain allowed", prompt)

    def test_measured_oil_repair_reuses_retry_and_runs_normal_verification(self):
        for cuisine in ("Mexican", "Korean"):
            with self.subTest(cuisine=cuisine):
                query = f"{cuisine} recipe under 10 dollars"
                intent = self.fixture.intent(query)
                candidate = fixtures.recipe(f"{cuisine} test meal", True)
                candidate["ingredients"] += ["10 ml canola oil"]
                candidate["instructions"] = ["Heat the beans and cooked rice, adding more oil as needed."]
                instructions = ["Cook the rice in water according to its package directions. Heat the beans with the cooked rice in 10 ml canola oil."]
                pipeline = self.fixture.configure_pipeline(intent, [], [candidate])
                pipeline.recipe_enhancer.initialize(Mock(predict=Mock(return_value=json.dumps({"instructions": instructions}))), aicr_service)
                result = self.fixture.ask(pipeline, query)
                self.assertEqual(result["matches_found"], 1)
                accepted = result["source_documents"][0]
                self.assertEqual(accepted["ingredients"], candidate["ingredients"])
                self.assertEqual(accepted["servings"], candidate["servings"])
                self.assertEqual(accepted["instructions"], instructions)
                self.assertEqual(accepted["budget_assessment"]["status"], "estimated_within_budget")
                pipeline.recipe_enhancer.generate_fallback_recipes.assert_called_once()
                pipeline.recipe_enhancer.llm.predict.assert_called_once()
                pipeline.recipe_verifier.batch_verify_recipes.assert_called_once()

    def test_instruction_repair_does_not_bypass_failed_safety(self):
        intent = self.fixture.intent("Korean recipe under $10")
        candidate = {**fixtures.recipe(generated=True), "unsafe": True,
                     "instructions": ["Heat the beans and add a dash of hot sauce."]}
        pipeline = self.fixture.configure_pipeline(intent, [], [candidate])
        model = Mock(predict=Mock(return_value=json.dumps({"instructions": ["Heat the beans with the fully cooked rice."]})))
        pipeline.recipe_enhancer.initialize(model, aicr_service)
        self.assertEqual(self.fixture.ask(pipeline)["matches_found"], 0)
        model.predict.assert_called_once()
        pipeline.recipe_verifier.batch_verify_recipes.assert_called_once()

    def test_quantity_and_safety_repairs_fit_existing_three_attempts(self):
        intent = self.fixture.intent("Korean recipe under $10")
        candidate = {**fixtures.recipe(generated=True), "instructions": ["Brown the batter, adding more oil as needed."]}
        model = Mock(predict=Mock(side_effect=[
            json.dumps({"instructions": ["Brown the batter in a nonstick pan."]}),
            json.dumps({"instructions": ["Cook the batter in a nonstick pan until the center reaches 160°F (71°C)."]}),
        ]))
        pipeline = self.fixture.configure_pipeline(intent, [], [candidate])
        pipeline.recipe_enhancer.initialize(model, aicr_service)

        def verify(recipes, *args):
            for recipe in recipes:
                safe = "160°F" in recipe["instructions"][0]
                recipe["verification_details"] = {"passes_verification": safe, "relevance": "match",
                    "constraint_violations": [] if safe else ["Guideline food_safety: Center endpoint missing"]}
            return recipes

        pipeline.recipe_verifier.batch_verify_recipes.side_effect = verify
        self.assertEqual(self.fixture.ask(pipeline)["matches_found"], 1)
        pipeline.recipe_enhancer.generate_fallback_recipes.assert_called_once()
        pipeline.recipe_enhancer.generate_structured_fallback_recipe.assert_not_called()
        self.assertEqual(model.predict.call_count, 2)
        self.assertEqual(pipeline.recipe_verifier.batch_verify_recipes.call_count, 2)

    def test_changed_ingredients_can_be_repaired_after_earlier_price_miss(self):
        query = "Korean recipe under $10"
        intent = self.fixture.intent(query)
        first = {**fixtures.recipe("First attempt", True), "ingredients": ["100 g fresh zucchini", "10 ml canola oil"],
                 "instructions": ["Cook the zucchini, adding more oil as needed."]}
        second = {**fixtures.recipe("Second attempt", True), "ingredients": [*fixtures.recipe()["ingredients"], "10 ml canola oil"],
                  "instructions": ["Heat the beans and rice, adding more oil as needed."]}
        pipeline = self.fixture.configure_pipeline(intent, [], [first])
        pipeline.recipe_enhancer.generate_structured_fallback_recipe.return_value = [second]
        model = Mock(predict=Mock(side_effect=[
            json.dumps({"instructions": ["Cook the zucchini in 10 ml canola oil until tender."]}),
            json.dumps({"instructions": ["Cook the rice according to package instructions. Heat the beans and rice in 10 ml canola oil."]}),
        ]))
        pipeline.recipe_enhancer.initialize(model, aicr_service)
        with patch("app.services.rag_service.budget_service", self.service):
            matches = pipeline._generate_verified_fallback_recipes(query, intent, [], [fixtures.recipe()], set())
        self.assertEqual([recipe["name"] for recipe in matches], ["Second attempt"])
        pipeline.recipe_enhancer.generate_fallback_recipes.assert_called_once()
        self.assertEqual(model.predict.call_count, 2)

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
