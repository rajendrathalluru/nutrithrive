from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar
from contextlib import contextmanager
from time import monotonic, perf_counter
import logging
import threading

import openai
import requests
from requests.adapters import HTTPAdapter

from app.core.config import settings
from app.services.model_errors import RecipeModelUnavailable

model_deadline = ContextVar("recipe_model_deadline", default=None)
final_review_limit = ContextVar("recipe_final_review_limit", default=None)
logger = logging.getLogger(__name__)
_pool_lock = threading.Lock()
_io_executors = {}


def configure_openai_connection_pool() -> requests.Session:
    if isinstance(getattr(openai, "requestssession", None), requests.Session):
        return openai.requestssession
    with _pool_lock:
        if isinstance(getattr(openai, "requestssession", None), requests.Session):
            return openai.requestssession
        session = requests.Session()
        adapter = HTTPAdapter(pool_connections=16, pool_maxsize=32, max_retries=0)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        openai.requestssession = session
        return session


def get_io_executor(workers: int = None) -> ThreadPoolExecutor:
    size = max(1, int(workers or settings.RECIPE_IO_WORKERS))
    executor = _io_executors.get(size)
    if executor is None:
        with _pool_lock:
            executor = _io_executors.get(size)
            if executor is None:
                executor = ThreadPoolExecutor(max_workers=size, thread_name_prefix="recipe-io")
                _io_executors[size] = executor
    return executor


configure_openai_connection_pool()


class ModelBudgetExhausted(RecipeModelUnavailable):
    pass


@contextmanager
def final_review_window():
    deadline = model_deadline.get()
    if deadline is None:
        yield
        return
    limit = final_review_limit.get()
    if limit is None:
        limit = deadline
    review_deadline = min(limit, max(deadline, monotonic() + settings.RECIPE_FINAL_REVIEW_SECONDS))
    token = model_deadline.set(review_deadline)
    try:
        yield
    finally:
        model_deadline.reset(token)


def is_luna_or_reasoning_model(model_name: str) -> bool:
    name = str(model_name or "").strip().lower()
    return "luna" in name or name.startswith(("gpt-5", "gpt-6", "o1", "o3", "o4"))


def build_chat_model_kwargs(model_name: str, max_tokens: int, temperature: float, reasoning_effort: str = None) -> dict:
    if is_luna_or_reasoning_model(model_name):
        effort = reasoning_effort or settings.LLM_REASONING_EFFORT
        return {
            "model_name": model_name,
            "temperature": 1.0,
            "max_tokens": None,
            "model_kwargs": {
                "max_completion_tokens": max_tokens,
                "reasoning_effort": effort,
            },
            "request_timeout": settings.LLM_REQUEST_TIMEOUT_SECONDS,
            "max_retries": settings.LLM_MAX_RETRIES,
            "openai_api_key": settings.OPENAI_API_KEY,
        }
    return {
        "model_name": model_name,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "request_timeout": settings.LLM_REQUEST_TIMEOUT_SECONDS,
        "max_retries": settings.LLM_MAX_RETRIES,
        "openai_api_key": settings.OPENAI_API_KEY,
    }


def predict_with_budget(model, prompt, stage="recipe", **kwargs):
    deadline = model_deadline.get()
    if deadline is not None:
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise ModelBudgetExhausted("Recipe model time budget exhausted")
        kwargs["request_timeout"] = min(remaining, settings.LLM_REQUEST_TIMEOUT_SECONDS)
    model_name = getattr(model, "model_name", "")
    if isinstance(model_name, str) and is_luna_or_reasoning_model(model_name):
        if "max_tokens" in kwargs:
            kwargs["max_completion_tokens"] = kwargs.pop("max_tokens")
        kwargs.setdefault(
            "reasoning_effort",
            settings.INTENT_REASONING_EFFORT if stage in {"intent", "context_intent"} else settings.LLM_REASONING_EFFORT,
        )
    started = perf_counter()
    try:
        response = model.predict(prompt, **kwargs)
        logger.info("Model stage=%s duration=%.2fs input_chars=%s output_chars=%s",
                    stage, perf_counter() - started, len(prompt), len(response) if isinstance(response, str) else 0)
        return response
    except Exception as error:
        logger.warning("Model stage=%s duration=%.2fs failure=%s",
                       stage, perf_counter() - started, type(error).__name__)
        raise
