import copy
import json
import unittest
from pathlib import Path
from unittest.mock import Mock

from app.services.aicr_guidelines_service import aicr_service
from app.services.data_loader import DataLoader
from app.services.intent_analyzer import IntentAnalyzer
from app.services.preparation_validation import explicit_hand_effort, explicit_preparation_position
from app.services.rag_service import RecipeRAGService
from app.services.recipe_enhancer import RecipeEnhancer
from app.services.recipe_verifier import RecipeVerifier


SEATED_QUERY = "Show meals I can prepare sitting down."
HAND_QUERY = "What recipes require minimal hand strength to prepare?"


def assembly_recipe():
    return {
        "name": "Ready-to-Eat Bean Wrap", "type": "Main Dish", "generated_by_llm": True,
        "ingredients": ["1 ready-to-eat bean pouch in manageable packaging", "1 whole-wheat tortilla",
                        "1 cup purchased prewashed shredded lettuce"],
        "instructions": ["Arrange ingredients and a light bowl within reach on a stable table.",
                         "Gently mix the ready-to-eat beans with the lettuce in the bowl.",
                         "Spoon onto the tortilla, fold loosely, and serve."],
    }


class PreparationAccessibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.loader = DataLoader()
        cls.loader.load_data(Path(__file__).parents[1] / "app/data/Recipe.csv")

    def intent(self, query):
        analyzer = IntentAnalyzer()
        parsed = analyzer._get_fallback_intent_data(query)
        parsed["query_type"] = "food_guidance"
        return analyzer._post_process_intent(query, parsed)

    def assessment(self, recipe, intent):
        assessment = {
            "id": 0, "relevance": "match", "constraint_violations": [],
            "constraint_checks": {key: {"status": "pass", "evidence": "Model claims every requirement is satisfied."}
                                  for key in RecipeVerifier()._required_checks(intent)},
        }
        for field, value, check_key in (("preparation_position", "seated", "seated_preparation_check"),
                                         ("hand_effort", "low", "hand_effort_check")):
            if intent["constraints"].get(field) == value:
                assessment[check_key] = {
                    "step_checks": [{"instruction_index": index, "status": "pass", "quote": step}
                                    for index, step in enumerate(recipe["instructions"])],
                    "unresolved_dependencies": [], "conflicting_guidance": [],
                }
        return assessment

    def verify(self, recipe, query=SEATED_QUERY, assessment=None, batch=True):
        intent = self.intent(query)
        assessment = self.assessment(recipe, intent) if assessment is None else assessment
        verifier = RecipeVerifier()
        verifier.initialize(Mock(predict=Mock(return_value=json.dumps([assessment] if batch else assessment))))
        if batch:
            return verifier.batch_verify_recipes([copy.deepcopy(recipe)], intent, aicr_service)[0]["verification_details"]
        return verifier.verify_recipe_against_constraints(recipe, intent)

    def test_exact_prompts_route_to_recipes_not_generic_advice(self):
        for query, field, value in ((SEATED_QUERY, "preparation_position", "seated"), (HAND_QUERY, "hand_effort", "low")):
            intent = self.intent(query)
            self.assertEqual(intent["query_type"], "recipe_search")
            self.assertEqual(intent["constraints"][field], value)
            for unrelated in ("chewing_effort", "preparation_mode", "attention_level", "time_max_minutes"):
                self.assertIsNone(intent["constraints"][unrelated])
            self.assertFalse(intent["constraints"]["leftover_friendly"])
            self.assertEqual(intent["cancer_patient_specific"]["symptoms"], [])
        self.assertIsNone(self.intent(SEATED_QUERY)["constraints"]["hand_effort"])
        self.assertIsNone(self.intent(HAND_QUERY)["constraints"]["preparation_position"])

    def test_recipe_discovery_paraphrases_and_advice_are_distinct(self):
        for query in ("What meals can I prepare seated?", "Suggest dinners I can make while sitting.", "Give me lunch ideas.",
                      "What meals use frozen ingredients from start to finish?"):
            self.assertEqual(self.intent(query)["query_type"], "recipe_search")
        self.assertEqual(self.intent("What meals use frozen ingredients from start to finish?")["constraints"]["ingredient_storage"], "frozen_only")
        for query in ("Give me tips for preparing meals sitting down", "Explain how to organize a seated workspace",
                      "Show foods that taste good warm but not hot"):
            self.assertEqual(self.intent(query)["query_type"], "food_guidance")
        analyzer = IntentAnalyzer()
        for route in ("recipe_question", "recipe_adaptation", "clarification"):
            parsed = analyzer._get_fallback_intent_data(SEATED_QUERY)
            parsed["query_type"] = route
            self.assertEqual(analyzer._post_process_intent(SEATED_QUERY, parsed)["query_type"], route)

    def test_physical_requirements_are_not_inferred_from_other_requests(self):
        for query in ("Meals I can finish in one sitting", "Meals without standing over the stove", "I have arthritis"):
            self.assertIsNone(explicit_preparation_position(query))
            self.assertIsNone(explicit_hand_effort(query))

    def test_user_requirements_survive_followups_and_remain_chat_local(self):
        analyzer = IntentAnalyzer()
        analyzer.initialize(Mock(predict=Mock(side_effect=lambda prompt: json.dumps(analyzer._get_fallback_intent_data("More recipes")))))
        history = [{"role": "user", "content": SEATED_QUERY}, {"role": "user", "content": HAND_QUERY}]
        intent = analyzer.understand_query_intent_with_context("More recipes", history)
        self.assertEqual(intent["constraints"]["preparation_position"], "seated")
        self.assertEqual(intent["constraints"]["hand_effort"], "low")
        self.assertIsNone(analyzer.understand_query_intent("Dinner recipes")["constraints"]["hand_effort"])
        assistant_only = [{"role": "assistant", "content": SEATED_QUERY + HAND_QUERY}]
        intent = analyzer.understand_query_intent_with_context("More recipes", assistant_only)
        self.assertIsNone(intent["constraints"]["preparation_position"])
        self.assertIsNone(intent["constraints"]["hand_effort"])

    def test_withdrawals_and_reset_override_stale_model_resolution(self):
        analyzer = IntentAnalyzer()
        for current, expected in (("Standing is fine now", (None, "low")),
                                  ("Remove the hand-strength restriction", ("seated", None)),
                                  ("Start over: soup recipes", (None, None))):
            resolved = SEATED_QUERY + " " + HAND_QUERY
            intent = analyzer._post_process_intent(resolved, analyzer._get_fallback_intent_data(resolved), current_query=current)
            self.assertEqual((intent["constraints"]["preparation_position"], intent["constraints"]["hand_effort"]), expected)

    def test_reported_database_recipes_fail_seated_check_despite_positive_model(self):
        service = RecipeRAGService()
        for name in ("French-Style Bean Stew", "BBQ Peach and Chicken Naan Pizzas", "Moroccan Chickpea Sorghum Bowl"):
            recipe = service._build_recipe_data_from_record(self.loader.get_recipe_record(name))
            for batch in (False, True):
                with self.subTest(name=name, batch=batch):
                    details = self.verify(recipe, batch=batch)
                    self.assertFalse(details["passes_verification"])
                    self.assertEqual(details["relevance"], "adaptable")

    def test_tabletop_assembly_passes_each_requirement_and_their_combination(self):
        for query in (SEATED_QUERY, HAND_QUERY, SEATED_QUERY + " " + HAND_QUERY):
            for generated in (True, False):
                recipe = assembly_recipe()
                recipe["generated_by_llm"] = generated
                self.assertTrue(self.verify(recipe, query)["passes_verification"])

    def test_seated_preparation_does_not_ban_light_cutting(self):
        recipe = assembly_recipe()
        recipe["instructions"].insert(1, "Slice a soft banana on a stable cutting board at the table.")
        self.assertTrue(self.verify(recipe)["passes_verification"])

    def test_all_steps_need_valid_nonduplicated_citations_and_pass_status(self):
        recipe = assembly_recipe()
        for query, key in ((SEATED_QUERY, "seated_preparation_check"), (HAND_QUERY, "hand_effort_check")):
            for change in ("missing", "unknown", "invented", "duplicate", "dependency"):
                assessment = self.assessment(recipe, self.intent(query))
                check = assessment[key]
                if change == "missing":
                    check["step_checks"].pop()
                elif change == "unknown":
                    check["step_checks"][0]["status"] = "unknown"
                elif change == "invented":
                    check["step_checks"][0]["quote"] = "No physical effort needed."
                elif change == "duplicate":
                    check["step_checks"].append(check["step_checks"][0])
                else:
                    check["unresolved_dependencies"] = ["Requires an unspecified adaptive opener"]
                self.assertFalse(self.verify(recipe, query, assessment)["passes_verification"])

    def test_missing_accessibility_assessment_has_one_bounded_completion(self):
        for query, key in ((SEATED_QUERY, "seated_preparation_check"), (HAND_QUERY, "hand_effort_check")):
            recipe = assembly_recipe()
            initial = self.assessment(recipe, self.intent(query))
            completion = {key: initial.pop(key)}
            verifier = RecipeVerifier()
            model = Mock(predict=Mock(side_effect=[json.dumps(initial), json.dumps(completion)]))
            verifier.initialize(model)
            details = verifier.verify_recipe_against_constraints(recipe, self.intent(query))
            self.assertTrue(details["passes_verification"])
            self.assertEqual(model.predict.call_count, 2)

    def test_seated_heating_and_hand_force_conflicts_in_every_guidance_field(self):
        for field in ("instructions", "helpful_tips", "ingredient_adaptations", "storage_instructions", "source_notes"):
            for query, instruction in ((SEATED_QUERY, "Roast the vegetables on the top oven rack."),
                                       (HAND_QUERY, "Squeeze fresh lime over the dish.")):
                recipe = assembly_recipe()
                recipe[field] = [instruction] if field in {"instructions", "helpful_tips", "ingredient_adaptations"} else instruction
                self.assertFalse(self.verify(recipe, query)["passes_verification"])

    def test_minimal_hand_strength_rejects_forceful_steps_not_just_time(self):
        for step in ("Knead the dough for 5 minutes.", "Open the vacuum-sealed jar.", "Open the can of beans.",
                     "Grate the carrots.", "Chop the raw squash.", "Lift the heavy cast-iron pan.", "Mash the potatoes."):
            recipe = assembly_recipe()
            recipe["instructions"].append(step)
            self.assertFalse(self.verify(recipe, HAND_QUERY)["passes_verification"])

    def test_no_constraints_keeps_existing_recipe_behavior(self):
        recipe = assembly_recipe()
        recipe["instructions"] = ["Knead dough and bake in an oven."]
        self.assertTrue(self.verify(recipe, "Show recipes")["passes_verification"])

    def test_generation_and_repair_prompts_include_distinct_constraints(self):
        enhancer = RecipeEnhancer()
        model = Mock(predict=Mock(return_value=json.dumps([assembly_recipe()])))
        enhancer.initialize(model, aicr_service)
        intent = self.intent(SEATED_QUERY + " " + HAND_QUERY)
        enhancer.generate_fallback_recipes(SEATED_QUERY, intent, [])
        prompt = model.predict.call_args.args[0]
        self.assertIn('"preparation_position": "seated"', prompt)
        self.assertIn('"hand_effort": "low"', prompt)
        self.assertIn("Do not infer arthritis", prompt)
        rejected = assembly_recipe()
        rejected["verification_details"] = {"passes_verification": False, "constraint_violations": ["Forceful opening"]}
        enhancer.generate_fallback_recipes(SEATED_QUERY, intent, [rejected])
        self.assertIn("Forceful opening", model.predict.call_args.args[0])
        self.assertIn("hand_effort='low'", model.predict.call_args.args[0])

    def service(self, query, database_recipes):
        service = RecipeRAGService()
        service.is_initialized = True
        service._contains_phi_like_content = Mock(return_value=False)
        intent = self.intent(query)
        service.intent_analyzer.understand_query_intent_with_context = Mock(return_value=intent)
        service.response_generator.answer_food_guidance = Mock(side_effect=AssertionError("Must return recipe cards"))
        service.search_engine.multi_query_search = Mock(return_value=database_recipes)
        service.search_engine.rerank_with_constraint_filtering = Mock(side_effect=lambda recipes, *args, **kwargs: recipes)
        service._build_recipe_data_from_doc = Mock(side_effect=copy.deepcopy)
        service._get_database_search_candidates = Mock(return_value=[])
        service.recipe_enhancer.prepare_recipes_for_verification = Mock(side_effect=lambda recipes, intent: recipes)
        service.recipe_enhancer.batch_enhance_recipes = Mock(side_effect=lambda recipes, intent: recipes)
        service.recipe_enhancer.generate_fallback_recipes = Mock(return_value=[assembly_recipe()])

        def assess(prompt):
            recipes = json.loads(prompt.split("RECIPES TO VERIFY:\n", 1)[1].split("\n\nUSER REQUIREMENTS:", 1)[0])
            return json.dumps([self.assessment(recipe, intent) for recipe in recipes])

        service.recipe_verifier.initialize(Mock(predict=Mock(side_effect=assess)))
        return service

    def test_route_rejects_reported_recipes_and_uses_database_guided_generation(self):
        builder = RecipeRAGService()
        recipe = builder._build_recipe_data_from_record(self.loader.get_recipe_record("French-Style Bean Stew"))
        service = self.service(SEATED_QUERY, [recipe])
        result = service.ask_question(SEATED_QUERY)
        self.assertEqual(result["matches_found"], 1)
        self.assertEqual(result["source_documents"][0]["source_label"], "AI Generated")
        self.assertIn("seated preparation", result["response"])
        self.assertEqual(service.recipe_enhancer.generate_fallback_recipes.call_args.kwargs["grounding_recipes"][0]["name"], recipe["name"])

    def test_database_first_and_low_force_summary_are_preserved(self):
        recipe = assembly_recipe()
        recipe.update({"generated_by_llm": False, "database_record_found": True, "source_name": "AICR",
                       "recipe_link": "https://www.aicr.org/cancer-prevention/recipes/example/"})
        service = self.service(HAND_QUERY, [recipe])
        result = service.ask_question(HAND_QUERY)
        service.recipe_enhancer.generate_fallback_recipes.assert_not_called()
        self.assertEqual(result["source_documents"][0]["source_label"], "Sourced from AICR")
        self.assertIn("low-force preparation", result["response"])

    def test_failing_final_tips_are_removed_before_display(self):
        service = self.service(HAND_QUERY, [])
        recipe = assembly_recipe()
        recipe.update({"helpful_tips": ["Crush nuts for a garnish."], "guidance_generated": True})
        result = service._validate_final_recipes([recipe], self.intent(HAND_QUERY))
        self.assertEqual(len(result), 1)
        self.assertFalse(result[0].get("helpful_tips"))


if __name__ == "__main__":
    unittest.main()
