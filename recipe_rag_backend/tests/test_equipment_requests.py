import copy
import json
import unittest
from unittest.mock import Mock, patch

from app.services.data_loader import DataLoader
from app.services.equipment_validation import audit_equipment, equipment_usage_evidence, explicit_equipment_constraints
from app.services.intent_analyzer import IntentAnalyzer
from app.services.rag_service import RecipeRAGService
from app.services.recipe_prompt_rules import EQUIPMENT_RULES, active_recipe_rules
from app.services.recipe_verifier import RecipeVerifier
from app.services.response_generator import ResponseGenerator
from app.services.search_engine import SearchEngine


QUERY = "What meals can I make with an air fryer?"
CONSTRAINTS = {"equipment_required": ["air fryer"], "equipment_only": []}


class EquipmentIntentTests(unittest.TestCase):
    def test_exact_query_routes_to_recipes_and_requires_use_not_exclusivity(self):
        analyzer = IntentAnalyzer()
        parsed = analyzer._get_fallback_intent_data(QUERY)
        parsed["query_type"] = "food_guidance"
        parsed["constraints"]["equipment_only"] = ["air fryer"]
        intent = analyzer._post_process_intent(QUERY, parsed)
        self.assertEqual(intent["query_type"], "recipe_search")
        self.assertEqual(intent["constraints"]["equipment_required"], ["air fryer"])
        self.assertEqual(intent["constraints"]["equipment_only"], [])
        self.assertEqual(intent["constraints"]["meal_suitability"], "meal")

    def test_common_aliases_and_explicit_only(self):
        for query, expected in (("Recipes using only my air-fryer", "air fryer"),
                                ("Meals with an Instant Pot only", "pressure cooker"),
                                ("Show crockpot recipes", "slow cooker")):
            with self.subTest(query=query):
                result = explicit_equipment_constraints(query)
                self.assertEqual(result["equipment_required"], [expected])
                self.assertEqual(result["equipment_only"], [] if "crockpot" in query else [expected])

    def test_exclusions_ownership_options_do_not_become_required_use(self):
        for query in ("Meals without an air fryer", "Don't use an air fryer", "I own an air fryer",
                      "Meals using an oven or an air fryer", "Use an oven instead of an air fryer",
                      "An air fryer is optional", "Meals in a microwave-safe bowl"):
            self.assertEqual(explicit_equipment_constraints(query), {}, query)

    def test_multiple_appliances_and_additive_followup_do_not_drop_required_use(self):
        self.assertEqual(explicit_equipment_constraints("Meals using an air fryer and a blender")["equipment_required"],
                         ["air fryer", "blender"])
        analyzer = IntentAnalyzer()
        parsed = analyzer._get_fallback_intent_data("Meals using an air fryer and a blender")
        parsed["constraints"]["equipment_required"] = ["air fryer", "blender"]
        analyzer.initialize(Mock(predict=Mock(return_value=json.dumps(parsed))))
        result = analyzer.understand_query_intent_with_context("Also use a blender", [{"role": "user", "content": QUERY}])
        self.assertEqual(result["constraints"]["equipment_required"], ["air fryer", "blender"])

    def test_standalone_equipment_request_does_not_keep_prior_leftover_task(self):
        analyzer = IntentAnalyzer()
        analyzer.initialize(Mock(predict=Mock(return_value=json.dumps(analyzer._get_fallback_intent_data(QUERY)))))
        result = analyzer.understand_query_intent_with_context(QUERY, [
            {"role": "user", "content": "Show recipes that don't require finishing in one sitting"},
            {"role": "assistant", "content": "Mediterranean Bean Salad keeps well for later servings."},
        ])
        self.assertEqual(result["context_action"], "new_request")
        self.assertFalse(result["constraints"]["leftover_friendly"])
        self.assertEqual(result["constraints"]["equipment_required"], ["air fryer"])
        self.assertNotIn("Mediterranean Bean Salad", analyzer.llm.predict.call_args.args[0])

    def test_more_retains_equipment_and_rules_are_active_only_when_requested(self):
        analyzer = IntentAnalyzer()
        parsed = analyzer._get_fallback_intent_data(QUERY)
        parsed["constraints"].update(CONSTRAINTS)
        analyzer.initialize(Mock(predict=Mock(return_value=json.dumps(parsed))))
        result = analyzer.understand_query_intent_with_context("More recipes", [{"role": "user", "content": QUERY}])
        self.assertEqual(result["context_action"], "continue_request")
        self.assertEqual(result["constraints"]["equipment_required"], ["air fryer"])
        self.assertIn(EQUIPMENT_RULES, active_recipe_rules(result))
        self.assertNotIn(EQUIPMENT_RULES, active_recipe_rules({"constraints": {}}))
        self.assertIn("air fryer cooking recipes", SearchEngine()._generate_contextual_search_queries(result))


