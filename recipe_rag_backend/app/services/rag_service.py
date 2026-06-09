import logging
import time
import re
from typing import List, Dict, Any, Optional

from app.core.config import settings
from app.services.data_loader import DataLoader
from app.services.aicr_guidelines_service import aicr_service
from app.services.intent_analyzer import IntentAnalyzer
from app.services.recipe_verifier import RecipeVerifier
from app.services.recipe_enhancer import RecipeEnhancer
from app.services.search_engine import SearchEngine
from app.services.response_generator import ResponseGenerator

logger = logging.getLogger(__name__)

class RecipeRAGService:
    def __init__(self):
        self.embeddings = None
        self.llm = None
        self.vector_store = None
        self.data_loader = DataLoader()
        self.is_initialized = False
        self.initialization_error = None
        
        # Initialize modular services
        self.intent_analyzer = IntentAnalyzer()
        self.recipe_verifier = RecipeVerifier()
        self.recipe_enhancer = RecipeEnhancer()
        self.search_engine = SearchEngine()
        self.response_generator = ResponseGenerator()
        
    def initialize(self):
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
            
            # Initialize modular services with LLM and embeddings
            self.intent_analyzer.initialize(self.llm)
            self.recipe_verifier.initialize(self.llm)
            self.recipe_enhancer.initialize(self.llm, aicr_service)
            self.search_engine.initialize(self.vector_store, self.llm)
            self.response_generator.initialize(self.llm)
            
            self.data_loader.load_data()
            documents = self.data_loader.prepare_documents()
            
            text_splitter = RecursiveCharacterTextSplitter(
                chunk_size=settings.CHUNK_SIZE,
                chunk_overlap=settings.CHUNK_OVERLAP
            )
            split_docs = text_splitter.split_documents(documents)
            
            logger.info(f"Creating vector store with {len(split_docs)} document chunks")
            self.vector_store = FAISS.from_documents(split_docs, self.embeddings)
            
            # Update search engine with vector store
            self.search_engine.vector_store = self.vector_store
            
            self.is_initialized = True
            self.initialization_error = None
            logger.info("RAG system initialized successfully")
            
        except Exception as e:
            self.is_initialized = False
            self.initialization_error = str(e)
            logger.error(f"Error initializing RAG system: {e}")
            raise
    "main initialization"
    def ask_question(self, query: str, mode: str = "auto", conversation_history: List[Dict] = None) -> Dict[str, Any]:
        """
        Main entry point with conversation context support
        """
        if not self.is_initialized:
            raise ValueError("RAG system not initialized")
        
        logger.info(f"Processing query: '{query}' with {len(conversation_history or [])} previous messages")
        start_time = time.time()
        
        try:
            if self._contains_phi_like_content(query):
                logger.info("Detected PHI-like content, returning privacy redirect response")
                return self._build_phi_redirect_response(query, mode, conversation_history)

            if self._is_small_talk_query(query):
                logger.info("Detected small-talk query, returning conversational response")
                return self._build_small_talk_response(query, mode, conversation_history)

            # Step 1: Enhanced intent understanding with conversation context
            intent_data = self.intent_analyzer.understand_query_intent_with_context(query, conversation_history)
            logger.info(f"Intent analysis: {time.time() - start_time:.2f}s")
            effective_query = intent_data.get("search_strategy", {}).get("enhanced_query") or query
            
            # Step 2: Multi-query search
            docs = self.search_engine.multi_query_search(effective_query, intent_data, k=settings.SEARCH_K * 2)
            logger.info(f"Search complete: {time.time() - start_time:.2f}s, found {len(docs)} docs")
            
            # Step 3: Reranking
            reranked_docs = self.search_engine.rerank_with_constraint_filtering(docs, effective_query, intent_data, top_k=settings.SEARCH_K)
            logger.info(f"Reranking complete: {time.time() - start_time:.2f}s, {len(reranked_docs)} docs")
            
            # Step 4: Extract recipe details
            candidate_recipes = []
            for doc in reranked_docs:
                try:
                    recipe_details = self.search_engine.extract_recipe_details(doc.page_content)
                    recipe_data = {
                        "name": self.search_engine.safe_get_metadata(doc, "name"),
                        "type": self.search_engine.safe_get_metadata(doc, "type"),
                        "calories": self.search_engine.safe_get_metadata(doc, "calories", 0),
                        "content": doc.page_content,
                        "youtube_link": self.search_engine.safe_get_metadata(doc, "youtube_link", ""),
                        **recipe_details
                    }
                    candidate_recipes.append(recipe_data)
                except Exception as e:
                    logger.error(f"Error extracting recipe: {e}")
                    continue
            
            logger.info(f"Extraction complete: {time.time() - start_time:.2f}s")

            # Step 4.5: Fill missing ingredients/instructions before verification
            candidate_recipes = self.recipe_enhancer.prepare_recipes_for_verification(candidate_recipes, intent_data)
            logger.info(f"Pre-verification enrichment complete: {time.time() - start_time:.2f}s")
            
            # Step 5: BATCH VERIFICATION with AICR validation
            candidate_recipes = self.recipe_verifier.batch_verify_recipes(candidate_recipes, intent_data, aicr_service)
            logger.info(f"Batch verification complete: {time.time() - start_time:.2f}s")
            
            # Separate passed/failed
            verified_recipes = [r for r in candidate_recipes if r.get("verification_details", {}).get("passes_verification")]
            failed_recipes = [r for r in candidate_recipes if not r.get("verification_details", {}).get("passes_verification")]
            
            logger.info(f"Verification: {len(verified_recipes)} passed, {len(failed_recipes)} failed")
            
            # Step 6: Generate fallback if needed with AICR guidelines
            source_docs = verified_recipes
            
            if not verified_recipes:
                logger.warning("No recipes passed - generating AICR-compliant custom recipes")
                generated_recipes = self.recipe_enhancer.generate_fallback_recipes(effective_query, intent_data, failed_recipes)
                
                if generated_recipes:
                    source_docs = generated_recipes
                else:
                    return {
                        "query": query,
                        "response": self.response_generator.generate_helpful_no_results_message(effective_query, intent_data),
                        "source": "no_results",
                        "matches_found": 0,
                        "mode": mode,
                        "intent_analysis": intent_data,
                        "source_documents": []
                    }
            
            # Step 7: PARALLEL ENHANCEMENT with AICR guidelines
            source_docs = self.recipe_enhancer.batch_enhance_recipes(source_docs, intent_data)
            logger.info(f"Enhancement complete: {time.time() - start_time:.2f}s")
            
            # Step 8: Generate response
            response_text = self.response_generator.generate_personalized_response(effective_query, source_docs, intent_data)
            
            total_time = time.time() - start_time
            logger.info(f"TOTAL TIME: {total_time:.2f}s")
            
            return {
                "query": query,
                "response": response_text,
                "source": "database" if verified_recipes else "llm_generated",
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
                    "llm_generated": len(source_docs) if not verified_recipes else 0
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

    def _contains_phi_like_content(self, query: str) -> bool:
        normalized = query.lower()

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
            r"\bi am\s+[a-z]+(?:\s+[a-z]+)?\b",
            r"\bi'm\s+[a-z]+(?:\s+[a-z]+)?\b",
            r"\bfor\s+[a-z]+(?:\s+[a-z]+){0,2}\b",
            r"\bfor my\s+(?:mother|father|mom|dad|son|daughter|wife|husband|brother|sister|friend|patient)\b",
            r"\bpatient\s+[a-z]+(?:\s+[a-z]+){0,2}\b",
            r"\bmember\s+[a-z]+(?:\s+[a-z]+){0,2}\b",
            r"\bfor\s+[a-z]+(?:\s+[a-z]+){1,2}\b",
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
        has_name_like_reference = bool(
            re.search(r"\b(?:for|patient|member)\s+[a-z]+(?:\s+[a-z]+){0,2}\b", normalized)
        )
        has_explicit_identity_phrase = bool(
            re.search(r"\b(?:my name is|patient\s+[a-z]+|member\s+[a-z]+|for my\s+(?:mother|father|mom|dad|son|daughter|wife|husband|brother|sister|friend|patient)|for\s+[a-z]+(?:\s+[a-z]+){0,2})\b", normalized)
        )

        return (
            has_strong_identifier or
            has_identifier_value or
            (has_direct_personal_info and has_health_context and has_explicit_identity_phrase) or
            (has_name_like_reference and has_health_context)
        )

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
            "swallow",
            "appetite"
        }

        if any(keyword in normalized.split() for keyword in recipe_keywords):
            return False

        if normalized in small_talk_patterns:
            return True

        if any(re.fullmatch(pattern, normalized) for pattern in conversational_patterns):
            return True

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
                recipe_details = self.search_engine.extract_recipe_details(doc.page_content)
                recipe = {
                    "name": self.search_engine.safe_get_metadata(doc, "name"),
                    "type": self.search_engine.safe_get_metadata(doc, "type"),
                    "calories": self.search_engine.safe_get_metadata(doc, "calories", 0),
                    "content": doc.page_content,
                    "youtube_link": self.search_engine.safe_get_metadata(doc, "youtube_link", ""),
                    **recipe_details
                }
                
                # Add AICR validation to search results
                aicr_compliance = aicr_service.validate_recipe_compliance(recipe)
                recipe["aicr_compliance"] = aicr_compliance
                
                recipes.append(recipe)
            except Exception as e:
                logger.error(f"Error processing document: {e}")
                continue
        
        return recipes
    
    def get_system_info(self) -> Dict[str, Any]:
        """Get system information"""
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
                "source": aicr_service.get_guidelines()["metadata"]["source"],
                "version": aicr_service.get_guidelines()["metadata"]["version"]
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
