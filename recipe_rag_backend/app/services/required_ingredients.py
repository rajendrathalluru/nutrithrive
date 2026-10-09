import re
import unicodedata
from typing import Any, Dict, List


ALIASES = {
    "garbanzo bean": "chickpea",
    "garbanzo": "chickpea",
    "bean curd": "tofu",
    "aubergine": "eggplant",
    "courgette": "zucchini",
}


def normalize_ingredient(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode().lower()
    words = re.findall(r"[a-z]+", text)
    normalized = []
    for word in words:
        if word.endswith("ies") and len(word) > 4:
            word = word[:-3] + "y"
        elif word.endswith("oes"):
            word = word[:-2]
        elif word.endswith("s") and not word.endswith(("ss", "us")) and len(word) > 3:
            word = word[:-1]
        normalized.append(word)
    text = " ".join(normalized)
    for alias, canonical in ALIASES.items():
        text = re.sub(r"\b" + re.escape(alias) + r"\b", canonical, text)
    return text


def ingredient_present(ingredient: str, lines: List[str]) -> bool:
    words = normalize_ingredient(ingredient).split()
    if not words:
        return False
    pattern = re.compile(r"\b" + r"\s+(?:\w+\s+){0,2}".join(map(re.escape, words)) + r"\b")
    for line in lines:
        text = normalize_ingredient(line)
        for match in pattern.finditer(text):
            if re.search(r"\b(?:no|without|omit|avoid)\s*$", text[:match.start()]):
                continue
            if re.match(r"\s+free\b", text[match.end():]):
                continue
            return True
    return False


def missing_required_ingredients(recipe: Dict[str, Any], required: List[str]) -> List[str]:
    lines = recipe.get("ingredients") or []
    if isinstance(lines, str):
        lines = lines.splitlines()
    return [ingredient for ingredient in required if not ingredient_present(ingredient, lines)]


def explicit_ingredient_combination(query: str, ingredients: List[str]) -> bool:
    match = re.search(r"\b(?:make|cook|prepare|recipes?|meals?)\b[^.!?]*\b(?:with|using)\s+([^.!?]+)", query, re.I)
    if not match or not isinstance(ingredients, list) or len(ingredients) < 2:
        return False
    selection = match[1]
    if re.search(r"\b(?:or|any|either|some|choose|whichever|without|exclude|except)\b", selection, re.I):
        return False
    return all(ingredient_present(ingredient, [selection]) for ingredient in ingredients)
