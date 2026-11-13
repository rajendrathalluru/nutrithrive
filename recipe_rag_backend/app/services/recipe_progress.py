import asyncio
import json
import logging
import threading
from time import monotonic
from contextvars import ContextVar

import anyio

from app.core.config import settings
from app.models.schemas import RecipeResponse
from app.services.model_latency import model_deadline, final_review_limit

logger = logging.getLogger(__name__)
_progress_callback = ContextVar("recipe_progress_callback", default=None)
_request_limiter = None
_stream_tasks = set()

STAGES = {
    "queued": "Waiting for the recipe engine…",
    "reviewing": "Reviewing your request…",
    "understanding": "Understanding your requirements…",
    "searching": "Searching the recipe database…",
    "ranking": "Selecting relevant database recipes…",
    "verifying": "Checking recipes against your requirements and guidelines…",
    "searching_more": "Checking additional database candidates…",
    "generating": "Creating a recipe for your requirements…",
    "enhancing": "Preparing recipe guidance…",
    "finalizing": "Applying final recipe checks…",
    "summarizing": "Preparing your response…",
}


class RecipeRequestCancelled(Exception):
    pass


def report_progress(stage):
    callback = _progress_callback.get()
    if callback is not None:
        callback(stage)


async def run_recipe_work(work, callback=None):
    global _request_limiter
    if _request_limiter is None:
        _request_limiter = anyio.CapacityLimiter(settings.RECIPE_REQUEST_WORKERS)

    def run():
        token = _progress_callback.set(callback)
        deadline = monotonic() + settings.RECIPE_MODEL_BUDGET_SECONDS
        deadline_token = model_deadline.set(deadline)
        review_token = final_review_limit.set(deadline + settings.RECIPE_FINAL_REVIEW_SECONDS)
        try:
            report_progress("reviewing")
            return work()
        finally:
            final_review_limit.reset(review_token)
            model_deadline.reset(deadline_token)
            _progress_callback.reset(token)

    return await anyio.to_thread.run_sync(run, limiter=_request_limiter)


def event_frame(event, data):
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def stream_recipe_work(work):
    loop = asyncio.get_running_loop()
    events = asyncio.Queue()
    disconnected = threading.Event()

    def progress(stage):
        if disconnected.is_set():
            raise RecipeRequestCancelled()
        if stage in STAGES:
            loop.call_soon_threadsafe(events.put_nowait, ("progress", {"stage": stage, "message": STAGES[stage]}))

    async def produce():
        try:
            result = await run_recipe_work(work, progress)
            if disconnected.is_set():
                return
            payload = RecipeResponse.model_validate(result).model_dump(mode="json")
            await events.put(("result", payload))
        except RecipeRequestCancelled:
            return
        except Exception as error:
            logger.warning("Recipe progress request failed (%s)", type(error).__name__)
            await events.put(("error", {"message": "The recipe request could not be completed. Please try again."}))

    yield event_frame("progress", {"stage": "queued", "message": STAGES["queued"]})
    producer = asyncio.create_task(produce())
    _stream_tasks.add(producer)
    producer.add_done_callback(_stream_tasks.discard)
    try:
        while True:
            try:
                event, data = await asyncio.wait_for(events.get(), timeout=15)
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
                continue
            yield event_frame(event, data)
            if event in {"result", "error"}:
                break
    finally:
        disconnected.set()
