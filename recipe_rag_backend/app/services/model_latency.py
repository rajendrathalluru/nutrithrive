from contextvars import ContextVar
from contextlib import contextmanager
from time import monotonic, perf_counter
import logging

from app.core.config import settings
from app.services.model_errors import RecipeModelUnavailable

model_deadline = ContextVar("recipe_model_deadline", default=None)
final_review_limit = ContextVar("recipe_final_review_limit", default=None)
logger = logging.getLogger(__name__)


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


def predict_with_budget(model, prompt, stage="recipe", **kwargs):
    deadline = model_deadline.get()
    if deadline is not None:
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise ModelBudgetExhausted("Recipe model time budget exhausted")
        kwargs["request_timeout"] = min(remaining, settings.LLM_REQUEST_TIMEOUT_SECONDS)
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
