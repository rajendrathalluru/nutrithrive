import csv
import unittest
from pathlib import Path
from unittest.mock import Mock

from app.services.intent_analyzer import IntentAnalyzer
from app.services.rag_service import RecipeRAGService
from app.services.recipe_enhancer import RecipeEnhancer
from app.services.recipe_verifier import RecipeVerifier
from app.services.response_generator import ResponseGenerator
from app.services.search_engine import SearchEngine
from app.services.storage_guidance import extract_storage_guidance, requests_reheating, storage_summary


class StorageGuidanceTests(unittest.TestCase):
    def test_reheating_requests_use_leftover_evidence_without_assuming_other_constraints(self):
        for query in (
            "What foods don’t change texture when reheated?", "Which foods reheat well?",
            "What meals can be reheated?", "Recipes suitable for reheating",
        ):
            with self.subTest(query=query):
                analyzer = IntentAnalyzer()
                intent = analyzer._post_process_intent(query, analyzer._get_fallback_intent_data(query))
                self.assertTrue(requests_reheating(query))
                self.assertTrue(intent["constraints"]["leftover_friendly"])
                self.assertIsNone(intent["constraints"]["chewing_effort"])
                self.assertIsNone(intent["constraints"]["preparation_mode"])
        for query in ("Meals without reheating", "Foods that don't reheat well", "Breakfast recipes"):
            self.assertFalse(requests_reheating(query), query)

    def test_reheating_uses_real_source_guidance_not_speculative_model_approval(self):
        query = "What foods don’t change texture when reheated?"
        service = RecipeRAGService()
        service.data_loader.load_data(Path(__file__).parents[1] / "app/data/Recipe.csv")
        analyzer = IntentAnalyzer()
        intent = analyzer._post_process_intent(query, analyzer._get_fallback_intent_data(query))
        recipes = [service._build_recipe_data_from_record(service.data_loader.get_recipe_record(name)) for name in (
            "Air Fryer Plantains with Cilantro Crema", "Vegetable Stone Soup",
        )]
        for recipe in recipes:
            recipe["verification_details"] = {"passes_verification": True, "relevance": "match"}
        matches = service._get_verified_matches(recipes, intent)
        self.assertEqual([recipe["name"] for recipe in matches], ["Vegetable Stone Soup"])
        generator = ResponseGenerator()
        generator.initialize(Mock())
        response = generator.generate_personalized_response(query, matches, intent)
        self.assertIn("no recipe guarantees an identical result", response)
        self.assertIn("add croutons just before serving", response)
        self.assertNotIn("Plantains", response)
        generator.llm.predict.assert_not_called()

    @classmethod
    def setUpClass(cls):
        filename = Path(__file__).resolve().parents[1] / "app/data/Recipe.csv"
        with filename.open(newline='', encoding='utf-8-sig') as handle:
            cls.records = {row["Name"]: row for row in csv.DictReader(handle) if row["Name"] in {
                "Pomegranate Salsa", "Peach, Strawberry, and Cottage Cheese Protein Smoothie"
            }}

    def test_live_smoothie_note_excludes_continue_as_directed(self):
        note = self.records["Peach, Strawberry, and Cottage Cheese Protein Smoothie"]["Notes"]
        self.assertEqual(extract_storage_guidance(note),
                         "Store any remaining servings in an airtight container in the refrigerator for up to 2 days or freeze for up to 3 months.")

    def test_unpunctuated_tip_bullets_are_not_joined_into_storage_guidance(self):
        text = "\n".join([
            "To increase protein, consider adding diced grilled chicken or tofu",
            "For added fiber, serve over greens or grains",
            "Make a larger batch and store it in an airtight container in the refrigerator for 2 days",
        ])
        evidence = extract_storage_guidance(text)
        self.assertNotIn("chicken", evidence)
        self.assertNotIn("greens", evidence)
        self.assertIn("refrigerator for 2 days", evidence)

    def test_raw_ingredient_forms_and_generic_meal_prep_are_not_storage_instructions(self):
        for text in ("1 cup frozen berries", "2 tablespoons freeze-dried fruit", "Great for meal prep.",
                     "Ingredients:\n1 cup frozen pineapple\nDirections:\nBlend and serve."):
            self.assertEqual(extract_storage_guidance(text), "")

    def test_complete_storage_sentence_is_not_cut_at_320_characters(self):
        text = "Store leftovers in the refrigerator in a covered container. " + (
            "Reheat the portion you plan to eat " + "with the instructions on the recipe card " * 7 + "before serving."
        )
        self.assertGreater(len(text), 320)
        self.assertEqual(storage_summary(text), text)
        self.assertEqual(storage_summary(text * 3, max_chars=100), "See the recipe card for complete storage guidance.")

    def test_storage_warning_is_preserved(self):
        self.assertEqual(storage_summary("Refrigerate for 2 days. Do not freeze. Serve with herbs."),
                         "Refrigerate for 2 days. Do not freeze.")

    def test_source_salsa_guidance_wins_over_generated_tips(self):
        service = RecipeRAGService()
        recipe = service._build_recipe_data_from_record(self.records["Pomegranate Salsa"])
        recipe["helpful_tips"] = ["Add grilled chicken.", "Store the salsa all week in the refrigerator."]
        recipe["storage_evidence"] = "Store the salsa all week in the refrigerator."
        evidence = service._get_recipe_storage_evidence(recipe)
        self.assertEqual(evidence, "Salsa keeps for 2 days, tightly covered in the refrigerator.")

    def test_actual_one_and_two_step_database_recipes_are_not_marked_incomplete(self):
        service = RecipeRAGService()
        enhancer = RecipeEnhancer()
        enhancer.initialize(Mock(), Mock())
        for record in self.records.values():
            with self.subTest(recipe=record["Name"]):
                recipe = service._build_recipe_data_from_record(record)
                self.assertEqual(len(recipe["instructions"]), len(record["Directions"].splitlines()))
                self.assertFalse(recipe["needs_instruction_generation"])
                enhancer.prepare_recipes_for_verification([recipe], {"constraints": {"leftover_friendly": True}})
        enhancer.llm.predict.assert_not_called()

    def test_missing_directions_still_require_completion(self):
        recipe = SearchEngine().extract_recipe_details("Ingredients:\n1 cup beans\nDirections:\nNotes: No directions available.")
        self.assertTrue(recipe["needs_instruction_generation"])

    def test_source_storage_reaches_verifier_before_selection(self):
        service = RecipeRAGService()
        service.recipe_enhancer.prepare_recipes_for_verification = Mock(side_effect=lambda recipes, intent: recipes)
        service.recipe_verifier.batch_verify_recipes = Mock(side_effect=lambda recipes, *args: recipes)
        recipe = service._build_recipe_data_from_record(self.records["Pomegranate Salsa"])
        result = service._verify_candidates([recipe], {"constraints": {"leftover_friendly": True}})
        self.assertEqual(result[0]["storage_evidence"], "Salsa keeps for 2 days, tightly covered in the refrigerator.")

    def test_summary_contains_storage_not_unrelated_protein_tips(self):
        generator = ResponseGenerator()
        result = generator.generate_personalized_response("Do not finish in one sitting", [{
            "name": "Salsa", "storage_evidence": "Add chicken for protein. Refrigerate for 2 days."
        }], {"constraints": {"leftover_friendly": True}})
        self.assertIn("Refrigerate for 2 days.", result)
        self.assertNotIn("chicken", result)


