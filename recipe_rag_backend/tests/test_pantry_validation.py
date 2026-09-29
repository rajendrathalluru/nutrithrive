import copy
import json
import unittest
from unittest.mock import Mock

from app.services.pantry_validation import audit_pantry_ingredients
from app.services.recipe_verifier import RecipeVerifier


LIVE_SOUP = {
    "name": "Mediterranean Lentil Soup",
    "description": "A soup made with shelf-stable ingredients.",
    "ingredients": [
        "1 cup dried green lentils",
        "1 can diced tomatoes",
        "1/2 cup chopped carrots",
        "1/2 cup chopped celery",
        "1/4 cup chopped onion",
        "2 cloves garlic, minced",
        "1 teaspoon dried oregano",
        "4 cups low-sodium vegetable broth",
        "Salt and pepper to taste",
    ],
    "instructions": ["Cook the vegetables and lentils in broth."],
}


def model_pass():
    return {
        "id": 0,
        "passes_verification": True,
        "relevance": "match",
        "verification_score": 100,
        "constraint_violations": [],
        "constraint_checks": {
            "constraints.ingredient_storage": {"status": "pass", "evidence": "The ingredients are specified in pantry forms."}
        },
        "ingredient_storage_check": {
            "required_non_pantry_ingredients": [],
            "unspecified_ingredient_forms": [],
            "conflicting_guidance": [],
        },
    }


class PantryValidationTests(unittest.TestCase):
    def test_live_false_positive_is_rejected_in_batch_and_individual_paths(self):
        for storage in ("pantry_based", "shelf_stable_only"):
            for batch in (True, False):
                for generated in (True, False):
                    with self.subTest(storage=storage, batch=batch, generated=generated):
                        verifier = RecipeVerifier()
                        response = [model_pass()] if batch else model_pass()
                        verifier.initialize(Mock(predict=Mock(return_value=json.dumps(response))))
                        recipe = copy.deepcopy(LIVE_SOUP)
                        recipe["generated_by_llm"] = generated
                        intent = {"constraints": {"ingredient_storage": storage}}
                        guidelines = Mock()
                        if batch:
                            result = verifier.batch_verify_recipes([recipe], intent, guidelines)[0]["verification_details"]
                        else:
                            result = verifier.verify_recipe_against_constraints(recipe, intent)
                        self.assertFalse(result["passes_verification"])
                        self.assertEqual(result["relevance"], "adaptable")
                        self.assertFalse(result["meets_preferences"])
                        assessment = result["ingredient_storage_check"]
                        self.assertEqual(assessment["required_non_pantry_ingredients"], LIVE_SOUP["ingredients"][2:6])
                        self.assertEqual(assessment["unspecified_ingredient_forms"], [LIVE_SOUP["ingredients"][7]])
                        guidelines.validate_recipe_compliance.assert_not_called()

    def test_explicit_pantry_substitutions_pass(self):
        recipe = copy.deepcopy(LIVE_SOUP)
        recipe["ingredients"] = [
            "1 cup dried green lentils", "1 can diced tomatoes", "1 can sliced carrots",
            "1 teaspoon celery powder", "1 teaspoon onion powder", "1 teaspoon granulated garlic",
            "1 teaspoon dried oregano", "4 cups water", "1 teaspoon vegetable bouillon",
            "1/4 teaspoon black pepper", "1 tablespoon olive oil",
        ]
        verifier = RecipeVerifier()
        verifier.initialize(Mock(predict=Mock(return_value=json.dumps(model_pass()))))
        result = verifier.verify_recipe_against_constraints(recipe, {"constraints": {"ingredient_storage": "pantry_based"}})
        self.assertTrue(result["passes_verification"])

    def test_other_requests_are_unchanged(self):
        verifier = RecipeVerifier()
        verifier.initialize(Mock(predict=Mock(return_value=json.dumps(model_pass()))))
        result = verifier.verify_recipe_against_constraints(LIVE_SOUP, {"constraints": {}})
        self.assertTrue(result["passes_verification"])

    def test_ingredient_forms_and_mixed_lines(self):
        examples = [
            ("1 red bell pepper, diced", True),
            ("1/2 cup corn kernels", True),
            ("1/4 cup chopped fresh cilantro", True),
            ("1 cup frozen corn", True),
            ("1 cup refrigerated tofu", True),
            ("1 can tomatoes and 1 onion", True),
            ("1 can tomatoes, fresh parsley", True),
            ("1 can corn or frozen corn", True),
            ("1 cup shelf-stable tofu", False),
            ("1 can corn", False),
            ("1 can chicken", False),
            ("1 tablespoon peanut butter", False),
            ("1 teaspoon cream of tartar", False),
            ("1 teaspoon garlic powder", False),
            ("1 teaspoon garlic salt", False),
            ("1 teaspoon freshly ground black pepper", False),
            ("1 can fire-roasted, crushed tomatoes with juice", False),
            ("1 can crushed or diced tomatoes, with juice", False),
            ("3 tablespoons canola or corn oil", False),
            ("1 tablespoon canola, corn, or olive oil", False),
            ("3 tablespoons tomato paste", False),
            ("1 teaspoon onion, dried", False),
            ("1 can diced tomatoes, chopped onion", True),
            ("1 cup frozen corn, canned tomatoes", True),
            ("1 cup coconut milk", True),
            ("1 can coconut milk", False),
        ]
        for ingredient, should_fail in examples:
            with self.subTest(ingredient=ingredient):
                findings = audit_pantry_ingredients({"ingredients": [ingredient]}, "pantry_based")
                self.assertEqual(any(findings.values()), should_fail)

    def test_optional_garnish_requires_optional_directions_and_permissive_intent(self):
        recipe = {
            "ingredients": ["1 can black beans", "Fresh cilantro (optional)"],
            "instructions": ["Heat the beans. Garnish with cilantro if desired."],
        }
        self.assertFalse(any(audit_pantry_ingredients(recipe, "pantry_based").values()))
        self.assertTrue(any(audit_pantry_ingredients(recipe, "shelf_stable_only").values()))
        recipe["instructions"] = ["Mix the cilantro into the beans."]
        self.assertTrue(any(audit_pantry_ingredients(recipe, "pantry_based").values()))

    def test_missing_ingredients_cannot_pass(self):
        for ingredients in ([], None, "carrots", [None]):
            with self.subTest(ingredients=ingredients):
                self.assertTrue(any(audit_pantry_ingredients({"ingredients": ingredients}, "pantry_based").values()))

    def test_batch_failure_still_enforces_pantry_audit_on_fallback(self):
        verifier = RecipeVerifier()
        verifier.initialize(Mock(predict=Mock(side_effect=["invalid JSON", json.dumps(model_pass())])))
        result = verifier.batch_verify_recipes(
            [copy.deepcopy(LIVE_SOUP)], {"constraints": {"ingredient_storage": "pantry_based"}}, Mock()
        )
        self.assertFalse(result[0]["verification_details"]["passes_verification"])
