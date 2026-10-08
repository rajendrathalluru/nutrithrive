import copy
import csv
import json
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app.services.intent_analyzer import IntentAnalyzer
from app.services.rag_service import RecipeRAGService
from app.services.recipe_enhancer import RecipeEnhancer
from app.services.recipe_prompt_rules import CHEWING_RULES
from app.services.recipe_verifier import RecipeVerifier
from app.services.response_generator import ResponseGenerator


QUERY = "What meals can I make that don’t require much chewing?"
INTENT = {"constraints": {"chewing_effort": "low"}, "preferences": {}, "search_strategy": {}}
SOUP = {
    "recipe_id": "carrot-soup", "name": "Carrot Soup", "type": "Main Dish",
    "ingredients": ["2 cups carrots", "2 cups vegetable broth"],
    "instructions": ["Simmer the carrots in broth until soft.", "Blend the entire soup until smooth."],
    "description": "A vegetable soup.", "database_record_found": True,
    "source_name": "AHA", "recipe_link": "https://example.com/carrot-soup",
}


def citation(field, index, quote):
    return {"field": field, "index": index, "quote": quote}


def model_pass(recipe, intent=INTENT):
    instructions = recipe.get("instructions", [])
    evidence = [citation("instructions", index, step) for index, step in enumerate(instructions)]
    return {
        "id": recipe.get("id", 0), "relevance": "match", "constraint_violations": [],
        "constraint_checks": {
            key: {"status": "pass", "evidence": "Model claims the recipe is suitable."}
            for key in RecipeVerifier()._required_checks(intent)
        },
        "chewing_check": {
            "components": [
                {"ingredient_index": index, "status": "pass", "evidence": evidence}
                for index in range(len(recipe.get("ingredients", [])))
            ],
            "serving_evidence": evidence[-1:], "conflicting_guidance": [],
        },
    }


class ChewingIntentTests(unittest.TestCase):
    def test_explicit_requests_survive_missing_model_fields(self):
        for query in (QUERY, "Meals without much chewing", "Easy-to-chew dinner", "Soft food recipes",
                      "I have difficulty chewing", "Meals requiring minimal chewing"):
            with self.subTest(query=query):
                intent = IntentAnalyzer()._post_process_intent(query, {})
                self.assertEqual(intent["constraints"]["chewing_effort"], "low")
                self.assertIn("pureed soup", intent["search_strategy"]["search_keywords"])
                self.assertIn("low chewing effort", intent["search_strategy"]["enhanced_query"])
                self.assertEqual(intent["cancer_patient_specific"]["symptoms"], [])
                self.assertIsNone(intent["constraints"]["attention_level"])
                self.assertFalse(intent["constraints"]["leftover_friendly"])

    def test_unrelated_requests_and_negations_do_not_acquire_low_chewing(self):
        for query in ("Easy to prepare dinners", "Meals easy to digest", "Soft tacos",
                      "I have no difficulty chewing", "I don't have trouble chewing", "No chewing problems",
                      "I don't need soft foods", "I have difficulty swallowing"):
            with self.subTest(query=query):
                intent = IntentAnalyzer()._post_process_intent(query, {})
                self.assertIsNone(intent["constraints"]["chewing_effort"])

    def test_follow_up_keeps_requirement_and_current_user_can_release_it(self):
        analyzer = IntentAnalyzer()
        analyzer.initialize(Mock(predict=Mock(return_value=json.dumps({**copy.deepcopy(INTENT), "query_type": "recipe_search", "resolved_query": QUERY}))))
        history = [{"role": "user", "content": QUERY}]
        self.assertEqual(analyzer.understand_query_intent_with_context("more recipes", history)["constraints"]["chewing_effort"], "low")
        released = analyzer.understand_query_intent_with_context("I no longer need soft foods", history)
        self.assertIsNone(released["constraints"]["chewing_effort"])
        self.assertNotIn("pureed soup", released["search_strategy"]["search_keywords"])
        analyzer.llm.predict.return_value = '{}'
        self.assertIsNone(analyzer.understand_query_intent_with_context("Chinese dinner", [])["constraints"]["chewing_effort"])

    def test_current_explicit_request_is_not_lost_in_model_resolution(self):
        analyzer = IntentAnalyzer()
        analyzer.initialize(Mock(predict=Mock(return_value=json.dumps({"query_type": "recipe_search", "resolved_query": "Dinner meals"}))))
        intent = analyzer.understand_query_intent_with_context(QUERY, [{"role": "user", "content": "Dinner ideas"}])
        self.assertEqual(intent["constraints"]["chewing_effort"], "low")
        self.assertFalse(intent.get("context_resolution_failed"))

    def test_no_context_model_failure_retains_explicit_requirement(self):
        analyzer = IntentAnalyzer()
        analyzer.initialize(Mock(predict=Mock(side_effect=ValueError("Invalid JSON"))))
        self.assertEqual(analyzer.understand_query_intent(QUERY)["constraints"]["chewing_effort"], "low")


class ChewingVerificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        names = {"Muesli", "Summer Shrimp and Pineapple Stir Fry", "Roasted Vegetables with Chipotle Ranch Sauce"}
        cls.reported_recipes = []
        filename = Path(__file__).resolve().parents[1] / "app/data/Recipe.csv"
        with filename.open(newline='', encoding='utf-8-sig') as handle:
            for row in csv.DictReader(handle):
                if row["Name"] in names:
                    cls.reported_recipes.append({
                        "name": row["Name"], "ingredients": row["Ingredients"].splitlines(),
                        "instructions": row["Directions"].splitlines(), "description": row["Description"],
                    })

    def verify(self, recipe, assessment=None, batch=False, intent=INTENT):
        assessment = model_pass(recipe, intent) if assessment is None else assessment
        verifier = RecipeVerifier()
        verifier.initialize(Mock(predict=Mock(return_value=json.dumps([assessment] if batch else assessment))))
        if batch:
            guidelines = Mock(validate_recipe_compliance=Mock(return_value={"overall_compliant": True}))
            return verifier.batch_verify_recipes([copy.deepcopy(recipe)], intent, guidelines)[0]["verification_details"]
        return verifier.verify_recipe_against_constraints(recipe, intent)

    def test_all_three_reported_csv_recipes_fail_even_if_model_claims_pass(self):
        self.assertEqual(len(self.reported_recipes), 3)
        for record in self.reported_recipes:
            for generated in (False, True):
                for batch in (False, True):
                    with self.subTest(recipe=record["name"], generated=generated, batch=batch):
                        recipe = {**record, "generated_by_llm": generated}
                        result = self.verify(recipe, batch=batch)
                        self.assertFalse(result["passes_verification"])
                        self.assertEqual(result["relevance"], "adaptable")
                        self.assertFalse(result["meets_preferences"])
                        self.assertIn("chewing_check", result)

    def test_missing_partial_unknown_or_invented_component_evidence_fails(self):
        for problem in ("missing", "partial", "unknown", "invented", "wrong ingredient", "duplicate", "no serving"):
            with self.subTest(problem=problem):
                assessment = model_pass(SOUP)
                check = assessment["chewing_check"]
                if problem == "missing":
                    assessment.pop("chewing_check")
                elif problem == "partial":
                    check["components"].pop()
                elif problem == "unknown":
                    check["components"][0]["status"] = "unknown"
                elif problem == "invented":
                    check["components"][0]["evidence"][0] = citation("instructions", 0, "Mash the nuts")
                elif problem == "wrong ingredient":
                    check["components"][0]["evidence"] = [citation("ingredients", 1, "vegetable broth")]
                elif problem == "duplicate":
                    check["components"].append(copy.deepcopy(check["components"][0]))
                else:
                    check.pop("serving_evidence")
                self.assertFalse(self.verify(SOUP, assessment)["passes_verification"])

    def test_cooked_soft_and_pureed_vegetables_are_not_blanket_banned(self):
        for batch in (False, True):
            self.assertTrue(self.verify(SOUP, batch=batch)["passes_verification"])

    def test_smooth_sauce_does_not_establish_texture_of_other_components(self):
        recipe = {"name": "Creamy Dinner", "ingredients": ["1 cup walnuts", "1 cup yogurt"],
                  "instructions": ["Blend the yogurt sauce until smooth.", "Serve with the walnuts."]}
        self.assertFalse(self.verify(recipe)["passes_verification"])

    def test_milk_yogurt_and_smooth_nut_butter_are_not_whole_nuts(self):
        recipe = {"name": "Smooth drink", "ingredients": ["1 cup almond milk", "2 tablespoons smooth peanut butter"],
                  "instructions": ["Whisk until combined and serve."]}
        self.assertTrue(self.verify(recipe)["passes_verification"])

    def test_blended_nuts_are_not_rejected_for_being_added_before_blending(self):
        recipe = {"name": "Smooth drink", "ingredients": ["2 tablespoons almonds", "1 cup milk"],
                  "instructions": ["Add almonds and milk to a blender.", "Blend all ingredients until smooth."]}
        self.assertTrue(self.verify(recipe)["passes_verification"])

    def test_soft_titles_do_not_prove_chicken_or_meatball_preparation(self):
        for ingredient in ("1 cup diced chicken", "4 turkey meatballs"):
            recipe = {"name": "Soft and Creamy Dinner", "ingredients": [ingredient, "1 cup mashed sweet potatoes"],
                      "instructions": ["Cook the meat to 165 F and serve with the mashed sweet potatoes."]}
            self.assertFalse(self.verify(recipe)["passes_verification"])
            recipe["instructions"] = ["Cook the chicken or turkey meatballs to 165 F, simmer until soft, and mash with a fork. Serve with the potatoes."]
            self.assertTrue(self.verify(recipe)["passes_verification"])

    def test_conflicting_optional_tips_and_toppings_are_rejected(self):
        for field in ("helpful_tips", "ingredient_adaptations", "instructions"):
            recipe = copy.deepcopy(SOUP)
            recipe.setdefault(field, []).append("Top with chopped walnuts for crunch, if desired.")
            self.assertFalse(self.verify(recipe)["passes_verification"])
        recipe = {**SOUP, "helpful_tips": ["Do not add crunchy toppings."]}
        self.assertTrue(self.verify(recipe)["passes_verification"])

    def test_component_evidence_is_not_required_for_other_requests(self):
        assessment = model_pass(SOUP, {})
        assessment.pop("chewing_check")
        self.assertTrue(self.verify(SOUP, assessment, intent={})["passes_verification"])

    def test_texture_checks_do_not_replace_other_active_constraints(self):
        intent = {"constraints": {"chewing_effort": "low", "allergens_to_avoid": ["carrots"]}}
        self.assertFalse(self.verify(SOUP, model_pass(SOUP), intent=intent)["passes_verification"])

    def test_texture_assessments_use_single_recipe_batches(self):
        verifier = RecipeVerifier()
        verifier.initialize(Mock(predict=Mock(return_value=json.dumps([model_pass(SOUP)]))))
        guidelines = Mock(validate_recipe_compliance=Mock(return_value={"overall_compliant": True}))
        results = verifier.batch_verify_recipes([copy.deepcopy(SOUP) for _ in range(3)], INTENT, guidelines)
        self.assertEqual(verifier.llm.predict.call_count, 3)
        self.assertTrue(all(recipe["verification_details"]["passes_verification"] for recipe in results))


