import unittest
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from threading import Event, Lock, get_ident
from unittest.mock import Mock, call, patch

from langchain.schema import Document
from openai.error import OpenAIError

from app.services import search_engine
from app.services.model_errors import RecipeModelUnavailable
from app.services.search_engine import SearchEngine


class SearchParallelismTests(unittest.TestCase):
    def setUp(self):
        self.engine = SearchEngine()
        self.engine.initialize(Mock(), Mock())

    def workers(self, count):
        return patch.object(search_engine.settings, "RECIPE_IO_WORKERS", count, create=True)

    def test_overlapping_searches_are_bounded_and_merged_in_query_order(self):
        for worker_count in (2, 3):
            with self.subTest(workers=worker_count), self.workers(worker_count):
                queries = [f"query {index}" for index in range(6)]
                self.engine._generate_contextual_search_queries = Mock(return_value=queries)
                releases = {query: Event() for query in queries}
                started = Queue()
                finished = Queue()
                lock = Lock()
                active = 0
                max_active = 0
                calls = []
                common_prefix = "shared recipe " * 8
                documents = {
                    query: [
                        Document(page_content=query),
                        Document(page_content=common_prefix + query, metadata={"query": query}),
                    ]
                    for query in queries
                }

                def search(query, k):
                    nonlocal active, max_active
                    with lock:
                        active += 1
                        max_active = max(max_active, active)
                        calls.append((query, k))
                    started.put(query)
                    try:
                        if not releases[query].wait(timeout=5):
                            raise AssertionError(f"Search was not released: {query}")
                        return documents[query]
                    finally:
                        with lock:
                            active -= 1
                        finished.put(query)

                self.engine.vector_store.similarity_search = search
                completion_order = queries[:worker_count][::-1] + queries[worker_count:]
                with ThreadPoolExecutor(max_workers=1) as caller:
                    result = caller.submit(self.engine.multi_query_search, "original", {}, 7)
                    try:
                        initial_queries = [started.get(timeout=5) for _ in range(worker_count)]
                        self.assertCountEqual(initial_queries, queries[:worker_count])
                        started_count = worker_count
                        for query in completion_order:
                            releases[query].set()
                            self.assertEqual(finished.get(timeout=5), query)
                            if started_count < len(queries):
                                self.assertEqual(started.get(timeout=5), queries[started_count])
                                started_count += 1
                        actual = result.result(timeout=5)
                    finally:
                        for release in releases.values():
                            release.set()

                expected = documents[queries[0]] + [documents[query][0] for query in queries[1:]]
                self.assertEqual(actual, expected)
                self.assertIs(actual[1], documents[queries[0]][1])
                self.assertCountEqual(calls, [(query, 7) for query in queries])
                self.assertEqual(max_active, worker_count)
                self.assertEqual(active, 0)
                self.engine.llm.predict.assert_not_called()

    def test_one_worker_runs_serially_on_calling_thread(self):
        queries = ["first", "second", "third"]
        self.engine._generate_contextual_search_queries = Mock(return_value=queries)
        calls = []
        caller_thread = get_ident()

        def search(query, k):
            calls.append((query, k, get_ident()))
            return [Document(page_content=query)]

        self.engine.vector_store.similarity_search = search
        with self.workers(1), patch.object(search_engine, "ThreadPoolExecutor") as executor:
            result = self.engine.multi_query_search("original", {}, 4)

        executor.assert_not_called()
        self.assertEqual(calls, [(query, 4, caller_thread) for query in queries])
        self.assertEqual([doc.page_content for doc in result], queries)

    def test_individual_failure_does_not_discard_other_results(self):
        for worker_count in (1, 3):
            with self.subTest(workers=worker_count), self.workers(worker_count):
                queries = ["first", "broken", "last"]
                self.engine._generate_contextual_search_queries = Mock(return_value=queries)

                def search(query, k):
                    if query == "broken":
                        raise ValueError("individual search failure")
                    return [Document(page_content=query), Document(page_content="shared")]

                self.engine.vector_store.similarity_search = Mock(side_effect=search)
                with self.assertLogs(search_engine.logger, level="ERROR") as logs:
                    result = self.engine.multi_query_search("original", {}, 9)

                self.assertEqual([doc.page_content for doc in result], ["first", "shared", "last"])
                self.assertIn("Error in search 'broken': individual search failure", logs.output[0])
                self.engine.vector_store.similarity_search.assert_has_calls(
                    [call(query, k=9) for query in queries], any_order=True
                )

    def test_result_iteration_failure_preserves_partial_results(self):
        for worker_count in (1, 3):
            with self.subTest(workers=worker_count), self.workers(worker_count):
                self.engine._generate_contextual_search_queries = Mock(return_value=["first", "last"])

                def partial_results():
                    yield Document(page_content="partial")
                    raise ValueError("invalid result")

                def search(query, k):
                    return partial_results() if query == "first" else [Document(page_content="last")]

                self.engine.vector_store.similarity_search = Mock(side_effect=search)
                with self.assertLogs(search_engine.logger, level="ERROR"):
                    result = self.engine.multi_query_search("original", {}, 2)
                self.assertEqual([doc.page_content for doc in result], ["partial", "last"])

    def test_model_unavailable_propagates(self):
        for worker_count in (1, 3):
            for error in (RecipeModelUnavailable("unavailable"), OpenAIError("provider failed")):
                with self.subTest(workers=worker_count, error=type(error)), self.workers(worker_count):
                    queries = ["first", "broken", "last"]
                    self.engine._generate_contextual_search_queries = Mock(return_value=queries)

                    def search(query, k):
                        if query == "broken":
                            raise error
                        return [Document(page_content=query)]

                    self.engine.vector_store.similarity_search = Mock(side_effect=search)
                    with self.assertRaises(RecipeModelUnavailable) as raised:
                        self.engine.multi_query_search("original", {}, 5)
                    if isinstance(error, RecipeModelUnavailable):
                        self.assertIs(raised.exception, error)
                    else:
                        self.assertIs(raised.exception.__cause__, error)
                    if worker_count == 1:
                        self.assertEqual(
                            self.engine.vector_store.similarity_search.call_args_list,
                            [call("first", k=5), call("broken", k=5)],
                        )

    def test_generated_queries_and_fallback_are_unchanged(self):
        intent = {
            "search_strategy": {"enhanced_query": "enhanced", "search_keywords": ["quick", "beans"]},
            "constraints": {
                "equipment_required": ["blender"],
                "ingredients_must_use": ["beans"],
                "dietary_restrictions": ["vegan"],
                "max_ingredients": 5,
                "leftover_friendly": True,
            },
            "preferences": {"meal_types": ["lunch"]},
        }
        expected_queries = [
            "enhanced", "blender cooking recipes", "quick beans", "beans recipes",
            "vegan lunch", "simple 5 ingredient recipes",
        ]
        cases = [
            ("original", intent, expected_queries),
            ("  original query  ", {}, ["original query"]),
            (" \t ", {}, []),
        ]
        for worker_count in (1, 3):
            for original, intent_data, queries in cases:
                with self.subTest(workers=worker_count, original=original), self.workers(worker_count):
                    self.engine.vector_store.similarity_search = Mock(return_value=[])
                    self.assertEqual(self.engine.multi_query_search(original, intent_data, 11), [])
                    self.assertCountEqual(
                        self.engine.vector_store.similarity_search.call_args_list,
                        [call(query, k=11) for query in queries],
                    )


if __name__ == "__main__":
    unittest.main()
