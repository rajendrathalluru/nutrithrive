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
         "package_price": "5", "source_url": "https://example.com/oil"},
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

    def test_money_extraction_does_not_confuse_time_or_ingredient_count(self):
        for query in ["under $5", "under 5 dollars", "under five dollars", "under US$5"]:
            with self.subTest(query=query):
                self.assertEqual(self.intent(query)["budget_request"]["limit"], "5")
                self.assertTrue(self.intent(query)["budget_request"]["exclusive"])
        for query in ["under 5 minutes", "only 5 ingredients", "make dinner for 5 people", "recipes with 5 pounds of chicken"]:
            self.assertNotIn("budget_request", self.intent(query))
        self.assertFalse(self.intent("at most $5")["budget_request"]["exclusive"])
        self.assertEqual(self.intent("under $5 with oil that costs $10")["budget_request"]["limit"], "5")

    def test_ambiguous_budget_asks_cost_basis_and_followup_resolves_it(self):
        first = "Show meals under $5"
        self.assertIn("per serving", budget_clarification(self.intent(first)))
        followup = self.intent("Whole recipe", [{"role": "user", "content": first}])
        self.assertEqual(followup["budget_request"]["basis"], "recipe")
        self.assertFalse(budget_clarification(followup))
        self.assertIn("maximum food budget", budget_clarification(self.intent("affordable meals")))

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
                           {"role": "assistant", "content": budget_clarification(self.intent(first))}]
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

    def test_ranking_prefers_fewer_purchases_without_imposing_a_hard_count_limit(self):
        intent = self.intent()
        simple = recipe("Simple Bowl")
        more = recipe("Bowl with Oil")
        more["ingredients"].append("1 tbsp canola oil")
        ranked = self.service.rank(self.service.annotate([more, simple], intent))
        self.assertEqual([item["name"] for item in ranked], ["Simple Bowl", "Bowl with Oil"])
        self.assertEqual(len(ranked), 2)

    def assessment(self, intent):
        return {"id": 0, "relevance": "match", "constraint_violations": [],
                "budget_recipe_check": {"status": "pass", "evidence": "All ingredients are listed, and the two servings are realistic."},
                "guideline_checks": passing_guideline_checks(),
                "constraint_checks": {key: {"status": "pass", "evidence": "Matches actual ingredients and preparation."}
                                      for key in RecipeVerifier()._required_checks(intent)}}

    def test_existing_guideline_and_completeness_checks_cannot_be_overridden_by_cheap_price(self):
        intent = self.intent()
        for category in ["food_safety", "nutrition", "symptom_suitability", "completeness"]:
            verification = self.assessment(intent)
            if category == "completeness":
                verification.pop("budget_recipe_check")
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
        self.assertIn("budget_recipe_check", prompt)
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
        pipeline = self.configure_pipeline(self.intent(), [recipe(f"Bowl {index}") for index in range(5)], [])
        result = self.ask(pipeline)
        self.assertEqual(len(result["source_documents"]), 3)
        for candidate in result["source_documents"]:
            self.assertEqual(candidate["source_name"], "AICR")
            self.assertEqual(candidate["recipe_link"], "https://example.com/recipe")
            self.assertEqual(candidate["budget_assessment"]["status"], "estimated_within_budget")

    def test_ambiguous_budget_and_missing_catalog_do_not_trigger_generation(self):
        for intent, missing in [(self.intent("meals under $5"), False), (self.intent(), True)]:
            if missing:
                self.path.unlink()
            pipeline = self.configure_pipeline(intent, [], [])
            result = self.ask(pipeline)
            self.assertEqual(result["source_documents"], [])
            pipeline.search_engine.multi_query_search.assert_not_called()
            pipeline.recipe_enhancer.generate_fallback_recipes.assert_not_called()

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
