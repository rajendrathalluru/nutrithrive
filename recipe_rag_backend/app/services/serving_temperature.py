import re
from typing import Any, Dict, List, Optional


TEMPERATURES = {"warm_not_hot", "warm", "hot", "cold", "room_temperature"}
SERVING_VERB = r"\b(?:serve[ds]?|eat|eaten|enjoy(?:ed)?)(?:\s+(?:it|them|this|the dish|the meal|the soup|the salad))?\s+"
WARM_SERVING = re.compile(
    SERVING_VERB + r"(?:(?:while|still|comfortably|slightly)\s+)*(?:warm|lukewarm)\b|"
    r"\bcool\b[^.!?]{0,65}\buntil\s+(?:comfortably\s+)?(?:warm|lukewarm)\b", re.I,
)
COLD_SERVING = re.compile(SERVING_VERB + r"(?:well[- ]?)?(?:cold|chilled)\b", re.I)
ROOM_SERVING = re.compile(SERVING_VERB + r"(?:at\s+)?room temperature\b", re.I)
HOT_SERVING = re.compile(SERVING_VERB + r"(?:(?:piping|steaming)\s+)?hot\b", re.I)
NEGATED_REQUEST = re.compile(
    r"\b(?:not|never|avoid|don't|do not)(?:\s+(?:want|show|suggest|recommend))?\s+(?:(?:any|comfortably|slightly)\s+)?$", re.I,
)


def explicit_serving_temperature(query: str) -> Optional[str]:
    text = query.lower().replace("’", "'")
    if re.search(r"\b(?:any (?:serving )?temperature|temperature (?:doesn't|does not) matter|"
                 r"(?:don't|do not) care about (?:the )?(?:serving )?temperature|"
                 r"(?:drop|remove) (?:the )?(?:serving )?temperature (?:restriction|requirement))\b", text):
        return "any"
    matches = []
    for temperature, pattern in (
        ("warm_not_hot", r"\b(?:warm\s*(?:[,;]|but|and)?\s*(?:not|never)\s+(?:piping\s+)?hot|lukewarm|comfortably warm)\b"),
        ("cold", r"\b(?:serve[ds]?|eat|eaten|enjoy(?:ed)?|taste\s+good)\s+(?:it\s+|them\s+)?(?:cold|chilled)\b|\bcold (?:meals?|foods?|recipes?)\b"),
        ("room_temperature", r"\b(?:serve[ds]?|eat|eaten|enjoy(?:ed)?|taste\s+good)\s+(?:at\s+)?room temperature\b"),
        ("warm", r"\b(?:serve[ds]?|eat|eaten|enjoy(?:ed)?|taste\s+good)\s+(?:it\s+|them\s+)?warm\b|\bwarm (?:meals?|foods?|recipes?)\b"),
        ("hot", r"\b(?:serve[ds]?|eat|eaten|enjoy(?:ed)?)\s+(?:it\s+|them\s+)?(?:piping\s+)?hot\b"),
    ):
        for match in re.finditer(pattern, text):
            if not NEGATED_REQUEST.search(text[:match.start()]):
                matches.append((match.start(), match.end(), temperature))
    if not matches:
        return None
    latest = max(matches)
    if any(start < latest[1] and end > latest[0] and temperature == "warm_not_hot" for start, end, temperature in matches):
        return "warm_not_hot"
    return latest[2]


def is_temperature_food_guidance(query: str) -> bool:
    text = query.lower()
    if re.search(r"\b(?:recipes?|instructions?|steps?|make|cook|prepare|these|those|above)\b", text):
        return False
    return bool(
        explicit_serving_temperature(text)
        and re.search(r"\b(?:show|suggest|recommend|list|what|which|why)\b", text)
        and re.search(r"\bfoods?\b", text)
    )


def _positive_match(text: str, pattern: re.Pattern) -> bool:
    return any(
        not re.search(r"\b(?:not|never|don't|do not)\s+$", text[:match.start()], re.I)
        for match in pattern.finditer(text)
    )


def audit_serving_temperature(recipe: Dict[str, Any], requirement: str, assessment: Any) -> List[str]:
    if not requirement:
        return []
    if requirement not in TEMPERATURES:
        return ["Unsupported serving-temperature requirement"]
    problems = []
    if not isinstance(assessment, dict):
        assessment = {}
    for field in ("conflicting_guidance", "food_safety_concerns"):
        if not isinstance(assessment.get(field), list):
            problems.append(f"Serving-temperature assessment missing {field}")
        elif assessment[field]:
            problems.append(f"Serving-temperature assessment reports {field}")
    target = {
        "warm_not_hot": WARM_SERVING, "warm": WARM_SERVING, "hot": HOT_SERVING,
        "cold": COLD_SERVING, "room_temperature": ROOM_SERVING,
    }[requirement]
    evidence = assessment.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        problems.append("Missing final serving-temperature evidence")
        evidence = []
    supported = False
    for citation in evidence:
        if not isinstance(citation, dict):
            problems.append("Invalid serving-temperature citation")
            continue
        field = citation.get("field")
        value = recipe.get(field) if field in {"instructions", "source_notes"} else None
        if isinstance(value, list):
            index = citation.get("index")
            value = value[index] if isinstance(index, int) and not isinstance(index, bool) and 0 <= index < len(value) else None
        quote = citation.get("quote")
        if not isinstance(value, str) or not isinstance(quote, str) or not quote.strip() or quote not in value:
            problems.append("Serving-temperature citation does not match recipe data")
        elif _positive_match(quote, target) and _positive_match(value, target):
            supported = True
    if not supported:
        problems.append("Recipe does not establish the requested final serving temperature")
    if requirement in {"warm", "warm_not_hot"}:
        for field in ("instructions", "helpful_tips", "ingredient_adaptations", "source_notes"):
            value = recipe.get(field, [])
            lines = value if isinstance(value, list) else str(value or "").splitlines()
            for line in lines:
                for text in re.split(r"(?<=[.!?])\s+", str(line)):
                    if _positive_match(text, WARM_SERVING):
                        continue
                    if supported and re.match(r"\s*(?:alternatively|or)\b", text, re.I):
                        continue
                    conflicts = (COLD_SERVING, ROOM_SERVING) + ((HOT_SERVING,) if requirement == "warm_not_hot" else ())
                    if any(_positive_match(text, pattern) for pattern in conflicts):
                        problems.append(f"Conflicting serving instruction in {field}: {text}")
    return list(dict.fromkeys(problems))
