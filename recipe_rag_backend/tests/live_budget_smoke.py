import argparse
import json
import logging
import threading
import time
from decimal import Decimal

from app.services.model_errors import RecipeModelUnavailable
from app.services.rag_service import RecipeRAGService
from app.services.required_ingredients import ingredient_present, missing_required_ingredients


CASES = [
    ("mexican", "Please help me to get a Mexican recipe under 10 dollars", [], []),
    ("korean", "can you help me to generate a korean dish inder 10 dollars", [], []),
    ("required_foods", "Make a Mexican dinner under $10 using chicken and broccoli, without beans or rice.",
     ["chicken", "broccoli"], ["beans", "rice"]),
]


class LimitedModel:
    def __init__(self, client):
        self.client = client
        self.calls = 0
        self.lock = threading.Lock()

    def predict(self, prompt, **kwargs):
        with self.lock:
            if self.calls >= 30:
                raise RecipeModelUnavailable("Live smoke-test model-call limit reached")
            self.calls += 1
        return self.client.predict(prompt, **kwargs)


def run():
    parser = argparse.ArgumentParser(description="Paid, opt-in synthetic budget checks; never part of the offline suite.")
    parser.add_argument("--run-live", action="store_true", help="Allow model, embedding and retailer web-search API calls.")
    arguments = parser.parse_args()
    if not arguments.run_live:
        parser.error("Pass --run-live to explicitly allow paid external API calls.")
    logging.disable(logging.CRITICAL)
    pipeline = RecipeRAGService()
    pipeline.initialize()
    client = pipeline.llm.copy(update={"request_timeout": 30, "max_retries": 0})
    model = LimitedModel(client)
    pipeline.llm = model
    for service in (pipeline.intent_analyzer, pipeline.search_engine, pipeline.recipe_enhancer,
                    pipeline.recipe_verifier, pipeline.response_generator):
        service.llm = model
    failed = False
    for label, query, required, excluded in CASES:
        started = time.monotonic()
        previous_calls = model.calls
        result = pipeline.ask_question(query)
        recipes = result.get("source_documents") or []
        valid = bool(recipes) and len(recipes) <= 3
        for recipe in recipes:
            budget = recipe.get("budget_assessment") or {}
            valid = valid and bool(recipe.get("ingredients")) and bool(recipe.get("instructions"))
            valid = valid and recipe.get("verification_details", {}).get("passes_verification") is True
            valid = valid and budget.get("status") == "estimated_within_budget"
            valid = valid and Decimal(budget.get("planning_ceiling", "Infinity")) < Decimal("10")
            valid = valid and not missing_required_ingredients(recipe, required)
            valid = valid and not any(ingredient_present(food, recipe["ingredients"]) for food in excluded)
        failed = failed or not valid
        print(json.dumps({"case": label, "passed": bool(valid), "recipes": len(recipes),
                          "seconds": round(time.monotonic() - started, 2),
                          "model_calls": model.calls - previous_calls}), flush=True)
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(run())
