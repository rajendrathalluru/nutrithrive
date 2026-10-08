import math
import re
from typing import Any, Dict, List


HEAT_ACTION = re.compile(
    r"\b(?:pre[- ]?heat|reheat|heat|boil(?:ing)?|simmer(?:ing)?|saute|sauté|fry|frying|"
    r"stir[- ]fry|bake|baking|roast|roasting|grill|grilling|broil|steam|steaming|"
    r"microwave|sear|poach|blanch|toast|melt|cook|cooking)\b|\b(?:hot|boiling) water\b", re.I,
)
STEAM_ACTION = re.compile(r"\b(?:steam|steaming|boil|boiling|simmer|simmering|pressure[- ]cook)\b", re.I)
SPLATTER_ACTION = re.compile(r"\b(?:fry|frying|stir[- ]fry|saute|sauté|sear|splatter)\b", re.I)
NEGATED_ACTION = re.compile(r"\b(?:do not|don't|never|without|no need to|no|not)\s+(?:use\s+|any\s+)?$", re.I)
DURATION = re.compile(
    r"(?<![\d.])(\d+(?:\.\d+)?)\s*(?:(?:-|–|—|to)\s*(\d+(?:\.\d+)?)\s*)?"
    r"(?:more\s+|additional\s+)?(seconds?|secs?|minutes?|mins?|hours?|hrs?)\b", re.I,
)


def explicit_preparation_constraints(query: str) -> Dict[str, Any]:
    text = query.lower().replace("’", "'")
    constraints = {}
    if re.search(r"\b(?:no[- ](?:heat|cook(?:ing)?)|without (?:using )?(?:any )?(?:heat|cooking)|"
                 r"(?:cooked|cook|prepare(?:d)?) cold|not cooking|don't (?:require|need) (?:any )?cooking)\b", text):
        constraints["preparation_mode"] = "no_heat"
    if re.search(r"\b(?:only assembl(?:y|e|ing)|assembl(?:y|e|ing)[- ]only|just assembl(?:e|ing))\b", text):
        constraints["preparation_mode"] = "assembly_only"
    if re.search(r"\b(?:cooking|heat|heating) is (?:fine|ok(?:ay)?|allowed)\b|"
                 r"\b(?:remove|drop) (?:the )?no[- ](?:heat|cook) (?:rule|requirement|restriction)\b", text):
        constraints["preparation_mode"] = None
    for hazard in ("steam", "splatter"):
        if re.search(r"\b(?:no|without|avoid|don't|do not|doesn't|does not)\b[^.!?]{0,45}\b" + hazard + r"\b", text):
            constraints[f"avoid_{hazard}"] = True
        if re.search(r"\b" + hazard + r"(?:ing)? is (?:fine|ok(?:ay)?|allowed)\b", text):
            constraints[f"avoid_{hazard}"] = False
    if re.search(r"\b(?:(?:only|all) frozen (?:foods?|ingredients?)|frozen ingredients (?:only|from start to finish))\b", text):
        constraints["ingredient_storage"] = "frozen_only"
    limit = re.search(r"\b(less than|under|within|at most|no more than)\s+(\d+(?:\.\d+)?)\s*(minutes?|mins?|hours?|hrs?)\b", text)
    trailing_limit = re.search(r"\b(\d+(?:\.\d+)?)\s*(minutes?|mins?|hours?|hrs?)\s+(?:or less|or fewer|maximum|max)\b", text)
    if limit:
        constraints["time_max_minutes"] = float(limit[2]) * (60 if limit[3].startswith("h") else 1)
        constraints["time_limit_exclusive"] = limit[1] in {"less than", "under"}
    elif trailing_limit:
        constraints["time_max_minutes"] = float(trailing_limit[1]) * (60 if trailing_limit[2].startswith("h") else 1)
        constraints["time_limit_exclusive"] = False
    return constraints


def _positive_action(text: str, pattern: re.Pattern) -> bool:
    text = re.sub(r"\b(?:cooking|cook's) tips?\s*:\s*", "", text, flags=re.I)
    for match in pattern.finditer(text):
        prefix = text[max(0, match.start() - 45):match.start()]
        suffix = text[match.end():]
        if re.match(r"\s+(?:(?:is|are)\s+)?(?:not (?:needed|required|necessary)|isn't required)\b", suffix, re.I):
            continue
        if match[0].lower() == "toast" and re.search(r"\b(?:purchased|packaged|ready[- ]made)\s+(?:\w+[- ]\w+\s+)?$", prefix, re.I):
            continue
        if not NEGATED_ACTION.search(prefix) and not re.search(r"\b(?:no[- ]|pre[- ])$", prefix, re.I):
            return True
    return False


