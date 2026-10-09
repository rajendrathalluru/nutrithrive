import copy
import json
import unittest
from unittest.mock import Mock

from app.services.intent_analyzer import IntentAnalyzer
from app.services.recipe_verifier import RecipeVerifier
from app.services.recipe_prompt_rules import COOKING_ATTENTION_RULES


class VerificationContractTests(unittest.TestCase):
    def setUp(self):
        self.recipe = {
            "name": "Lentil and Chickpea Soup",
            "ingredients": ["1 cup dried lentils", "1 can diced tomatoes", "1 can chickpeas", "water"],
            "instructions": ["Simmer in water until lentils are tender."],
        }
        self.intent = {"constraints": {"ingredient_storage": "pantry_based"}}
        self.assessment = {
            "id": 0, "relevance": "match", "constraint_violations": [],
            "constraint_checks": {
                "constraints.ingredient_storage": {"status": "pass", "evidence": "Dry lentils and canned vegetables."}
            },
            "ingredient_storage_check": {
                "required_non_pantry_ingredients": [], "unspecified_ingredient_forms": [], "conflicting_guidance": [],
            },
        }

    def verify(self, assessment=None, intent=None):
        verifier = RecipeVerifier()
        verifier.initialize(Mock(predict=Mock(return_value=json.dumps(
            self.assessment if assessment is None else assessment
        ))))
        return verifier.verify_recipe_against_constraints(self.recipe, self.intent if intent is None else intent)

    def test_backend_owns_verdict_instead_of_contradictory_model_boolean(self):
        self.assessment.update({"passes_verification": False, "verification_score": 0})
        result = self.verify()
        self.assertTrue(result["passes_verification"])
        self.assertTrue(result["meets_preferences"])
        self.assertEqual(result["verification_score"], 100)

    def test_missing_failed_unknown_and_evidenceless_checks_fail_closed(self):
        for check in (None, {}, {"status": "pass"}, {"status": "pass", "evidence": ""},
                      {"status": "unknown", "evidence": "Form unspecified"},
                      {"status": "fail", "evidence": "Requires fresh produce"}):
            with self.subTest(check=check):
                self.assessment["constraint_checks"]["constraints.ingredient_storage"] = check
                self.assessment["passes_verification"] = True
                self.assertFalse(self.verify()["passes_verification"])

    def test_allergen_and_equipment_constraints_cannot_be_dropped(self):
        for key, value in (("allergens_to_avoid", ["peanuts"]), ("equipment_only", ["microwave"])):
            with self.subTest(key=key):
                intent = copy.deepcopy(self.intent)
                intent["constraints"][key] = value
                result = self.verify(intent=intent)
                self.assertFalse(result["passes_verification"])
                self.assertTrue(any(key in reason for reason in result["constraint_violations"]))

    def test_legacy_boolean_without_requirement_evidence_does_not_pass(self):
        del self.assessment["constraint_checks"]
        self.assessment["passes_verification"] = True
        self.assertFalse(self.verify()["passes_verification"])

    def test_unrelated_recipe_and_reported_violations_always_fail(self):
        self.assessment["relevance"] = "unrelated"
        self.assertFalse(self.verify()["passes_verification"])
        self.assessment["relevance"] = "match"
        self.assessment["constraint_violations"] = ["Contains an excluded ingredient"]
        self.assertFalse(self.verify()["passes_verification"])

    def test_explicit_fresh_ingredients_override_positive_model_checks(self):
        self.recipe["ingredients"].append("1 fresh bell pepper")
        self.assertFalse(self.verify()["passes_verification"])

    def test_expected_checks_cover_preferences_additional_criteria_and_zero_limits(self):
        checks = RecipeVerifier()._required_checks({
            "recipe_request": "Chinese recipes without chopping",
            "constraints": {"time_max_minutes": 0, "leftover_friendly": False, "skill_level": None},
            "preferences": {"cuisine_types": ["Chinese"], "flavor_profiles": []},
            "search_strategy": {"must_match_criteria": ["no chopping"]},
        })
        self.assertEqual(set(checks), {"recipe_request", "constraints.time_max_minutes", "preferences.cuisine_types", "search_strategy.must_match_criteria"})

    def test_original_request_is_checked_even_without_named_constraints(self):
        query = "What foods don’t change texture when reheated?"
        intent = {"recipe_request": query, "constraints": {}, "search_strategy": {"must_match_criteria": []}}
        self.assertEqual(RecipeVerifier()._required_checks(intent), {"recipe_request": query})
        for status, passes in ((None, False), ("unknown", False), ("fail", False), ("pass", True)):
            with self.subTest(status=status):
                assessment = {"relevance": "match", "constraint_violations": [], "constraint_checks": {}}
                if status:
                    assessment["constraint_checks"]["recipe_request"] = {"status": status, "evidence": "Recipe preparation assessment."}
                self.assertEqual(self.verify(assessment, intent)["passes_verification"], passes)

    def test_batching_bounds_output_and_checks_every_candidate(self):
        verifier = RecipeVerifier()

        def response(prompt):
            example = prompt.split("Example shape (replace all example values with your assessment, never copy example evidence):\n")[1].split("\n")[0]
            self.assertEqual(json.loads(example)[0]["id"], 0)
            count = 3 if "Verify ALL 3 recipes." in prompt else 1
            return json.dumps([{**self.assessment, "id": index} for index in range(count)])

        verifier.initialize(Mock(predict=Mock(side_effect=response)))
        guidelines = Mock(validate_recipe_compliance=Mock(return_value={"overall_compliant": True}))
        results = verifier.batch_verify_recipes([copy.deepcopy(self.recipe) for _ in range(7)], self.intent, guidelines)
        self.assertEqual(len(results), 7)
        self.assertTrue(all(recipe["verification_details"]["passes_verification"] for recipe in results))
        self.assertEqual(verifier.llm.predict.call_count, 3)

    def test_followup_cannot_skip_original_user_goal_when_rewrite_omits_it(self):
        intent = {
            "recipe_request": "Make a recipe with lentils and carrots",
            "user_request_context": [
                "What foods will still turn out okay even if I don't cook them exactly right?",
                "Make a recipe with those ingredients",
            ],
        }
        assessment = {
            "relevance": "match", "constraint_violations": [],
            "constraint_checks": {"recipe_request": {"status": "pass", "evidence": "Uses lentils and carrots."}},
        }
        self.assertFalse(self.verify(assessment, intent)["passes_verification"])
        assessment["constraint_checks"]["user_request_context"] = {
            "status": "pass", "evidence": "Simmer until tender rather than relying on an exact endpoint time.",
        }
        self.assertTrue(self.verify(assessment, intent)["passes_verification"])

    def test_each_explicitly_required_ingredient_needs_its_own_check(self):
        intent = {"constraints": {"ingredients_must_use": ["barley", "tofu", "spinach"]}}
        checks = RecipeVerifier()._required_checks(intent)
        self.assertEqual(checks, {
            "constraints.ingredients_must_use[0]": "barley",
            "constraints.ingredients_must_use[1]": "tofu",
            "constraints.ingredients_must_use[2]": "spinach",
        })
        assessment = {
            "relevance": "match", "constraint_violations": [],
            "constraint_checks": {"constraints.ingredients_must_use[1]": {"status": "pass", "evidence": "Tofu is present."}},
        }
        result = self.verify(assessment, intent)
        self.assertFalse(result["passes_verification"])
        self.assertTrue(any("ingredients_must_use[0]" in violation for violation in result["constraint_violations"]))
        self.assertTrue(any("ingredients_must_use[2]" in violation for violation in result["constraint_violations"]))

    def test_attention_is_verified_against_instructions_not_total_time(self):
        intent = {"constraints": {"attention_level": "low"}}
        assessment = {
            "relevance": "match", "constraint_violations": [],
            "constraint_checks": {"constraints.attention_level": {
                "status": "pass", "evidence": "Bake for 45 minutes, checking once halfway through."
            }},
        }
        self.assertTrue(self.verify(assessment, intent)["passes_verification"])
        assessment["constraint_checks"]["constraints.attention_level"] = {
            "status": "fail", "evidence": "Stir constantly for 20 minutes."
        }
        self.assertFalse(self.verify(assessment, intent)["passes_verification"])


