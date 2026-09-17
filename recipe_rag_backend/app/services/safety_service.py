import re
from typing import Any, Dict, List, Optional


class SafetyService:
    _CRISIS_PATTERNS = [
        r"\b(?:suicidal|sucidal|suicidial|suicidle)\b",
        r"\bsuicid(?:e|al) (?:thoughts?|ideation|plan|plans)\b",
        r"\b(?:kill|hurt|harm) myself\b",
        r"\bself[- ]harm(?:ing)?\b",
        r"\b(?:end|take) my (?:own )?life\b",
        r"\b(?:want|wish|plan(?:ning)?) to die\b",
        r"\b(?:do not|don['’]?t|dont|no longer) want to (?:live|be alive)\b",
        r"\bbetter off dead\b",
        r"\bunalive myself\b",
        r"\bend it all\b",
        r"\b(?:want|plan(?:ning)?) to overdose\b",
        r"\b(?:want|plan(?:ning)?) to jump (?:off|from)\b",
        r"\b(?:want|plan(?:ning)?) to hang myself\b",
    ]

    _NEGATED_CRISIS_PATTERNS = [
        r"\b(?:i am|i['’]?m|im) not (?:currently )?(?:suicidal|sucidal|suicidial)\b",
        r"\b(?:i do not|i don['’]?t|i dont) have (?:any )?(?:suicidal|sucidal|suicidial) thoughts\b",
        r"\bno (?:current )?(?:suicidal|sucidal|suicidial) thoughts\b",
    ]

    _CURRENT_SAFETY_PATTERNS = [
        r"\b(?:i am|i['’]?m|im) safe now\b",
        r"\bi am not in immediate danger\b",
        r"\bi contacted (?:988|9-8-8|a crisis line|emergency services)\b",
        r"\bsomeone is (?:here|with me) now\b",
    ]

    _CRISIS_FOLLOW_UP_PATTERNS = [
        r"\b(?:these|those|the) thoughts\b",
        r"\b(?:still|again) (?:feel|feeling|having|thinking)\b",
        r"\b(?:not safe|in danger|have a plan|access to means)\b",
        r"\b(?:help me|stay with me|what now|what should i do)\b",
        r"\bwhat can i eat(?: now)?\b",
        r"\b(?:getting|feeling) worse\b",
    ]

    _SHORT_CRISIS_REPLIES = {
        "yes",
        "no",
        "maybe",
        "i don't know",
        "i dont know",
        "not sure",
        "i am not safe",
        "i'm not safe",
        "im not safe",
    }

    def should_intercept(
        self,
        query: str,
        conversation_history: Optional[List[Dict[str, Any]]] = None,
    ) -> bool:
        if self.contains_crisis_language(query):
            return True

        if self._states_current_safety(query):
            return False

        if not self._is_crisis_follow_up(query):
            return False

        for message in reversed(conversation_history or []):
            if not isinstance(message, dict):
                continue
            if str(message.get("role", "")).lower() != "user":
                continue
            return self.contains_crisis_language(str(message.get("content", "")))

        return False

    def contains_crisis_language(self, text: str) -> bool:
        normalized = self._normalize(text)
        if not normalized:
            return False

        without_negated_statements = normalized
        for pattern in self._NEGATED_CRISIS_PATTERNS:
            without_negated_statements = re.sub(pattern, " ", without_negated_statements)

        return any(
            re.search(pattern, without_negated_statements)
            for pattern in self._CRISIS_PATTERNS
        )

    def build_crisis_response(
        self,
        query: str,
        mode: str = "auto",
        conversation_history: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        response_text = (
            "I'm really sorry you're dealing with this. Your immediate safety matters more than choosing a meal right now.\n\n"
            "If you might act on these thoughts, have a plan, or have access to something you could use to hurt yourself, "
            "call local emergency services now or go to the nearest emergency department. In the U.S., call or text 988. "
            "In Canada, call or text 9-8-8. Elsewhere, use https://findahelpline.com to find a verified local crisis line.\n\n"
            "Please move away from anything you could use to hurt yourself and contact someone you trust who can stay with you. "
            "If eating feels manageable while you reach out, choose something requiring no preparation, such as yogurt, soup, "
            "or a nutrition drink—but please do not stay alone.\n\n"
            "Are you in immediate danger, or do you have a plan or access to means to hurt yourself right now?"
        )

        return {
            "query": query,
            "response": response_text,
            "source": "safety_redirect",
            "matches_found": 0,
            "mode": mode,
            "source_documents": [],
            "dynamically_adapted": False,
            "instructions_generated": False,
            "aicr_compliant": False,
            "verification_details": {
                "total_candidates": 0,
                "passed_verification": 0,
                "failed_verification": 0,
                "llm_generated": 0,
            },
            "performance": {"total_time_seconds": 0},
            "conversation_context_used": bool(conversation_history),
            "previous_messages_considered": len(conversation_history or []),
            "safety_redirect": True,
            "safety_category": "self_harm_crisis",
        }

    def _states_current_safety(self, text: str) -> bool:
        normalized = self._normalize(text)
        return any(re.search(pattern, normalized) for pattern in self._CURRENT_SAFETY_PATTERNS)

    def _is_crisis_follow_up(self, text: str) -> bool:
        normalized = self._normalize(text).strip(" .!?\t\n")
        if normalized in self._SHORT_CRISIS_REPLIES:
            return True
        return any(re.search(pattern, normalized) for pattern in self._CRISIS_FOLLOW_UP_PATTERNS)

    def _normalize(self, text: str) -> str:
        normalized = str(text or "").lower().strip()
        normalized = re.sub(r"\s+", " ", normalized)
        return normalized


safety_service = SafetyService()