class EquipmentEvidenceTests(unittest.TestCase):
    def test_salad_cannot_pass_using_title_description_or_optional_tips(self):
        for name in ("Mediterranean Bean Salad", "Tuna, Brown Rice, and White Bean Salad"):
            recipe = {"name": name, "description": "Make this using an air fryer.",
                      "ingredients": ["1 can beans", "1 cup cooked rice"],
                      "instructions": ["Mix the beans and rice with the dressing. Serve cold."],
                      "helpful_tips": ["Air-fry the beans for 10 minutes."]}
            self.assertTrue(audit_equipment(recipe, CONSTRAINTS))

    def test_setup_negations_and_hypothetical_alternatives_do_not_pass(self):
        cases = [
            ["Preheat an air fryer to 180 C.", "Mix beans and rice and serve."],
            ["Mix beans and rice.", "Optionally, air-fry the beans."],
            ["Don't air-fry the beans; mix and serve."],
            ["You could cook the beans in an air fryer."],
            ["Preheat an air fryer.", "Cook the beans in a saucepan.", "Serve."],
            ["Cook the beans in the oven, not in the air fryer."],
        ]
        for instructions in cases:
            with self.subTest(instructions=instructions):
                self.assertTrue(audit_equipment({"instructions": instructions}, CONSTRAINTS))

    def test_explicit_and_contextual_cooking_steps_are_supported(self):
        for instructions in (
            ["Air-fry tofu at 180 C for 15 minutes, until golden."],
            ["Place the tofu in the air fryer basket.", "Cook at 180 C for 15 minutes, until golden."],
            ["Arrange the tofu in the air fryer basket and cook until golden."],
            ["Preheat the air fryer.", "Place the chicken in the basket.", "Cook until no longer pink and check doneness."],
        ):
            self.assertEqual(audit_equipment({"instructions": instructions}, CONSTRAINTS), [], instructions)

    def test_other_common_appliances_and_multiple_requirements(self):
        for equipment, instructions in (
            ("microwave", ["Microwave the vegetables for 4 minutes, until tender."]),
            ("slow cooker", ["Put lentils in a crockpot.", "Cover and cook on LOW until tender."]),
            ("blender", ["Add yogurt and fruit to a blender.", "Blend until smooth."]),
        ):
            with self.subTest(equipment=equipment):
                recipe = {"instructions": instructions}
                self.assertEqual(audit_equipment(recipe, {"equipment_required": [equipment]}), [])
                self.assertTrue(audit_equipment(recipe, {"equipment_required": [equipment, "air fryer"]}))

    def test_no_equipment_requirement_leaves_ordinary_recipes_unchanged(self):
        self.assertEqual(audit_equipment({"instructions": ["Mix and serve."]}, {}), [])
        self.assertEqual(audit_equipment({}, {"equipment_required": None}), [])

    def test_database_air_fryer_recipes_have_actual_preparation_evidence(self):
        loader = DataLoader()
        loader.load_data()
        rows = loader.df[loader.df["Name"].str.startswith("Air Fryer")]
        self.assertEqual(len(rows), 3)
        for _, record in rows.iterrows():
            recipe = {"instructions": record["Directions"].splitlines()}
            self.assertEqual(audit_equipment(recipe, CONSTRAINTS), [], record["Name"])

    def test_equipment_evidence_prioritizes_csv_recipes_before_generation(self):
        service = RecipeRAGService()
        service.data_loader.load_data()
        recipes = service._get_database_search_candidates(QUERY, {"constraints": CONSTRAINTS}, set(), 3)
        self.assertEqual(len(recipes), 3)
        self.assertTrue(all(equipment_usage_evidence(recipe, ["air fryer"]) for recipe in recipes))