def _guidance_lines(recipe: Dict[str, Any]):
    for field in ("instructions", "helpful_tips", "ingredient_adaptations", "storage_instructions", "source_notes"):
        value = recipe.get(field, [])
        lines = value if isinstance(value, list) else str(value or "").splitlines()
        for index, line in enumerate(lines):
            if str(line).strip():
                yield field, index, str(line)


def _duration_minutes(text: str) -> List[float]:
    durations = []
    for match in DURATION.finditer(text):
        amount = max(float(match[1]), float(match[2] or match[1]))
        unit = match[3].lower()
        durations.append(amount * 60 if unit.startswith("h") else amount / 60 if unit.startswith("s") else amount)
    return durations


def _exceeds_limit(minutes: float, constraints: Dict[str, Any]) -> bool:
    limit = constraints["time_max_minutes"]
    return minutes >= limit if constraints.get("time_limit_exclusive") else minutes > limit


def declared_time_check(recipe: Dict[str, Any]) -> Dict[str, Any] | None:
    declarations = []
    total_time = recipe.get("total_time")
    if isinstance(total_time, str) and total_time.strip():
        declarations.append(("total_time", total_time.strip()))
    notes = str(recipe.get("source_notes") or "")
    for match in re.finditer(r"\btotal(?:\s+elapsed)?\s+time\s*[:=]?\s*([^|\n]+)", notes, re.I):
        declarations.append(("source_notes", match[0]))
    totals = []
    evidence = []
    for field, declaration in declarations:
        value = re.sub(r"^(?:estimated\s+)?(?:total(?:\s+elapsed)?\s+time\s*[:=]?\s*)?", "", declaration, flags=re.I).strip()
        duration_end = 0
        total = 0
        for duration in DURATION.finditer(value):
            if value[duration_end:duration.start()].strip().lower() not in {"", "and"}:
                break
            total += _duration_minutes(duration[0])[0]
            duration_end = duration.end()
        if not duration_end or value[duration_end:].strip(" .;"):
            return None
        totals.append(total)
        evidence.append({"field": field, "quote": declaration})
    if not totals:
        return None
    return {"total_minutes": max(totals), "evidence": evidence}


def time_limit_generation_guidance(constraints: Dict[str, Any]) -> str:
    limit = constraints.get("time_max_minutes")
    if not isinstance(limit, (int, float)) or isinstance(limit, bool) or not math.isfinite(limit) or limit < 0:
        return ""
    comparison = "strictly less than" if constraints.get("time_limit_exclusive") else "at most"
    boundary = (
        f"Exactly {limit:g} minutes does NOT qualify."
        if constraints.get("time_limit_exclusive") else f"Exactly {limit:g} minutes is allowed."
    )
    return f"""ELAPSED-TIME BUDGET: {comparison} {limit:g} minutes ({limit * 60:g} seconds). {boundary}
Design the preparation to fit this budget; do not merely relabel a slower recipe with a shorter time.
For a very short budget prefer simple assembly or blending with explicitly ready-to-eat ingredients.
Specify purchased prewashed/precut/ready-cooked forms when needed; do not hide preparation in the ingredient list.
Count opening, measuring, washing, cutting, equipment setup, cooking, waiting, and serving in total_time.
State an estimated total_time with numeric units and realistic timings for ALL preparation steps.
Use seconds for brief steps. Sequential timings must fit the total; state any actual overlap explicitly.
Do not round a time up to the excluded boundary. Do not shorten necessary cooking for food safety.
Keep all other requirements. If no realistic recipe fits, return an empty array rather than a false match."""


