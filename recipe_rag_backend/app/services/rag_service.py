import logging
import time
import re
import hashlib
import threading
from typing import List, Dict, Any, Optional

from app.core.config import settings
from app.services.data_loader import DataLoader
from app.services.aicr_guidelines_service import aicr_service
from app.services.intent_analyzer import IntentAnalyzer
from app.services.recipe_verifier import RecipeVerifier
from app.services.recipe_enhancer import RecipeEnhancer
from app.services.search_engine import SearchEngine
from app.services.response_generator import ResponseGenerator
from app.services.safety_service import safety_service

logger = logging.getLogger(__name__)
MAX_RECIPES_PER_RESPONSE = 3

class RecipeRAGService:
    def __init__(self):
        self.embeddings = None
        self.llm = None
        self.vector_store = None
        self.data_loader = DataLoader()
        self.is_initialized = False
        self.initialization_error = None
        self._initialization_lock = threading.Lock()
        
        # Initialize modular services
        self.intent_analyzer = IntentAnalyzer()
        self.recipe_verifier = RecipeVerifier()
        self.recipe_enhancer = RecipeEnhancer()
        self.search_engine = SearchEngine()
        self.response_generator = ResponseGenerator()

    def _normalize_recipe_name(self, recipe_name: str) -> str:
        return " ".join(str(recipe_name).strip().lower().split())

    def _ensure_recipe_id(self, recipe: Dict[str, Any]) -> Dict[str, Any]:
        if recipe.get("recipe_id"):
            return recipe

        normalized_name = self._normalize_recipe_name(recipe.get("name", ""))
        normalized_type = self._normalize_recipe_name(recipe.get("type", ""))
        calories = str(recipe.get("calories", "")).strip()
        slug = re.sub(r"[^a-z0-9]+", "-", normalized_name).strip("-") or "recipe"
        digest = hashlib.md5(f"{normalized_name}|{normalized_type}|{calories}".encode("utf-8")).hexdigest()[:10]

        recipe_with_id = dict(recipe)
        recipe_with_id["recipe_id"] = f"{slug}-{digest}"
        return recipe_with_id

    def _get_recipe_identity(self, recipe: Dict[str, Any]) -> str:
        recipe = self._ensure_recipe_id(recipe)
        recipe_id = str(recipe.get("recipe_id", "")).strip()
        if recipe_id:
            return recipe_id
        return self._normalize_recipe_name(recipe.get("name", ""))

    def _deduplicate_recipes(self, recipes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        deduplicated: List[Dict[str, Any]] = []
        seen_identities = set()

        for recipe in recipes:
            recipe = self._ensure_recipe_id(recipe)
            identity = self._get_recipe_identity(recipe)
            if not identity or identity in seen_identities:
                continue

            seen_identities.add(identity)
            deduplicated.append(recipe)

        return deduplicated

    def _get_database_search_candidates(
        self, query: str, intent_data: Dict[str, Any], excluded_ids: set[str], limit: int,
        excluded_names: Optional[set[str]] = None
    ) -> List[Dict[str, Any]]:
        if self.data_loader.df is None:
            return []

        generic_terms = {
            "what", "some", "that", "are", "the", "and", "any", "can", "for", "give",
            "how", "make", "please", "recipe", "recipes", "show", "want", "with", "without",
            "you", "provide", "rely", "using", "need", "could", "would",
            "meal", "meals", "dinner", "lunch", "breakfast", "food", "foods"
        }
        search_text = " ".join([
            query,
            *intent_data.get("search_strategy", {}).get("search_keywords", []),
            *intent_data.get("preferences", {}).get("cuisine_types", [])
        ])
        terms = set(re.findall(r"[a-z0-9]+", search_text.lower())) - generic_terms
        terms = {term for term in terms if len(term) > 2}
        ranked = []
        for _, row in self.data_loader.df.iterrows():
            record = row.to_dict()
            if record.get("recipe_id") in excluded_ids:
                continue
            if self._normalize_recipe_name(record.get("Name", "")) in (excluded_names or set()):
                continue
            title_terms = set(re.findall(r"[a-z0-9]+", str(record.get("Name", "")).lower()))
            content = self.data_loader.build_recipe_text(record)
            content_terms = set(re.findall(r"[a-z0-9]+", content.lower()))
            score = 3 * len(terms & title_terms) + len(terms & content_terms)
            if not terms:
                score = 1
                meal_types = intent_data.get("preferences", {}).get("meal_types", [])
                recipe_type = str(record.get("Type", "")).lower()
                if any(meal in {"dinner", "lunch"} for meal in meal_types):
                    score += 3 * any(label in recipe_type for label in ("entree", "main dish", "one-dish"))
                elif any(meal in recipe_type for meal in meal_types):
                    score += 3
            if intent_data.get("constraints", {}).get("leftover_friendly"):
                score += self.search_engine.storage_evidence_score(content)
            if score:
                ranked.append((score, record))
        ranked.sort(key=lambda item: item[0], reverse=True)
        return [self._build_recipe_data_from_record(record) for _, record in ranked[:limit]]

    def _verify_candidates(self, recipes: List[Dict[str, Any]], intent_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        prepared = self.recipe_enhancer.prepare_recipes_for_verification(recipes, intent_data)
        return self.recipe_verifier.batch_verify_recipes(prepared, intent_data, aicr_service)

    def _get_verified_matches(self, recipes: List[Dict[str, Any]], intent_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        matches = [
            recipe for recipe in recipes
            if recipe.get("verification_details", {}).get("passes_verification") is True
            and recipe.get("verification_details", {}).get("relevance") == "match"
        ]
        return self._apply_deterministic_constraints(matches, intent_data)

    def _verify_new_generated_recipes(
        self, recipes: List[Dict[str, Any]], intent_data: Dict[str, Any], excluded_names: set[str]
    ) -> List[Dict[str, Any]]:
        new_recipes = self._exclude_previously_shown_recipes(recipes, excluded_names)
        return self._get_verified_matches(self._verify_candidates(new_recipes, intent_data), intent_data)

    def _apply_deterministic_constraints(
        self,
        recipes: List[Dict[str, Any]],
        intent_data: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        if not intent_data.get("constraints", {}).get("leftover_friendly"):
            return recipes

        matching_recipes = []
        for recipe in recipes:
            evidence = self._get_recipe_storage_evidence(recipe)
            if not evidence:
                continue
            recipe_with_evidence = dict(recipe)
            recipe_with_evidence["storage_evidence"] = evidence
            matching_recipes.append(recipe_with_evidence)

        return matching_recipes

    def _get_recipe_storage_evidence(self, recipe: Dict[str, Any]) -> str:
        explicit_guidance = str(
            recipe.get("storage_evidence") or recipe.get("storage_instructions") or ""
        ).strip()
        if explicit_guidance:
            return explicit_guidance

        searchable_fields = [
            recipe.get("content", ""),
            recipe.get("description", ""),
            " ".join(str(item) for item in recipe.get("instructions", []) if item),
            " ".join(str(item) for item in recipe.get("helpful_tips", []) if item),
        ]
        return self.search_engine.extract_storage_evidence("\n".join(map(str, searchable_fields)))

    def _normalize_recipe_request(self, query: str) -> str:
        replacements = {
            r"\bmaggie\b": "Maggi",
            r"\bbindi\b": "Bhindi",
            r"\bpanner\b": "Paneer",
            r"\baneer\b": "Paneer"
        }
        normalized_query = query
        for pattern, replacement in replacements.items():
            normalized_query = re.sub(pattern, replacement, normalized_query, flags=re.IGNORECASE)
        return normalized_query

    def _is_more_recipes_query(self, query: str) -> bool:
        normalized = re.sub(r"\s+", " ", query.lower()).strip()
        patterns = [
            r"\bmore recipes?\b",
            r"\bmore options?\b",
            r"\banother recipes?\b",
            r"\bother recipes?\b",
            r"\bshow (?:me )?(?:more|others?)\b",
            r"\bwhat else\b"
        ]
        return any(re.search(pattern, normalized) for pattern in patterns)

    def _get_previous_recipe_request(
        self,
        conversation_history: Optional[List[Dict]] = None
    ) -> Optional[str]:
        for message in reversed(conversation_history or []):
            if not isinstance(message, dict) or str(message.get("role", "")).lower() != "user":
                continue

            content = str(message.get("content", "")).strip()
            if content and not self._is_more_recipes_query(content):
                return content

        return None

    def _get_previously_shown_recipe_names(
        self,
        conversation_history: Optional[List[Dict]] = None
    ) -> set[str]:
        shown_names: set[str] = set()
        marker = "previously shown recipes:"

        for message in conversation_history or []:
            if not isinstance(message, dict) or str(message.get("role", "")).lower() != "assistant":
                continue

            content = str(message.get("content", ""))
            for line in content.splitlines():
                if marker not in line.lower():
                    continue
                names = line.split(":", 1)[1].split("|")
                shown_names.update(self._normalize_recipe_name(name) for name in names if name.strip())

        return shown_names

    def _exclude_previously_shown_recipes(
        self,
        recipes: List[Dict[str, Any]],
        shown_names: set[str]
    ) -> List[Dict[str, Any]]:
        if not shown_names:
            return recipes
        return [
            recipe for recipe in recipes
            if self._normalize_recipe_name(recipe.get("name", "")) not in shown_names
        ]

    def _get_conversation_recipes(self, conversation_history: Optional[List[Dict]]) -> List[Dict[str, Any]]:
        recipes = {}
        for message in conversation_history or []:
            if not isinstance(message, dict) or message.get("role") != "assistant":
                continue
            for recipe in message.get("recipes") or []:
                if isinstance(recipe, dict) and recipe.get("recipe_id"):
                    recipes[str(recipe["recipe_id"])] = dict(recipe)
        return list(recipes.values())

    def _build_context_reply(self, query: str, mode: str, intent_data: Dict[str, Any], response: str) -> Dict[str, Any]:
        return {
            "query": query, "mode": mode, "response": response,
            "source": "recipe_follow_up", "matches_found": 0,
            "source_documents": [], "intent_analysis": intent_data,
            "conversation_context_used": True
        }

    def _build_recipe_data_from_doc(self, doc: Any) -> Dict[str, Any]:
        recipe_id = self.search_engine.safe_get_metadata(doc, "recipe_id", "")
        recipe_name = self.search_engine.safe_get_metadata(doc, "name")
        full_recipe_record = self.data_loader.get_recipe_record(recipe_name)
        if full_recipe_record:
            return self._build_recipe_data_from_record(full_recipe_record)

        recipe_content = self.data_loader.build_recipe_text(full_recipe_record) or doc.page_content
        recipe_details = self.search_engine.extract_recipe_details(recipe_content)

        return {
            "recipe_id": recipe_id,
            "name": recipe_name,
            "type": self.search_engine.safe_get_metadata(doc, "type"),
            "calories": self.search_engine.safe_get_metadata(doc, "calories", 0),
            "content": recipe_content,
            "youtube_link": self.search_engine.safe_get_metadata(doc, "youtube_link", ""),
            "recipe_link": self.search_engine.safe_get_metadata(doc, "recipe_link", ""),
            "source_name": self.search_engine.safe_get_metadata(doc, "source_name", ""),
            "database_record_found": False,
            **recipe_details
        }

    def _build_recipe_data_from_record(self, record: Dict[str, Any]) -> Dict[str, Any]:
        recipe_content = self.data_loader.build_recipe_text(record)
        recipe_details = self.search_engine.extract_recipe_details(recipe_content)
        calories = record.get("Calories", 0)
        try:
            calories = float(calories) if calories != "" else 0
        except (TypeError, ValueError):
            calories = 0

        return {
            "recipe_id": record.get("recipe_id", ""),
            "name": record.get("Name", "Unknown"),
            "type": record.get("Type", "Unknown"),
            "calories": calories,
            "content": recipe_content,
            "youtube_link": record.get("YT Link", ""),
            "recipe_link": record.get("Recipe Link", ""),
            "source_name": record.get("Source Name (AICR or ACS)", ""),
            "database_record_found": True,
            **recipe_details
        }

    def _get_leftover_friendly_database_recipes(self, limit: int) -> List[Dict[str, Any]]:
        if self.data_loader.df is None:
            return []

        ranked_recipes = []
        for _, row in self.data_loader.df.iterrows():
            record = row.to_dict()
            recipe_content = self.data_loader.build_recipe_text(record)
            storage_evidence = self.search_engine.extract_storage_evidence(recipe_content)
            if not storage_evidence:
                continue

            recipe = self._build_recipe_data_from_record(record)
            recipe["storage_evidence"] = storage_evidence
            ranked_recipes.append((self.search_engine.storage_evidence_score(recipe_content), recipe))

        ranked_recipes.sort(
            key=lambda item: (-item[0], self._normalize_recipe_name(item[1].get("name", "")))
        )
        return [recipe for _, recipe in ranked_recipes[:limit]]
        
    def initialize(self):
        with self._initialization_lock:
            if self.is_initialized:
                return

            try:
                if not settings.OPENAI_API_KEY:
                    raise ValueError("OPENAI_API_KEY not found")
                
                from langchain.embeddings import OpenAIEmbeddings
                from langchain.vectorstores import FAISS
                from langchain.text_splitter import RecursiveCharacterTextSplitter
                from langchain.chat_models import ChatOpenAI
                
                self.embeddings = OpenAIEmbeddings(
                    model=settings.EMBEDDING_MODEL,
                    openai_api_key=settings.OPENAI_API_KEY
                )
                
                self.llm = ChatOpenAI(
                    model_name=settings.LLM_MODEL,
                    temperature=settings.LLM_TEMPERATURE,
                    max_tokens=settings.LLM_MAX_TOKENS,
                    openai_api_key=settings.OPENAI_API_KEY
                )
                
                self.data_loader.load_data()
                documents = self.data_loader.prepare_documents()
                
                text_splitter = RecursiveCharacterTextSplitter(
                    chunk_size=settings.CHUNK_SIZE,
                    chunk_overlap=settings.CHUNK_OVERLAP
                )
                split_docs = text_splitter.split_documents(documents)
                
                logger.info(f"Creating vector store with {len(split_docs)} document chunks")
                self.vector_store = FAISS.from_documents(split_docs, self.embeddings)

                self.intent_analyzer.initialize(self.llm)
                self.recipe_verifier.initialize(self.llm)
                self.recipe_enhancer.initialize(self.llm, aicr_service)
                self.search_engine.initialize(self.vector_store, self.llm)
                self.response_generator.initialize(self.llm)
                
                self.is_initialized = True
                self.initialization_error = None
                logger.info("RAG system initialized successfully")
                
            except Exception as e:
                self.is_initialized = False
                self.initialization_error = str(e)
                logger.error(f"Error initializing RAG system: {e}")
                raise

    def _classify_recipe_source_tier(self, recipe: Dict[str, Any]) -> str:
        if recipe.get("generated_by_llm"):
            return "llm_generated"

        core_completion_flags = [
            recipe.get("ingredients_generated", False),
            recipe.get("instructions_generated", False),
            recipe.get("dynamically_adapted", False)
        ]

        if any(core_completion_flags):
            return "database_completed"

        return "database_exact"

    def _annotate_recipe_source_tiers(self, recipes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        annotated_recipes = []
        for recipe in recipes:
            annotated_recipe = dict(recipe)
            source_tier = self._classify_recipe_source_tier(annotated_recipe)
            annotated_recipe["source_tier"] = source_tier
            annotated_recipe["source"] = source_tier
            annotated_recipe["source_label"] = (
                "AI Generated"
                if source_tier == "llm_generated"
                else f"Sourced from {annotated_recipe.get('source_name') or 'AICR'}"
            )
            annotated_recipes.append(annotated_recipe)
        return annotated_recipes

    def _classify_response_source(self, recipes: List[Dict[str, Any]]) -> str:
        if not recipes:
            return "database_exact"

        source_tiers = {recipe.get("source_tier") or self._classify_recipe_source_tier(recipe) for recipe in recipes}

        if source_tiers == {"database_exact"}:
            return "database_exact"
        if source_tiers.issubset({"database_exact", "database_completed"}):
            return "database_completed"
        if source_tiers == {"llm_generated"}:
            return "llm_generated"

        return "database_completed"
    "main initialization"
    def ask_question(self, query: str, mode: str = "auto", conversation_history: List[Dict] = None) -> Dict[str, Any]:
        """
        Main entry point with conversation context support
        """
        if safety_service.should_intercept(query, conversation_history):
            logger.warning("Detected self-harm crisis language; returning safety response")
            return safety_service.build_crisis_response(query, mode, conversation_history)

        if not self.is_initialized:
            raise ValueError("RAG system not initialized")

        logger.info(
            "Processing recipe query (%s characters) with %s previous messages",
            len(query),
            len(conversation_history or []),
        )
        start_time = time.time()
        
        try:
            if self._contains_phi_like_content(query, conversation_history):
                logger.info("Detected PHI-like content, returning privacy redirect response")
                return self._build_phi_redirect_response(query, mode, conversation_history)

            conversation_recipes = self._get_conversation_recipes(conversation_history)
            references_previous_recipe = bool(conversation_recipes) and bool(re.search(
                r"\b(it|them|those|these|that|first|second|third|one|ones)\b", query, re.IGNORECASE
            ))
            if self._is_small_talk_query(query) and not references_previous_recipe:
                logger.info("Detected small-talk query, returning conversational response")
                return self._build_small_talk_response(query, mode, conversation_history)

            is_more_request = self._is_more_recipes_query(query)
            previous_recipe_request = self._get_previous_recipe_request(conversation_history)
            recipe_request_query = previous_recipe_request if is_more_request and previous_recipe_request else query
            previously_shown_names = self._get_previously_shown_recipe_names(conversation_history)
            excluded_names = previously_shown_names if is_more_request else set()
            intent_history = conversation_history
            if is_more_request:
                intent_history = [
                    ({"role": "assistant", "content": "Previously shown recipe reference data.", "recipes": message["recipes"]}
                     if message.get("role") == "assistant" else message)
                    for message in (conversation_history or [])
                    if isinstance(message, dict)
                    and (
                        message.get("role") == "user"
                        or (message.get("role") == "assistant" and message.get("recipes"))
                    )
                ]

            # Step 1: Enhanced intent understanding with conversation context
            intent_data = self.intent_analyzer.understand_query_intent_with_context(query, intent_history)
            if intent_data.get("context_resolution_failed"):
                return self._build_context_reply(
                    query, mode, intent_data,
                    "I couldn't reliably interpret this follow-up. Please try again so I can keep your earlier requirements."
                )
            recipe_request_query = str(intent_data.get("resolved_query") or recipe_request_query)
            intent_data = {**intent_data, "recipe_request": self._normalize_recipe_request(recipe_request_query)}
            query_type = intent_data.get("query_type")
            reference_ids = intent_data.get("referenced_recipe_ids") or []
            referenced_recipes = [recipe for recipe in conversation_recipes if recipe["recipe_id"] in reference_ids]
            if query_type == "clarification" or (
                query_type in {"recipe_question", "recipe_adaptation"}
                and (not referenced_recipes or len(referenced_recipes) != len(set(reference_ids)))
            ):
                return self._build_context_reply(
                    query, mode, intent_data,
                    "Which recipe do you mean? Please use its name or its position in the last recipe list."
                )
            if query_type == "recipe_question":
                return self._build_context_reply(
                    query, mode, intent_data,
                    self.response_generator.answer_recipe_question(recipe_request_query, referenced_recipes, intent_data)
                )
            is_recipe_adaptation = query_type == "recipe_adaptation"
            logger.info(f"Intent analysis: {time.time() - start_time:.2f}s")
            effective_query = intent_data.get("search_strategy", {}).get("enhanced_query") or recipe_request_query
            
            # Step 2: Multi-query search
            docs = [] if is_recipe_adaptation else self.search_engine.multi_query_search(effective_query, intent_data, k=settings.SEARCH_K * 2)
            logger.info(f"Search complete: {time.time() - start_time:.2f}s, found {len(docs)} docs")
            
            # Step 3: Reranking
            reranked_docs = self.search_engine.rerank_with_constraint_filtering(docs, effective_query, intent_data, top_k=settings.SEARCH_K)
            logger.info(f"Reranking complete: {time.time() - start_time:.2f}s, {len(reranked_docs)} docs")
            
            # Step 4: Extract recipe details
            candidate_recipes = referenced_recipes if is_recipe_adaptation else []
            for doc in reranked_docs:
                try:
                    candidate_recipes.append(self._build_recipe_data_from_doc(doc))
                except Exception as e:
                    logger.error(f"Error extracting recipe: {e}")
                    continue

            candidate_recipes = self._deduplicate_recipes(candidate_recipes)
            if is_more_request:
                candidate_recipes = self._exclude_previously_shown_recipes(candidate_recipes, previously_shown_names)
            normalized_recipe_request = self._normalize_recipe_request(recipe_request_query)
            logger.info(f"Extraction complete: {time.time() - start_time:.2f}s")

            # Step 4.5: Fill missing ingredients/instructions before verification
            candidate_recipes = self._verify_candidates(candidate_recipes, intent_data)
            logger.info(f"Batch verification complete: {time.time() - start_time:.2f}s")

            verified_recipes = self._get_verified_matches(candidate_recipes, intent_data)
            if not verified_recipes and not is_recipe_adaptation:
                seen_ids = {self._get_recipe_identity(recipe) for recipe in candidate_recipes}
                additional = self._get_database_search_candidates(
                    normalized_recipe_request, intent_data, seen_ids, settings.SEARCH_K,
                    excluded_names=excluded_names
                )
                for doc in docs:
                    try:
                        recipe = self._build_recipe_data_from_doc(doc)
                        if self._get_recipe_identity(recipe) not in seen_ids:
                            additional.append(recipe)
                    except Exception as error:
                        logger.warning("Skipping invalid retrieval candidate: %s", error)
                additional = self._deduplicate_recipes(additional)
                if is_more_request:
                    additional = self._exclude_previously_shown_recipes(additional, previously_shown_names)
                candidate_recipes.extend(self._verify_candidates(additional[:settings.SEARCH_K], intent_data))
                candidate_recipes = self._deduplicate_recipes(candidate_recipes)
                verified_recipes = self._get_verified_matches(candidate_recipes, intent_data)
            
            # Separate passed/failed
            failed_recipes = [r for r in candidate_recipes if not r.get("verification_details", {}).get("passes_verification")]
            
            logger.info(f"Verification: {len(verified_recipes)} passed, {len(failed_recipes)} failed")
            
            # Step 6: Generate fallback if needed with AICR guidelines
            source_docs = verified_recipes
            
            if not verified_recipes:
                grounding_recipes = referenced_recipes if is_recipe_adaptation else [
                    recipe for recipe in candidate_recipes
                    if recipe.get("database_record_found")
                    and recipe.get("verification_details", {}).get("relevance") in {"match", "adaptable"}
                ][:3]
                logger.info("Generating recipes with %s database references", len(grounding_recipes))
                generation_query = normalized_recipe_request
                if is_more_request and previously_shown_names:
                    generation_query += (
                        ". Generate different recipes and do not repeat: "
                        + ", ".join(sorted(previously_shown_names))
                    )
                generated_recipes = self.recipe_enhancer.generate_fallback_recipes(
                    generation_query,
                    intent_data,
                    failed_recipes,
                    grounding_recipes=grounding_recipes
                )
                generated_recipes = self._verify_new_generated_recipes(
                    generated_recipes, intent_data, excluded_names
                )

                if not generated_recipes:
                    logger.warning("Initial AI recipe generation returned no usable recipes - retrying once")
                    generated_recipes = self.recipe_enhancer.generate_fallback_recipes(
                        f"Create complete recipes with ingredients and step-by-step instructions for: {generation_query}",
                        intent_data,
                        failed_recipes,
                        grounding_recipes=grounding_recipes
                    )
                    generated_recipes = self._verify_new_generated_recipes(
                        generated_recipes, intent_data, excluded_names
                    )

                if not generated_recipes:
                    logger.warning("JSON recipe generation failed - using structured recipe fallback")
                    generated_recipes = self.recipe_enhancer.generate_structured_fallback_recipe(
                        generation_query,
                        intent_data,
                        grounding_recipes=grounding_recipes
                    )
                    generated_recipes = self._verify_new_generated_recipes(
                        generated_recipes, intent_data, excluded_names
                    )
                
                if generated_recipes:
                    source_docs = generated_recipes
                else:
                    return {
                        "query": query,
                        "response": (
                            f"I couldn't find additional recipes matching your earlier request, \"{recipe_request_query}\", right now. "
                            "I kept your requirements and excluded recipes already shown."
                            if is_more_request else
                            self.response_generator.generate_helpful_no_results_message(effective_query, intent_data)
                        ),
                        "source": "no_results",
                        "matches_found": 0,
                        "mode": mode,
                        "intent_analysis": intent_data,
                        "source_documents": []
                    }
            
            # Step 7: PARALLEL ENHANCEMENT with AICR guidelines
            source_docs = self.recipe_enhancer.batch_enhance_recipes(source_docs[:MAX_RECIPES_PER_RESPONSE], intent_data)
            if any(recipe.get("dynamically_adapted") for recipe in source_docs):
                source_docs = self._verify_candidates(source_docs, intent_data)
                source_docs = self._get_verified_matches(source_docs, intent_data)
            source_docs = self._deduplicate_recipes(source_docs)
            source_docs = self._apply_deterministic_constraints(source_docs, intent_data)
            source_docs = self._annotate_recipe_source_tiers(source_docs)
            if is_more_request:
                source_docs = self._exclude_previously_shown_recipes(source_docs, previously_shown_names)
            source_docs = source_docs[:MAX_RECIPES_PER_RESPONSE]
            logger.info(f"Enhancement complete: {time.time() - start_time:.2f}s")

            if not source_docs:
                return {
                    "query": query,
                    "response": "I don't have additional matching recipes to show right now.",
                    "source": "no_results",
                    "matches_found": 0,
                    "mode": mode,
                    "intent_analysis": intent_data,
                    "source_documents": []
                }
            
            # Step 8: Generate response
            response_text = self.response_generator.generate_personalized_response(effective_query, source_docs, intent_data)
            
            total_time = time.time() - start_time
            logger.info(f"TOTAL TIME: {total_time:.2f}s")
            
            return {
                "query": query,
                "response": response_text,
                "source": self._classify_response_source(source_docs),
                "matches_found": len(source_docs),
                "mode": mode,
                "source_documents": source_docs,
                "intent_analysis": intent_data,
                "dynamically_adapted": any(doc.get("dynamically_adapted", False) for doc in source_docs),
                "instructions_generated": any(doc.get("instructions_generated", False) for doc in source_docs),
                "aicr_compliant": all(doc.get("aicr_compliance", {}).get("overall_compliant", False) for doc in source_docs),
                "verification_details": {
                    "total_candidates": len(candidate_recipes),
                    "passed_verification": len(verified_recipes),
                    "failed_verification": len(failed_recipes),
                    "llm_generated": len([doc for doc in source_docs if doc.get("source_tier") == "llm_generated"]),
                    "database_exact": len([doc for doc in source_docs if doc.get("source_tier") == "database_exact"]),
                    "database_completed": len([doc for doc in source_docs if doc.get("source_tier") == "database_completed"])
                },
                "performance": {
                    "total_time_seconds": round(total_time, 2)
                },
                "conversation_context_used": conversation_history is not None and len(conversation_history) > 0,
                "previous_messages_considered": len(conversation_history) if conversation_history else 0
            }
            
        except Exception as e:
            logger.error(f"Error processing query: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {
                "query": query,
                "response": "I apologize for the error. Please try rephrasing your question.",
                "source": "error",
                "matches_found": 0,
                "mode": mode,
                "source_documents": []
            }

    def _contains_phi_like_content(self, query: str, conversation_history: Optional[List[Dict]] = None) -> bool:
        normalized = query.lower()

        if self._is_safe_recipe_follow_up_query(normalized, conversation_history):
            return False

        strong_identifier_patterns = [
            r"\b\d{3}-\d{2}-\d{4}\b",  # SSN
            r"\b(?:mrn|medical record number|member id|insurance id|policy number|claim number|patient identifier|patient id|unique patient identifier|account number|license number|certificate number|device identifier|vehicle identifier)\b",
            r"\b(?:date of birth|dob|born on|my birthday)\b",
            r"\b[\w\.-]+@[\w\.-]+\.\w+\b",  # email
            r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b",  # phone
            r"\b[a-z]{1,6}-?\d{4,}\b",  # PT-00077891, MRN12345, ID998877
            r"\b\d{5,}\b"  # long unique numeric identifiers
        ]

        health_context_terms = {
            "diet",
            "recipe",
            "meal",
            "nutrition",
            "symptom",
            "symptoms",
            "treatment",
            "diagnosis",
            "condition",
            "cancer",
            "nausea",
            "allergy",
            "doctor",
            "hospital",
            "insurance",
            "medication",
            "patient",
            "health"
        }

        direct_personal_patterns = [
            r"\bmy name is\s+[a-z]+(?:\s+[a-z]+)?\b",
            r"\bfor my\s+(?:mother|father|mom|dad|son|daughter|wife|husband|brother|sister|friend|patient)\b",
            r"\bpatient\s+[a-z]+(?:\s+[a-z]+){0,2}\b",
            r"\bmember\s+[a-z]+(?:\s+[a-z]+){0,2}\b",
            r"\blive at\b",
            r"\bmy address is\b",
            r"\bmy phone number is\b",
            r"\bmy email is\b"
        ]

        identifier_value_patterns = [
            r"\b(?:patient identifier|patient id|member id|medical record number|mrn|insurance id|policy number|claim number|account number|device identifier|vehicle identifier)\s*[:#-]?\s*[a-z0-9-]{4,}\b",
            r"\b(?:identifier|id)\s*[:#-]?\s*[a-z]{0,4}-?\d{4,}\b"
        ]

        has_health_context = any(term in normalized for term in health_context_terms)
        has_strong_identifier = any(re.search(pattern, normalized) for pattern in strong_identifier_patterns)
        has_direct_personal_info = any(re.search(pattern, normalized) for pattern in direct_personal_patterns)
        has_identifier_value = any(re.search(pattern, normalized) for pattern in identifier_value_patterns)
        has_name_like_reference = self._has_name_like_reference(normalized)
        has_explicit_identity_phrase = bool(
            re.search(r"\b(?:my name is|patient\s+[a-z]+|member\s+[a-z]+|for my\s+(?:mother|father|mom|dad|son|daughter|wife|husband|brother|sister|friend|patient))\b", normalized)
        )

        return (
            has_strong_identifier or
            has_identifier_value or
            (has_direct_personal_info and has_health_context and has_explicit_identity_phrase) or
            (has_name_like_reference and has_health_context)
        )

    def _has_name_like_reference(self, normalized_query: str) -> bool:
        name_reference_matches = re.finditer(r"\b(?:patient|member)\s+([a-z]+(?:\s+[a-z]+){0,2})\b", normalized_query)
        excluded_terms = {
            "breakfast", "lunch", "dinner", "snack", "dessert", "meal", "meals", "recipe", "recipes",
            "diet", "diets", "nutrition", "healthy", "nutritious", "vegetarian", "vegan", "protein",
            "chinese", "indian", "mexican", "italian", "mediterranean", "thai", "japanese", "korean",
            "more", "other", "another", "missing", "these", "those", "them", "options", "ideas",
            "today", "tonight", "week", "weekend", "runner", "running", "muscle", "cramps",
            "me", "myself", "us", "ourselves", "you", "yourself", "someone", "anyone"
        }

        for match in name_reference_matches:
            candidate = match.group(1).strip()
            candidate_tokens = [token for token in candidate.split() if token]
            if candidate_tokens and all(token not in excluded_terms for token in candidate_tokens):
                return True

        return False

    def _is_safe_recipe_follow_up_query(
        self,
        normalized_query: str,
        conversation_history: Optional[List[Dict]] = None
    ) -> bool:
        if not conversation_history:
            return False

        follow_up_patterns = [
            r"\bother recipes?\b",
            r"\bmissing recipes?\b",
            r"\bshow me (?:the )?(?:other|rest|remaining)\b",
            r"\bwhat are the other\b",
            r"\bcan i see (?:the )?(?:other|rest|remaining)\b",
            r"\bmore recipes?\b",
            r"\bmore options\b",
            r"\bshow (?:them|those|more)\b",
        ]
        recipe_reference_terms = ("recipe", "recipes", "meal", "meals", "breakfast", "lunch", "dinner", "snack")

        if not any(re.search(pattern, normalized_query) for pattern in follow_up_patterns):
            return False

        sanitized_history = []
        for msg in conversation_history or []:
            if isinstance(msg, dict):
                content = str(msg.get("content", "")).lower()
                role = str(msg.get("role", "")).lower()
                if content and role:
                    sanitized_history.append({"role": role, "content": content})

        recent_assistant_recipe_reply = any(
            msg["role"] == "assistant" and any(term in msg["content"] for term in recipe_reference_terms)
            for msg in sanitized_history[-4:]
        )

        return recent_assistant_recipe_reply

    def _build_phi_redirect_response(
        self,
        query: str,
        mode: str,
        conversation_history: Optional[List[Dict]] = None
    ) -> Dict[str, Any]:
        response_text = (
            "Please do not share personal or identifying health information here. "
            "Please ask me about diet-based recipe or nutrition questions without personal details."
        )

        return {
            "query": query,
            "response": response_text,
            "source": "privacy_redirect",
            "matches_found": 0,
            "mode": mode,
            "source_documents": [],
            "intent_analysis": {
                "query_type": "privacy_redirect",
                "constraints": {},
                "preferences": {},
                "cancer_patient_specific": {},
                "search_strategy": {
                    "primary_focus": "privacy_redirect",
                    "search_keywords": [],
                    "must_match_criteria": [],
                    "enhanced_query": query
                }
            },
            "dynamically_adapted": False,
            "instructions_generated": False,
            "aicr_compliant": False,
            "verification_details": {
                "total_candidates": 0,
                "passed_verification": 0,
                "failed_verification": 0,
                "llm_generated": 0
            },
            "performance": {
                "total_time_seconds": 0
            },
            "conversation_context_used": conversation_history is not None and len(conversation_history) > 0,
            "previous_messages_considered": len(conversation_history) if conversation_history else 0
        }

    def _is_small_talk_query(self, query: str) -> bool:
        normalized = re.sub(r"\s+", " ", query.lower()).strip()
        normalized = re.sub(r"[^\w\s]", "", normalized)

        if not normalized:
            return True

        small_talk_patterns = {
            "hi",
            "hello",
            "hey",
            "good morning",
            "good afternoon",
            "good evening",
            "how are you",
            "whats up",
            "what is up",
            "howdy",
            "yo",
            "sup",
            "thanks",
            "thank you",
            "ok",
            "okay"
        }

        conversational_patterns = [
            r"^hi(?:\s+there)?$",
            r"^hello(?:\s+there)?$",
            r"^hey(?:\s+there)?$",
            r"^how are you(?: doing)?(?: today)?$",
            r"^hows it going(?: today)?$",
            r"^what are you doing(?: today)?$",
            r"^whats up(?: today)?$",
            r"^can you help me$",
            r"^who are you$",
            r"^what can you do$",
            r"^thanks(?: you)?$"
        ]

        recipe_keywords = {
            "recipe",
            "recipes",
            "meal",
            "meals",
            "diet",
            "dietary",
            "eat",
            "eating",
            "food",
            "foods",
            "cook",
            "cooking",
            "ingredients",
            "nutrition",
            "nutritious",
            "healthy",
            "symptom",
            "symptoms",
            "side",
            "effect",
            "effects",
            "protein",
            "calories",
            "microwave",
            "breakfast",
            "lunch",
            "dinner",
            "snack",
            "vegetarian",
            "vegan",
            "nausea",
            "fever",
            "swallow",
            "appetite"
        }

        recipe_request_patterns = [
            r"\bbreakfasts?\b",
            r"\blunch(?:es)?\b",
            r"\bdinners?\b",
            r"\bsnacks?\b",
            r"\bmeal(?:s)?\b",
            r"\brecipe(?:s)?\b",
            r"\bmeal ideas?\b",
            r"\bbreakfast ideas?\b",
            r"\blunch ideas?\b",
            r"\bdinner ideas?\b",
            r"\bsnack ideas?\b",
            r"\bcould you provide me some\b",
            r"\bshow me some\b",
            r"\bgive me some\b",
            r"\bfind me some\b",
            r"\bsheet pan\b",
            r"\broasted vegetables?\b",
            r"\bvegetables and beans\b"
        ]

        if any(keyword in normalized.split() for keyword in recipe_keywords):
            return False

        if any(re.search(pattern, normalized) for pattern in recipe_request_patterns):
            return False

        if normalized in small_talk_patterns:
            return True

        if any(re.fullmatch(pattern, normalized) for pattern in conversational_patterns):
            return True

        # Short noun-phrase prompts are often recipe lookups rather than small talk.
        if len(normalized.split()) >= 2:
            conversational_verbs = {
                "are", "am", "is", "was", "were", "do", "does", "did",
                "can", "could", "would", "should", "who", "what", "why", "how",
                "thanks", "thank", "hello", "hi", "hey"
            }
            words = normalized.split()
            if not any(word in conversational_verbs for word in words):
                return False

        # Short, non-domain prompts are treated as conversation instead of recipe requests.
        if len(normalized.split()) <= 6:
            return True

        return False

    def _build_small_talk_response(
        self,
        query: str,
        mode: str,
        conversation_history: Optional[List[Dict]] = None
    ) -> Dict[str, Any]:
        normalized = re.sub(r"\s+", " ", query.lower()).strip()

        if normalized in {"thanks", "thank you"}:
            response_text = (
                "Thanks for reaching out. Please ask me about diet-based, nutrition, or recipe-related questions and I’ll be happy to help."
            )
        elif normalized in {"how are you", "how are you doing today", "whats up", "what is up"}:
            response_text = (
                "Thanks for reaching out. Please ask me about diet-based recipe-related questions, meal ideas, symptoms, or ingredients you want to work with."
            )
        else:
            response_text = (
                "Thanks for reaching out. Please ask me about diet-based recipe-related questions, nutrition-friendly meals, symptom-aware food suggestions, or cooking with ingredients you already have."
            )

        return {
            "query": query,
            "response": response_text,
            "source": "conversation",
            "matches_found": 0,
            "mode": mode,
            "source_documents": [],
            "intent_analysis": {
                "query_type": "small_talk",
                "constraints": {},
                "preferences": {},
                "cancer_patient_specific": {},
                "search_strategy": {
                    "primary_focus": "conversation",
                    "search_keywords": [],
                    "must_match_criteria": [],
                    "enhanced_query": query
                }
            },
            "dynamically_adapted": False,
            "instructions_generated": False,
            "aicr_compliant": False,
            "verification_details": {
                "total_candidates": 0,
                "passed_verification": 0,
                "failed_verification": 0,
                "llm_generated": 0
            },
            "performance": {
                "total_time_seconds": 0
            },
            "conversation_context_used": conversation_history is not None and len(conversation_history) > 0,
            "previous_messages_considered": len(conversation_history) if conversation_history else 0
        }
    
    def search_recipes(self, query: str, k: int = None) -> List[Dict[str, Any]]:
        """Search for recipes"""
        if not self.is_initialized:
            raise ValueError("RAG system not initialized")
        
        k = k or settings.SEARCH_K
        intent_data = self.intent_analyzer.understand_query_intent(query)
        docs = self.search_engine.multi_query_search(query, intent_data, k=k)
        reranked_docs = self.search_engine.rerank_with_constraint_filtering(docs, query, intent_data, top_k=k)
        
        recipes = []
        for doc in reranked_docs:
            try:
                recipe = self._build_recipe_data_from_doc(doc)
                
                # Add AICR validation to search results
                aicr_compliance = aicr_service.validate_recipe_compliance(recipe)
                recipe["aicr_compliance"] = aicr_compliance
                
                recipes.append(recipe)
            except Exception as e:
                logger.error(f"Error processing document: {e}")
                continue

        recipes = self._deduplicate_recipes(recipes)
        recipes = self._apply_deterministic_constraints(recipes, intent_data)
        return self._annotate_recipe_source_tiers(recipes)[:MAX_RECIPES_PER_RESPONSE]
    
    def get_system_info(self) -> Dict[str, Any]:
        """Get system information"""
        aicr_guidelines = aicr_service.get_guidelines()
        return {
            "initialized": self.is_initialized,
            "initialization_error": self.initialization_error,
            "recipes_loaded": self.data_loader.recipes_count if self.data_loader else 0,
            "vector_store_ready": self.vector_store is not None,
            "supports_dynamic_adaptation": True,
            "supports_constraint_based_search": True,
            "supports_recipe_verification": True,
            "supports_llm_generation": True,
            "supports_aicr_guidelines": True,
            "supports_conversation_context": True,
            "optimizations": {
                "batch_verification": True,
                "parallel_enhancement": True,
                "combined_enhancement": True,
                "token_reduction": True,
                "advanced_caching": True,
                "aicr_validation": True,
                "conversation_context": True
            },
            "cache_statistics": self.get_combined_cache_stats(),
            "aicr_guidelines": {
                "loaded": aicr_service._initialized,
                "source": aicr_guidelines["metadata"]["source"],
                "version": aicr_guidelines["metadata"]["version"]
            }
        }
    
    def get_combined_cache_stats(self) -> Dict[str, Any]:
        """Combine cache stats from all services"""
        return {
            "intent_analyzer": self.intent_analyzer.get_cache_stats(),
            "recipe_verifier": self.recipe_verifier.get_cache_stats(),
            "recipe_enhancer": self.recipe_enhancer.get_cache_stats()
        }
    
    def clear_caches(self):
        """Clear all caches"""
        self.intent_analyzer.clear_caches()
        self.recipe_verifier.clear_caches()
        self.recipe_enhancer.clear_caches()
        logger.info("All caches cleared")

# Global instance
rag_service = RecipeRAGService()
