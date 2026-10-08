import unittest
from pathlib import Path

from app.services.data_loader import DataLoader
from app.services.rag_service import RecipeRAGService


class SourceAnnotationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.loader = DataLoader()
        cls.loader.load_data(Path(__file__).parents[1] / "app/data/Recipe.csv")

    def test_existing_footnotes_are_preserved_without_markdown_cleanup(self):
        record = self.loader.get_recipe_record("Celery Rosemary Tonic")
        annotations = self.loader.get_source_annotations(record)
        self.assertEqual(annotations["source_notes"], record["Notes"])
        self.assertIn("**Pure Maple", annotations["source_notes"])
        self.assertIn("***A pinch", annotations["source_notes"])
        self.assertEqual(annotations["unresolved_footnotes"], [])

    def test_missing_zaatar_footnote_is_flagged_not_invented(self):
        record = self.loader.get_recipe_record("Sheet Pan Roasted Vegetables and Beans")
        service = RecipeRAGService()
        service.data_loader = self.loader
        recipe = service._build_recipe_data_from_record(record)
        self.assertEqual(recipe["source_notes"], "")
        self.assertEqual(recipe["unresolved_footnotes"], ["*"])
        self.assertTrue(any("za'atar*" in ingredient for ingredient in recipe["ingredients"]))

    def test_related_recipe_resolves_to_actual_csv_link_and_identity(self):
        record = self.loader.get_recipe_record("Sautéed Zucchini, Tomato and Chickpea Ragout")
        service = RecipeRAGService()
        service.data_loader = self.loader
        recipe = service._build_recipe_data_from_record(record)
        references = recipe["related_recipes"]
        self.assertEqual(len(references), 1)
        self.assertEqual(references[0]["name"], "Chickpea Salad with Tomatoes and Cucumber")
        self.assertEqual(references[0]["recipe_link"], "https://recipes.heart.org/en/recipes/chickpea-salad-with-tomatoes-and-cucumber")
        self.assertTrue(references[0]["recipe_id"])
        self.assertEqual(references[0]["source_name"], "AHA")

    def test_unknown_references_are_not_guessed_and_bullets_are_not_footnotes(self):
        annotations = self.loader.get_source_annotations({"Ingredients": "* 1 cup beans\nUnknown dish (see related recipes)"})
        self.assertEqual(annotations["related_recipes"], [])
        self.assertEqual(annotations["unresolved_footnotes"], [])

    def test_notes_with_multiple_marker_lengths_are_distinct(self):
        result = self.loader.get_source_annotations({"Ingredients": "1 cup beans*\n1 cup rice**", "Notes": "*A note about beans."})
        self.assertEqual(result["unresolved_footnotes"], ["**"])


if __name__ == "__main__":
    unittest.main()
