import re


STORAGE_CUE = re.compile(
    r"\b(?:refrigerate(?:d)?|freeze|freezing|reheat\w*|thaw\w*)\b(?![- ]dried)"
    r"|\b(?:store[ds]?|storing|keeps?|leftovers?)\b.{0,140}\b(?:refrigerator|fridge|freezer|"
    r"airtight|covered|containers?|days?|weeks?|months?)\b"
    r"|\b(?:can|may) be frozen\b",
    re.IGNORECASE,
)
GUIDANCE_LABEL = re.compile(
    r"(?:Quick Tips|Cooking Tip|Keep it Healthy|Tip|Notes|Directions|Instructions|Storage):\s*",
    re.IGNORECASE,
)


def requests_reheating(query: str) -> bool:
    text = str(query or "").lower().replace("’", "'")
    pattern = (
        r"\b(?:when|after) (?:being )?reheat(?:ed|ing)\b|"
        r"\breheat(?:s)? well\b|\b(?:reheat[- ]friendly|reheatable)\b|"
        r"\bcan (?:(?:i|we|be) )?reheat(?:ed)?\b|\b(?:suitable|good) for reheating\b"
    )
    for match in re.finditer(pattern, text):
        if not re.search(r"\b(?:not|never|without|don't|doesn't|do not|does not)\s*$", text[:match.start()]):
            return True
    return False


def extract_storage_guidance(text: str) -> str:
    """Keep storage sentences without flattening neighboring recipe fields or bullet points."""
    without_ingredients = re.sub(
        r"(?:^|\n)Ingredients:[\s\S]*?(?=\n(?:Directions|Instructions|Notes):|\Z)",
        "", str(text or ""), flags=re.IGNORECASE,
    )
    labeled = GUIDANCE_LABEL.sub("\n", without_ingredients)
    fragments = re.split(r"\n+|[•|]|(?<=[.!?])\s+", labeled)
    snippets = []
    for fragment in fragments:
        sentence = re.sub(r"\s+", " ", fragment).strip().lstrip("-* ")
        if sentence and STORAGE_CUE.search(sentence) and sentence not in snippets:
            snippets.append(sentence)
    return " ".join(snippets)


def storage_summary(text: str, max_chars: int = 600) -> str:
    guidance = extract_storage_guidance(text)
    if not guidance or len(guidance) > max_chars:
        return "See the recipe card for complete storage guidance."
    return guidance
