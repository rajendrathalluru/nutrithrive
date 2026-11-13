import unittest
from unittest.mock import Mock, patch

from langchain.schema import Document

from app.services.search_engine import SearchEngine


class LocalRecipeRankingTests(unittest.TestCase):
    def setUp(self):
        self.engine = SearchEngine()
        self.engine.llm = Mock()
        self.intent = {"constraints": {}, "preferences": {"meal_types": ["dinner"]}}
        self.docs = [
            Document(page_content="Snack", metadata={"name": "Granola Bars", "type": "Snacks"}),
            Document(page_content="Side", metadata={"name": "Asparagus", "type": "Side Dishes"}),
            Document(page_content="Soup", metadata={"name": "Bean Soup", "type": "Main Dishes, Soups"}),
            Document(page_content="Pasta", metadata={"name": "Bean Pasta", "type": "Entree"}),
        ]

    def test_dinner_ranking_needs_no_model_and_does_not_assert_verification(self):
        with patch("app.services.search_engine.settings.RECIPE_LLM_RERANKING", False):
            result = self.engine.rerank_with_constraint_filtering(self.docs, "Dinner in 30 minutes", self.intent, 2)
        self.assertEqual(result, self.docs[2:])
        self.engine.llm.predict.assert_not_called()
        self.assertTrue(all("verification_details" not in doc.metadata for doc in result))

    def test_malformed_opt_in_model_response_uses_meal_aware_fallback(self):
        self.engine.llm.predict.return_value = "not json"
        with patch("app.services.search_engine.settings.RECIPE_LLM_RERANKING", True):
            result = self.engine.rerank_with_constraint_filtering(self.docs, "Dinner", self.intent, 2)
        self.assertEqual(result, self.docs[2:])
        self.engine.llm.predict.assert_called_once()

    def test_missing_categories_preserve_retrieval_order(self):
        docs = [Document(page_content="First"), Document(page_content="Second")]
        self.assertEqual(self.engine.rank_candidates_locally(docs, "Dinner", self.intent), docs)

    def test_ranking_does_not_discard_candidates(self):
        result = self.engine.rank_candidates_locally(self.docs, "Dinner", self.intent)
        self.assertEqual(len(result), len(self.docs))
        self.assertEqual(self.docs[0].metadata["name"], "Granola Bars")


if __name__ == "__main__":
    unittest.main()
