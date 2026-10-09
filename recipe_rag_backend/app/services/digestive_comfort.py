import re
import unicodedata
from typing import Any, Dict, List, Optional


DIGESTIVE_REQUEST = re.compile(
    r"\b(?:upset (?:stomach|tummy)|(?:stomach|tummy) (?:is |feels? )?upset|nausea|nauseous|nauseated|queasy|"
    r"sick to (?:my|the|your) stomach|(?:easy|gentle) on (?:my |the |an? |your )?(?:stomach|digestion)|"
    r"sensitive stomach)\b", re.I,
)
STRONG_SPICE = re.compile(
    r"\b(?:(?:chili|chilli|chile) powder|cayenne|jalapenos?|habaneros?|serrano peppers?|"
    r"(?:crushed )?red pepper flakes|(?:red )?chili flakes|crushed red pepper|hot (?:sauce|peppers?)|sriracha|harissa|wasabi)\b", re.I,
)
DEEP_FRY = re.compile(r"\b(?:deep[- ]fry(?:ing|ied)?|deep[- ]fried)\b", re.I)
TOLERANCE_DEPENDENT = re.compile(
    r"\b(?:lentils?|chickpeas?|garbanzos?|(?:black|kidney|pinto|navy|white|cannellini) beans?|"
    r"brown rice|wild rice|quinoa|whole[- ](?:grain|wheat)|bran|broccoli|cabbage|cauliflower|"
    r"almonds?|walnuts?|pecans?|chia|flaxseed)\b", re.I,
)


def digestive_tolerance_cautions(recipe: Dict[str, Any]) -> List[str]:
    return [str(line) for line in (recipe.get("ingredients") or []) if TOLERANCE_DEPENDENT.search(str(line))]


def explicit_digestive_comfort(query: str) -> Optional[str]:
    text = query.lower().replace("’", "'")
    if re.search(r"\b(?:no longer (?:nauseous|nauseated|queasy)|(?:stomach|tummy) (?:is |feels? )?(?:fine|better) now|"
                 r"(?:no longer|don't|do not) have (?:an? )?(?:upset stomach|nausea)|"
                 r"(?:drop|remove) (?:the )?(?:stomach|digestive) (?:restriction|requirement))\b", text):
        return "unrestricted"
    for match in DIGESTIVE_REQUEST.finditer(text):
        if not re.search(r"\b(?:no|not|don't have|do not have|without)\s+(?:an?\s+)?$", text[:match.start()]):
            return "gentle"
    return None


def audit_digestive_comfort(recipe: Dict[str, Any], constraints: Dict[str, Any]) -> List[str]:
    if constraints.get("digestive_comfort") != "gentle":
        return []
    problems = []
    for field in ("ingredients", "instructions", "helpful_tips", "ingredient_adaptations"):
        lines = recipe.get(field) or []
        if isinstance(lines, str):
            lines = lines.splitlines()
        for index, line in enumerate(lines):
            text = unicodedata.normalize("NFKD", str(line)).encode("ascii", "ignore").decode().lower()
            for pattern in (STRONG_SPICE, DEEP_FRY):
                for match in pattern.finditer(text):
                    if re.search(r"\b(?:no|without|avoid|omit|skip|don't|do not)\s+(?:adding |the |any )*$", text[:match.start()]):
                        continue
                    problems.append(f"Gentle-food request conflicts with {field}[{index}]: {line}")
                    break
    return list(dict.fromkeys(problems))