class AttentionIntentTests(unittest.TestCase):
    def test_hands_off_paraphrases_survive_empty_model_intent(self):
        for query in (
            "What recipes don’t require constant attention?", "Meals without constant stirring",
            "Hands-off recipes", "Meals that need minimal monitoring", "Recipes that do not need much attention",
        ):
            with self.subTest(query=query):
                result = IntentAnalyzer()._post_process_intent(query, {})
                self.assertEqual(result["constraints"]["attention_level"], "low")
                self.assertIn("slow cooker", result["search_strategy"]["search_keywords"])
                self.assertNotIn("time_max_minutes", result["constraints"])
                self.assertEqual(result["constraints"]["equipment_only"], [])
                self.assertIsNone(result["constraints"]["ingredient_storage"])

    def test_pantry_expansion_survives_missing_model_search_terms(self):
        result = IntentAnalyzer()._post_process_intent("Show meals that rely on shelf-stable foods.", {
            "constraints": {"ingredient_storage": "pantry_based"}
        })
        self.assertIn("canned beans", result["search_strategy"]["search_keywords"])
        self.assertIn("dried lentils", result["search_strategy"]["enhanced_query"])
        self.assertIsNone(result["constraints"]["attention_level"])

    def test_unrelated_requests_do_not_acquire_attention_constraints(self):
        result = IntentAnalyzer()._post_process_intent("Quick chicken stir fry", {})
        self.assertIsNone(result["constraints"]["attention_level"])

    def test_pantry_request_does_not_inherit_attention_from_prompt_examples(self):
        result = IntentAnalyzer()._post_process_intent("Show meals that rely on shelf-stable foods.", {
            "constraints": {"ingredient_storage": "pantry_based", "attention_level": "low"}
        })
        self.assertIsNone(result["constraints"]["attention_level"])
        self.assertNotIn("slow cooker", result["search_strategy"]["search_keywords"])

    def test_attention_rules_are_shared_by_intent_and_verification(self):
        self.assertIn(COOKING_ATTENTION_RULES, IntentAnalyzer()._build_intent_prompt("Hands-off recipes"))
        self.assertIn(COOKING_ATTENTION_RULES, RecipeVerifier()._build_individual_verification_prompt(
            {}, {"constraints": {"attention_level": "low"}}
        ))

    def test_follow_up_retains_resolved_attention_and_other_chat_does_not(self):
        analyzer = IntentAnalyzer()
        resolved = analyzer._get_fallback_intent_data("Hands-off vegetarian meals")
        resolved["constraints"]["dietary_restrictions"] = ["vegetarian"]
        fresh = analyzer._get_fallback_intent_data("Chicken stir fry")
        analyzer.initialize(Mock(predict=Mock(side_effect=[json.dumps(resolved), json.dumps(fresh)])))
        follow_up = analyzer.understand_query_intent_with_context("more recipes", [{"role": "user", "content": "Hands-off vegetarian meals"}])
        self.assertEqual(follow_up["constraints"]["attention_level"], "low")
        self.assertEqual(follow_up["constraints"]["dietary_restrictions"], ["vegetarian"])
        self.assertIsNone(analyzer.understand_query_intent_with_context("Chicken stir fry", [])["constraints"]["attention_level"])
