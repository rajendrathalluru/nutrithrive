import argparse
import json
import os
import tempfile
import time
from copy import deepcopy
from pathlib import Path

from app.core.config import settings
from app.services.aicr_guidelines_service import aicr_service
from app.services.preparation_validation import time_candidate_rank
from app.services.rag_service import RecipeRAGService
from app.services.verified_catalog import fingerprint, policy_identity, simple_timed_intent


def main():
    parser = argparse.ArgumentParser(description="Build public-recipe assessments outside the interactive request path.")
    parser.add_argument("--query", action="append", help="Exact supported standalone time-limit request; may repeat.")
    parser.add_argument("--output", default=settings.RECIPE_VERIFIED_CATALOG_PATH)
    parser.add_argument("--target", type=int, default=12)
    parser.add_argument("--max-candidates", type=int, default=100)
    parser.add_argument("--allow-model-calls", action="store_true", help="Acknowledge paid model verification calls.")
    args = parser.parse_args()
    if not args.allow_model_calls:
        parser.error("Building the catalog uses paid model calls. Supply --allow-model-calls to proceed.")
    if not 3 <= args.target <= 100 or not args.target <= args.max_candidates <= 500:
        parser.error("Require 3 <= target <= max-candidates <= 500, with target <= 100.")
    queries = args.query or ["Show recipes that take 30 minutes or less for dinner"]
    intents = [simple_timed_intent(query) for query in queries]
    if any(intent is None for intent in intents):
        parser.error("Unsupported query. Use e.g. 'Show recipes that take 30 minutes or less for dinner'.")

    from langchain.chat_models import ChatOpenAI

    service = RecipeRAGService()
    service.data_loader.load_data()
    model = ChatOpenAI(model_name=settings.LLM_MODEL, temperature=settings.LLM_TEMPERATURE,
                       max_tokens=settings.LLM_MAX_TOKENS, openai_api_key=settings.OPENAI_API_KEY)
    service.recipe_verifier.initialize(model)
    profiles = {}
    for intent in intents:
        candidates = service._get_database_search_candidates(
            intent["resolved_query"], intent, set(), args.max_candidates
        )
        candidates = [recipe for recipe in candidates if recipe.get("ingredients") and recipe.get("instructions")
                      and time_candidate_rank(recipe, intent["constraints"]) > 0
                      and not service.recipe_verifier._requires_guideline_review(recipe)]
        entries = []
        for start in range(0, len(candidates), settings.RECIPE_IO_WORKERS):
            originals = candidates[start:start + settings.RECIPE_IO_WORKERS]
            assessed = service.recipe_verifier.batch_verify_recipes(deepcopy(originals), intent, aicr_service)
            for original, recipe in zip(originals, assessed):
                if service._get_verified_matches([recipe], intent):
                    entries.append({"name": original["name"], "recipe_hash": fingerprint(original),
                                    "assessment": recipe["verification_details"]})
            print(f"{intent['resolved_query']}: {min(start + len(originals), len(candidates))} assessed; {len(entries)} passed", flush=True)
            if len(entries) >= args.target:
                break
        if len(entries) < 3:
            raise SystemExit("Fewer than three verified matches. Existing catalog left unchanged; inspect failures before publishing.")
        profiles[fingerprint(intent)] = entries[:args.target]

    catalog = {"created_at": time.time(), "policy": policy_identity(), "profiles": profiles}
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=output.parent, delete=False) as handle:
            temporary = handle.name
            json.dump(catalog, handle, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, output)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)
    print(f"Published {len(profiles)} profiles to {output}. No participant conversations were used.")


if __name__ == "__main__":
    main()
