import logging
import json
import re
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

class IntentAnalyzer:
    def __init__(self):
        self.llm = None
        self.intent_cache = {}
        self.cache_hits = 0
        self.cache_misses = 0
        
    def initialize(self, llm):
        self.llm = llm
    
    def understand_query_intent(self, query: str) -> Dict[str, Any]:
        """Original intent analysis without context"""
        normalized_query = self._normalize_query(query)
        if normalized_query in self.intent_cache:
            self.cache_hits += 1
            logger.info(f"Intent cache HIT for query: '{query}'")
            return self.intent_cache[normalized_query]
        
        self.cache_misses += 1
        
        try:
            intent_prompt = self._build_intent_prompt(query)
            response = self.llm.predict(intent_prompt)
            intent_data = self._parse_intent_response(response)
            intent_data = self._post_process_intent(query, intent_data)
            
            self.intent_cache[normalized_query] = intent_data
            return intent_data
            
        except Exception as e:
            logger.error(f"Error understanding query intent: {e}")
            return self._get_fallback_intent_data(query)
    
    def understand_query_intent_with_context(self, query: str, conversation_history: List[Dict] = None) -> Dict[str, Any]:
        """Enhanced intent analysis with conversation context"""
        if not conversation_history:
            return self.understand_query_intent(query)
        
        try:
            # Build conversation context
            context_lines = []
            for msg in conversation_history[-6:]:  # Last 3 exchanges
                role = "User" if msg.get("role") == "user" else "Assistant"
                context_lines.append(f"{role}: {msg.get('content', '')}")
            
            conversation_context = "\n".join(context_lines)
            
            enhanced_prompt = f"""You are an expert at understanding user recipe queries WITH conversation context.

CONVERSATION HISTORY (most recent first):
{conversation_context}

CURRENT USER QUERY: "{query}"

Analyze this query considering the conversation history. Extract ALL relevant information including:

1. **Constraints** (from current query AND previous context)
2. **Preferences** (from current query AND previous context)  
3. **Search Strategy** (considering the full conversation flow)

Pay special attention to:
- Follow-up questions that reference previous recipes
- Refinements or changes to previous constraints
- New information that builds on previous context

Return the SAME JSON format as the original intent analysis, but with context-aware understanding.
"""

            response = self.llm.predict(enhanced_prompt)
            intent_data = self._parse_intent_response(response)
            intent_data = self._post_process_intent(query, intent_data, conversation_history)
            logger.info(f"Context-aware intent analysis: {intent_data['query_type']}")
            
            # Cache with context consideration
            cache_key = self._normalize_query(query + str(hash(str(conversation_history))))
            self.intent_cache[cache_key] = intent_data
            
            return intent_data
            
        except Exception as e:
            logger.error(f"Error in context-aware intent analysis: {e}")
            fallback_intent = self._get_fallback_intent_data(query)
            return self._post_process_intent(query, fallback_intent, conversation_history)
    
    def _build_intent_prompt(self, query: str) -> str:
        """Build the intent analysis prompt"""
        return f"""You are an expert at understanding user recipe queries. Analyze this query and extract ALL relevant information.

User Query: "{query}"

Extract the following information:

[Your existing intent prompt structure here - too long to duplicate]
"""

    def _parse_intent_response(self, response: str) -> Dict[str, Any]:
        """Parse the LLM response into intent data"""
        response = response.strip()
        if response.startswith("```json"):
            response = response[7:]
        elif response.startswith("```"):
            response = response[3:]
        if response.endswith("```"):
            response = response[:-3]
        response = response.strip()
        
        return json.loads(response)
    
    def _normalize_query(self, query: str) -> str:
        """Normalize query for caching"""
        normalized = query.lower().strip()
        normalized = re.sub(r'\s+', ' ', normalized)
        normalized = normalized.replace('?', '').replace('!', '').strip()
        return normalized
    
    def _get_fallback_intent_data(self, query: str) -> Dict[str, Any]:
        """Fallback intent data"""
        return {
            "query_type": "general",
            "constraints": {
                "budget_max": None,
                "time_max_minutes": None,
                "max_ingredients": None,
                "min_ingredients": None,
                "ingredients_available": [],
                "ingredients_must_use": [],
                "equipment_required": [],
                "equipment_only": [],
                "dietary_restrictions": [],
                "allergens_to_avoid": [],
                "health_conditions": [],
                "skill_level": None
            },
            "preferences": {
                "cuisine_types": [],
                "flavor_profiles": [],
                "meal_types": [],
                "texture_preferences": [],
                "nutritional_goals": [],
                "cooking_methods": []
            },
            "cancer_patient_specific": {
                "symptoms": [],
                "dietary_needs": [],
                "texture_requirements": []
            },
            "search_strategy": {
                "primary_focus": query,
                "search_keywords": query.split()[:5],
                "must_match_criteria": [],
                "enhanced_query": query
            }
        }

    def _post_process_intent(
        self,
        query: str,
        intent_data: Dict[str, Any],
        conversation_history: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        constraints = intent_data.setdefault("constraints", {})
        preferences = intent_data.setdefault("preferences", {})
        cancer_specific = intent_data.setdefault("cancer_patient_specific", {})
        strategy = intent_data.setdefault("search_strategy", {})

        constraints.setdefault("ingredients_available", [])
        constraints.setdefault("ingredients_must_use", [])
        constraints.setdefault("equipment_required", [])
        constraints.setdefault("equipment_only", [])
        constraints.setdefault("dietary_restrictions", [])
        constraints.setdefault("allergens_to_avoid", [])
        constraints.setdefault("health_conditions", [])
        preferences.setdefault("cuisine_types", [])
        preferences.setdefault("meal_types", [])
        preferences.setdefault("nutritional_goals", [])
        cancer_specific.setdefault("symptoms", [])

        query_lower = query.lower()
        cuisines = self._extract_cuisine_types(query_lower)
        meal_types = self._extract_meal_types(query_lower)
        nutritional_goals = self._extract_nutrition_goals(query_lower)
        symptoms = self._extract_symptoms(query_lower)

        if cuisines:
            preferences["cuisine_types"] = self._merge_unique(preferences["cuisine_types"], cuisines)
        if meal_types:
            preferences["meal_types"] = self._merge_unique(preferences["meal_types"], meal_types)
        if nutritional_goals:
            preferences["nutritional_goals"] = self._merge_unique(preferences["nutritional_goals"], nutritional_goals)
        if symptoms:
            cancer_specific["symptoms"] = self._merge_unique(cancer_specific["symptoms"], symptoms)

        if self._mentions_red_meat_avoidance(query_lower):
            constraints["avoid_red_meat"] = True
            constraints["dietary_restrictions"] = self._merge_unique(
                constraints["dietary_restrictions"],
                ["avoid red meat"]
            )

        if conversation_history and self._is_follow_up_query(query_lower):
            previous_context = self._extract_context_from_history(conversation_history)
            if not preferences["cuisine_types"] and previous_context["cuisine_types"]:
                preferences["cuisine_types"] = previous_context["cuisine_types"]
            if not preferences["meal_types"] and previous_context["meal_types"]:
                preferences["meal_types"] = previous_context["meal_types"]
            if not preferences["nutritional_goals"] and previous_context["nutritional_goals"]:
                preferences["nutritional_goals"] = previous_context["nutritional_goals"]
            if not cancer_specific["symptoms"] and previous_context["symptoms"]:
                cancer_specific["symptoms"] = previous_context["symptoms"]
            if previous_context["avoid_red_meat"]:
                constraints["avoid_red_meat"] = True
                constraints["dietary_restrictions"] = self._merge_unique(
                    constraints["dietary_restrictions"],
                    ["avoid red meat"]
                )

        strategy["primary_focus"] = strategy.get("primary_focus") or query
        strategy["search_keywords"] = self._build_search_keywords(query, preferences, constraints, cancer_specific)
        strategy["enhanced_query"] = self._build_enhanced_query(query, preferences, constraints, cancer_specific)

        return intent_data

    def _extract_context_from_history(self, conversation_history: List[Dict[str, Any]]) -> Dict[str, Any]:
        cuisine_types: List[str] = []
        meal_types: List[str] = []
        nutritional_goals: List[str] = []
        symptoms: List[str] = []
        avoid_red_meat = False

        for msg in conversation_history:
            if msg.get("role") != "user":
                continue
            content = str(msg.get("content", "")).lower()
            cuisine_types = self._merge_unique(cuisine_types, self._extract_cuisine_types(content))
            meal_types = self._merge_unique(meal_types, self._extract_meal_types(content))
            nutritional_goals = self._merge_unique(nutritional_goals, self._extract_nutrition_goals(content))
            symptoms = self._merge_unique(symptoms, self._extract_symptoms(content))
            avoid_red_meat = avoid_red_meat or self._mentions_red_meat_avoidance(content)

        return {
            "cuisine_types": cuisine_types,
            "meal_types": meal_types,
            "nutritional_goals": nutritional_goals,
            "symptoms": symptoms,
            "avoid_red_meat": avoid_red_meat
        }

    def _is_follow_up_query(self, query_lower: str) -> bool:
        follow_up_patterns = [
            r"\banother\b",
            r"\bother recipes?\b",
            r"\bmore recipes?\b",
            r"\bsome other\b",
            r"\bsimilar\b",
            r"\bfollow ?up\b",
            r"\bwhat else\b",
            r"\bmore options\b"
        ]
        return any(re.search(pattern, query_lower) for pattern in follow_up_patterns)

    def _extract_cuisine_types(self, text: str) -> List[str]:
        cuisine_map = {
            "chinese": "chinese",
            "indian": "indian",
            "mexican": "mexican",
            "italian": "italian",
            "mediterranean": "mediterranean",
            "thai": "thai",
            "japanese": "japanese",
            "korean": "korean"
        }
        return [value for key, value in cuisine_map.items() if key in text]

    def _extract_meal_types(self, text: str) -> List[str]:
        meal_map = ["breakfast", "lunch", "dinner", "snack", "dessert"]
        return [meal for meal in meal_map if meal in text]

    def _extract_nutrition_goals(self, text: str) -> List[str]:
        goal_phrases = {
            "nutritious": "nutritious",
            "healthy": "healthy",
            "high protein": "high protein",
            "protein": "high protein",
            "low calorie": "low calorie",
            "calorie": "calorie aware"
        }
        found = []
        for phrase, label in goal_phrases.items():
            if phrase in text:
                found.append(label)
        return list(dict.fromkeys(found))

    def _extract_symptoms(self, text: str) -> List[str]:
        symptom_map = ["nausea", "mouth sores", "difficulty swallowing", "low appetite", "taste changes"]
        return [symptom for symptom in symptom_map if symptom in text]

    def _mentions_red_meat_avoidance(self, text: str) -> bool:
        patterns = [
            "avoid red meat",
            "no red meat",
            "without red meat",
            "dont want red meat",
            "do not want red meat",
            "avoid pork",
            "no pork",
            "without pork"
        ]
        return any(pattern in text for pattern in patterns)

    def _build_search_keywords(
        self,
        query: str,
        preferences: Dict[str, Any],
        constraints: Dict[str, Any],
        cancer_specific: Dict[str, Any]
    ) -> List[str]:
        keywords = []
        keywords.extend(str(query).split()[:5])
        keywords.extend(preferences.get("cuisine_types", [])[:2])
        keywords.extend(preferences.get("meal_types", [])[:2])
        keywords.extend(preferences.get("nutritional_goals", [])[:2])
        keywords.extend(cancer_specific.get("symptoms", [])[:2])
        if constraints.get("avoid_red_meat"):
            keywords.append("no red meat")
        return list(dict.fromkeys([keyword for keyword in keywords if keyword]))

    def _build_enhanced_query(
        self,
        query: str,
        preferences: Dict[str, Any],
        constraints: Dict[str, Any],
        cancer_specific: Dict[str, Any]
    ) -> str:
        parts = [query.strip()]
        if preferences.get("cuisine_types"):
            parts.append(f"{preferences['cuisine_types'][0]} cuisine")
        if preferences.get("meal_types"):
            parts.append(preferences["meal_types"][0])
        if preferences.get("nutritional_goals"):
            parts.extend(preferences["nutritional_goals"][:2])
        if cancer_specific.get("symptoms"):
            parts.extend(cancer_specific["symptoms"][:1])
        if constraints.get("avoid_red_meat"):
            parts.append("without red meat or pork")
        return " ".join(dict.fromkeys([part for part in parts if part]))

    def _merge_unique(self, existing: List[str], incoming: List[str]) -> List[str]:
        return list(dict.fromkeys([item for item in [*existing, *incoming] if item]))
    
    def get_cache_stats(self) -> Dict[str, Any]:
        return {
            "cache_size": len(self.intent_cache),
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "hit_rate": f"{round(self.cache_hits / max(self.cache_hits + self.cache_misses, 1) * 100, 1)}%"
        }
    
    def clear_caches(self):
        self.intent_cache.clear()
        self.cache_hits = 0
        self.cache_misses = 0