class EquipmentVerificationTests(unittest.TestCase):
    def test_side_only_categories_need_adaptation_for_meals_but_remain_valid_sides(self):
        verifier = RecipeVerifier()
        for category in ("Side Dishes", "Appetizers, Snacks, Side Dishes", "Main Dishes, Side Dishes", "Entree"):
            for meal in (True, False):
                with self.subTest(category=category, meal=meal):
                    intent = {"constraints": {**CONSTRAINTS, "meal_suitability": "meal" if meal else None}}
                    assessment = {"relevance": "match", "constraint_violations": [], "constraint_checks": {
                        key: {"status": "pass", "evidence": "Air-fryer preparation."} for key in verifier._required_checks(intent)
                    }}
                    recipe = {"type": category, "instructions": ["Air-fry potatoes until golden."]}
                    result = verifier._finalize_verification(assessment, recipe, intent)
                    self.assertEqual(result["passes_verification"], not meal or category in {"Main Dishes, Side Dishes", "Entree"})

    def test_equipment_summary_does_not_add_unrequested_storage_claims(self):
        generator = ResponseGenerator()
        generator.initialize(Mock())
        result = generator.generate_personalized_response(
            QUERY, [{"name": "Air Fryer Tofu Bowl"}], {"constraints": CONSTRAINTS}
        )
        self.assertIn("1 recipe", result)
        self.assertIn("air fryer", result)
        self.assertIn("Air Fryer Tofu Bowl", result)
        self.assertNotIn("sittings", result)
        generator.llm.predict.assert_not_called()

    def test_backend_overrules_fabricated_equipment_pass_in_both_verification_paths(self):
        intent = {"recipe_request": QUERY, "constraints": CONSTRAINTS}
        recipe = {"name": "Mediterranean Bean Salad", "ingredients": ["1 can beans"],
                  "instructions": ["Mix beans and dressing. Serve cold."]}
        verifier = RecipeVerifier()
        assessment = {"id": 0, "relevance": "match", "constraint_violations": [], "constraint_checks": {
            key: {"status": "pass", "evidence": "Cook beans in an air fryer."} for key in verifier._required_checks(intent)
        }}
        self.assertIn("constraints.equipment_required[0]", assessment["constraint_checks"])
        verifier.initialize(Mock(predict=Mock(return_value=json.dumps(assessment))))
        result = verifier.verify_recipe_against_constraints(recipe, intent)
        self.assertFalse(result["passes_verification"])
        self.assertEqual(result["relevance"], "adaptable")
        guidelines = Mock(validate_recipe_compliance=Mock(return_value={"overall_compliant": True}))
        verifier.llm.predict.return_value = json.dumps([assessment])
        results = verifier.batch_verify_recipes([copy.deepcopy(recipe)], intent, guidelines)
        self.assertFalse(results[0]["verification_details"]["passes_verification"])
        guidelines.validate_recipe_compliance.assert_not_called()

    def test_rejected_salad_reaches_existing_database_guided_generation(self):
        service = RecipeRAGService()
        service.is_initialized = True
        service._contains_phi_like_content = Mock(return_value=False)
        service._is_small_talk_query = Mock(return_value=False)
        intent = {"resolved_query": QUERY, "query_type": "recipe_search", "constraints": CONSTRAINTS}
        service.intent_analyzer.understand_query_intent_with_context = Mock(return_value=intent)
        salad = {"recipe_id": "salad", "name": "Mediterranean Bean Salad", "type": "Main Dish",
                 "ingredients": ["1 can chickpeas", "1 cup vegetables"], "instructions": ["Mix and serve."],
                 "database_record_found": True, "source_name": "AICR", "recipe_link": "https://www.aicr.org/recipe"}
        generated = {**salad, "recipe_id": "air-fryer-bowl", "name": "Air Fryer Chickpea Bowl",
                     "database_record_found": False, "source_name": "", "recipe_link": "", "generated_by_llm": True,
                     "instructions": ["Air-fry chickpeas and vegetables at 180 C until tender, about 15 minutes."]}
        service.search_engine.multi_query_search = Mock(return_value=[salad])
        service.search_engine.rerank_with_constraint_filtering = Mock(side_effect=lambda docs, *args, **kwargs: docs)
        service._build_recipe_data_from_doc = Mock(side_effect=copy.deepcopy)
        service._get_database_search_candidates = Mock(return_value=[])
        service.recipe_enhancer.prepare_recipes_for_verification = Mock(side_effect=lambda recipes, intent: recipes)
        service.recipe_enhancer.batch_enhance_recipes = Mock(side_effect=lambda recipes, intent: recipes)
        service.recipe_enhancer.generate_fallback_recipes = Mock(return_value=[generated])
        service.response_generator.generate_personalized_response = Mock(return_value="Open the air-fryer recipe.")
        assessment = {"id": 0, "relevance": "match", "constraint_violations": [], "constraint_checks": {
            key: {"status": "pass", "evidence": "Air-fryer preparation."}
            for key in service.recipe_verifier._required_checks({**intent, "recipe_request": QUERY})
        }}
        service.recipe_verifier.initialize(Mock(predict=Mock(return_value=json.dumps([assessment]))))
        with patch("app.services.rag_service.safety_service.should_intercept", return_value=False), patch(
            "app.services.rag_service.aicr_service.validate_recipe_compliance", return_value={"overall_compliant": True}
        ):
            result = service.ask_question(QUERY)
        self.assertEqual(result["source_documents"][0]["name"], generated["name"])
        self.assertEqual(result["source_documents"][0]["source_label"], "AI Generated")
        references = service.recipe_enhancer.generate_fallback_recipes.call_args.kwargs["grounding_recipes"]
        self.assertEqual(references[0]["name"], salad["name"])
