import copy
import json
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app.services.aicr_guidelines_service import aicr_service
from app.services.rag_service import RecipeRAGService
from app.services.recipe_enhancer import RecipeEnhancer
from app.services.recipe_verifier import RecipeVerifier


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


class GenerationAndVerificationTests(unittest.TestCase):
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
