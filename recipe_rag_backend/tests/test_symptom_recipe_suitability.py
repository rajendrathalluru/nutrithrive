import copy
import json
import unittest
from unittest.mock import Mock, patch

from app.services.conversation_scope import starts_new_request
from app.services.data_loader import DataLoader
from app.services.digestive_comfort import audit_digestive_comfort, explicit_digestive_comfort
from app.services.intent_analyzer import IntentAnalyzer
from app.services.preparation_validation import audit_preparation_effort
from app.services.rag_service import RecipeRAGService
from app.services.recipe_prompt_rules import DIGESTIVE_COMFORT_RULES, LOW_EXERTION_RULES, active_recipe_rules
from app.services.recipe_verifier import RecipeVerifier
from app.services.response_generator import ResponseGenerator


STOMACH_QUERY = "What is safe to cook for an upset stomach?"
WEAKNESS_QUERY = "What are some easy recipes I can push through with body weakness?"


class SymptomIntentTests(unittest.TestCase):
    def analyze(self, query, history=None):
        analyzer = IntentAnalyzer()
        analyzer.initialize(Mock(predict=Mock(return_value=json.dumps(analyzer._get_fallback_intent_data(query)))))
        return analyzer.understand_query_intent_with_context(query, history)

    def test_exact_prompts_request_recipes_without_inventing_a_diagnosis(self):
        for query, field, expected in ((STOMACH_QUERY, "digestive_comfort", "gentle"),
                                       (WEAKNESS_QUERY, "preparation_effort", "low")):
            with self.subTest(query=query):
                intent = self.analyze(query)
                self.assertTrue(starts_new_request(query))
                self.assertEqual(intent["query_type"], "recipe_search")
                self.assertEqual(intent["constraints"][field], expected)
                self.assertEqual(intent["constraints"]["health_conditions"], [])
                self.assertEqual(intent["cancer_patient_specific"]["symptoms"], [])
                for unrelated in ("preparation_position", "hand_effort", "time_max_minutes", "preparation_mode", "attention_level"):
                    self.assertIsNone(intent["constraints"][unrelated])

    def test_new_requests_do_not_inherit_other_symptom_or_task(self):
        intent = self.analyze(WEAKNESS_QUERY, [{"role": "user", "content": STOMACH_QUERY}])
        self.assertIsNone(intent["constraints"]["digestive_comfort"])
        intent = self.analyze(STOMACH_QUERY, [{"role": "user", "content": "Show meals with an air fryer under 20 minutes"}])
        self.assertEqual(intent["constraints"]["equipment_required"], [])
        self.assertIsNone(intent["constraints"]["time_max_minutes"])

    def test_explicit_followups_keep_only_current_task_and_withdrawals_clear(self):
        history = [{"role": "user", "content": STOMACH_QUERY}, {"role": "user", "content": WEAKNESS_QUERY}]
        intent = self.analyze("More recipes", history)
        self.assertEqual(intent["constraints"]["preparation_effort"], "low")
        self.assertIsNone(intent["constraints"]["digestive_comfort"])
        intent = self.analyze("My stomach is fine now; drop the stomach restriction", [{"role": "user", "content": STOMACH_QUERY}])
        self.assertIsNone(intent["constraints"]["digestive_comfort"])
        intent = self.analyze("I'm no longer feeling weak", [{"role": "user", "content": WEAKNESS_QUERY}])
        self.assertIsNone(intent["constraints"]["preparation_effort"])

    def test_casual_easy_requests_and_assistant_claims_do_not_add_symptom_constraints(self):
        intent = self.analyze("More recipes", [
            {"role": "user", "content": "Show easy dinner recipes"},
            {"role": "assistant", "content": "Good for nausea, easy on the stomach, and useful for body weakness."},
        ])
        self.assertIsNone(intent["constraints"]["digestive_comfort"])
        self.assertIsNone(intent["constraints"]["preparation_effort"])
        self.assertNotIn(DIGESTIVE_COMFORT_RULES, active_recipe_rules(intent))
        self.assertNotIn(LOW_EXERTION_RULES, active_recipe_rules(intent))
        self.assertEqual(explicit_digestive_comfort("I do not have an upset stomach"), "unrestricted")

    def test_symptom_does_not_invent_portion_or_meal_requirements(self):
        analyzer = IntentAnalyzer()
        for query, meal, portion in ((WEAKNESS_QUERY, None, None), ("Show small meals for body weakness", "meal", "small")):
            parsed = analyzer._get_fallback_intent_data(query)
            parsed["constraints"].update({"meal_suitability": "meal", "portion_size": "small"})
            result = analyzer._post_process_intent(query, parsed)
            self.assertEqual(result["constraints"]["meal_suitability"], meal)
            self.assertEqual(result["constraints"]["portion_size"], portion)


class SymptomSuitabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.loader = DataLoader()
        cls.loader.load_data()

    def record(self, name):
        record = self.loader.get_recipe_record(name)
        self.assertIsNotNone(record)
        return {"name": name, "ingredients": record["Ingredients"].splitlines(), "instructions": record["Directions"].splitlines()}

    def assessment(self, verifier, intent):
        return {"relevance": "match", "constraint_violations": [], "constraint_checks": {
            key: {"status": "pass", "evidence": "A nutritious, easy recipe."} for key in verifier._required_checks(intent)
        }}

    def test_reported_chili_cannot_pass_generic_model_praise(self):
        recipe = self.record("Three-Bean Chili - Delicious Decisions")
        intent = {"constraints": {"digestive_comfort": "gentle"}}
        verifier = RecipeVerifier()
        result = verifier._finalize_verification(self.assessment(verifier, intent), recipe, intent)
        self.assertFalse(result["passes_verification"])
        self.assertEqual(result["relevance"], "adaptable")
        self.assertTrue(any("2 tablespoons chili powder" in reason for reason in result["constraint_violations"]))
        ordinary = {"constraints": {}}
        self.assertTrue(verifier._finalize_verification(self.assessment(verifier, ordinary), recipe, ordinary)["passes_verification"])

    def test_not_a_blanket_ban_on_every_spice_or_acidic_food(self):
        recipe = self.record("Steamed Chicken with Vegetables and Rice")
        self.assertEqual(audit_digestive_comfort(recipe, {"digestive_comfort": "gentle"}), [])
        verifier = RecipeVerifier()
        intent = {"constraints": {"digestive_comfort": "gentle"}}
        result = verifier._finalize_verification(self.assessment(verifier, intent), recipe, intent)
        self.assertTrue(result["passes_verification"])

    def test_optional_tips_cannot_reintroduce_spicy_seasoning_or_deep_frying(self):
        for field, line in (("helpful_tips", "Add jalapeños for more flavor."),
                            ("ingredient_adaptations", "Deep-fry the potatoes for crunch."),
                            ("instructions", "Stir in hot sauce before serving.")):
            self.assertTrue(audit_digestive_comfort({field: [line]}, {"digestive_comfort": "gentle"}))
        self.assertEqual(audit_digestive_comfort({"helpful_tips": ["Avoid hot sauce.", "Omit chili powder."]},
                                                {"digestive_comfort": "gentle"}), [])

    def test_all_three_weakness_examples_need_preparation_changes(self):
        verifier = RecipeVerifier()
        intent = {"constraints": {"preparation_effort": "low"}}
        for name in ("Easy Scalloped Potato White Bean Skillet", "Turkey and Barley Vegetable Soup", "Creamy Broccoli Apple Salad"):
            with self.subTest(recipe=name):
                recipe = self.record(name)
                result = verifier._finalize_verification(self.assessment(verifier, intent), recipe, intent)
                self.assertFalse(result["passes_verification"])
                self.assertEqual(result["relevance"], "adaptable")
                self.assertTrue(audit_preparation_effort(recipe))

    def test_dense_produce_and_repetitive_breading_are_not_low_exertion(self):
        for name in ("Maple Dijon Roasted Rutabaga", "Air Fryer Fried Okra",
                     "Baked Mozzarella Cheese Bites with Easy Marinara Sauce", "BBQ Peach and Chicken Naan Pizzas", "Grape Grilled Cheese"):
            self.assertTrue(audit_preparation_effort(self.record(name)), name)
        self.assertEqual(audit_preparation_effort({
            "ingredients": ["1 cup purchased pre-cut rutabaga"], "instructions": ["Microwave until tender."]
        }), [])

    def test_gentle_selection_prefers_lower_caution_matches_without_banning_ingredients(self):
        service = RecipeRAGService()
        recipes = []
        for name in ("Steamed Chicken with Vegetables and Rice", "Red Lentils with Vegetables and Brown Rice"):
            recipes.append({**self.record(name), "verification_details": {"passes_verification": True, "relevance": "match"}})
        intent = {"constraints": {"digestive_comfort": "gentle"}}
        self.assertEqual([recipe["name"] for recipe in service._get_verified_matches(recipes, intent)], [recipes[0]["name"]])
        self.assertEqual(service._get_verified_matches(recipes[1:], intent), recipes[1:])
        self.assertEqual(service._get_verified_matches(recipes, {"constraints": {}}), recipes)

    def test_optional_enhancement_cannot_add_generic_protein_or_fiber_tips(self):
        service = RecipeRAGService()
        service.recipe_enhancer.batch_enhance_recipes = Mock()
        recipe = {**self.record("Steamed Chicken with Vegetables and Rice"),
                  "verification_details": {"passes_verification": True, "relevance": "match"}}
        for constraint in ({"digestive_comfort": "gentle"}, {"preparation_effort": "low"}):
            results = service._enhance_verified_recipes([recipe], {"constraints": constraint})
            self.assertEqual(results[0]["instructions"], recipe["instructions"])
            self.assertNotIn("helpful_tips", results[0])
        service.recipe_enhancer.batch_enhance_recipes.assert_not_called()

    def test_explicitly_purchased_prepared_forms_are_not_counted_as_manual_work(self):
        recipe = {"ingredients": ["1 bag pre-cut broccoli florets", "1 cup packaged shredded carrots",
                                   "1 cup purchased diced apples", "1/4 cup pre-chopped pecans", "1 cup yogurt"],
                  "instructions": ["Stir together in a light serving bowl."]}
        verifier = RecipeVerifier()
        intent = {"constraints": {"preparation_effort": "low"}}
        self.assertTrue(verifier._finalize_verification(self.assessment(verifier, intent), recipe, intent)["passes_verification"])

    def test_brief_heating_and_long_passive_wait_are_not_automatically_prohibited(self):
        for instructions in (["Microwave purchased cooked rice for 2 minutes following the package directions."],
                             ["Combine ready-to-eat ingredients and refrigerate for 2 hours."]):
            self.assertEqual(audit_preparation_effort({"instructions": instructions}), [])

    def test_summaries_avoid_medical_guarantees_and_do_not_encourage_pushing_through(self):
        generator = ResponseGenerator()
        generator.initialize(Mock())
        recipes = [{"name": "Plain Rice and Egg Bowl"}]
        for constraints in ({"digestive_comfort": "gentle"}, {"preparation_effort": "low"},
                            {"digestive_comfort": "gentle", "preparation_effort": "low"}):
            result = generator.generate_personalized_response(STOMACH_QUERY, recipes, {"constraints": constraints})
            self.assertIn("1 ", result)
            if constraints.get("digestive_comfort"):
                self.assertIn("Food tolerance varies", result)
                self.assertIn("can't keep fluids down", result)
            if constraints.get("preparation_effort"):
                self.assertIn("Don't push through", result)
            generator.llm.predict.assert_not_called()

    def test_batch_verification_and_generation_preserve_existing_fallback_and_labels(self):
        service = RecipeRAGService()
        service.is_initialized = True
        service._contains_phi_like_content = Mock(return_value=False)
        service._is_small_talk_query = Mock(return_value=False)
        intent = {"query_type": "recipe_search", "constraints": {"preparation_effort": "low"}, "resolved_query": WEAKNESS_QUERY}
        service.intent_analyzer.understand_query_intent_with_context = Mock(return_value=intent)
        salad = {**self.record("Creamy Broccoli Apple Salad"), "recipe_id": "salad", "type": "Salad",
                 "database_record_found": True, "source_name": "AICR", "recipe_link": "https://www.aicr.org/recipe"}
        generated = {**salad, "recipe_id": "prepared-salad", "name": "Quick Broccoli Apple Bowl",
                     "ingredients": ["1 bag ready-to-eat pre-cut salad mix", "1 cup yogurt"],
                     "instructions": ["Combine in a lightweight bowl."], "database_record_found": False,
                     "generated_by_llm": True, "source_name": "", "recipe_link": ""}
        service.search_engine.multi_query_search = Mock(return_value=[salad])
        service.search_engine.rerank_with_constraint_filtering = Mock(side_effect=lambda recipes, *args, **kwargs: recipes)
        service._build_recipe_data_from_doc = Mock(side_effect=copy.deepcopy)
        service._get_database_search_candidates = Mock(return_value=[])
        service.recipe_enhancer.prepare_recipes_for_verification = Mock(side_effect=lambda recipes, intent: recipes)
        service.recipe_enhancer.batch_enhance_recipes = Mock(side_effect=lambda recipes, intent: recipes)
        service.recipe_enhancer.generate_fallback_recipes = Mock(return_value=[generated])
        assessment = self.assessment(service.recipe_verifier, {**intent, "recipe_request": WEAKNESS_QUERY})
        service.recipe_verifier.initialize(Mock(predict=Mock(return_value=json.dumps([{"id": 0, **assessment}]))))
        with patch("app.services.rag_service.safety_service.should_intercept", return_value=False), patch(
            "app.services.rag_service.aicr_service.validate_recipe_compliance", return_value={"overall_compliant": True}
        ):
            result = service.ask_question(WEAKNESS_QUERY)
        self.assertEqual(result["source_documents"][0]["source_label"], "AI Generated")
        self.assertEqual(result["source_documents"][0]["name"], generated["name"])
        references = service.recipe_enhancer.generate_fallback_recipes.call_args.kwargs["grounding_recipes"]
        self.assertEqual(references[0]["name"], salad["name"])
