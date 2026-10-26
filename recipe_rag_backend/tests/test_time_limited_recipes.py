import copy
import json
import unittest
from guideline_fixtures import passing_guideline_checks
from pathlib import Path
from unittest.mock import Mock

from app.services.aicr_guidelines_service import aicr_service
from app.services.data_loader import DataLoader
from app.services.intent_analyzer import IntentAnalyzer
from app.services.preparation_validation import declared_time_check, time_candidate_rank
from app.services.rag_service import RecipeRAGService
from app.services.recipe_enhancer import RecipeEnhancer
from app.services.recipe_verifier import RecipeVerifier
from app.services.response_generator import ResponseGenerator


QUERIES = (
    "Show recipes that take less than 5 minutes  to make",
    "Help me to prepare recipes that take less than 5 minutes",
)


def timed_recipe(minutes=3):
    return {
        "name": "Yogurt and Banana Bowl", "type": "Breakfast", "calories": 240,
        "ingredients": ["1 cup pasteurized plain Greek yogurt", "1 banana", "1 tbsp smooth peanut butter"],
        "instructions": [
            "Open and measure the yogurt and peanut butter into a bowl: 1 minute.",
            "Peel and slice the banana: 1 minute.",
            "Stir the peanut butter into the yogurt, top with banana and serve: 1 minute.",
        ],
        "total_time": f"Estimated total time: {minutes} minutes", "generated_by_llm": True,
    }


