import copy
import json
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app.services.data_loader import DataLoader
from app.services.intent_analyzer import IntentAnalyzer
from app.services.preparation_validation import audit_preparation, explicit_preparation_constraints
from app.services.rag_service import RecipeRAGService
from app.services.recipe_prompt_rules import PREPARATION_RULES
from app.services.recipe_verifier import RecipeVerifier


class PreparationValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.loader = DataLoader()
        cls.loader.load_data(Path(__file__).parents[1] / "app/data/Recipe.csv")
        cls.service = RecipeRAGService()
        cls.service.data_loader = cls.loader

    def recipe(self, name):
        return self.service._build_recipe_data_from_record(self.loader.get_recipe_record(name))

    def assessment(self, constraints):
        required = RecipeVerifier()._required_checks({"constraints": constraints})
        return {
            "id": 0, "relevance": "match", "constraint_violations": [],
            "constraint_checks": {key: {"status": "pass", "evidence": "Model claims this matches."} for key in required},
            "preparation_check": {"conflicting_steps": [], "unresolved_dependencies": [], "conflicting_guidance": []},
            "frozen_ingredient_check": {"non_frozen_ingredients": [], "unspecified_forms": [], "conflicting_guidance": []},
            "time_check": {"total_minutes": 4, "evidence": [{"field": "total_time", "quote": "4 minutes"}]},
        }

    def verify(self, recipe, constraints, batch=False):
        verifier = RecipeVerifier()
        result = self.assessment(constraints)
        verifier.initialize(Mock(predict=Mock(return_value=json.dumps([result] if batch else result))))
        if batch:
            guidelines = Mock(validate_recipe_compliance=Mock(return_value={"overall_compliant": True}))
            return verifier.batch_verify_recipes([copy.deepcopy(recipe)], {"constraints": constraints}, guidelines)[0]["verification_details"]
        return verifier.verify_recipe_against_constraints(recipe, {"constraints": constraints})

    def test_pdf_prompts_normalize_even_when_intent_model_omits_constraints(self):
        examples = [
            ("Generate recipes that can be cooked cold or with no heat?", {"preparation_mode": "no_heat"}),
            ("Show recipe that takes less than 5 minutes.", {"time_max_minutes": 5, "time_limit_exclusive": True}),
            ("what meals require only assembling, not cooking?", {"preparation_mode": "assembly_only"}),
            ("what meals use frozen ingredients from start to finish?", {"ingredient_storage": "frozen_only"}),
            ("Show recipes that don’t splatter and steam", {"avoid_steam": True, "avoid_splatter": True}),
        ]
        for query, expected in examples:
            with self.subTest(query=query):
                analyzer = IntentAnalyzer()
                intent = analyzer._post_process_intent(query, analyzer._get_fallback_intent_data(query))
                for key, value in expected.items():
                    self.assertEqual(intent["constraints"][key], value)

    def test_cold_serving_and_some_frozen_ingredients_are_not_strict_preparation_rules(self):
        for query in ("Meals served cold", "Soup with frozen vegetables", "Cook the soup then serve cold"):
            self.assertEqual(explicit_preparation_constraints(query), {})

    def test_inclusive_exclusive_and_hour_limits(self):
        for query, minutes, exclusive in (("under 5 minutes", 5, True), ("5 minutes or less", 5, False),
                                          ("within 0.5 hours", 30, False), ("at most 1 hour", 60, False)):
            constraints = explicit_preparation_constraints(query)
            self.assertEqual(constraints["time_max_minutes"], minutes)
            self.assertEqual(constraints["time_limit_exclusive"], exclusive)

    def test_latest_request_can_relax_preparation_and_time_rules(self):
        analyzer = IntentAnalyzer()
        intent = analyzer._get_fallback_intent_data("more")
        intent = analyzer._post_process_intent("No heat and under 5 minutes", intent,
                                             current_query="Cooking is fine, within 20 minutes")
        self.assertIsNone(intent["constraints"]["preparation_mode"])
        self.assertEqual(intent["constraints"]["time_max_minutes"], 20)
        self.assertFalse(intent["constraints"]["time_limit_exclusive"])

    def test_same_chat_resolved_followup_preserves_no_heat(self):
        analyzer = IntentAnalyzer()
        intent = analyzer._post_process_intent("More no-heat meals", analyzer._get_fallback_intent_data("more"), current_query="more")
        self.assertEqual(intent["constraints"]["preparation_mode"], "no_heat")
        self.assertIn("ready-to-eat", intent["search_strategy"]["enhanced_query"])
        self.assertIsNone(analyzer._post_process_intent("Soup", analyzer._get_fallback_intent_data("Soup"))["constraints"]["preparation_mode"])

    def test_reported_database_recipes_rejected_despite_positive_model_verdict(self):
        cases = [
            ("Quick Eight- Vegetable Soup", {"preparation_mode": "no_heat"}),
            ("Turkey Fajitas with Baby Spinach and Red Peppers", {"preparation_mode": "assembly_only"}),
            ("Quick Eight- Vegetable Soup", {"ingredient_storage": "frozen_only"}),
            ("Brussels Sprouts with Balsamic Glaze", {"avoid_steam": True, "avoid_splatter": True}),
        ]
        for name, constraints in cases:
            recipe = self.recipe(name)
            self.assertTrue(recipe["ingredients"])
            for batch in (False, True):
                with self.subTest(name=name, batch=batch):
                    result = self.verify(recipe, constraints, batch)
                    self.assertFalse(result["passes_verification"])
                    self.assertEqual(result["relevance"], "adaptable")
                    self.assertTrue(result["constraint_violations"])

    def test_no_heat_rejects_heating_in_all_user_visible_guidance(self):
        for field in ("instructions", "helpful_tips", "ingredient_adaptations", "storage_instructions", "source_notes"):
            for line in ("Microwave for 1 minute.", "Use boiling water.", "Cook according to package directions.",
                         "No stove is needed, but heat in a microwave.", "Toast the bread, then chill."):
                with self.subTest(field=field, line=line):
                    recipe = {"ingredients": ["1 can beans"], "instructions": ["Drain and mix."]}
                    recipe[field] = [line] if field in {"instructions", "helpful_tips", "ingredient_adaptations"} else line
                    self.assertFalse(self.verify(recipe, {"preparation_mode": "no_heat"})["passes_verification"])

    def test_valid_no_heat_preparations_and_negated_instructions_pass(self):
        for instructions in (["Drain canned beans and mix with ready-to-eat cooked rice."],
                             ["Do not heat. Mix with canned beans and serve."],
                             ["Blend the yogurt and fruit. No cooking required."]):
            for source in ("database_exact", "llm_generated"):
                recipe = {"source": source, "ingredients": ["1 can beans"], "instructions": instructions}
                self.assertTrue(self.verify(recipe, {"preparation_mode": "no_heat"})["passes_verification"])

    def test_missing_assessment_or_unresolved_dependency_fails_closed(self):
        recipe = {"ingredients": ["1 cup rice"], "instructions": ["Mix and serve."]}
        constraints = {"preparation_mode": "assembly_only"}
        for check in (None, {}, {"conflicting_steps": [], "unresolved_dependencies": ["Rice not specified cooked"], "conflicting_guidance": []}):
            assessment = self.assessment(constraints)
            assessment["preparation_check"] = check
            self.assertTrue(audit_preparation(recipe, constraints, assessment))

    def test_mixed_frozen_forms_fail_and_explicit_frozen_forms_pass(self):
        constraints = {"ingredient_storage": "frozen_only"}
        for ingredient, valid in (("1 cup frozen corn", True), ("1 cup corn", False),
                                  ("1 cup fresh or frozen corn", False), ("1 cup freeze-dried fruit", False),
                                  ("1 tsp olive oil", False), ("1 cup canned beans", False)):
            recipe = {"ingredients": [ingredient], "instructions": ["Prepare according to package directions."]}
            self.assertEqual(self.verify(recipe, constraints)["passes_verification"], valid)

    def test_fifteen_minute_step_and_marinating_cannot_pass_five_minute_limit(self):
        constraints = {"time_max_minutes": 5, "time_limit_exclusive": True}
        for step in ("Cook for 15 minutes.", "Marinate for 20-30 minutes.", "Chill for 2 hours before serving."):
            recipe = {"ingredients": ["beans"], "total_time": "4 minutes", "instructions": [step]}
            for batch in (False, True):
                self.assertFalse(self.verify(recipe, constraints, batch)["passes_verification"])

    def test_sequential_times_cannot_be_reported_as_one_short_step(self):
        recipe = {"ingredients": ["beans"], "total_time": "4 minutes", "instructions": ["Chop for 3 minutes.", "Mix for 3 minutes."]}
        self.assertFalse(self.verify(recipe, {"time_max_minutes": 5})["passes_verification"])

    def test_parallel_steps_and_leftover_storage_do_not_inflate_prep_time(self):
        recipe = {"ingredients": ["beans"], "total_time": "4 minutes",
                  "instructions": ["Cook for 3 minutes.", "Meanwhile, chop for 2 minutes.", "Store leftovers for 48 hours."]}
        self.assertTrue(self.verify(recipe, {"time_max_minutes": 5})["passes_verification"])

    def test_strict_boundary_missing_and_invented_timing_fail(self):
        recipe = {"ingredients": ["beans"], "total_time": "4 minutes", "instructions": ["Mix and serve."]}
        self.assertTrue(self.verify(recipe, {"time_max_minutes": 4})["passes_verification"])
        self.assertFalse(self.verify(recipe, {"time_max_minutes": 4, "time_limit_exclusive": True})["passes_verification"])
        del recipe["total_time"]
        self.assertFalse(self.verify(recipe, {"time_max_minutes": 5})["passes_verification"])
        self.assertTrue(audit_preparation(recipe, {"time_max_minutes": 5}, {}))

    def test_source_total_time_cannot_be_overridden_by_optimistic_model(self):
        recipe = {"ingredients": ["beans"], "total_time": "4 minutes", "source_notes": "Servings 4 | Total Time 25 min | Tips",
                  "instructions": ["Mix and serve."]}
        self.assertFalse(self.verify(recipe, {"time_max_minutes": 5})["passes_verification"])

    def test_unrestricted_requests_keep_existing_verification_behavior(self):
        self.assertTrue(self.verify(self.recipe("Quick Eight- Vegetable Soup"), {})["passes_verification"])

    def test_cooking_tip_labels_are_not_cooking_requirements(self):
        recipe = {"ingredients": ["1 can beans"], "instructions": ["Mix and serve."],
                  "source_notes": "Cooking Tip: Use a large bowl. Cooking is not required."}
        self.assertTrue(self.verify(recipe, {"preparation_mode": "no_heat"})["passes_verification"])

    def test_overnight_and_while_stirring_do_not_bypass_time_check(self):
        for steps in (["Chill overnight before serving."], ["Cook for 3 minutes while stirring.", "Cook for 3 more minutes."]):
            recipe = {"ingredients": ["beans"], "total_time": "4 minutes", "instructions": steps}
            self.assertFalse(self.verify(recipe, {"time_max_minutes": 5})["passes_verification"])

    def test_non_numeric_time_constraint_fails_closed(self):
        self.assertTrue(audit_preparation({}, {"time_max_minutes": "five"}, {}))

    def test_detailed_batches_keep_one_assessment_per_recipe_in_order(self):
        constraints = {"preparation_mode": "no_heat"}
        verifier = RecipeVerifier()
        verifier.initialize(Mock(predict=Mock(return_value=json.dumps([self.assessment(constraints)]))))
        recipes = [{"name": f"Bowl {index}", "ingredients": ["1 can beans"], "instructions": ["Drain and mix."]} for index in range(3)]
        guidelines = Mock(validate_recipe_compliance=Mock(return_value={"overall_compliant": True}))
        result = verifier.batch_verify_recipes(recipes, {"constraints": constraints}, guidelines)
        self.assertEqual([recipe["name"] for recipe in result], [recipe["name"] for recipe in recipes])
        self.assertTrue(all(recipe["verification_details"]["passes_verification"] for recipe in result))
        self.assertEqual(verifier.llm.predict.call_count, 3)

    def test_shared_rules_reach_both_verification_prompts_and_intent(self):
        verifier = RecipeVerifier()
        intent = {"constraints": {"preparation_mode": "no_heat"}}
        self.assertIn(PREPARATION_RULES, verifier._build_batch_verification_prompt([], intent))
        self.assertIn(PREPARATION_RULES, verifier._build_individual_verification_prompt({}, intent))
        self.assertIn(PREPARATION_RULES, IntentAnalyzer()._build_intent_prompt("no heat"))

    def routing_service(self, candidates):
        constraints = {"preparation_mode": "no_heat"}
        service = RecipeRAGService()
        service.is_initialized = True
        service._contains_phi_like_content = Mock(return_value=False)
        service.intent_analyzer.understand_query_intent_with_context = Mock(return_value={
            "query_type": "recipe_search", "constraints": constraints, "preferences": {}, "search_strategy": {},
        })
        service.search_engine.multi_query_search = Mock(return_value=candidates)
        service.search_engine.rerank_with_constraint_filtering = Mock(side_effect=lambda recipes, *args, **kwargs: recipes)
        service._build_recipe_data_from_doc = Mock(side_effect=copy.deepcopy)
        service._get_database_search_candidates = Mock(return_value=[])
        service.recipe_enhancer.prepare_recipes_for_verification = Mock(side_effect=lambda recipes, intent: recipes)
        service.recipe_enhancer.batch_enhance_recipes = Mock(side_effect=lambda recipes, intent: recipes)
        service.recipe_enhancer.generate_fallback_recipes = Mock(return_value=[])
        assessment = self.assessment(constraints)
        assessment["constraint_checks"]["recipe_request"] = {"status": "pass", "evidence": "Model claims the no-heat preparation matches."}
        service.recipe_verifier.initialize(Mock(predict=Mock(return_value=json.dumps([assessment]))))
        service.response_generator.generate_personalized_response = Mock(return_value="Recipes ready.")
        return service

    def test_real_verifier_keeps_database_first_and_excludes_stove_soup(self):
        soup = self.recipe("Quick Eight- Vegetable Soup")
        salad = self.recipe("Chickpea Salad with Tomatoes and Cucumber")
        service = self.routing_service([soup, salad])
        with patch("app.services.rag_service.aicr_service") as guidelines:
            guidelines.validate_recipe_compliance.return_value = {"overall_compliant": True}
            result = service.ask_question("Show no-heat recipes")
        self.assertEqual([recipe["name"] for recipe in result["source_documents"]], [salad["name"]])
        self.assertEqual(result["source_documents"][0]["source_label"], "Sourced from AHA")
        service.recipe_enhancer.generate_fallback_recipes.assert_not_called()

    def test_generated_heating_recipe_retries_with_database_context(self):
        soup = self.recipe("Quick Eight- Vegetable Soup")
        service = self.routing_service([soup])
        invalid = {"name": "Chilled Soup", "generated_by_llm": True, "ingredients": ["1 can beans"],
                   "instructions": ["Simmer the beans, then chill."]}
        valid = {"name": "Ready-to-Eat Bean Bowl", "generated_by_llm": True, "ingredients": ["1 can beans", "1 can ready-to-eat vegetables"],
                 "instructions": ["Drain the beans and mix with ready-to-eat canned vegetables."]}
        service.recipe_enhancer.generate_fallback_recipes.side_effect = [[invalid], [valid]]
        with patch("app.services.rag_service.aicr_service") as guidelines:
            guidelines.validate_recipe_compliance.return_value = {"overall_compliant": True}
            result = service.ask_question("Show no-heat recipes")
        self.assertEqual([recipe["name"] for recipe in result["source_documents"]], [valid["name"]])
        self.assertEqual(result["source_documents"][0]["source_label"], "AI Generated")
        self.assertEqual(service.recipe_enhancer.generate_fallback_recipes.call_count, 2)
        for call in service.recipe_enhancer.generate_fallback_recipes.call_args_list:
            self.assertEqual(call.kwargs["grounding_recipes"][0]["name"], soup["name"])


if __name__ == "__main__":
    unittest.main()
