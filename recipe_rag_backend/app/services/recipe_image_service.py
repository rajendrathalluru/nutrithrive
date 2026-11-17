import hashlib
import json
import logging
import re
import threading
from typing import Any, Dict, List, Optional
import requests

from app.core.config import settings
from app.services.response_cache import ResponseCache

logger = logging.getLogger(__name__)


class RecipeImageService:
    def __init__(self):
        self.cache = ResponseCache(ttl=3600, capacity=64)
        self._inflight_lock = threading.Lock()
        self._inflight: Dict[str, threading.Event] = {}
        self._working_model: Optional[str] = None

    def _candidate_models(self) -> List[str]:
        candidates = [
            self._working_model,
            settings.RECIPE_IMAGE_MODEL,
            "gpt-image-1",
            "gpt-image-1-mini",
            "gpt-image-1.5",
            "dall-e-3",
            "dall-e-2",
        ]
        seen = set()
        ordered: List[str] = []
        for model in candidates:
            name = str(model or "").strip()
            if name and name not in seen:
                seen.add(name)
                ordered.append(name)
        return ordered

    def _clean_text(self, text: str, max_len: int = 120) -> str:
        cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
        return cleaned[:max_len]

    def build_image_prompt(
        self,
        title: str,
        description: str = "",
        ingredients: Optional[List[str]] = None,
    ) -> str:
        dish_title = self._clean_text(title, 100) or "Wholesome home-cooked meal"
        dish_desc = self._clean_text(description, 160)
        ing_list = [
            self._clean_text(ing, 60)
            for ing in (ingredients or [])[:6]
            if isinstance(ing, str) and ing.strip()
        ]
        ingredients_phrase = (
            f" featuring {', '.join(ing_list)}" if ing_list else ""
        )
        desc_phrase = f" ({dish_desc})" if dish_desc else ""
        return (
            f"Natural, appetizing overhead food photography of {dish_title}"
            f"{desc_phrase}{ingredients_phrase}, plated in a simple ceramic dish on a warm "
            "linen tabletop with soft natural daylight, realistic home-cooked textures, "
            "editorial food magazine style. No text, no labels, no logos, no watermarks, "
            "no people or hands."
        )[:950]

    def generate_recipe_image(
        self,
        title: str,
        description: str = "",
        ingredients: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        if not settings.OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY not configured")

        prompt = self.build_image_prompt(title, description, ingredients)
        cache_key = hashlib.sha256(
            json.dumps([settings.RECIPE_IMAGE_MODEL, prompt]).encode("utf-8")
        ).hexdigest()

        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached

        with self._inflight_lock:
            cached = self.cache.get(cache_key)
            if cached is not None:
                return cached
            event = self._inflight.get(cache_key)
            is_owner = event is None
            if is_owner:
                event = threading.Event()
                self._inflight[cache_key] = event

        if not is_owner:
            event.wait(timeout=40)
            cached = self.cache.get(cache_key)
            if cached is not None:
                return cached

        try:
            response = None
            for model in self._candidate_models():
                response = requests.post(
                    "https://api.openai.com/v1/images/generations",
                    headers={
                        "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={"model": model, "prompt": prompt, "n": 1, "size": "1024x1024"},
                    timeout=60,
                )
                if response.ok:
                    if self._working_model != model:
                        logger.info("Recipe image model in use: %s", model)
                    self._working_model = model
                    break
                logger.warning(
                    "Recipe image model %s failed (%s): %s",
                    model, response.status_code, response.text[:300],
                )
                # Only try another model when this one is unavailable/unsupported for the account.
                if response.status_code not in (400, 403, 404):
                    break

            if response is None or not response.ok:
                raise RuntimeError("Unable to generate recipe image right now.")

            data = response.json()
            items = data.get("data") if isinstance(data, dict) else None
            if not isinstance(items, list) or not items or not isinstance(items[0], dict):
                raise RuntimeError("Empty image generation response.")

            first = items[0]
            image_url = ""
            if isinstance(first.get("b64_json"), str) and first["b64_json"].strip():
                image_url = f"data:image/png;base64,{first['b64_json'].strip()}"
            elif isinstance(first.get("url"), str) and first["url"].strip().startswith("https://"):
                image_url = first["url"].strip()

            if not image_url:
                raise RuntimeError("No valid image returned from generator.")

            result = {"image_url": image_url}
            self.cache.put(cache_key, result)
            return result
        finally:
            if is_owner:
                with self._inflight_lock:
                    self._inflight.pop(cache_key, None)
                    event.set()


recipe_image_service = RecipeImageService()