class TimeLimitedRecipeTests(unittest.TestCase):
    def intent(self, query=QUERIES[0]):
        analyzer = IntentAnalyzer()
        return analyzer._post_process_intent(query, analyzer._get_fallback_intent_data(query))

    def assessment(self, intent):
        return {
            "id": 0, "relevance": "match", "constraint_violations": [],
            "guideline_checks": passing_guideline_checks(),
            "constraint_checks": {
                key: {"status": "pass", "evidence": "The stated total and complete steps fit the request."}
                for key in RecipeVerifier()._required_checks(intent)
            },
        }

    def verify(self, recipe, intent=None, assessment=None):
        intent = intent or self.intent()
        assessment = assessment if assessment is not None else self.assessment(intent)
        verifier = RecipeVerifier()
        verifier.initialize(Mock(predict=Mock(return_value=json.dumps([assessment]))))
        return verifier.batch_verify_recipes([copy.deepcopy(recipe)], intent, aicr_service)[0]

    def test_reported_phrasings_keep_the_same_strict_boundary(self):
        for query in QUERIES:
            intent = self.intent(query)
            self.assertEqual(intent["constraints"]["time_max_minutes"], 5)
            self.assertTrue(intent["constraints"]["time_limit_exclusive"])

    def test_reported_thirty_minute_limit_and_other_budgets(self):
        for minutes in (5, 15, 30, 45, 60):
            with self.subTest(minutes=minutes):
                inclusive = self.intent(f"show recipes that take {minutes} minutes or less")
                exclusive = self.intent(f"show recipes that take less than {minutes} minutes")
                self.assertEqual(inclusive["constraints"]["time_max_minutes"], minutes)
                self.assertTrue(self.verify(timed_recipe(minutes), inclusive)["verification_details"]["passes_verification"])
                self.assertFalse(self.verify(timed_recipe(minutes), exclusive)["verification_details"]["passes_verification"])

    def test_database_rescue_prioritizes_documented_total_times(self):
        service = RecipeRAGService()
        service.data_loader.load_data(Path(__file__).parents[1] / "app/data/Recipe.csv")
        query = "show recipes that take 30 minutes or less"
        intent = self.intent(query)
        candidates = service._get_database_search_candidates(query, intent, set(), 8)
        self.assertEqual(len(candidates), 8)
        self.assertTrue(all(time_candidate_rank(recipe, intent["constraints"]) == 2 for recipe in candidates))
        excluded = candidates[0]["recipe_id"]
        next_candidates = service._get_database_search_candidates(query, intent, {excluded}, 8)
        self.assertNotIn(excluded, [recipe["recipe_id"] for recipe in next_candidates])

    def test_time_ranking_respects_exclusive_boundaries_without_accepting_recipes(self):
        for query, expected in (("30 minutes or less", 2), ("under 30 minutes", 0)):
            self.assertEqual(time_candidate_rank(timed_recipe(30), self.intent(query)["constraints"]), expected)
        self.assertEqual(time_candidate_rank({}, self.intent()["constraints"]), 1)
        self.assertEqual(time_candidate_rank(timed_recipe(30), {}), 0)

    def test_generated_steps_need_timings_without_requiring_new_source_metadata(self):
        recipe = timed_recipe(10)
        recipe["instructions"].insert(0, "Gather ingredients and wash the bowl.")
        intent = self.intent("30 minutes or less")
        self.assertFalse(self.verify(recipe, intent)["verification_details"]["passes_verification"])
        recipe["generated_by_llm"] = False
        self.assertTrue(self.verify(recipe, intent)["verification_details"]["passes_verification"])

    def test_parallel_steps_do_not_erase_later_sequential_time(self):
        recipe = timed_recipe(30)
        recipe["instructions"] = [
            "Prepare the vegetables for 10 minutes.", "Cook rice for 20 minutes.",
            "Meanwhile, mix the dressing for 5 minutes.", "Assemble and serve for 5 minutes.",
        ]
        self.assertFalse(self.verify(recipe, self.intent("30 minutes or less"))["verification_details"]["passes_verification"])

    def test_per_side_and_sequential_times_within_one_step_are_counted(self):
        for step in ("Cook for 16 minutes on each side.", "Cook for 20 minutes, then rest for 15 minutes.",
                     "Cook for 15 minutes per side, then rest for 2 minutes.",
                     "Chill for 1 hour and 5 minutes."):
            recipe = timed_recipe(30)
            recipe["instructions"] = [step]
            self.assertFalse(self.verify(recipe, self.intent("30 minutes or less"))["verification_details"]["passes_verification"])

    def test_time_pass_cannot_override_failed_or_missing_guideline_review(self):
        for category in ("food_safety", "nutrition", "symptom_suitability"):
            for check in (None, {"status": "unknown", "evidence": "Preparation cannot be established."},
                          {"status": "fail", "evidence": "Conflicts with configured policy."}, {"status": "pass"}):
                assessment = self.assessment(self.intent())
                assessment["guideline_checks"][category] = check
                result = self.verify(timed_recipe(), assessment=assessment)["verification_details"]
                self.assertFalse(result["passes_verification"])
                self.assertTrue(any("guideline" in violation.lower() for violation in result["constraint_violations"]))

    def test_individual_verification_enforces_the_same_guideline_review(self):
        verifier = RecipeVerifier()
        assessment = self.assessment(self.intent())
        assessment.pop("guideline_checks")
        verifier.initialize(Mock(predict=Mock(return_value=json.dumps(assessment))))
        result = verifier.verify_recipe_against_constraints(timed_recipe(), self.intent())
        self.assertFalse(result["passes_verification"])

    def test_full_policy_reaches_verification_and_generation(self):
        intent = self.intent("30 minutes or less")
        policy = aicr_service.get_verification_policy(intent)
        self.assertIn("proper_storage", policy["food_safety"])
        self.assertIn("internal_temps", policy["food_safety"]["cook_thoroughly"])
        self.assertEqual(policy["symptom_suitability"], {})
        verifier = RecipeVerifier()
        for prompt in (verifier._build_batch_verification_prompt([], intent),
                       verifier._build_individual_verification_prompt(timed_recipe(), intent)):
            self.assertIn("guideline_checks", prompt)
            self.assertIn("proper_storage", prompt)
            self.assertIn("not a mandatory 20-30g", prompt)
            self.assertIn("official AICR/AHA/ACS certification", prompt)
        enhancer = RecipeEnhancer()
        model = Mock(predict=Mock(return_value=json.dumps([timed_recipe()])))
        enhancer.initialize(model, aicr_service)
        enhancer.generate_fallback_recipes("30 minutes or less", intent, [])
        self.assertIn("165", model.predict.call_args.args[0])
        self.assertIn("raw sprouts", model.predict.call_args.args[0])

    def test_explicit_total_provides_real_citation_when_model_omits_time_check(self):
        recipe = self.verify(timed_recipe())
        details = recipe["verification_details"]
        self.assertTrue(details["passes_verification"])
        self.assertEqual(details["time_check"], {
            "total_minutes": 3,
            "evidence": [{"field": "total_time", "quote": "Estimated total time: 3 minutes"}],
        })

    def test_exactly_five_minutes_is_rejected_even_with_positive_model_checks(self):
        result = self.verify(timed_recipe(5))["verification_details"]
        self.assertFalse(result["passes_verification"])
        self.assertEqual(result["relevance"], "adaptable")
        self.assertTrue(any("requested limit" in reason for reason in result["constraint_violations"]))

    def test_inclusive_boundary_allows_five_minutes(self):
        result = self.verify(timed_recipe(5), self.intent("5 minutes or less"))
        self.assertTrue(result["verification_details"]["passes_verification"])

    def test_declared_totals_support_seconds_ranges_and_compound_units(self):
        for text, expected in (("180 seconds", 3), ("3-4 minutes", 4), ("4 minutes 30 seconds", 4.5),
                               ("Total time: 1 hour and 5 minutes", 65), ("Estimated total time: 3 minutes", 3)):
            with self.subTest(text=text):
                self.assertEqual(declared_time_check({"total_time": text})["total_minutes"], expected)

    def test_ambiguous_totals_and_partial_cooking_times_are_not_invented(self):
        for text in ("quick", "about five", "5", "3 minutes per batch", "3 minutes plus chilling", "-3 minutes"):
            self.assertIsNone(declared_time_check({"total_time": text}))
        recipe = timed_recipe()
        recipe.pop("total_time")
        recipe["instructions"] = ["Blend for 1 minute."]
        recipe["description"] = "Quick and easy!"
        self.assertFalse(self.verify(recipe)["verification_details"]["passes_verification"])

    def test_source_total_is_preserved_and_cannot_be_lowered_by_ai_assessment(self):
        recipe = timed_recipe()
        recipe["source_notes"] = "Servings 2 | Total Time 5 min | A source tip"
        result = self.verify(recipe)["verification_details"]
        self.assertEqual(result["time_check"]["total_minutes"], 5)
        self.assertFalse(result["passes_verification"])

    def test_explicit_model_contradiction_is_not_replaced_with_optimistic_metadata(self):
        assessment = self.assessment(self.intent())
        assessment["time_check"] = {"total_minutes": 6, "evidence": []}
        self.assertFalse(self.verify(timed_recipe(), assessment=assessment)["verification_details"]["passes_verification"])
        assessment["time_check"] = {"total_minutes": None, "evidence": []}
        self.assertFalse(self.verify(timed_recipe(), assessment=assessment)["verification_details"]["passes_verification"])

    def test_independent_total_check_rejects_citing_only_a_short_step(self):
        assessment = self.assessment(self.intent())
        recipe = timed_recipe(6)
        assessment["time_check"] = {
            "total_minutes": 3, "evidence": [{"field": "instructions", "index": 0, "quote": "1 minute"}],
        }
        self.assertFalse(self.verify(recipe, assessment=assessment)["verification_details"]["passes_verification"])

    def test_backend_cites_exact_metadata_instead_of_requiring_model_to_copy_its_format(self):
        recipe = timed_recipe(4)
        recipe["total_time"] = "4 minutes"
        assessment = self.assessment(self.intent())
        assessment["time_check"] = {
            "total_minutes": 4,
            "evidence": [{"field": "total_time", "index": None, "quote": "Total time: 4 minutes"}],
        }
        details = self.verify(recipe, assessment=assessment)["verification_details"]
        self.assertTrue(details["passes_verification"])
        self.assertEqual(details["time_check"]["evidence"], [{"field": "total_time", "quote": "4 minutes"}])

    def test_missing_recipe_timing_cannot_be_repaired_from_a_model_only_claim(self):
        recipe = timed_recipe(4)
        recipe.pop("total_time")
        assessment = self.assessment(self.intent())
        assessment["time_check"] = {
            "total_minutes": 4, "evidence": [{"field": "total_time", "quote": "4 minutes"}],
        }
        self.assertFalse(self.verify(recipe, assessment=assessment)["verification_details"]["passes_verification"])

    def test_total_does_not_override_long_steps_or_failed_dietary_checks(self):
        recipe = timed_recipe()
        recipe["instructions"].append("Chill for 20 minutes before serving.")
        self.assertFalse(self.verify(recipe)["verification_details"]["passes_verification"])
        intent = self.intent()
        intent["constraints"]["allergens_to_avoid"] = ["peanuts"]
        assessment = self.assessment(intent)
        assessment["constraint_checks"]["constraints.allergens_to_avoid"] = {
            "status": "fail", "evidence": "Contains peanut butter.",
        }
        self.assertFalse(self.verify(timed_recipe(), intent, assessment)["verification_details"]["passes_verification"])

    def test_generation_keeps_one_complete_timed_recipe_and_explicit_budget(self):
        model = Mock(predict=Mock(return_value=json.dumps([timed_recipe(), timed_recipe(4)])))
        enhancer = RecipeEnhancer()
        enhancer.initialize(model, aicr_service)
        recipes = enhancer.generate_fallback_recipes(QUERIES[0], self.intent(), [])
        self.assertEqual(len(recipes), 1)
        self.assertEqual(recipes[0]["total_time"], timed_recipe()["total_time"])
        prompt = model.predict.call_args.args[0]
        self.assertIn("strictly less than 5 minutes (300 seconds)", prompt)
        self.assertIn("Exactly 5 minutes does NOT qualify", prompt)
        self.assertIn("exactly ONE complete recipe", prompt)
        self.assertIn("do not merely relabel a slower recipe", prompt)

    def test_repair_prompt_includes_original_time_and_strict_budget(self):
        rejected = timed_recipe(5)
        rejected["verification_details"] = {"passes_verification": False, "constraint_violations": ["Time limit exceeded"]}
        model = Mock(predict=Mock(return_value=json.dumps([timed_recipe()])))
        enhancer = RecipeEnhancer()
        enhancer.initialize(model, aicr_service)
        enhancer.generate_fallback_recipes(QUERIES[0], self.intent(), [rejected])
        prompt = model.predict.call_args.args[0]
        self.assertIn("Repair ONE rejected recipe", prompt)
        self.assertIn("Estimated total time: 5 minutes", prompt)
        self.assertIn("Exactly 5 minutes does NOT qualify", prompt)

    def test_unrestricted_generation_keeps_existing_batch_size(self):
        enhancer = RecipeEnhancer()
        enhancer.initialize(Mock(predict=Mock(return_value=json.dumps([timed_recipe()] * 3))), aicr_service)
        self.assertEqual(len(enhancer.generate_fallback_recipes("Breakfast recipes", {}, [])), 3)

    def test_structured_fallback_preserves_timing_as_metadata_not_a_cooking_step(self):
        response = """RECIPE_NAME: Yogurt and Banana Bowl
RECIPE_TYPE: Breakfast
INGREDIENTS:
- 1 cup pasteurized Greek yogurt
- 1 banana
COOKING_INSTRUCTIONS:
Estimated total time: 3 minutes
1. Open and measure yogurt into a bowl: 1 minute.
2. Peel and slice the banana: 1 minute.
3. Top yogurt with banana and serve: 1 minute.
INGREDIENT_MODIFICATIONS:
HELPFUL_TIPS:
"""
        enhancer = RecipeEnhancer()
        enhancer.initialize(Mock(predict=Mock(return_value=response)), aicr_service)
        recipes = enhancer.generate_structured_fallback_recipe(QUERIES[0], self.intent())
        self.assertEqual(recipes[0]["total_time"], "Estimated total time: 3 minutes")
        self.assertEqual(len(recipes[0]["instructions"]), 3)
        self.assertTrue(self.verify(recipes[0])["verification_details"]["passes_verification"])

    def test_guidance_does_not_rewrite_existing_database_timing(self):
        recipe = timed_recipe(5)
        recipe["generated_by_llm"] = False
        enhancer = RecipeEnhancer()
        enhancer.initialize(Mock(predict=Mock(return_value="""COOKING_INSTRUCTIONS:
Estimated total time: 3 minutes
1. Mix ingredients for 3 minutes.
INGREDIENT_MODIFICATIONS:
HELPFUL_TIPS:
""")), aicr_service)
        enhanced = enhancer.enhance_single_recipe(recipe, self.intent())
        self.assertEqual(enhanced["total_time"], recipe["total_time"])
        self.assertEqual(enhanced["instructions"], recipe["instructions"])

    def routing_service(self, query, database_recipes, generated_recipes):
        service = RecipeRAGService()
        service.is_initialized = True
        service._contains_phi_like_content = Mock(return_value=False)
        intent = self.intent(query)
        intent["recipe_request"] = query
        service.intent_analyzer.understand_query_intent_with_context = Mock(return_value=intent)
        service.search_engine.multi_query_search = Mock(return_value=database_recipes)
        service.search_engine.rerank_with_constraint_filtering = Mock(side_effect=lambda recipes, *args, **kwargs: recipes)
        service._build_recipe_data_from_doc = Mock(side_effect=copy.deepcopy)
        service._get_database_search_candidates = Mock(return_value=[])
        generations = iter(generated_recipes)

        def response(prompt):
            if prompt.startswith("Generate COMPLETE recipe enhancement"):
                return "INGREDIENTS:\nCOOKING_INSTRUCTIONS:\nINGREDIENT_MODIFICATIONS:\nHELPFUL_TIPS:"
            return json.dumps(next(generations))

        service.recipe_enhancer.initialize(Mock(predict=Mock(side_effect=response)), aicr_service)
        service.recipe_verifier.initialize(Mock(predict=Mock(return_value=json.dumps([self.assessment(intent)]))))
        return service

    def test_pipeline_returns_verified_ai_recipe_when_no_database_match_exists(self):
        for query in (*QUERIES, "show recipes that take 30 minutes or less"):
            service = self.routing_service(query, [], [[timed_recipe()]])
            result = service.ask_question(query)
            self.assertEqual(result["matches_found"], 1)
            self.assertEqual(result["source_documents"][0]["source_label"], "AI Generated")
            self.assertEqual(result["source_documents"][0]["generation_basis"], "ai_only")
            self.assertIn("approximately 3 minutes total", result["response"])

    def test_failed_guideline_check_reaches_repair_and_is_reverified(self):
        query = "show recipes that take 30 minutes or less"
        service = self.routing_service(query, [], [[timed_recipe()], [timed_recipe()]])
        accepted = self.assessment(self.intent(query))
        accepted["constraint_checks"]["recipe_request"] = {"status": "pass", "evidence": "Complete three-minute preparation."}
        rejected = copy.deepcopy(accepted)
        rejected["guideline_checks"]["food_safety"] = {"status": "fail", "evidence": "Unsafe storage advice needs correction."}
        service.recipe_verifier.llm.predict.side_effect = [json.dumps([rejected]), json.dumps([accepted])]
        service._enhance_verified_recipes = Mock(side_effect=lambda recipes, intent: recipes)
        result = service.ask_question(query)
        self.assertEqual(result["matches_found"], 1)
        self.assertIn("Unsafe storage advice", service.recipe_enhancer.llm.predict.call_args.args[0])
        self.assertEqual(result["source_documents"][0]["verification_details"]["guideline_checks"]["food_safety"]["status"], "pass")

    def test_pipeline_repairs_excluded_boundary_using_database_context(self):
        loader = DataLoader()
        loader.load_data(Path(__file__).parents[1] / "app/data/Recipe.csv")
        database_recipe = RecipeRAGService()._build_recipe_data_from_record(loader.get_recipe_record("Hummus"))
        service = self.routing_service(QUERIES[0], [database_recipe], [[timed_recipe(5)], [timed_recipe()]])
        result = service.ask_question(QUERIES[0])
        self.assertEqual(result["matches_found"], 1)
        recipe = result["source_documents"][0]
        self.assertEqual(recipe["source_label"], "AI Generated")
        self.assertEqual(recipe["generation_basis"], "database_guided")
        self.assertEqual(recipe["reference_sources"][0]["name"], "Hummus")
        self.assertTrue(any("Repair ONE" in call.args[0] for call in service.recipe_enhancer.llm.predict.call_args_list))

    def test_source_recipe_remains_first_choice_when_inclusive_time_allows_it(self):
        loader = DataLoader()
        loader.load_data(Path(__file__).parents[1] / "app/data/Recipe.csv")
        database_recipe = RecipeRAGService()._build_recipe_data_from_record(loader.get_recipe_record("Hummus"))
        service = self.routing_service("5 minutes or less", [database_recipe], [])
        service.recipe_enhancer.generate_fallback_recipes = Mock(side_effect=AssertionError("Database match must take priority"))
        result = service.ask_question("5 minutes or less")
        self.assertEqual([recipe["name"] for recipe in result["source_documents"]], ["Hummus"])
        self.assertEqual(result["source_documents"][0]["source_label"], "Sourced from AHA")
        self.assertTrue(result["source_documents"][0]["recipe_link"])

    def test_timing_summary_uses_verified_duration_without_another_model_call(self):
        recipe = self.verify(timed_recipe())
        generator = ResponseGenerator()
        generator.initialize(Mock())
        response = generator.generate_personalized_response(QUERIES[0], [recipe], self.intent())
        self.assertIn("approximately 3 minutes total", response)
        generator.llm.predict.assert_not_called()

    def test_no_results_explains_verification_instead_of_blame_on_phrasing(self):
        response = ResponseGenerator().generate_helpful_no_results_message(QUERIES[0], self.intent())
        self.assertIn("less than 5 minutes", response)
        self.assertIn("Your request is clear", response)
        self.assertNotIn("rephras", response)


if __name__ == "__main__":
    unittest.main()
