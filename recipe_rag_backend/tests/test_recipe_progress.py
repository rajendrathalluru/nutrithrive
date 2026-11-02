import asyncio
import json
import threading
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from starlette.requests import Request

from app import main
from app.models.schemas import RecipeResponse
from app.services import recipe_progress as progress
import test_budget_service as budget_fixtures


def result(query="Dinner"):
    return {"query": query, "response": "A checked dinner", "source": "llm_generated",
            "matches_found": 1, "mode": "auto", "source_documents": [{"name": "Checked bowl"}]}


def decode(frame):
    return json.loads(frame.split("data: ", 1)[1])


class RecipeProgressTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        progress._request_limiter = None

    async def test_http_route_delivers_progress_before_blocking_work_finishes(self):
        release = threading.Event()
        delivered = []
        received = False
        self.addCleanup(release.set)

        def work(**kwargs):
            progress.report_progress("verifying")
            if not release.wait(3):
                raise TimeoutError("Progress did not reach the client")
            return result()

        async def receive():
            nonlocal received
            if not received:
                received = True
                return {"type": "http.request", "body": b'{"query":"Dinner"}', "more_body": False}
            await asyncio.Event().wait()

        async def send(message):
            delivered.append(message)
            if message["type"] == "http.response.body" and b'"stage": "verifying"' in message.get("body", b""):
                release.set()

        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST",
                 "path": "/ask", "raw_path": b"/ask", "query_string": b"", "root_path": "", "scheme": "https",
                 "headers": [(b"content-type", b"application/json"), (b"accept", b"text/event-stream")],
                 "server": ("test", 443), "client": ("127.0.0.1", 1)}
        with patch.object(main.access_control, "enabled", False), \
                patch.object(main, "_ensure_rag_ready"), patch.object(main.safety_service, "should_intercept", return_value=False), \
                patch.object(main.rag_service, "ask_question", side_effect=work):
            await asyncio.wait_for(main.app(scope, receive, send), 4)
        self.assertEqual(delivered[0]["status"], 200)
        payload = b"".join(message.get("body", b"") for message in delivered)
        self.assertLess(payload.index(b'"stage": "verifying"'), payload.index(b"event: result"))

    async def test_same_endpoint_stream_and_json_keep_identical_result_and_history(self):
        query = main.ConversationQueryRequest(query="Dinner", conversation_history=[{"role": "user", "content": "Vegetarian"}])
        http = Request({"type": "http", "headers": [(b"accept", b"text/event-stream")]})
        with patch.object(main, "_ensure_rag_ready"), patch.object(main.safety_service, "should_intercept", return_value=False), \
                patch.object(main.rag_service, "ask_question", side_effect=lambda **kwargs: result()) as ask:
            plain = await main.ask_question(query)
            stream = await main.ask_question(query, http)
            frames = [frame async for frame in stream.body_iterator]
        self.assertEqual(decode(frames[-1]), RecipeResponse.model_validate(plain).model_dump(mode="json"))
        self.assertEqual(ask.call_args_list[0], ask.call_args_list[1])
        self.assertEqual(stream.headers["cache-control"], "no-store")
        self.assertEqual(stream.headers["x-accel-buffering"], "no")

    async def test_progress_arrives_before_work_completes_and_never_contains_recipes(self):
        release = threading.Event()
        self.addCleanup(release.set)

        def work():
            progress.report_progress("verifying")
            release.wait(3)
            return result()

        stream = progress.stream_recipe_work(work)
        self.assertEqual(decode(await anext(stream))["stage"], "queued")
        self.assertEqual(decode(await anext(stream))["stage"], "reviewing")
        checking = decode(await asyncio.wait_for(anext(stream), 2))
        self.assertEqual(checking, {"stage": "verifying", "message": progress.STAGES["verifying"]})
        release.set()
        self.assertIn("source_documents", decode(await anext(stream)))
        await stream.aclose()

    async def test_two_requests_run_independently_without_blocking_event_loop(self):
        release = threading.Event()
        started = [threading.Event(), threading.Event()]
        self.addCleanup(release.set)
        seen = [[], []]

        def work(index):
            started[index].set()
            progress.report_progress("searching" if index == 0 else "generating")
            release.wait(3)
            return result(str(index))

        with patch.object(progress.settings, "RECIPE_REQUEST_WORKERS", 2):
            tasks = [asyncio.create_task(progress.run_recipe_work(lambda index=index: work(index), seen[index].append))
                     for index in range(2)]
            for _ in range(100):
                if all(event.is_set() for event in started):
                    break
                await asyncio.sleep(0.01)
            self.assertTrue(all(event.is_set() for event in started))
            self.assertFalse(any(task.done() for task in tasks))
            release.set()
            responses = await asyncio.gather(*tasks)
        self.assertEqual([item["query"] for item in responses], ["0", "1"])
        self.assertEqual(seen, [["reviewing", "searching"], ["reviewing", "generating"]])

    async def test_request_concurrency_is_bounded(self):
        release = threading.Event()
        started = threading.Event()
        second_started = threading.Event()
        self.addCleanup(release.set)

        def first():
            started.set()
            release.wait(3)
            return result()

        with patch.object(progress.settings, "RECIPE_REQUEST_WORKERS", 1):
            task = asyncio.create_task(progress.run_recipe_work(first))
            while not started.is_set():
                await asyncio.sleep(0.01)
            second = asyncio.create_task(progress.run_recipe_work(lambda: second_started.set()))
            await asyncio.sleep(0.03)
            self.assertFalse(second_started.is_set())
            release.set()
            await asyncio.gather(task, second)
            self.assertTrue(second_started.is_set())

    async def test_disconnect_stops_at_next_stage_without_releasing_running_work_early(self):
        release = threading.Event()
        stopped = threading.Event()
        proceeded = threading.Event()
        self.addCleanup(release.set)

        def work():
            progress.report_progress("generating")
            release.wait(3)
            try:
                progress.report_progress("verifying")
                proceeded.set()
            finally:
                stopped.set()
            return result()

        stream = progress.stream_recipe_work(work)
        await anext(stream)
        await anext(stream)
        await anext(stream)
        await stream.aclose()
        self.assertEqual(progress._request_limiter.borrowed_tokens, 1)
        release.set()
        for _ in range(100):
            if stopped.is_set() and not progress._stream_tasks:
                break
            await asyncio.sleep(0.01)
        self.assertTrue(stopped.is_set())
        self.assertFalse(proceeded.is_set())
        self.assertEqual(progress._request_limiter.borrowed_tokens, 0)

    async def test_failure_does_not_emit_result_or_internal_exception(self):
        def work():
            raise ValueError("private debug details")

        frames = [frame async for frame in progress.stream_recipe_work(work)]
        self.assertTrue(frames[-1].startswith("event: error"))
        self.assertNotIn("private debug details", "".join(frames))
        self.assertNotIn("event: result", "".join(frames))

    async def test_safety_and_readiness_gates_precede_streaming(self):
        query = main.ConversationQueryRequest(query="Synthetic safety test")
        http = Request({"type": "http", "headers": [(b"accept", b"text/event-stream")]})
        with patch.object(main.safety_service, "should_intercept", return_value=True), \
                patch.object(main.safety_service, "build_crisis_response", return_value={"safety_redirect": True}), \
                patch.object(main, "run_recipe_work") as work, patch.object(main, "_ensure_rag_ready") as ready:
            self.assertEqual(await main.ask_question(query, http), {"safety_redirect": True})
            work.assert_not_called()
            ready.assert_not_called()
        with patch.object(main.safety_service, "should_intercept", return_value=False), \
                patch.object(main, "_ensure_rag_ready", side_effect=HTTPException(503, "Warming up")):
            with self.assertRaises(HTTPException) as caught:
                await main.ask_question(query, http)
            self.assertEqual(caught.exception.status_code, 503)

    async def test_real_pipeline_orders_generation_before_checks_and_keeps_final_results(self):
        fixture = budget_fixtures.BudgetTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        intent = fixture.intent()
        pipeline = fixture.configure_pipeline(intent, [], [budget_fixtures.recipe(generated=True)])
        stages = []
        with patch("app.services.rag_service.budget_service", fixture.service), \
                patch("app.services.rag_service.safety_service.should_intercept", return_value=False):
            checked = await progress.run_recipe_work(lambda: pipeline.ask_question("Dinner under $5"), stages.append)
            plain = await progress.run_recipe_work(lambda: pipeline.ask_question("Dinner under $5"))
        checked.pop("performance", None)
        plain.pop("performance", None)
        self.assertEqual(checked, plain)
        self.assertEqual(checked["matches_found"], 1)
        self.assertLess(stages.index("generating"), stages.index("verifying"))
        self.assertLess(stages.index("verifying"), stages.index("finalizing"))
        self.assertLess(stages.index("finalizing"), stages.index("summarizing"))
