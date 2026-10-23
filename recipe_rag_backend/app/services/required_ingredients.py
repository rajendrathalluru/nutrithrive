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
            if re.search(r"\b(?:no|without|omit|avoid|instead of|rather than)\s*$", text[:match.start()]):
                continue
            if re.match(r"\s+free\b", text[match.end():]):
                continue
            return True
    return False


def recipe_ingredient_present(ingredient: str, lines: List[str]) -> bool:
    required = normalize_ingredient(ingredient)
    modifiers = {"fresh", "frozen", "canned", "dried", "cooked", "raw", "chopped", "sliced", "diced",
                 "minced", "shredded", "ground", "whole", "white", "brown", "black", "red", "green",
                 "yellow", "small", "medium", "large", "finely", "coarsely", "boneless", "skinless"}
    for line in lines:
        if not isinstance(line, str) or re.search(r"\b(?:optional|if desired|if using)\b", line, re.I):
            continue
        alternatives = re.split(r"\bor\b", re.sub(r"\b\d+(?:\.\d+)?\s+or\s+(?=\d)", "", line, flags=re.I), flags=re.I)
        if not any(ingredient_present(ingredient, [alternative]) for alternative in alternatives):
            continue
        supported = True
        for alternative in alternatives:
            text = normalize_ingredient(alternative)
            modifier_words = set(text.split()) - {"cup", "tbsp", "tsp", "oz", "ounce", "pound", "lb", "gram", "g", "kg", "of"}
            if modifier_words and modifier_words <= modifiers:
                continue
            text = re.sub(r"\b" + re.escape(required) + r"\s+(?:(?:flavored|flavoured)\s+)?(?:broth|stock|bouillon|flavor|flavour|seasoning|extract)\b", "derivative", text)
            if required in {"chicken", "turkey", "beef", "pork", "fish", "shrimp"}:
                text = re.sub(r"\b(?:vegan|vegetarian|plant based|meatless|mock|imitation)\s+(?:\w+\s+){0,2}" + re.escape(required) + r"\b", "substitute", text)
            if not ingredient_present(ingredient, [text]):
                supported = False
        if supported:
            return True
    return False


def missing_required_ingredients(recipe: Dict[str, Any], required: List[str]) -> List[str]:
    lines = recipe.get("ingredients") or []
    if isinstance(lines, str):
        lines = lines.splitlines()
    return [ingredient for ingredient in required if not recipe_ingredient_present(ingredient, lines)]


def _ingredient_list(text: str, candidates: List[str]) -> List[str]:
    if re.search(r"\b(?:or|any|either|some of|choose|whichever|without|exclude|except|not|no)\b", text, re.I):
        return []
    ingredients = []
    for part in re.split(r",|\band\b|&|\bplus\b", text, flags=re.I):
        part = part.strip(" .:;!?").lower()
        part = re.sub(r"^(?:some |a little |a few )", "", part)
        part = re.sub(r"^(?:\d+[\d./ ]*\s*)(?:(?:cups?|oz|ounces?|pounds?|lbs?|grams?|g|kg)\s+(?:of\s+)?)?", "", part)
        if not part:
            continue
        if len(part.split()) > 6 or re.search(r"\b(?:recipe|recipes|ingredients|ideas|want|need|can|using|these|those|them)\b", part):
            return []
        matched = [candidate for candidate in candidates if recipe_ingredient_present(candidate, [part])]
        ingredients.append(max(matched, key=len) if matched else part)
    return list(dict.fromkeys(ingredients))


def inventory_ingredient_requirements(requests: List[str], candidates: List[str]) -> tuple[List[str], List[str]]:
    inventory = []
    required = []
    removed = []
    for request in requests:
        match = re.search(
            r"\b(?:i|we)\s+(?:have on hand|have(?: got)?)\s+([^.!?;]+?)(?=[.!?;]|"
            r"\s+(?:please\s+)?(?:generate|make|cook|prepare|create|give|show|suggest)\b|$)", request, re.I,
        )
        if match:
            inventory = _ingredient_list(match[1], candidates)
        selection = request[match.end():] if match else request
        selection = re.sub(r"\b(?:don't|do not|never)\s+(?:use|include|incorporate)\b[^.!?]*", "", selection, flags=re.I)
        if re.search(r"\b(?:using|use|with|include|incorporate)\s+(?:(?:all|both)\s+(?:of\s+)?)?(?:these|those|them|both|it)(?:\s+ingredients)?\b", selection, re.I):
            required = list(inventory)
        replacement = re.search(r"\breplace\s+(.+?)\s+with\s+([^.!?]+)", request, re.I)
        if not replacement:
            inverse = re.search(r"\buse\s+(.+?)\s+instead of\s+([^.!?]+)", request, re.I)
            if inverse:
                replacement = (inverse[0], inverse[2], inverse[1])
        if replacement:
            old = [ingredient for ingredient in required if ingredient_present(ingredient, [replacement[1]])]
            if old:
                required = [ingredient for ingredient in required if ingredient not in old]
                required.extend(_ingredient_list(replacement[2], candidates))
                removed.extend(old)
        withdrawal = re.search(r"\b(?:without|omit|remove|skip|(?:don't|do not|no longer) (?:have|use|need))\s+([^.!?]+)", request, re.I)
        if withdrawal:
            old = [ingredient for ingredient in required if ingredient_present(ingredient, [withdrawal[1]])]
            required = [ingredient for ingredient in required if ingredient not in old]
            removed.extend(old)
    return list(dict.fromkeys(required)), [ingredient for ingredient in dict.fromkeys(removed) if ingredient not in required]


def explicit_ingredient_combination(query: str, ingredients: List[str]) -> bool:
    match = re.search(r"\b(?:make|cook|prepare|recipes?|meals?)\b[^.!?]*\b(?:with|using)\s+([^.!?]+)", query, re.I)
    if not match or not isinstance(ingredients, list) or len(ingredients) < 2:
        return False
    selection = match[1]
    if re.search(r"\b(?:or|any|either|some|choose|whichever|without|exclude|except)\b", selection, re.I):
        return False
    return all(ingredient_present(ingredient, [selection]) for ingredient in ingredients)