class ChewingPipelineTests(unittest.TestCase):
    def setUp(self):
        self.service = RecipeRAGService()
        self.service.is_initialized = True
        self.service._contains_phi_like_content = Mock(return_value=False)
        self.service._is_small_talk_query = Mock(return_value=False)
        self.service.intent_analyzer.understand_query_intent_with_context = Mock(return_value=copy.deepcopy(INTENT))
        self.service.search_engine.multi_query_search = Mock(return_value=[])
        self.service.search_engine.rerank_with_constraint_filtering = Mock(side_effect=lambda docs, *args, **kwargs: docs)
        self.service._build_recipe_data_from_doc = Mock(side_effect=copy.deepcopy)
        self.service._get_database_search_candidates = Mock(return_value=[])
        self.service.recipe_enhancer.prepare_recipes_for_verification = Mock(side_effect=lambda recipes, intent: recipes)
        self.service.recipe_enhancer.batch_enhance_recipes = Mock(side_effect=lambda recipes, intent: recipes)
        self.service.recipe_enhancer.generate_fallback_recipes = Mock(return_value=[{
            **copy.deepcopy(SOUP), "name": "New Carrot Puree", "database_record_found": False,
            "generated_by_llm": True, "source_name": "", "recipe_link": "",
        }])

        def response(prompt):
            recipes = json.JSONDecoder().raw_decode(prompt.split("RECIPES TO VERIFY:\n", 1)[1])[0]
            return json.dumps([model_pass(recipe, {**INTENT, "recipe_request": QUERY}) for recipe in recipes])

        self.service.recipe_verifier.initialize(Mock(predict=Mock(side_effect=response)))

    def ask(self):
        with patch("app.services.rag_service.safety_service.should_intercept", return_value=False), patch(
            "app.services.rag_service.aicr_service.validate_recipe_compliance", return_value={"overall_compliant": True}
        ):
            result = self.service.ask_question(QUERY)
        self.assertNotEqual(result["source"], "error", result)
        return result

    def test_verified_database_recipe_still_wins_with_source_link(self):
        self.service.search_engine.multi_query_search.return_value = [copy.deepcopy(SOUP)]
        result = self.ask()
        self.assertEqual(result["source"], "database_exact")
        self.assertEqual(result["source_documents"][0]["recipe_link"], SOUP["recipe_link"])
        self.service.recipe_enhancer.generate_fallback_recipes.assert_not_called()

    def test_nonmatching_database_recipe_guides_generated_adaptation(self):
        firm = {**SOUP, "instructions": ["Roast carrots until cooked. Serve with broth."]}
        self.service.search_engine.multi_query_search.return_value = [firm]
        result = self.ask()
        self.assertEqual(result["source"], "llm_generated")
        references = self.service.recipe_enhancer.generate_fallback_recipes.call_args.kwargs["grounding_recipes"]
        self.assertEqual(references[0]["name"], SOUP["name"])
        self.assertEqual(result["source_documents"][0]["source_label"], "AI Generated")

    def test_no_database_context_still_allows_verified_ai_recipe(self):
        result = self.ask()
        self.assertEqual(result["source"], "llm_generated")
        self.assertEqual(self.service.recipe_enhancer.generate_fallback_recipes.call_args.kwargs["grounding_recipes"], [])

    def test_final_guidance_recheck_removes_incompatible_generated_tips(self):
        self.service.search_engine.multi_query_search.return_value = [copy.deepcopy(SOUP)]
        self.service.recipe_enhancer.batch_enhance_recipes.side_effect = lambda recipes, intent: [
            {**recipe, "guidance_generated": True, "helpful_tips": ["Add walnuts for crunch."]} for recipe in recipes
        ]
        result = self.ask()
        self.assertEqual(result["source"], "database_exact")
        self.assertNotIn("helpful_tips", result["source_documents"][0])


