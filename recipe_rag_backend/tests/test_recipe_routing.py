import copy
import json
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app.services.aicr_guidelines_service import aicr_service
from app.services.rag_service import RecipeRAGService
from app.services.recipe_enhancer import RecipeEnhancer
from app.services.recipe_verifier import RecipeVerifier
from app.services.intent_analyzer import IntentAnalyzer
from app.services.response_generator import ResponseGenerator
from app.services.search_engine import SearchEngine
from app.services.recipe_prompt_rules import INGREDIENT_STORAGE_RULES


def recipe_record(name, relevance="match", generated=False):
    return {
        "recipe_id": name.lower().replace(" ", "-"),
        "name": name,
        "type": "Main Dish",
        "ingredients": ["1 cup tofu", "1 cup cooked rice"],
        "instructions": ["Cook the tofu and serve with rice."],
        "description": "A dinner recipe.",
        "database_record_found": not generated,
        "source_name": "AHA" if not generated else "",
        "recipe_link": "https://recipes.heart.org/en/recipes/example" if not generated else "",
        "generated_by_llm": generated,
        "test_relevance": relevance,
    }


class RecipeRoutingTests(unittest.TestCase):
    def setUp(self):
        self.service = RecipeRAGService()
        self.service.is_initialized = True
        self.service._contains_phi_like_content = Mock(return_value=False)
        self.service._is_small_talk_query = Mock(return_value=False)
        self.service.intent_analyzer.understand_query_intent_with_context = Mock(return_value={
            "constraints": {},
            "preferences": {"cuisine_types": ["chinese"], "meal_types": ["dinner"]},
            "search_strategy": {},
        })
        self.service.search_engine.multi_query_search = Mock(return_value=[])
        self.service.search_engine.rerank_with_constraint_filtering = Mock(side_effect=lambda docs, *args, **kwargs: docs)
        self.service._build_recipe_data_from_doc = Mock(side_effect=copy.deepcopy)
        self.service._get_database_search_candidates = Mock(return_value=[])
        self.service.recipe_enhancer.prepare_recipes_for_verification = Mock(side_effect=lambda recipes, intent: recipes)
        self.service.recipe_enhancer.batch_enhance_recipes = Mock(side_effect=lambda recipes, intent: recipes)
        self.service.recipe_verifier.batch_verify_recipes = Mock(side_effect=self.verify)
        self.service.recipe_enhancer.generate_fallback_recipes = Mock(return_value=[recipe_record("New Dinner", generated=True)])
        self.service.recipe_enhancer.generate_structured_fallback_recipe = Mock(return_value=[])
        self.service.response_generator.generate_personalized_response = Mock(return_value="Recipes ready.")
        self.service.response_generator.generate_helpful_no_results_message = Mock(return_value="No matching recipes.")

    def verify(self, recipes, intent, guidelines):
        for recipe in recipes:
            relevance = recipe["test_relevance"]
            recipe["verification_details"] = {
                "relevance": relevance,
                "passes_verification": relevance == "match" and not recipe.get("test_constraint_failure"),
                "constraint_violations": ["Dietary restriction"] if recipe.get("test_constraint_failure") else [],
            }
        return recipes

    def ask(self, query="What are some dinner recipes that are Chinese", history=None):
        with patch("app.services.rag_service.safety_service.should_intercept", return_value=False):
            result = self.service.ask_question(query, conversation_history=history)
        self.assertNotEqual(result.get("source"), "error", result)
        return result

    def test_good_database_match_wins_without_literal_query_words(self):
        self.service.search_engine.multi_query_search.return_value = [recipe_record("Hot-and-Sour Soup")]
        result = self.ask()
        self.assertEqual(result["source_documents"][0]["name"], "Hot-and-Sour Soup")
        self.assertEqual(result["source_documents"][0]["source_label"], "Sourced from AHA")
        self.service.recipe_enhancer.generate_fallback_recipes.assert_not_called()
        self.service._get_database_search_candidates.assert_not_called()

    def test_csv_rescue_precedes_generation(self):
        self.service._get_database_search_candidates.return_value = [recipe_record("Garden Vegetable Stir-Fried Sorghum")]
        result = self.ask()
        self.assertEqual(result["source"], "database_exact")
        self.service.recipe_enhancer.generate_fallback_recipes.assert_not_called()

    def test_reranking_omission_does_not_discard_useful_retrieved_recipe(self):
        self.service.search_engine.multi_query_search.return_value = [recipe_record("Hot-and-Sour Soup")]
        self.service.search_engine.rerank_with_constraint_filtering.side_effect = None
        self.service.search_engine.rerank_with_constraint_filtering.return_value = []
        self.assertEqual(self.ask()["source"], "database_exact")
        self.service.recipe_enhancer.generate_fallback_recipes.assert_not_called()

    def test_safety_interception_still_precedes_retrieval(self):
        expected = {"source": "safety", "source_documents": []}
        with patch("app.services.rag_service.safety_service.should_intercept", return_value=True), patch(
            "app.services.rag_service.safety_service.build_crisis_response", return_value=expected
        ):
            self.assertEqual(self.service.ask_question("crisis message"), expected)
        self.service.search_engine.multi_query_search.assert_not_called()
        self.service.recipe_enhancer.generate_fallback_recipes.assert_not_called()

    def test_related_database_recipe_becomes_generation_context(self):
        self.service.search_engine.multi_query_search.return_value = [recipe_record("Related Soup", "adaptable")]
        result = self.ask()
        references = self.service.recipe_enhancer.generate_fallback_recipes.call_args.kwargs["grounding_recipes"]
        self.assertEqual(references[0]["name"], "Related Soup")
        self.assertEqual(references[0]["ingredients"], ["1 cup tofu", "1 cup cooked rice"])
        self.assertEqual(result["source_documents"][0]["source_label"], "AI Generated")

    def test_unrelated_recipe_is_not_used_as_context(self):
        self.service.search_engine.multi_query_search.return_value = [recipe_record("Chocolate Cake", "unrelated")]
        result = self.ask()
        self.assertEqual(self.service.recipe_enhancer.generate_fallback_recipes.call_args.kwargs["grounding_recipes"], [])
        self.assertEqual(result["source"], "llm_generated")

    def test_constraint_failure_is_not_served_as_database_match(self):
        candidate = recipe_record("Related Soup")
        candidate["test_constraint_failure"] = True
        self.service.search_engine.multi_query_search.return_value = [candidate]
        result = self.ask()
        self.assertEqual(result["source"], "llm_generated")

    def test_retries_and_structured_fallback_retain_context(self):
        self.service.search_engine.multi_query_search.return_value = [recipe_record("Related Soup", "adaptable")]
        self.service.recipe_enhancer.generate_fallback_recipes.return_value = []
        self.service.recipe_enhancer.generate_structured_fallback_recipe.return_value = [recipe_record("New Dinner", generated=True)]
        result = self.ask()
        self.assertEqual(result["source"], "llm_generated")
        calls = self.service.recipe_enhancer.generate_fallback_recipes.call_args_list
        calls += self.service.recipe_enhancer.generate_structured_fallback_recipe.call_args_list
        self.assertEqual(len(calls), 3)
        self.assertTrue(all(call.kwargs["grounding_recipes"][0]["name"] == "Related Soup" for call in calls))

    def test_generated_constraints_are_verified_and_retried(self):
        invalid = recipe_record("Invalid Dinner", generated=True)
        invalid["test_constraint_failure"] = True
        self.service.recipe_enhancer.generate_fallback_recipes.side_effect = [[invalid], [recipe_record("Valid Dinner", generated=True)]]
        result = self.ask()
        self.assertEqual(result["source_documents"][0]["name"], "Valid Dinner")
        self.assertEqual(self.service.recipe_enhancer.generate_fallback_recipes.call_count, 2)
        self.assertEqual(self.service.recipe_enhancer.generate_fallback_recipes.call_args.args[2][0]["name"], "Invalid Dinner")

    def test_guidance_added_after_verification_is_rechecked_and_removed_if_conflicting(self):
        recipe = recipe_record("Pantry Bean Bowl")
        self.service.search_engine.multi_query_search.return_value = [recipe]

        def enhance(recipes, intent):
            for candidate in recipes:
                candidate["helpful_tips"] = ["Add grilled chicken and fresh cilantro."]
                candidate["ingredient_adaptations"] = ["Use frozen corn."]
                candidate["guidance_generated"] = True
            return recipes

        def verify_guidance(recipes, intent, guidelines):
            for candidate in recipes:
                bad_guidance = bool(candidate.get("helpful_tips") or candidate.get("ingredient_adaptations"))
                candidate["verification_details"] = {
                    "passes_verification": not bad_guidance,
                    "relevance": "adaptable" if bad_guidance else "match",
                    "constraint_violations": ["Conflicting pantry guidance"] if bad_guidance else [],
                }
            return recipes

        self.service.recipe_enhancer.batch_enhance_recipes.side_effect = enhance
        self.service.recipe_verifier.batch_verify_recipes.side_effect = verify_guidance
        result = self.ask("Meals using shelf-stable ingredients")
        self.assertEqual(result["matches_found"], 1)
        returned = result["source_documents"][0]
        self.assertNotIn("helpful_tips", returned)
        self.assertNotIn("ingredient_adaptations", returned)
        self.assertEqual(returned["ingredients"], recipe["ingredients"])
        self.assertEqual(returned["recipe_link"], recipe["recipe_link"])
        self.assertEqual(self.service.recipe_verifier.batch_verify_recipes.call_count, 3)

    def test_removing_guidance_does_not_allow_invalid_core_ingredients(self):
        recipe = recipe_record("Fresh Pepper Bowl")
        recipe.update({"guidance_generated": True, "helpful_tips": ["Add grilled chicken."], "test_constraint_failure": True})
        self.assertEqual(self.service._validate_final_recipes([recipe], {}), [])

    def test_final_validation_failure_attempts_correction_instead_of_stopping(self):
        database_recipe = recipe_record("Database Bean Bowl")
        self.service.search_engine.multi_query_search.return_value = [database_recipe]
        self.service.recipe_enhancer.batch_enhance_recipes.side_effect = lambda recipes, intent: [
            {**recipe, "guidance_generated": True, "helpful_tips": ["Conflicting advice"]}
            for recipe in recipes
        ]
        self.service._validate_final_recipes = Mock(return_value=[])
        result = self.ask("Show meals that rely on shelf-stable foods.")
        self.assertEqual(result["matches_found"], 1)
        self.assertEqual(result["source_documents"][0]["name"], "New Dinner")
        self.service.recipe_enhancer.generate_fallback_recipes.assert_called_once()
        self.assertEqual(self.service.recipe_enhancer.batch_enhance_recipes.call_count, 1)

    def test_final_validation_failure_uses_remaining_database_matches_first(self):
        self.service.search_engine.multi_query_search.return_value = [recipe_record(f"Dinner {number}") for number in range(4)]
        self.service.recipe_enhancer.batch_enhance_recipes.side_effect = lambda recipes, intent: [
            {**recipe, "guidance_generated": True} for recipe in recipes
        ]
        self.service._validate_final_recipes = Mock(return_value=[])
        result = self.ask()
        self.assertEqual([recipe["name"] for recipe in result["source_documents"]], ["Dinner 3"])
        self.service.recipe_enhancer.generate_fallback_recipes.assert_not_called()

    def test_failed_final_correction_is_bounded_and_first_request_is_not_called_additional(self):
        self.service.search_engine.multi_query_search.return_value = [recipe_record("Database Bowl")]
        self.service.recipe_enhancer.batch_enhance_recipes.side_effect = lambda recipes, intent: [
            {**recipe, "guidance_generated": True} for recipe in recipes
        ]
        self.service._validate_final_recipes = Mock(return_value=[])
        self.service.recipe_enhancer.generate_fallback_recipes.return_value = []
        result = self.ask("Show meals that rely on shelf-stable foods.")
        self.assertEqual(result["source"], "no_results")
        self.assertNotIn("additional", result["response"])
        self.service.recipe_enhancer.generate_fallback_recipes.assert_called_once()

    def test_final_correction_still_rejects_constraint_failures(self):
        self.service.search_engine.multi_query_search.return_value = [recipe_record("Database Bowl")]
        self.service.recipe_enhancer.batch_enhance_recipes.side_effect = lambda recipes, intent: [
            {**recipe, "guidance_generated": True} for recipe in recipes
        ]
        self.service._validate_final_recipes = Mock(return_value=[])
        invalid = recipe_record("Fresh Pepper Salad", generated=True)
        invalid["test_constraint_failure"] = True
        self.service.recipe_enhancer.generate_fallback_recipes.return_value = [invalid]
        result = self.ask("Show meals that rely on shelf-stable foods.")
        self.assertEqual(result["source"], "no_results")
        self.assertEqual(result["source_documents"], [])
        self.service.recipe_enhancer.generate_fallback_recipes.assert_called_once()

    def test_final_correction_preserves_follow_up_exclusions_and_database_context(self):
        reference = recipe_record("Database Bowl")
        self.service.search_engine.multi_query_search.return_value = [reference]
        self.service.recipe_enhancer.batch_enhance_recipes.side_effect = lambda recipes, intent: [
            {**recipe, "guidance_generated": True} for recipe in recipes
        ]
        self.service._validate_final_recipes = Mock(return_value=[])
        self.service.recipe_enhancer.generate_fallback_recipes.return_value = [recipe_record("Previous Dinner", generated=True)]
        result = self.ask("more recipes", [
            {"role": "user", "content": "Meals from pantry ingredients"},
            {"role": "assistant", "content": "Previously shown recipes: Previous Dinner"},
        ])
        self.assertEqual(result["source_documents"], [])
        call = self.service.recipe_enhancer.generate_fallback_recipes.call_args
        self.assertIn("previous dinner", call.args[0])
        self.assertEqual(call.kwargs["grounding_recipes"][0]["recipe_id"], reference["recipe_id"])

    def test_invalid_generated_results_are_not_shown(self):
        self.service.recipe_enhancer.generate_fallback_recipes.return_value = [recipe_record("Wrong Dish", "unrelated", True)]
        result = self.ask()
        self.assertEqual(result["source"], "no_results")
        self.assertEqual(result["source_documents"], [])

    def test_three_recipe_limit_without_ai_filling(self):
        self.service.search_engine.multi_query_search.return_value = [recipe_record(f"Dinner {number}") for number in range(5)]
        self.assertEqual(self.ask()["matches_found"], 3)
        self.service.recipe_enhancer.generate_fallback_recipes.assert_not_called()

    def test_follow_up_excludes_previous_recipe_before_fallback(self):
        self.service.search_engine.multi_query_search.return_value = [recipe_record("Previous Dinner")]
        self.service._get_database_search_candidates.return_value = [recipe_record("Another Dinner")]
        history = [
            {"role": "user", "content": "Chinese dinner recipes"},
            {"role": "assistant", "content": "Previously shown recipes: Previous Dinner"},
        ]
        result = self.ask("more recipes", history)
        self.assertEqual(result["source_documents"][0]["name"], "Another Dinner")
        self.assertEqual(result["intent_analysis"]["recipe_request"], "Chinese dinner recipes")

    def test_more_retries_when_generation_repeats_previous_recipe(self):
        previous = "Greek Yogurt and Berry Parfait"
        history = [
            {"role": "user", "content": "Show meals that taste mild but are still flavorful"},
            {"role": "assistant", "content": f"Only 4 ingredients and 18g protein.\nPreviously shown recipes: {previous}"},
        ]
        self.service.recipe_enhancer.generate_fallback_recipes.side_effect = [
            [recipe_record(previous, generated=True)],
            [recipe_record("Mild Vegetable Rice Bowl", generated=True)],
        ]
        result = self.ask("more recipes", history)
        self.assertEqual(result["matches_found"], 1)
        self.assertEqual(result["source_documents"][0]["name"], "Mild Vegetable Rice Bowl")
        self.assertEqual(self.service.recipe_enhancer.generate_fallback_recipes.call_count, 2)

    def test_more_intent_uses_user_requests_not_assistant_claims(self):
        original = "Show meals that taste mild but are still flavorful"
        history = [
            {"role": "user", "content": original},
            {"role": "assistant", "content": "Only 4 ingredients; 18g protein; store for 1 day."},
            {"role": "user", "content": "more recipes"},
            {"role": "assistant", "content": "I couldn't find recipes."},
        ]
        self.ask("more recipes", history)
        arguments = self.service.intent_analyzer.understand_query_intent_with_context.call_args.args
        self.assertEqual(arguments[0], "more recipes")
        self.assertEqual(arguments[1], [
            {"role": "user", "content": original},
            {"role": "user", "content": "more recipes"},
        ])

    def test_contextual_refinement_uses_resolved_request_for_retrieval_and_generation(self):
        resolved = "Mild flavorful vegetarian dinners without onions"
        self.service.intent_analyzer.understand_query_intent_with_context.return_value.update({
            "resolved_query": resolved,
            "constraints": {"dietary_restrictions": ["vegetarian"]},
            "search_strategy": {"enhanced_query": resolved},
        })
        result = self.ask("without onions", [{"role": "user", "content": "Mild vegetarian dinners"}])
        self.assertEqual(result["intent_analysis"]["recipe_request"], resolved)
        self.assertEqual(self.service.search_engine.multi_query_search.call_args.args[0], resolved)
        self.assertEqual(self.service.recipe_enhancer.generate_fallback_recipes.call_args.args[0], resolved)

    def test_recipe_question_answers_from_referenced_recipe_without_search(self):
        recipe = recipe_record("Soup")
        self.service._is_small_talk_query = RecipeRAGService._is_small_talk_query.__get__(self.service)
        self.service.intent_analyzer.understand_query_intent_with_context.return_value.update({
            "query_type": "recipe_question", "resolved_query": "Can I freeze Soup?",
            "referenced_recipe_ids": [recipe["recipe_id"]],
        })
        self.service.response_generator.answer_recipe_question = Mock(return_value="Storage guidance is not provided.")
        result = self.ask("Can I freeze it?", [{"role": "assistant", "content": "Soup", "recipes": [recipe]}])
        self.assertEqual(result["response"], "Storage guidance is not provided.")
        self.assertEqual(self.service.response_generator.answer_recipe_question.call_args.args[1][0]["ingredients"], recipe["ingredients"])
        self.service.search_engine.multi_query_search.assert_not_called()
        self.service.recipe_enhancer.generate_fallback_recipes.assert_not_called()

    def test_more_keeps_constraints_added_in_earlier_more_request(self):
        history = [
            {"role": "user", "content": "Mild dinners"},
            {"role": "user", "content": "more recipes without onions"},
            {"role": "assistant", "content": "Try soup", "recipes": [recipe_record("Soup")]},
        ]
        self.ask("more recipes", history)
        sent_history = self.service.intent_analyzer.understand_query_intent_with_context.call_args.args[1]
        self.assertEqual(sent_history[1]["content"], "more recipes without onions")
        self.assertEqual(sent_history[2]["recipes"][0]["recipe_id"], "soup")
        self.assertNotIn("Try soup", sent_history[2]["content"])

    def test_missing_reference_does_not_use_another_chats_recipe(self):
        self.service.intent_analyzer.understand_query_intent_with_context.return_value.update({
            "query_type": "recipe_question", "referenced_recipe_ids": ["soup-from-another-chat"],
        })
        result = self.ask("Can I freeze it?", [{"role": "user", "content": "Hello"}])
        self.assertIn("Which recipe", result["response"])
        self.service.search_engine.multi_query_search.assert_not_called()

    def test_explicit_adaptation_uses_selected_recipe_instead_of_unrelated_search(self):
        first = recipe_record("First Recipe")
        second = recipe_record("Second Recipe", "adaptable", generated=True)
        self.service.intent_analyzer.understand_query_intent_with_context.return_value.update({
            "query_type": "recipe_adaptation", "resolved_query": "Make Second Recipe vegetarian",
            "referenced_recipe_ids": [second["recipe_id"]],
        })
        result = self.ask("Make the second one vegetarian", [{"role": "assistant", "content": "Two recipes", "recipes": [first, second]}])
        self.assertEqual(result["source"], "llm_generated")
        references = self.service.recipe_enhancer.generate_fallback_recipes.call_args.kwargs["grounding_recipes"]
        self.assertEqual([recipe["name"] for recipe in references], ["Second Recipe"])
        self.service.search_engine.multi_query_search.assert_not_called()

    def test_context_resolution_failure_does_not_search_without_previous_constraints(self):
        self.service.intent_analyzer.understand_query_intent_with_context.return_value["context_resolution_failed"] = True
        result = self.ask("without onions", [{"role": "user", "content": "Vegetarian dinners"}])
        self.assertIn("earlier requirements", result["response"])
        self.service.search_engine.multi_query_search.assert_not_called()

    def test_more_returns_new_recipes_when_generation_also_contains_repeat(self):
        self.service.recipe_enhancer.generate_fallback_recipes.return_value = [
            recipe_record("Previous Dinner", generated=True),
            recipe_record("New Dinner", generated=True),
        ]
        result = self.ask("more recipes", [
            {"role": "user", "content": "Mild flavorful meals"},
            {"role": "assistant", "content": "Previously shown recipes: Previous Dinner"},
        ])
        self.assertEqual([recipe["name"] for recipe in result["source_documents"]], ["New Dinner"])
        self.assertEqual(self.service.recipe_enhancer.generate_fallback_recipes.call_count, 1)

    def test_exhausted_more_request_retains_original_context_in_response(self):
        self.service.recipe_enhancer.generate_fallback_recipes.return_value = []
        result = self.ask("more recipes", [{"role": "user", "content": "Mild flavorful meals"}])
        self.assertEqual(result["source"], "no_results")
        self.assertIn("Mild flavorful meals", result["response"])
        self.assertNotIn("rephras", result["response"].lower())

    def test_leftover_requirement_still_requires_evidence(self):
        self.service.intent_analyzer.understand_query_intent_with_context.return_value["constraints"] = {"leftover_friendly": True}
        self.service.search_engine.multi_query_search.return_value = [recipe_record("Fresh Dinner")]
        result = self.ask()
        self.assertEqual(result["source"], "no_results")

    def test_actual_database_rescue_finds_chinese_recipes(self):
        service = RecipeRAGService()
        service.data_loader.load_data(str(Path(__file__).parents[1] / "app/data/Recipe.csv"))
        candidates = service._get_database_search_candidates(
            "What are some dinner recipes that are Chinese", {"preferences": {"cuisine_types": ["chinese"]}}, set(), 8
        )
        names = {recipe["name"] for recipe in candidates}
        self.assertIn("Hot-and-Sour Soup", names)
        self.assertIn("Garden Vegetable Stir-Fried Sorghum", names)

    def test_broad_dinner_request_can_use_csv_rescue(self):
        service = RecipeRAGService()
        service.data_loader.load_data(str(Path(__file__).parents[1] / "app/data/Recipe.csv"))
        candidates = service._get_database_search_candidates(
            "Show some dinner recipes", {"preferences": {"meal_types": ["dinner"]}}, set(), 8
        )
        self.assertTrue(candidates)
        self.assertTrue(all(any(label in recipe["type"].lower() for label in ("entree", "main dish", "one-dish")) for recipe in candidates))

    def test_csv_rescue_excludes_shown_names_before_applying_limit(self):
        service = RecipeRAGService()
        service.data_loader.load_data(str(Path(__file__).parents[1] / "app/data/Recipe.csv"))
        intent = {"preferences": {"cuisine_types": ["chinese"]}}
        first = service._get_database_search_candidates("Chinese dinner", intent, set(), 1)
        self.assertEqual(len(first), 1)
        shown = {service._normalize_recipe_name(first[0]["name"])}
        second = service._get_database_search_candidates("Chinese dinner", intent, set(), 1, excluded_names=shown)
        self.assertEqual(len(second), 1)
        self.assertNotEqual(first[0]["recipe_id"], second[0]["recipe_id"])


