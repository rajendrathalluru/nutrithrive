import re
from typing import Any, Dict, List


APPLIANCES = {
    "air fryer": r"air[-\s]*fryer",
    "microwave": r"microwave(?: oven)?(?![- ]safe)",
    "slow cooker": r"slow[- ]cooker|crock[- ]?pot",
    "pressure cooker": r"pressure[- ]cooker|instant pot",
    "rice cooker": r"rice[- ]cooker",
    "oven": r"(?<!microwave )(?<!toaster )oven|toaster oven",
    "stove": r"stove(?:top)?|hob|burner",
    "blender": r"blender",
    "food processor": r"food processor",
    "grill": r"grill|barbecue|bbq",
}
PATTERNS = {name: re.compile(r"\b(?:" + pattern + r")\b", re.I) for name, pattern in APPLIANCES.items()}
SETUP = re.compile(r"\b(?:preheat|pre[- ]heat|place|put|arrange|add|transfer|return|load|set|use)\b", re.I)
OPERATION = re.compile(r"\b(?:cook|bake|roast|fry|air[- ]fry|grill|broil|heat|reheat|steam|simmer|boil|blend|puree|purée|process)\b", re.I)
ADVISORY = re.compile(r"\b(?:optional(?:ly)?|could|can also|can use|may use|if desired|if you prefer|alternatively)\b", re.I)
NEGATION = re.compile(r"\b(?:without|avoid|no|not|never|don't|do not|cannot|can't)\b", re.I)


def normalize_equipment(values: Any) -> List[str]:
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, (list, tuple)):
        return []
    normalized = []
    for value in values or []:
        if not isinstance(value, str) or not value.strip():
            continue
        name = next((name for name, pattern in PATTERNS.items() if pattern.fullmatch(value.strip())), value.strip().lower())
        if name not in normalized:
            normalized.append(name)
    return normalized


def explicit_equipment_constraints(query: str) -> Dict[str, List[str]]:
    text = query.lower().replace("’", "'")
    required = []
    exclusive = False
    for name, pattern in PATTERNS.items():
        for match in pattern.finditer(text):
            prefix = re.split(r"[.!?;]", text[:match.start()])[-1]
            suffix = text[match.end():]
            if NEGATION.search(prefix) or re.match(r"\s+(?:is |are )?(?:optional|not (?:needed|required))\b", suffix):
                continue
            if re.search(r"\b(?:or|either|instead of)\b", text):
                continue
            direct = re.search(r"\b(?:with|using|use|in)\s+(?:only\s+)?(?:(?:an?|the|my)\s+)?$", prefix)
            conjunction = re.search(r"\b(?:with|using|use|in)\b.{0,80}\band\s+(?:(?:an?|the|my)\s+)?$", prefix)
            if direct or conjunction or re.match(r"\s+(?:recipes?|meals?|dishes?)\b", suffix):
                required.append(name)
                exclusive = exclusive or bool(re.search(r"\bonly\s+(?:(?:use|using)\s+)?(?:(?:an?|the|my)\s+)?$", prefix) or re.match(r"\s+only\b", suffix))
    if not required:
        return {}
    required = list(dict.fromkeys(required))
    return {"equipment_required": required, "equipment_only": required if exclusive else []}


def equipment_usage_evidence(recipe: Dict[str, Any], equipment: Any) -> Dict[str, Dict[str, Any]]:
    required = normalize_equipment(equipment)
    evidence = {}
    active = set()
    instructions = recipe.get("instructions") or []
    if isinstance(instructions, str):
        instructions = instructions.splitlines()
    for index, instruction in enumerate(instructions):
        for clause in re.split(r"[.!?;]\s*", str(instruction).replace("’", "'")):
            action = SETUP.search(clause) or OPERATION.search(clause)
            prefix = clause[:action.start()] if action else clause
            if ADVISORY.search(clause) or NEGATION.search(prefix):
                continue
            mentioned = {name for name, pattern in PATTERNS.items() if pattern.search(clause)}
            mentioned = {name for name in mentioned if not re.search(
                r"\b(?:without|not|instead of)\s+(?:(?:in|using|an?|the)\s+)*" + PATTERNS[name].pattern,
                clause, re.I,
            )}
            operation = OPERATION.search(clause)
            if mentioned and (SETUP.search(clause) or operation):
                active = mentioned
            elif re.search(r"\b(?:skillet|saucepan|frying pan|pot)\b", clause) and (SETUP.search(clause) or operation):
                active = {"stove"}
            air_fry_action = re.search(r"\bair[- ]fry\b", clause, re.I)
            if air_fry_action and not re.search(r"\b(?:not|never|instead of|without)\s+$", clause[:air_fry_action.start()], re.I):
                active = {"air fryer"}
                operation = True
            elif re.match(r"\s*(?:\d+[.)]?\s*)?microwave\s+(?!safe\b)", clause, re.I):
                active = {"microwave"}
                operation = True
            if operation:
                for name in active & set(required):
                    evidence.setdefault(name, {"instruction_index": index, "quote": str(instruction)})
    return evidence


def audit_equipment(recipe: Dict[str, Any], constraints: Dict[str, Any]) -> List[str]:
    required = normalize_equipment(constraints.get("equipment_required"))
    supported = [name for name in required if name in PATTERNS]
    evidence = equipment_usage_evidence(recipe, supported)
    return [f"No cooking/preparation step uses required equipment: {name}" for name in supported if name not in evidence]