class MealPortionTests(unittest.TestCase):
    def test_small_serving_paraphrases_activate_portioning_and_storage(self):
        for query in ("What meals can I break into multiple small servings?", "Meals I can divide into smaller portions",
                      "Show recipes I can split into small servings"):
            with self.subTest(query=query):
                intent = IntentAnalyzer()._post_process_intent(query, {})
                self.assertTrue(intent["constraints"]["leftover_friendly"])
                self.assertEqual(intent["constraints"]["portion_size"], "small")
                self.assertIn("stores well", intent["search_strategy"]["search_keywords"])

    def test_meals_and_unspecified_recipes_are_distinguished(self):
        analyzer = IntentAnalyzer()
        meals = analyzer._post_process_intent("What meals can I break into multiple small servings?", {})
        self.assertEqual(meals["constraints"]["meal_suitability"], "meal")
        recipes = analyzer._post_process_intent("Show recipes that don’t require finishing in one sitting", {})
        self.assertIsNone(recipes["constraints"]["meal_suitability"])
        self.assertTrue(recipes["constraints"]["leftover_friendly"])
        snacks = analyzer._post_process_intent("Snacks only, not meals", {"constraints": {"meal_suitability": "meal"}})
        self.assertIsNone(snacks["constraints"]["meal_suitability"])

    def test_verifier_cannot_omit_meal_and_portion_checks(self):
        intent = {"constraints": {"meal_suitability": "meal", "portion_size": "small"}}
        verdict = RecipeVerifier()._finalize_verification({
            "relevance": "match", "constraint_checks": {}, "constraint_violations": []
        }, {}, intent)
        self.assertFalse(verdict["passes_verification"])
        self.assertTrue(any("meal_suitability" in issue for issue in verdict["constraint_violations"]))
        self.assertTrue(any("portion_size" in issue for issue in verdict["constraint_violations"]))

    def test_small_portion_summary_keeps_exact_storage_duration(self):
        result = ResponseGenerator().generate_personalized_response("Small servings", [{
            "name": "Bean Salad", "storage_evidence": "Refrigerate for up to 2 days."
        }], {"constraints": {"leftover_friendly": True, "portion_size": "small"}})
        self.assertIn("multiple small servings", result)
        self.assertIn("up to 2 days", result)
        self.assertNotIn("week", result)