class GenerationAndVerificationTests(unittest.TestCase):
    def test_pantry_checks_reject_each_conflict_even_with_model_pass(self):
        fields = ["required_non_pantry_ingredients", "unspecified_ingredient_forms", "conflicting_guidance"]
        for field in fields:
            with self.subTest(field=field):
                assessment = {key: [] for key in fields}
                assessment[field] = ["Fresh pepper or conflicting advice"]
                verifier = RecipeVerifier()
                verifier.initialize(Mock(predict=Mock(return_value=json.dumps([{
                    "id": 0, "relevance": "match", "passes_verification": True,
                    "ingredient_storage_check": assessment,
                }]))))
                result = verifier.batch_verify_recipes([recipe_record("Quinoa Bowl")], {
                    "constraints": {"ingredient_storage": "pantry_based"}
                }, aicr_service)
                self.assertFalse(result[0]["verification_details"]["passes_verification"])
                self.assertEqual(result[0]["verification_details"]["ingredient_storage_check"], assessment)

    def test_pantry_verification_requires_complete_assessment(self):
        for assessment in [None, {}, {"required_non_pantry_ingredients": []}]:
            with self.subTest(assessment=assessment):
                verifier = RecipeVerifier()
                verifier.initialize(Mock(predict=Mock(return_value=json.dumps({
                    "relevance": "match", "passes_verification": True, "ingredient_storage_check": assessment
                }))))
                result = verifier.verify_recipe_against_constraints(recipe_record("Bowl"), {
                    "constraints": {"ingredient_storage": "shelf_stable_only"}
                })
                self.assertFalse(result["passes_verification"])

    def test_pantry_verification_accepts_complete_clean_assessment_and_sees_all_guidance(self):
        assessment = {"required_non_pantry_ingredients": [], "unspecified_ingredient_forms": [], "conflicting_guidance": []}
        verifier = RecipeVerifier()
        verifier.initialize(Mock(predict=Mock(return_value=json.dumps([{
            "id": 0, "relevance": "match", "passes_verification": True, "ingredient_storage_check": assessment
        }]))))
        recipe = recipe_record("Quinoa and Black Bean Bowl")
        recipe.update({
            "ingredients": ["1 cup dry quinoa", "1 can black beans", "1 can corn", "1 can diced tomatoes", "olive oil", "cumin"],
            "instructions": ["Cook quinoa, drain the canned vegetables, and combine."],
            "helpful_tips": ["Season with garlic powder."],
            "ingredient_adaptations": ["Use canned chickpeas instead of black beans."],
        })
        result = verifier.batch_verify_recipes([recipe], {"constraints": {"ingredient_storage": "pantry_based"}}, aicr_service)
        self.assertTrue(result[0]["verification_details"]["passes_verification"])
        prompt = verifier.llm.predict.call_args.args[0]
        self.assertIn("Season with garlic powder.", prompt)
        self.assertIn("Use canned chickpeas instead of black beans.", prompt)
        individual_prompt = verifier._build_individual_verification_prompt(recipe, {})
        self.assertIn("Season with garlic powder.", individual_prompt)

    def test_pantry_paraphrases_retrieve_same_csv_candidates_with_semantic_intent(self):
        service = RecipeRAGService()
        service.data_loader.load_data(str(Path(__file__).parents[1] / "app/data/Recipe.csv"))
        candidate_names = []
        for query in [
            "Show meals that rely on shelf-stable foods.",
            "can you provide me recipes that rely on shelf-stable foods.",
        ]:
            analyzer = IntentAnalyzer()
            intent = analyzer._get_fallback_intent_data(query)
            intent["search_strategy"] = {
                "search_keywords": ["canned beans", "canned tomatoes", "dried lentils", "rice", "pasta"],
                "enhanced_query": "pantry meals with canned beans tomatoes dried lentils rice pasta",
            }
            intent = analyzer._post_process_intent(query, intent)
            candidates = service._get_database_search_candidates(query, intent, set(), 8)
            candidate_names.append([recipe["name"] for recipe in candidates])
        self.assertTrue(candidate_names[0])
        self.assertEqual(candidate_names[0], candidate_names[1])
        self.assertIn("Tuna, Brown Rice and White Bean Salad", candidate_names[0])

    def test_vector_search_uses_semantic_keywords(self):
        engine = SearchEngine()
        vector_store = Mock(similarity_search=Mock(return_value=[]))
        engine.initialize(vector_store, Mock())
        engine.multi_query_search("shelf-stable meals", {
            "search_strategy": {"search_keywords": ["canned beans", "dried lentils", "rice"]}
        }, 8)
        self.assertEqual(vector_store.similarity_search.call_args.args[0], "canned beans dried lentils rice")

    def test_empty_search_strategy_still_searches_original_query(self):
        engine = SearchEngine()
        vector_store = Mock(similarity_search=Mock(return_value=[]))
        engine.initialize(vector_store, Mock())
        engine.multi_query_search("shelf-stable meals", {}, 8)
        self.assertEqual(vector_store.similarity_search.call_args.args[0], "shelf-stable meals")

    def test_query_keywords_keep_ingredient_form_beyond_first_five_words(self):
        analyzer = IntentAnalyzer()
        result = analyzer._post_process_intent("Show meals that rely on shelf-stable foods", {})
        self.assertIn("shelf-stable", result["search_strategy"]["search_keywords"])

    def test_storage_rules_reach_intent_verification_and_generation(self):
        analyzer = IntentAnalyzer()
        self.assertIn(INGREDIENT_STORAGE_RULES, analyzer._build_intent_prompt("pantry meals"))
        verifier = RecipeVerifier()
        self.assertIn(INGREDIENT_STORAGE_RULES, verifier._build_batch_verification_prompt([], {}))
        self.assertIn(INGREDIENT_STORAGE_RULES, verifier._build_individual_verification_prompt({}, {}))
        enhancer = RecipeEnhancer()
        llm = Mock(predict=Mock(return_value=json.dumps([recipe_record("Bean Bowl", generated=True)])))
        enhancer.initialize(llm, aicr_service)
        enhancer.generate_fallback_recipes("pantry meals", {"constraints": {"ingredient_storage": "shelf_stable_only"}}, [])
        self.assertIn(INGREDIENT_STORAGE_RULES, llm.predict.call_args.args[0])
        self.assertIn('"ingredient_storage": "shelf_stable_only"', llm.predict.call_args.args[0])
        generator = ResponseGenerator()
        generator.initialize(llm)
        generator.generate_personalized_response("pantry meals", [recipe_record("Bean Bowl")], {})
        self.assertIn(INGREDIENT_STORAGE_RULES, llm.predict.call_args.args[0])

    def test_semantic_pantry_search_terms_survive_intent_processing(self):
        analyzer = IntentAnalyzer()
        query = "Show meals that rely on shelf-stable foods."
        intent = analyzer._get_fallback_intent_data(query)
        intent["constraints"]["ingredient_storage"] = "pantry_based"
        intent["search_strategy"] = {
            "search_keywords": ["canned beans", "canned tomatoes", "dried lentils", "rice", "pasta"],
            "enhanced_query": "pantry meals with canned beans tomatoes dried lentils rice pasta",
        }
        result = analyzer._post_process_intent(query, intent)
        self.assertIn("canned beans", result["search_strategy"]["search_keywords"])
        self.assertIn("dried lentils", result["search_strategy"]["search_keywords"])
        self.assertIn("pantry meals", result["search_strategy"]["enhanced_query"])
        self.assertFalse(result["constraints"]["leftover_friendly"])
        self.assertEqual(result["constraints"]["ingredient_storage"], "pantry_based")

    def test_question_prompt_contains_actual_recipe_and_marks_unknown_facts(self):
        generator = ResponseGenerator()
        llm = Mock(predict=Mock(return_value="The recipe does not specify a freezing duration."))
        generator.initialize(llm)
        result = generator.answer_recipe_question("Can I freeze Soup?", [recipe_record("Soup")], {})
        self.assertIn("does not specify", result)
        prompt = llm.predict.call_args.args[0]
        self.assertIn("1 cup tofu", prompt)
        self.assertIn("do not invent nutrition totals or storage durations", prompt)

    def test_early_user_requirements_and_recipe_references_remain_in_long_chat(self):
        analyzer = IntentAnalyzer()
        parsed = analyzer._get_fallback_intent_data("Italian vegetarian dinner without peanuts")
        parsed["preferences"]["cuisine_types"] = ["italian"]
        parsed["constraints"]["dietary_restrictions"] = ["vegetarian"]
        analyzer.initialize(Mock(predict=Mock(return_value=json.dumps(parsed))))
        history = [{"role": "user", "content": "I am vegetarian; avoid peanuts. Chinese dinner please."}]
        history.append({"role": "assistant", "content": "A soup", "recipes": [recipe_record("Soup")]})
        history.extend({"role": "user", "content": "more recipes"} for _ in range(8))
        result = analyzer.understand_query_intent_with_context("Italian instead", history)
        prompt = analyzer.llm.predict.call_args.args[0]
        self.assertIn("I am vegetarian; avoid peanuts", prompt)
        self.assertIn('"recipe_id": "soup"', prompt)
        self.assertEqual(result["preferences"]["cuisine_types"], ["italian"])
        self.assertIn("Italian vegetarian dinner without peanuts", result["search_strategy"]["enhanced_query"])

    def test_contextual_intents_are_isolated_between_chats(self):
        analyzer = IntentAnalyzer()
        vegetarian = analyzer._get_fallback_intent_data("vegetarian dinner")
        vegetarian["constraints"]["dietary_restrictions"] = ["vegetarian"]
        fish = analyzer._get_fallback_intent_data("fish dinner")
        analyzer.initialize(Mock(predict=Mock(side_effect=[json.dumps(vegetarian), json.dumps(fish)])))
        first = analyzer.understand_query_intent_with_context("more recipes", [{"role": "user", "content": "Vegetarian dinner"}])
        second = analyzer.understand_query_intent_with_context("more recipes", [{"role": "user", "content": "Fish dinner"}])
        self.assertEqual(first["constraints"]["dietary_restrictions"], ["vegetarian"])
        self.assertEqual(second["constraints"]["dietary_restrictions"], [])
        self.assertNotIn("Vegetarian dinner", analyzer.llm.predict.call_args.args[0])

    def test_intent_prompt_provides_schema_for_mild_meal_follow_up(self):
        analyzer = IntentAnalyzer()
        query = "Show meals that taste mild but are still flavorful"
        parsed = analyzer._get_fallback_intent_data(query)
        parsed["preferences"]["flavor_profiles"] = ["mild", "flavorful"]
        llm = Mock(predict=Mock(return_value=json.dumps(parsed)))
        analyzer.initialize(llm)
        result = analyzer.understand_query_intent_with_context(query, [{"role": "user", "content": query}])
        prompt = llm.predict.call_args.args[0]
        self.assertIn('"flavor_profiles"', prompt)
        self.assertIn('"constraints"', prompt)
        self.assertIn("Only user messages establish requirements", prompt)
        self.assertNotIn("Your existing intent prompt", prompt)
        self.assertEqual(result["preferences"]["flavor_profiles"], ["mild", "flavorful"])
        self.assertIsNone(result["constraints"]["max_ingredients"])
        self.assertFalse(result["constraints"]["leftover_friendly"])
        self.assertEqual(result["preferences"]["meal_types"], [])

    def test_grounded_generation_receives_recipe_content_and_keeps_ai_provenance(self):
        llm = Mock()
        llm.predict.return_value = json.dumps([recipe_record("New Soup", generated=True)])
        enhancer = RecipeEnhancer()
        enhancer.initialize(llm, aicr_service)
        reference = recipe_record("Related Soup", "adaptable")
        recipes = enhancer.generate_fallback_recipes("Chinese dinner", {}, [], [reference])
        self.assertEqual(len(recipes), 1)
        prompt = llm.predict.call_args.args[0]
        self.assertIn("1 cup tofu", prompt)
        self.assertIn("Cook the tofu and serve with rice.", prompt)
        self.assertIn("Discard conflicting ingredients", prompt)
        self.assertEqual(recipes[0]["generation_basis"], "database_guided")
        self.assertEqual(recipes[0]["reference_sources"][0]["recipe_id"], reference["recipe_id"])
        self.assertNotIn("recipe_link", recipes[0])
        self.assertTrue(recipes[0]["generated_by_llm"])

    def test_ai_only_generation_has_no_database_attribution(self):
        enhancer = RecipeEnhancer()
        enhancer.initialize(Mock(predict=Mock(return_value=json.dumps([recipe_record("New Soup", generated=True)]))), aicr_service)
        recipe = enhancer.generate_fallback_recipes("dinner", {}, [])[0]
        self.assertEqual(recipe["generation_basis"], "ai_only")
        self.assertEqual(recipe["reference_sources"], [])

    def test_structured_fallback_uses_same_database_context(self):
        llm = Mock(predict=Mock(return_value="""INGREDIENTS:
- 1 cup tofu
COOKING_INSTRUCTIONS:
1. Cook the tofu thoroughly and serve warm.
INGREDIENT_MODIFICATIONS:
- Serve with rice if desired.
HELPFUL_TIPS:
- Enjoy warm.
"""))
        enhancer = RecipeEnhancer()
        enhancer.initialize(llm, aicr_service)
        result = enhancer.generate_structured_fallback_recipe("Chinese dinner", {}, [recipe_record("Related Soup")])
        self.assertEqual(len(result), 1)
        self.assertIn("DATABASE REFERENCE RECIPES", llm.predict.call_args.args[0])
        self.assertEqual(result[0]["generation_basis"], "database_guided")
        self.assertTrue(result[0]["generated_by_llm"])

    def test_noncompliant_generation_is_rejected(self):
        enhancer = RecipeEnhancer()
        guidelines = Mock()
        guidelines.get_prompt_context.return_value = "Guidelines"
        guidelines.validate_recipe_compliance.return_value = {"overall_compliant": False, "score": 40, "warnings": ["Unsafe ingredient"]}
        enhancer.initialize(Mock(predict=Mock(return_value=json.dumps([recipe_record("Unsafe Dinner", generated=True)]))), guidelines)
        self.assertEqual(enhancer.generate_fallback_recipes("dinner", {}, []), [])

    def test_verifier_rejects_unrelated_even_if_model_says_pass(self):
        verifier = RecipeVerifier()
        verifier.initialize(Mock(predict=Mock(return_value=json.dumps([{
            "id": 0, "relevance": "unrelated", "passes_verification": True
        }]))))
        results = verifier.batch_verify_recipes([recipe_record("Wrong Dish")], {}, aicr_service)
        self.assertFalse(results[0]["verification_details"]["passes_verification"])

    def test_verifier_accepts_semantic_match_and_checks_guidelines(self):
        verifier = RecipeVerifier()
        verifier.initialize(Mock(predict=Mock(return_value=json.dumps([{
            "id": 0, "relevance": "match", "passes_verification": True
        }]))))
        results = verifier.batch_verify_recipes([recipe_record("Hot-and-Sour Soup")], {"recipe_request": "What are some dinner recipes that are Chinese"}, aicr_service)
        self.assertTrue(results[0]["verification_details"]["passes_verification"])
        self.assertTrue(results[0]["aicr_compliance"]["overall_compliant"])
        self.assertIn("main dish or entree can be dinner", verifier.llm.predict.call_args.args[0])

    def test_verifier_rejects_contradictory_pass_with_constraint_violations(self):
        verifier = RecipeVerifier()
        verifier.initialize(Mock(predict=Mock(return_value=json.dumps([{
            "id": 0, "relevance": "match", "passes_verification": True,
            "constraint_violations": ["Contains an excluded allergen"]
        }]))))
        results = verifier.batch_verify_recipes([recipe_record("Soup")], {}, aicr_service)
        self.assertFalse(results[0]["verification_details"]["passes_verification"])

    def test_individual_verifier_fails_closed_on_missing_relevance(self):
        verifier = RecipeVerifier()
        verifier.initialize(Mock(predict=Mock(return_value='{"passes_verification": true}')))
        self.assertFalse(verifier.verify_recipe_against_constraints(recipe_record("Soup"), {})["passes_verification"])

    def test_verification_cache_separates_cuisine_and_recipe_changes(self):
        verifier = RecipeVerifier()
        verifier.initialize(Mock(predict=Mock(return_value='{"passes_verification": true, "relevance": "match"}')))
        recipe = recipe_record("Soup")
        chinese = {"preferences": {"cuisine_types": ["chinese"]}}
        italian = {"preferences": {"cuisine_types": ["italian"]}}
        verifier.verify_recipe_against_constraints(recipe, chinese)
        verifier.verify_recipe_against_constraints(recipe, chinese)
        verifier.verify_recipe_against_constraints(recipe, italian)
        recipe["ingredients"] = ["beef"]
        verifier.verify_recipe_against_constraints(recipe, italian)
        self.assertEqual(verifier.llm.predict.call_count, 3)


if __name__ == "__main__":
    unittest.main()