def _audit_time(recipe: Dict[str, Any], constraints: Dict[str, Any], check: Any) -> List[str]:
    problems = []
    total = check.get("total_minutes") if isinstance(check, dict) else None
    if not isinstance(total, (int, float)) or isinstance(total, bool) or not math.isfinite(total) or total < 0:
        return ["Total elapsed preparation time is unknown"]
    if _exceeds_limit(total, constraints):
        problems.append(f"Total elapsed time {total} minutes exceeds the requested limit")
    declared = declared_time_check(recipe)
    if declared and (declared["total_minutes"] > total or _exceeds_limit(declared["total_minutes"], constraints)):
        problems.append("Declared total elapsed time contradicts the assessment or requested limit")
    evidence = check.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        problems.append("Total elapsed time lacks recipe citations")
    else:
        for citation in evidence:
            if not isinstance(citation, dict):
                problems.append("Invalid total-time citation")
                continue
            field = citation.get("field")
            value = recipe.get(field) if field in {"instructions", "source_notes", "description", "total_time"} else None
            if isinstance(value, list):
                index = citation.get("index")
                value = value[index] if isinstance(index, int) and not isinstance(index, bool) and 0 <= index < len(value) else None
            quote = citation.get("quote")
            if not isinstance(value, str) or not isinstance(quote, str) or not quote.strip() or quote not in value:
                problems.append("Total-time citation does not match recipe data")
            elif not _duration_minutes(quote):
                problems.append("Total-time citation does not specify a duration")
            elif any(duration > total for duration in _duration_minutes(quote)):
                problems.append("Total-time estimate contradicts its cited duration")
    step_durations = []
    parallel_steps = False
    for index, line in enumerate(recipe.get("instructions", [])):
        text = str(line)
        if re.search(r"\b(?:leftovers?|refrigerat|freez|store|keeps?)", text, re.I) and not re.search(
            r"\b(?:before|until|chill|marinate|set|overnight)\b", text, re.I
        ):
            continue
        durations = _duration_minutes(text)
        if any(_exceeds_limit(duration, constraints) for duration in durations):
            problems.append(f"Instruction {index} alone exceeds the requested time: {line}")
        if durations and not re.search(r"\btotal\b", text, re.I):
            step_durations.append(max(durations))
        parallel_steps = parallel_steps or bool(re.search(
            r"\b(?:meanwhile|simultaneously|at the same time)\b|"
            r"\bwhile\b[^.!?]{0,45}\b(?:cooks|bakes|roasts|simmers|chills|rests|is cooking|is baking)\b", text, re.I
        ))
        if re.search(r"\bovernight\b", text, re.I) and not durations:
            problems.append("Overnight preparation has no verified duration")
    lower_bound = max(step_durations, default=0) if parallel_steps else sum(step_durations)
    if lower_bound > total or _exceeds_limit(lower_bound, constraints):
        problems.append("Elapsed time contradicts the timed preparation steps")
    for match in re.finditer(r"\btotal(?:\s+time)?\s*[:=]?\s*(\d[^|\n]*)", str(recipe.get("source_notes", "")), re.I):
        source_total = 0
        duration_end = 0
        for duration in DURATION.finditer(match[1]):
            if match[1][duration_end:duration.start()].strip() not in {"", "and"}:
                break
            source_total += _duration_minutes(duration[0])[0]
            duration_end = duration.end()
        if source_total > total or _exceeds_limit(source_total, constraints):
            problems.append(f"Source total time exceeds the requested limit: {match[0]}")
    return problems


def audit_preparation(recipe: Dict[str, Any], constraints: Dict[str, Any], assessment: Dict[str, Any]) -> List[str]:
    problems = []
    no_heat = constraints.get("preparation_mode") in {"no_heat", "assembly_only"}
    avoid_steam = constraints.get("avoid_steam") is True
    avoid_splatter = constraints.get("avoid_splatter") is True
    if no_heat or avoid_steam or avoid_splatter:
        check = assessment.get("preparation_check")
        fields = ("conflicting_steps", "unresolved_dependencies", "conflicting_guidance")
        if not isinstance(check, dict) or any(not isinstance(check.get(field), list) for field in fields):
            problems.append("Preparation assessment is missing or incomplete")
        elif any(check[field] for field in fields):
            problems.append("Preparation assessment reports incompatible steps, dependencies, or guidance")
        if not recipe.get("instructions"):
            problems.append("Missing instructions for preparation verification")
        for field, index, line in _guidance_lines(recipe):
            if no_heat and _positive_action(line, HEAT_ACTION):
                problems.append(f"No-heat conflict in {field}[{index}]: {line}")
            elif avoid_steam and _positive_action(line, STEAM_ACTION):
                problems.append(f"Steam conflict in {field}[{index}]: {line}")
            elif avoid_splatter and _positive_action(line, SPLATTER_ACTION):
                problems.append(f"Splatter conflict in {field}[{index}]: {line}")
    if constraints.get("ingredient_storage") == "frozen_only":
        check = assessment.get("frozen_ingredient_check")
        fields = ("non_frozen_ingredients", "unspecified_forms", "conflicting_guidance")
        if not isinstance(check, dict) or any(not isinstance(check.get(field), list) for field in fields):
            problems.append("Frozen ingredient assessment is missing or incomplete")
        elif any(check[field] for field in fields):
            problems.append("Recipe is not achievable using only frozen ingredients")
        for ingredient in recipe.get("ingredients", []):
            text = str(ingredient).strip()
            if not text or text.endswith(":"):
                continue
            if not re.search(r"\b(?:frozen|freezer)\b", text, re.I) or re.search(
                r"\b(?:fresh|canned|dried|refrigerated|not frozen|non[- ]frozen)\b", text, re.I
            ):
                problems.append(f"Ingredient not specified exclusively in frozen form: {text}")
    limit = constraints.get("time_max_minutes")
    if limit is not None:
        if isinstance(limit, (int, float)) and not isinstance(limit, bool) and math.isfinite(limit) and limit >= 0:
            problems.extend(_audit_time(recipe, constraints, assessment.get("time_check")))
        else:
            problems.append("Invalid numeric time requirement")
    return list(dict.fromkeys(problems))