class ChewingPromptAndSummaryTests(unittest.TestCase):
    def test_rules_reach_intent_verification_generation_repair_and_enhancement(self):
        self.assertIn(CHEWING_RULES, IntentAnalyzer()._build_intent_prompt(QUERY))
        verifier = RecipeVerifier()
        self.assertIn(CHEWING_RULES, verifier._build_batch_verification_prompt([], INTENT))
        self.assertIn(CHEWING_RULES, verifier._build_individual_verification_prompt(SOUP, INTENT))
        enhancer = RecipeEnhancer()
        guidelines = Mock(validate_recipe_compliance=Mock(return_value={"overall_compliant": True}))
        guidelines.extract_focus_areas_from_intent.return_value = []
        guidelines.get_prompt_context.return_value = "Preserve nutrition and safety requirements."
        model = Mock(predict=Mock(return_value='[]'))
        enhancer.initialize(model, guidelines)
        enhancer.generate_fallback_recipes(QUERY, INTENT, [])
        self.assertIn(CHEWING_RULES, model.predict.call_args.args[0])
        enhancer.enhance_single_recipe(SOUP, INTENT)
        self.assertIn(CHEWING_RULES, model.predict.call_args.args[0])
        self.assertIn(CHEWING_RULES, enhancer._build_repair_prompt(QUERY, INTENT, SOUP, "Guidelines"))

    def test_summary_uses_actual_preparation_without_inventing_texture_or_health_claims(self):
        generator = ResponseGenerator()
        generator.initialize(Mock())
        recipe = {**SOUP, "verification_details": model_pass(SOUP), "storage_evidence": "Refrigerate promptly."}
        result = generator.generate_personalized_response(QUERY, [recipe], {"constraints": {"chewing_effort": "low", "leftover_friendly": True}})
        self.assertIn("Blend the entire soup until smooth.", result)
        self.assertIn("Refrigerate promptly.", result)
        self.assertNotIn("safe to swallow", result)
        self.assertNotIn("easy to digest", result)
        generator.llm.predict.assert_not_called()

    def test_summary_does_not_echo_fabricated_evidence(self):
        generator = ResponseGenerator()
        recipe = {**SOUP, "verification_details": model_pass(SOUP)}
        recipe["verification_details"]["chewing_check"]["serving_evidence"][0]["quote"] = "Guaranteed easy to digest"
        self.assertNotIn("Guaranteed", generator.generate_personalized_response(QUERY, [recipe], INTENT))
