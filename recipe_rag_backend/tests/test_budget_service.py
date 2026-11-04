import copy
import json
import tempfile
import unittest
import pandas as pd
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch

from app.services.budget_service import BudgetService, apply_budget_intent, budget_clarification, budget_rules
from app.services.intent_analyzer import IntentAnalyzer
from app.services.recipe_verifier import RecipeVerifier
from app.services.recipe_enhancer import RecipeEnhancer
from app.services.rag_service import RecipeRAGService
from app.services.aicr_guidelines_service import aicr_service
from app.services.response_generator import ResponseGenerator
from guideline_fixtures import passing_guideline_checks


TODAY = date(2026, 11, 1)
CATALOG = {
    "currency": "USD", "region": "Test fixture, not retail prices", "observed_on": "2026-11-01",
    "planning_allowance": "0.20", "items": [
        {"name": "dry rice", "aliases": ["dry rice"], "unit": "g", "package_quantity": "1000",
         "package_price": "4", "source_url": "https://example.com/rice"},
        {"name": "canned beans", "aliases": ["canned beans"], "unit": "g", "package_quantity": "425.242846875",
         "package_price": "1", "source_url": "https://example.com/beans"},
        {"name": "canola oil", "aliases": ["canola oil"], "unit": "ml", "package_quantity": "1000",
         "package_price": "5", "food_role": "oil", "source_url": "https://example.com/oil"},
        {"name": "eggs", "aliases": ["eggs"], "unit": "count", "package_quantity": "12",
         "package_price": "3", "source_url": "https://example.com/eggs"},
    ],
}


def recipe(name="Bean and Rice Bowl", generated=False):
    return {"name": name, "recipe_id": name.lower().replace(" ", "-"), "type": "Main Dish",
            "description": "A bean and rice dinner.", "ingredients": ["100 g dry rice", "1 (15 oz) can canned beans"],
            "instructions": ["Cook the rice thoroughly in water. Heat the beans and combine. Divide into two servings."],
            "servings": 2, "generated_by_llm": generated, "database_record_found": not generated,
            "source_name": "AICR" if not generated else "", "recipe_link": "https://example.com/recipe" if not generated else ""}


class BudgetTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "prices.json"
        self.path.write_text(json.dumps(CATALOG))
        self.service = BudgetService(self.path, today=lambda: TODAY)

    def intent(self, query="Show meals under $5 for the whole recipe", history=None):
        analyzer = IntentAnalyzer()
        return analyzer._post_process_intent(query, analyzer._get_fallback_intent_data(query), history)

    def assess(self, candidate=None, **changes):
        request = {"currency": "USD", "limit": "5", "basis": "recipe", "exclusive": True, **changes}
        return self.service.assess(candidate or recipe(), request)

    def legacy_basis_question(self, limit):
        return (f"Is your USD ${limit} limit for the quantities used in the whole recipe, per serving, "
                "or for buying the groceries before tax and delivery fees? I use U.S. reference prices, not guaranteed local prices.")

    def test_money_extraction_does_not_confuse_time_or_ingredient_count(self):
        for query in ["under $5", "under 5 dollars", "under five dollars", "under US$5"]:
            with self.subTest(query=query):
                self.assertEqual(self.intent(query)["budget_request"]["limit"], "5")
                self.assertTrue(self.intent(query)["budget_request"]["exclusive"])
        for query in ["under 5 minutes", "only 5 ingredients", "make dinner for 5 people", "recipes with 5 pounds of chicken"]:
            self.assertNotIn("budget_request", self.intent(query))
        self.assertFalse(self.intent("at most $5")["budget_request"]["exclusive"])
        self.assertEqual(self.intent("under $5 with oil that costs $10")["budget_request"]["limit"], "5")

    def test_unspecified_budget_basis_defaults_to_recipe_and_explicit_basis_wins(self):
        first = "Show meals under $5"
        self.assertFalse(budget_clarification(self.intent(first)))
        self.assertEqual(self.intent(first)["budget_request"]["basis"], "recipe")
        self.assertTrue(self.intent(first)["budget_request"]["basis_assumed"])
        followup = self.intent("Whole recipe", [{"role": "user", "content": first}])
        self.assertEqual(followup["budget_request"]["basis"], "recipe")
        self.assertNotIn("basis_assumed", followup["budget_request"])
        self.assertFalse(budget_clarification(followup))
        for phrase, expected in [("per serving", "per_serving"), ("for groceries", "shopping")]:
            self.assertEqual(self.intent(first + " " + phrase)["budget_request"]["basis"], expected)
            self.assertEqual(self.intent(phrase, [{"role": "user", "content": first}])["budget_request"]["basis"], expected)
        self.assertIn("maximum food budget", budget_clarification(self.intent("affordable meals")))

    def test_serving_count_supports_words_digits_and_later_changes_not_dollars(self):
        first = "Can you help me to prepare a recipe for my dinner which is around 10 dollars"
        history = [{"role": "user", "content": first}]
        for reply in ["For the whole recipe, serving two people.", "Whole recipe for 2 people",
                      "Whole recipe, serves two", "Whole recipe, two servings", "Whole recipe, feeds 2"]:
            with self.subTest(reply=reply):
                self.assertEqual(self.intent(reply, history)["budget_request"]["servings"], 2)
        self.assertNotIn("servings", self.intent(first)["budget_request"])
        updated = self.intent("make it four servings", history + [{"role": "user", "content": "whole recipe for 2 people"}])
        self.assertEqual(updated["budget_request"]["servings"], 4)
        self.assertIn("1–100", budget_clarification(self.intent("under $10 whole recipe for zero people")))

    def test_scope_new_task_drops_budget_but_more_recipes_keeps_it(self):
        analyzer = IntentAnalyzer()
        analyzer.initialize(Mock(predict=Mock(return_value=json.dumps(analyzer._get_fallback_intent_data("Show soups")))))
        history = [{"role": "user", "content": "Show meals under $5 for the whole recipe"}, {"role": "assistant", "content": "Recipes."}]
        independent = analyzer.understand_query_intent_with_context("Show recipes with broccoli and chicken", history)
        self.assertNotIn("budget_request", independent)
        continuation = analyzer.understand_query_intent_with_context("more recipes", history)
        self.assertEqual(continuation["budget_request"]["limit"], "5")
        self.assertEqual(self.intent("Make it under $10 instead", history)["budget_request"]["limit"], "10")
        self.assertNotIn("budget_request", self.intent("remove the budget", history))

    def test_no_currency_conversion_or_fees_are_invented(self):
        self.assertIn("USD", budget_clarification(self.intent("Under €5 per serving")))
        self.assertIn("before tax", budget_clarification(self.intent("Under $5 for groceries including tax")))
        self.assertEqual(self.intent("Under $10 for groceries")["budget_request"]["basis"], "shopping")

    def test_budget_clarification_reply_cannot_be_routed_as_a_new_task(self):
        for first, reply, field, expected in [
            ("Show meals under $5", "Whole recipe", "basis", "recipe"),
            ("Show meals under €5 per serving", "Yes", "currency", "USD"),
            ("Show meals under $5 for groceries including tax", "Yes", "checkout_fees_required", None),
            ("Show affordable meals", "5", "limit", "5"),
        ]:
            with self.subTest(first=first):
                analyzer = IntentAnalyzer()
                model_intent = analyzer._get_fallback_intent_data(reply)
                model_intent.update(query_type="general", context_action="new_request")
                analyzer.initialize(Mock(predict=Mock(return_value=json.dumps(model_intent))))
                history = [{"role": "user", "content": first},
                           {"role": "assistant", "content": self.legacy_basis_question("5") if field == "basis" else budget_clarification(self.intent(first))}]
                intent = analyzer.understand_query_intent_with_context(reply, history)
                self.assertEqual(intent["query_type"], "recipe_search")
                self.assertEqual(intent["context_action"], "continue_request")
                self.assertEqual(intent["budget_request"].get(field), expected)
                pipeline = self.configure_pipeline(intent, [recipe()], [])
                pipeline._is_small_talk_query.return_value = True
                with patch("app.services.rag_service.budget_service", self.service), patch("app.services.rag_service.safety_service.should_intercept", return_value=False):
                    result = pipeline.ask_question(reply, conversation_history=history)
                self.assertNotEqual(result.get("source"), "error", result)
                pipeline._is_small_talk_query.assert_not_called()

    def test_used_cost_and_full_package_purchase_cost_are_distinct(self):
        result = self.assess()
        self.assertEqual(result["recipe_cost"], "1.40")
        self.assertEqual(result["shopping_cost"], "5.00")
        self.assertEqual(result["planning_ceiling"], "1.68")
        self.assertEqual(result["status"], "estimated_within_budget")
        self.assertEqual(self.assess(basis="shopping")["status"], "over_budget")

    def test_strict_boundary_rounding_and_allowance(self):
        self.assertEqual(self.assess(limit="1.68")["status"], "uncertain")
        self.assertEqual(self.assess(limit="1.68", exclusive=False)["status"], "estimated_within_budget")
        self.assertEqual(self.assess(limit="1.40")["status"], "over_budget")
        self.assertEqual(self.assess(limit="1.50")["status"], "uncertain")

    def test_unknown_forms_quantities_and_ingredients_never_cost_zero(self):
        for ingredient in ["1 cup dry rice", "100 g cooked rice", "rice to taste", "1 g saffron", "2 g garlic powder, optional",
                           "100 g canned beans, drained", "-100 g dry rice", "1/0 g dry rice", "100 g dry rice or quinoa", "1 cup milk:"]:
            candidate = recipe()
            candidate["ingredients"].append(ingredient)
            with self.subTest(ingredient=ingredient):
                self.assertEqual(self.assess(candidate)["status"], "uncertain")

    def test_group_headings_water_repeated_ingredients_and_fractional_amounts(self):
        candidate = recipe()
        candidate["ingredients"] = ["Base:", "50 g dry rice", "50 g dry rice", "1 1/2 (15 oz) cans canned beans", "2 cups water"]
        result = self.assess(candidate)
        self.assertEqual(result["ingredient_count"], 2)
        self.assertEqual(result["recipe_cost"], "1.90")
        self.assertEqual(result["line_items"][1]["packages_to_buy"], 2)
        self.assertIsNotNone(self.service.parse_ingredient("½ tbsp canola oil", CATALOG))
        self.assertEqual(self.service.parse_ingredient("2 eggs", CATALOG)[1], 2)

    def test_equivalent_sized_can_formats_keep_the_same_price_and_quantity(self):
        original = self.service.parse_ingredient("1 (15 oz) can canned beans, drained and rinsed", CATALOG)
        for line in ["1 can (15 oz) canned beans, drained and rinsed", "1 (15-ounce) can canned beans",
                     "1 can (15 ounces) canned beans", "1 can (15-ounce) canned beans"]:
            with self.subTest(line=line):
                self.assertEqual(self.service.parse_ingredient(line, CATALOG), original)
        self.assertIsNone(self.service.parse_ingredient("1 can canned beans", CATALOG))
        self.assertIsNone(self.service.parse_ingredient("1 can (15 oz) canned beans or tofu", CATALOG))
        self.assertEqual(self.service.parse_ingredient("2 count eggs", CATALOG)[1], 2)

    def test_budget_generation_contract_keeps_guidelines_references_and_exact_priced_forms(self):
        intent = self.intent()
        intent["budget_price_options"] = self.service.options()
        intent["constraints"]["allergens_to_avoid"] = ["peanuts"]
        candidate = recipe(generated=True)
        candidate["ingredients"] = ["100 g dry rice", "1 can (15 oz) canned beans"]
        model = Mock(predict=Mock(return_value=json.dumps([candidate, recipe("Second Bowl", True)])))
        enhancer = RecipeEnhancer()
        enhancer.initialize(model, aicr_service)
        reference = recipe("Reference Bowl")
        rejected = {**recipe("Rejected Bowl", True), "budget_assessment": {"issues": ["Unpriced honey"]}}
        generated = enhancer.generate_fallback_recipes("Meal under $5", intent, [rejected], grounding_recipes=[reference])
        prompt = model.predict.call_args.args[0]
        self.assertIn("Create exactly 1 complete", prompt)
        self.assertIn("AVAILABLE REFERENCE-PRICED INGREDIENTS", prompt)
        self.assertIn("<quantity> g dry rice", prompt)
        self.assertIn("Reference Bowl", prompt)
        self.assertIn("Unpriced honey", prompt)
        self.assertIn("peanuts", prompt)
        self.assertIn("NUTRITION AND FOOD SAFETY POLICY", prompt)
        self.assertIn("Do not convert a cooked weight to a dry weight", prompt)
        self.assertEqual(len(generated), 1)
        self.assertEqual(generated[0]["generation_basis"], "database_guided")
        self.assertEqual(self.assess(generated[0])["status"], "estimated_within_budget")

    def test_budget_structured_fallback_keeps_numeric_servings_and_same_verification_path(self):
        intent = self.intent()
        intent["budget_price_options"] = self.service.options()
        enhancer = RecipeEnhancer()
        enhancer.initialize(Mock(predict=Mock(return_value=json.dumps([recipe(generated=True)]))), aicr_service)
        generated = enhancer.generate_structured_fallback_recipe("Meal under $5", intent)
        self.assertEqual(generated[0]["servings"], 2)
        self.assertEqual(generated[0]["generation_basis"], "ai_only")
        self.assertEqual(self.assess(generated[0], basis="per_serving")["status"], "estimated_within_budget")

    def test_non_budget_generation_retains_its_existing_prompt_and_recipe_count(self):
        enhancer = RecipeEnhancer()
        model = Mock(predict=Mock(return_value=json.dumps([recipe("First Bowl", True), recipe("Second Bowl", True)])))
        enhancer.initialize(model, aicr_service)
        generated = enhancer.generate_fallback_recipes("Show meals", self.intent("Show meals"), [])
        self.assertEqual(len(generated), 2)
        self.assertNotIn("AVAILABLE REFERENCE-PRICED INGREDIENTS", model.predict.call_args.args[0])

    def test_pantry_credit_requires_explicit_quantity_and_does_not_change_used_cost(self):
        result = self.assess(basis="shopping", owned_ingredients=["200 g dry rice"])
        self.assertEqual(result["shopping_cost"], "1.00")
        self.assertEqual(result["recipe_cost"], "1.40")
        self.assertEqual(result["purchases"], 1)
        self.assertEqual(self.assess(owned_ingredients=["dry rice"])["shopping_cost"], "5.00")
        candidate = recipe()
        candidate["ingredients"][0] = "150 g dry rice"
        self.assertEqual(self.assess(candidate, owned_ingredients=["100 g dry rice", "100 g dry rice"])["shopping_cost"], "5.00")

    def test_per_serving_requires_supported_yield_and_requested_yield_is_not_silently_changed(self):
        self.assertEqual(self.assess(basis="per_serving")["estimate"], "0.70")
        for servings in [None, "2", 0, True, 1000, 2.5]:
            candidate = {**recipe(), "servings": servings}
            self.assertEqual(self.assess(candidate, basis="per_serving")["status"], "uncertain")
        self.assertEqual(self.assess(servings=4)["status"], "uncertain")

    def test_catalog_is_reloaded_and_stale_invalid_or_missing_prices_fail_closed(self):
        for changes in [{"observed_on": "2020-01-01"}, {"observed_on": "2099-01-01"}, {"currency": "EUR"},
                        {"planning_allowance": "NaN"}, {"items": [{**CATALOG["items"][0], "package_quantity": "0"}]}]:
            self.path.write_text(json.dumps({**CATALOG, **changes}))
            self.assertIsNone(self.service.catalog())
            self.assertEqual(self.assess()["status"], "uncertain")
        self.path.write_text("not json")
        self.assertIsNone(self.service.catalog())
        self.path.unlink()
        self.assertIsNone(self.service.catalog())

    def test_ranking_preserves_relevance_order_instead_of_preferring_fewer_purchases(self):
        intent = self.intent()
        simple = recipe("Simple Bowl")
        more = recipe("Bowl with Oil")
        more["ingredients"].append("1 tbsp canola oil")
        more["instructions"] = ["Bake the rice and beans with oil and sufficient water until fully cooked."]
        ranked = self.service.rank(self.service.annotate([more, simple], intent))
        self.assertEqual([item["name"] for item in ranked], ["Bowl with Oil", "Simple Bowl"])
        self.assertEqual(len(ranked), 2)

    def assessment(self, intent):
        return {"id": 0, "relevance": "match", "constraint_violations": [],
                "ingredient_completeness_check": {"status": "pass", "evidence": "All food additions are listed with quantities."},
                "portion_adequacy_check": {"status": "pass", "evidence": "The two servings are realistic."},
                "guideline_checks": passing_guideline_checks(),
                "constraint_checks": {key: {"status": "pass", "evidence": "Matches actual ingredients and preparation."}
                                      for key in RecipeVerifier()._required_checks(intent)}}

    def test_existing_guideline_and_completeness_checks_cannot_be_overridden_by_cheap_price(self):
        intent = self.intent()
        for category in ["food_safety", "nutrition", "symptom_suitability", "ingredient_completeness_check", "portion_adequacy_check"]:
            verification = self.assessment(intent)
            if category.endswith("_check"):
                verification.pop(category)
            else:
                verification["guideline_checks"][category] = {"status": "fail", "evidence": "Conflicting patient requirement."}
            verifier = RecipeVerifier()
            verifier.initialize(Mock(predict=Mock(return_value=json.dumps([verification]))))
            checked = verifier.batch_verify_recipes([recipe(generated=True)], intent, aicr_service)
            result = self.service.annotate(checked, intent)[0]
            self.assertFalse(result["verification_details"]["passes_verification"], category)
        self.assertNotIn("constraints.budget_max", RecipeVerifier()._required_checks(intent))

    def test_generation_and_verification_prompts_contain_the_budget_contract(self):
        intent = self.intent()
        self.assertIn("Never shrink portions", budget_rules(intent))
        prompt = RecipeVerifier()._build_individual_verification_prompt(recipe(), intent)
        self.assertIn('"servings": 2', prompt)
        self.assertIn("ingredient_completeness_check", prompt)
        self.assertIn("portion_adequacy_check", prompt)
        self.assertIn("backend_price_assessment", prompt)
        self.assertNotIn("budget_recipe_check", prompt)
        enhancer = RecipeEnhancer()
        enhancer.initialize(Mock(predict=Mock(return_value=json.dumps([recipe(generated=True)]))), aicr_service)
        with patch.object(aicr_service, "validate_recipe_compliance", return_value={"overall_compliant": True, "score": 100, "warnings": []}):
            generated = enhancer.generate_fallback_recipes("A meal under $5", intent, [])
        self.assertEqual(generated[0]["servings"], 2)

    def test_no_budget_does_not_load_catalog_change_order_or_touch_recipes(self):
        recipes = [recipe()]
        with patch.object(self.service, "catalog", side_effect=AssertionError("Must not read prices")):
            self.assertIs(self.service.annotate(recipes, {}), recipes)
        self.assertEqual(budget_rules({}), "")

    def test_final_filter_recalculates_modified_ingredients_and_catalog_prices(self):
        intent = self.intent()
        candidate = self.service.annotate([recipe()], intent)[0]
        pipeline = RecipeRAGService()
        with patch("app.services.rag_service.budget_service", self.service):
            self.assertEqual(len(pipeline._apply_deterministic_constraints([candidate], intent)), 1)
            candidate["ingredients"].append("1 g unpriced garnish")
            self.assertEqual(pipeline._apply_deterministic_constraints([candidate], intent), [])
            candidate["ingredients"].pop()
            updated = copy.deepcopy(CATALOG)
            updated["items"][1]["package_price"] = "20"
            self.path.write_text(json.dumps(updated))
            self.assertEqual(pipeline._apply_deterministic_constraints([candidate], intent), [])

    def test_low_cost_never_replaces_required_ingredients(self):
        intent = self.intent()
        intent["constraints"]["ingredients_must_use"] = ["chicken"]
        candidate = self.service.annotate([recipe()], intent)[0]
        with patch("app.services.rag_service.budget_service", self.service):
            self.assertEqual(RecipeRAGService()._apply_deterministic_constraints([candidate], intent), [])

    def configure_pipeline(self, intent, retrieved, generated):
        pipeline = RecipeRAGService()
        pipeline.is_initialized = True
        pipeline._contains_phi_like_content = Mock(return_value=False)
        pipeline._is_small_talk_query = Mock(return_value=False)
        pipeline.intent_analyzer.understand_query_intent_with_context = Mock(return_value=intent)
        pipeline.search_engine.multi_query_search = Mock(return_value=retrieved)
        pipeline.search_engine.rerank_with_constraint_filtering = Mock(side_effect=lambda docs, *args, **kwargs: docs)
        pipeline._build_recipe_data_from_doc = Mock(side_effect=copy.deepcopy)
        pipeline._get_database_search_candidates = Mock(return_value=[])
        pipeline.recipe_enhancer.prepare_recipes_for_verification = Mock(side_effect=lambda recipes, intent: recipes)
        def verify(recipes, *args):
            for item in recipes:
                item["verification_details"] = {"passes_verification": not item.get("unsafe"), "relevance": "match", "constraint_violations": []}
            return recipes
        pipeline.recipe_verifier.batch_verify_recipes = Mock(side_effect=verify)
        pipeline.recipe_enhancer.generate_fallback_recipes = Mock(return_value=generated)
        pipeline.recipe_enhancer.generate_structured_fallback_recipe = Mock(return_value=[])
        return pipeline

    def ask(self, pipeline, query="Show meals under $5 for the whole recipe"):
        with patch("app.services.rag_service.budget_service", self.service), patch("app.services.rag_service.safety_service.should_intercept", return_value=False):
            result = pipeline.ask_question(query)
        self.assertNotEqual(result.get("source"), "error", result)
        return result

    def test_pipeline_database_first_then_guided_generation_then_ai_only(self):
        intent = self.intent()
        pipeline = self.configure_pipeline(intent, [recipe()], [recipe("AI Bowl", True)])
        result = self.ask(pipeline)
        self.assertEqual(result["source_documents"][0]["source"], "database_exact")
        pipeline.recipe_enhancer.generate_fallback_recipes.assert_not_called()
        expensive = recipe()
        expensive["ingredients"][0] = "2000 g dry rice"
        pipeline = self.configure_pipeline(self.intent(), [expensive], [recipe("AI Bowl", True)])
        result = self.ask(pipeline)
        self.assertEqual(result["source_documents"][0]["source"], "llm_generated")
        self.assertTrue(pipeline.recipe_enhancer.generate_fallback_recipes.call_args.kwargs["grounding_recipes"])
        pipeline = self.configure_pipeline(self.intent(), [expensive], [])
        pipeline.recipe_enhancer.generate_fallback_recipes.side_effect = [[], [], [recipe("AI Bowl", True)]]
        self.assertEqual(len(self.ask(pipeline)["source_documents"]), 1)
        self.assertEqual(pipeline.recipe_enhancer.generate_fallback_recipes.call_args.kwargs["grounding_recipes"], [])

    def test_database_rescue_prices_actual_records_and_respects_exclusions(self):
        pipeline = RecipeRAGService()
        pipeline.data_loader.df = pd.DataFrame([
            {"recipe_id": "unknown", "Name": "Unpriced Bowl", "Type": "Main Dish", "Ingredients": "1 g saffron", "Directions": "Cook."},
            {"recipe_id": "priced", "Name": "Bean Bowl", "Type": "Main Dish",
             "Ingredients": "100 g dry rice\n1 (15 oz) can canned beans", "Directions": "Cook rice and heat beans."},
        ])
        intent = self.intent()
        intent["search_strategy"]["search_keywords"] = []
        with patch("app.services.rag_service.budget_service", self.service):
            candidates = pipeline._get_database_search_candidates("meals under $5 for the whole recipe", intent, set(), 1)
            self.assertEqual(candidates[0]["recipe_id"], "priced")
            excluded = pipeline._get_database_search_candidates("meals under $5 for the whole recipe", intent, {"priced"}, 1)
            self.assertEqual(excluded[0]["recipe_id"], "unknown")

    def test_budget_results_keep_database_attribution_and_three_recipe_limit(self):
        candidates = [recipe(f"Bowl {index}") for index in range(5)]
        for candidate, method in zip(candidates, ["Heat", "Steam", "Bake", "Microwave", "Simmer"]):
            candidate["instructions"] = [f"{method} the rice and beans until fully cooked."]
        pipeline = self.configure_pipeline(self.intent(), candidates, [])
        result = self.ask(pipeline)
        self.assertEqual(len(result["source_documents"]), 3)
        for candidate in result["source_documents"]:
            self.assertEqual(candidate["source_name"], "AICR")
            self.assertEqual(candidate["recipe_link"], "https://example.com/recipe")
            self.assertEqual(candidate["budget_assessment"]["status"], "estimated_within_budget")

    def test_missing_budget_amount_and_missing_catalog_do_not_trigger_generation(self):
        for intent, missing in [(self.intent("affordable meals"), False), (self.intent(), True)]:
            if missing:
                self.path.unlink()
            pipeline = self.configure_pipeline(intent, [], [])
            result = self.ask(pipeline)
            self.assertEqual(result["source_documents"], [])
            pipeline.search_engine.multi_query_search.assert_not_called()
            pipeline.recipe_enhancer.generate_fallback_recipes.assert_not_called()

    def test_reported_ten_dollar_whole_recipe_followup_returns_a_priced_recipe(self):
        first = "can you help me to prepare a meal under 10 dollars"
        history = [{"role": "user", "content": first},
                   {"role": "assistant", "content": self.legacy_basis_question("10")}]
        intent = self.intent("for the whole recipe", history)
        intent["recipe_request"] = first + "; for the whole recipe"
        intent["budget_price_options"] = self.service.options()
        pipeline = self.configure_pipeline(intent, [], [])
        pipeline.recipe_enhancer = RecipeEnhancer()
        pipeline.recipe_enhancer.initialize(Mock(predict=Mock(return_value=json.dumps([recipe("Bean and Rice Dinner", True)]))), aicr_service)
        pipeline.recipe_verifier = RecipeVerifier()
        pipeline.recipe_verifier.initialize(Mock(predict=Mock(return_value=json.dumps([self.assessment(intent)]))))
        result = self.ask(pipeline, "for the whole recipe")
        self.assertEqual(result["matches_found"], 1, result)
        self.assertEqual(result["source_documents"][0]["source"], "llm_generated")
        self.assertEqual(result["source_documents"][0]["budget_assessment"]["basis"], "recipe")
        self.assertEqual(result["source_documents"][0]["budget_assessment"]["status"], "estimated_within_budget")
        self.assertTrue(result["source_documents"][0]["verification_details"]["passes_verification"])

    def test_exact_dinner_exchange_preserves_context_and_returns_verified_recipe(self):
        first = "Can you help me to prepare a recipe for my dinner which is around 10 dollars"
        reply = "For the whole recipe, serving two people."
        analyzer = IntentAnalyzer()
        model_intent = analyzer._get_fallback_intent_data(first)
        analyzer.initialize(Mock(predict=Mock(return_value=json.dumps(model_intent))))
        initial = analyzer.understand_query_intent_with_context(first, [])
        history = [{"role": "user", "content": first},
                   {"role": "assistant", "content": self.legacy_basis_question("10")}]
        intent = analyzer.understand_query_intent_with_context(reply, history)
        self.assertEqual(intent["budget_request"]["servings"], 2)
        self.assertEqual(intent["budget_request"]["basis"], "recipe")
        self.assertIn("dinner", intent["resolved_query"])
        intent["recipe_request"] = intent["resolved_query"]
        pipeline = self.configure_pipeline(intent, [], [])
        pipeline.intent_analyzer = analyzer
        pipeline.recipe_enhancer = RecipeEnhancer()
        pipeline.recipe_enhancer.initialize(Mock(predict=Mock(return_value=json.dumps([recipe(generated=True)]))), aicr_service)
        pipeline.recipe_verifier = RecipeVerifier()
        model = Mock(predict=Mock(return_value=json.dumps([self.assessment(intent)])))
        pipeline.recipe_verifier.initialize(model)
        with patch("app.services.rag_service.budget_service", self.service), \
                patch("app.services.recipe_verifier.budget_service", self.service), \
                patch("app.services.rag_service.safety_service.should_intercept", return_value=False):
            result = pipeline.ask_question(reply, conversation_history=history)
        self.assertEqual(result["matches_found"], 1, result)
        candidate = result["source_documents"][0]
        self.assertEqual(candidate["servings"], 2)
        self.assertEqual(candidate["budget_assessment"]["status"], "estimated_within_budget")
        self.assertTrue(candidate["verification_details"]["passes_verification"])
        prompt = model.predict.call_args.args[0]
        self.assertIn('"requested_servings": 2', prompt)
        self.assertIn('"estimate": "1.40"', prompt)
        self.assertIn("Missing prices are NOT missing recipe ingredients", prompt)

    def test_dollar_requests_return_cards_without_a_cost_basis_followup(self):
        for query in ["Can you help me to prepare a recipe for my dinner which is around 10 dollars",
                      "Show meals under 5 dollars", "Prepare dinner under $10 for two people"]:
            with self.subTest(query=query):
                intent = self.intent(query)
                pipeline = self.configure_pipeline(intent, [], [recipe(generated=True)])
                result = self.ask(pipeline, query)
                self.assertEqual(result["matches_found"], 1, result)
                self.assertEqual(result["source_documents"][0]["budget_assessment"]["basis"], "recipe")
                self.assertIn("I've treated your budget", result["response"])
                self.assertNotIn("Is your USD", result["response"])
                pipeline.recipe_enhancer.generate_fallback_recipes.assert_called_once()
        explicit = self.intent("dinner under $10 per serving")
        result = self.ask(self.configure_pipeline(explicit, [recipe()], []), "dinner under $10 per serving")
        self.assertNotIn("I've treated your budget", result["response"])
        self.assertEqual(result["source_documents"][0]["budget_assessment"]["basis"], "per_serving")

    def test_budget_semantic_checks_stay_strict_even_when_price_passes(self):
        intent = self.intent()
        for field in ["ingredient_completeness_check", "portion_adequacy_check"]:
            for status in ["fail", "unknown"]:
                with self.subTest(field=field, status=status):
                    assessment = self.assessment(intent)
                    assessment[field] = {"status": status, "evidence": "Unlisted food addition or unsupported portion size."}
                    verifier = RecipeVerifier()
                    verifier.initialize(Mock(predict=Mock(return_value=json.dumps([assessment]))))
                    with patch("app.services.recipe_verifier.budget_service", self.service):
                        checked = verifier.batch_verify_recipes([recipe(generated=True)], intent, aicr_service)
                    final = self.service.annotate(checked, intent)[0]
                    self.assertEqual(final["budget_assessment"]["status"], "estimated_within_budget")
                    self.assertFalse(final["verification_details"]["passes_verification"])

    def test_price_gate_rejects_unknown_over_budget_and_wrong_servings_after_semantic_pass(self):
        intent = self.intent("Show dinner under $5 for the whole recipe for two people")
        for changes in [{"ingredients": ["2000 g dry rice", "1 (15 oz) can canned beans"]},
                        {"ingredients": [*recipe()["ingredients"], "1 g saffron"]}, {"servings": 4}]:
            with self.subTest(changes=changes):
                verifier = RecipeVerifier()
                verifier.initialize(Mock(predict=Mock(return_value=json.dumps([self.assessment(intent)]))))
                with patch("app.services.recipe_verifier.budget_service", self.service):
                    checked = verifier.batch_verify_recipes([{**recipe(generated=True), **changes}], intent, aicr_service)
                self.assertTrue(checked[0]["verification_details"]["passes_verification"])
                final = self.service.annotate(checked, intent)[0]
                self.assertNotEqual(final["budget_assessment"]["status"], "estimated_within_budget")
                self.assertFalse(final["verification_details"]["passes_verification"])

    def test_budget_verification_cache_tracks_current_prices_in_both_paths(self):
        intent = self.intent()
        candidate = recipe(generated=True)
        verifier = RecipeVerifier()
        model = Mock(predict=Mock(return_value=json.dumps([self.assessment(intent)])))
        verifier.initialize(model)
        with patch("app.services.recipe_verifier.budget_service", self.service):
            first = verifier.batch_verify_recipes([copy.deepcopy(candidate)], intent, aicr_service)
            second = verifier.batch_verify_recipes([copy.deepcopy(candidate)], intent, aicr_service)
            self.assertEqual(first, second)
            self.assertEqual(model.predict.call_count, 1)
            changed = copy.deepcopy(CATALOG)
            changed["items"][1]["package_price"] = "20"
            self.path.write_text(json.dumps(changed))
            checked = verifier.batch_verify_recipes([copy.deepcopy(candidate)], intent, aicr_service)
            self.assertEqual(model.predict.call_count, 2)
            self.assertEqual(self.service.annotate(checked, intent)[0]["budget_assessment"]["status"], "over_budget")
            model.predict.return_value = json.dumps(self.assessment(intent))
            verifier.verify_recipe_against_constraints(candidate, intent)
            verifier.verify_recipe_against_constraints(candidate, intent)
            self.assertEqual(model.predict.call_count, 3)
            self.path.write_text(json.dumps(CATALOG))
            verifier.verify_recipe_against_constraints(candidate, intent)
            self.assertEqual(model.predict.call_count, 4)

    def test_budget_summary_is_calculated_not_invented_by_response_llm(self):
        intent = self.intent()
        generator = ResponseGenerator()
        generator.llm = Mock(predict=Mock(side_effect=AssertionError("Do not invent prices")))
        response = generator.generate_personalized_response("under $5", self.service.annotate([recipe()], intent), intent)
        self.assertIn("USD $1.40", response)
        self.assertIn("planning ceiling $1.68", response)
        self.assertIn("not guaranteed", response)

    def test_budget_summary_preserves_existing_patient_cautions(self):
        intent = self.intent()
        intent["constraints"].update(digestive_comfort="gentle", preparation_effort="low")
        response = ResponseGenerator().generate_personalized_response("under $5", self.service.annotate([recipe()], intent), intent)
        self.assertIn("Don't push through cooking", response)
        self.assertIn("can't keep fluids down", response)

    def test_more_suitable_higher_cost_recipe_keeps_its_relevance_rank(self):
        catalog = copy.deepcopy(CATALOG)
        catalog["items"][3]["package_price"] = "36"
        self.path.write_text(json.dumps(catalog))
        intent = self.intent("Dinner under $10")
        better_match = recipe("Requested Egg and Bean Dinner")
        better_match["ingredients"].append("2 eggs")
        cheaper = recipe("Basic Rice Bowl")
        candidates = self.service.annotate([better_match, cheaper], intent)
        self.assertEqual(candidates[0]["budget_assessment"]["estimate"], "7.40")
        self.assertEqual(candidates[0]["budget_assessment"]["planning_ceiling"], "8.88")
        self.assertEqual([candidate["name"] for candidate in self.service.rank(candidates)],
                         [better_match["name"], cheaper["name"]])
        self.assertEqual(self.service.rank(list(reversed(candidates)))[0]["name"], cheaper["name"])
        self.assertEqual(self.assess(limit="10", candidate={**recipe(), "ingredients": ["2000 g dry rice"]})["status"],
                         "estimated_within_budget")

    def test_diversity_uses_main_foods_and_method_not_names_or_oil(self):
        first = recipe("Rice Bowl")
        renamed = recipe("Protein Power Dinner")
        renamed["ingredients"].append("10 ml canola oil")
        steamed = {**recipe("Steamed Beans and Rice"), "instructions": ["Steam the rice and beans until fully cooked."]}
        with_eggs = recipe("Egg Rice Dinner")
        with_eggs["ingredients"].append("2 eggs")
        ranked = self.service.rank([first, renamed, steamed, with_eggs])
        self.assertEqual([candidate["name"] for candidate in ranked], [first["name"], steamed["name"], with_eggs["name"]])
        self.assertEqual(self.service.rank([first, renamed], {"query_type": "recipe_adaptation"}), [first, renamed])

    def test_more_budget_recipes_reject_renamed_meals_but_new_requests_do_not(self):
        intent = self.intent()
        intent["budget_previous_recipes"] = [recipe("Previously Shown")]
        repeated = {**recipe("New Name"), "verification_details": {"passes_verification": True, "relevance": "match"}}
        checked = self.service.annotate([repeated], intent)[0]
        self.assertEqual(checked["budget_assessment"]["status"], "estimated_within_budget")
        self.assertFalse(checked["verification_details"]["passes_verification"])
        self.assertIn("changing its name", checked["verification_details"]["constraint_violations"][-1])
        with patch("app.services.rag_service.budget_service", self.service):
            self.assertEqual(RecipeRAGService()._apply_deterministic_constraints([repeated], intent), [])
        self.assertTrue(self.service.annotate([repeated], self.intent())[0]["verification_details"]["passes_verification"])

    def test_budget_pipeline_variety_context_is_followup_only_and_repairs_duplicates(self):
        original_query = "Show meals under $5 for the whole recipe"
        history = [{"role": "user", "content": original_query},
                   {"role": "assistant", "content": "Here is a recipe.", "recipes": [recipe("Original Bowl")]}]
        for query, expected_calls in [("more recipes", 2), (original_query, 1)]:
            with self.subTest(query=query):
                intent = self.intent(original_query)
                intent["budget_previous_recipes"] = [recipe("Stale Context")]
                pipeline = self.configure_pipeline(intent, [], [])
                different = recipe("Egg and Bean Dinner", True)
                different["ingredients"].append("2 eggs")
                pipeline.recipe_enhancer.generate_fallback_recipes.side_effect = [
                    [recipe("Renamed Bowl", True)], [different],
                ]
                with patch("app.services.rag_service.budget_service", self.service), \
                        patch("app.services.rag_service.safety_service.should_intercept", return_value=False):
                    result = pipeline.ask_question(query, conversation_history=history)
                self.assertEqual(result["matches_found"], 1, result)
                self.assertEqual(pipeline.recipe_enhancer.generate_fallback_recipes.call_count, expected_calls)
                generation_intent = pipeline.recipe_enhancer.generate_fallback_recipes.call_args.args[1]
                if query == "more recipes":
                    self.assertEqual(generation_intent["budget_previous_recipes"][0]["name"], "Original Bowl")
                    self.assertEqual(result["source_documents"][0]["name"], different["name"])
                else:
                    self.assertNotIn("budget_previous_recipes", generation_intent)
                    self.assertEqual(result["source_documents"][0]["name"], "Renamed Bowl")

    def test_budget_prompt_preserves_patient_requirements_and_does_not_minimize_cost(self):
        intent = self.intent("A vegetarian dinner under $10")
        intent["constraints"].update(allergens_to_avoid=["soy"], time_max_minutes=20,
                                     chewing_effort="low", ingredients_must_use=["lentils"])
        intent["budget_price_options"] = self.service.options()
        intent["budget_previous_recipes"] = [recipe("Previous Bowl")]
        enhancer = RecipeEnhancer()
        prompt = enhancer._build_budget_generation_prompt("Dinner", intent, "Existing nutrition policy", [], [])
        for expected in ["soy", "lentils", "20", "chewing_effort", "Previous Bowl", "Existing nutrition policy",
                         "not the cheapest combination", "More expensive does not automatically mean better",
                         "do not assume everyone needs high fiber", "Do not rotate dish names"]:
            self.assertIn(expected, prompt)

    def test_budget_cannot_override_any_user_requirement_verification(self):
        intent = self.intent("Dinner under $10")
        intent["recipe_request"] = "A vegetarian dinner with beans, no eggs, under $10"
        intent["constraints"].update(ingredients_must_use=["beans"], dietary_restrictions=["vegetarian"],
                                     allergens_to_avoid=["eggs"], time_max_minutes=20)
        required = RecipeVerifier()._required_checks(intent)
        for key in ["recipe_request", "constraints.ingredients_must_use[0]", "constraints.dietary_restrictions",
                    "constraints.allergens_to_avoid", "constraints.time_max_minutes"]:
            with self.subTest(key=key):
                self.assertIn(key, required)
                verdict = self.assessment(intent)
                verdict["constraint_checks"][key] = {"status": "fail", "evidence": "Does not satisfy the requested requirement."}
                verifier = RecipeVerifier()
                verifier.initialize(Mock(predict=Mock(return_value=json.dumps([verdict]))))
                with patch("app.services.recipe_verifier.budget_service", self.service):
                    checked = verifier.batch_verify_recipes([recipe(generated=True)], intent, aicr_service)
                self.assertFalse(self.service.annotate(checked, intent)[0]["verification_details"]["passes_verification"])

    def test_expanded_catalog_is_priceable_without_equating_different_food_forms(self):
        path = Path(__file__).resolve().parents[1] / "app/data/ingredient_prices.json"
        service = BudgetService(path, today=lambda: date(2026, 11, 4))
        catalog = service.catalog()
        self.assertIsNotNone(catalog)
        self.assertEqual(len(catalog["items"]), 20)
        for item in catalog["items"]:
            with self.subTest(item=item["name"]):
                self.assertIsNotNone(service.parse_ingredient(f"1 {item['unit']} {item['name']}", catalog))
        for line in ["100 g cooked brown rice", "100 g gluten-free penne", "100 g shelf-stable tofu",
                     "100 g fresh chicken breast", "100 g cooked lentils", "2 pasteurized large eggs"]:
            self.assertIsNone(service.parse_ingredient(line, catalog), line)
        self.assertEqual({item["food_role"] for item in catalog["items"]}, {"protein", "grain", "vegetable", "oil", "seasoning"})
        dish = {"name": "Tofu and Vegetable Penne", "servings": 2,
                "ingredients": ["200 g refrigerated super-firm tofu", "150 g dry whole wheat penne",
                                "200 g frozen broccoli florets", "100 g fresh spinach", "10 ml canola oil", "2 g garlic powder"]}
        assessment = service.assess(dish, {"limit": "10", "currency": "USD", "basis": "recipe", "exclusive": True})
        self.assertEqual(assessment["status"], "estimated_within_budget")
        self.assertTrue(any("target.com" in line["source_url"] for line in assessment["line_items"]))
        self.assertTrue(any("walmart.com" in line["source_url"] for line in assessment["line_items"]))
