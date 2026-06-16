import logging
import re
import json
from typing import List, Dict, Any
from langchain.schema import Document

logger = logging.getLogger(__name__)

class SearchEngine:
    def __init__(self):
        self.vector_store = None
        self.llm = None
        
    def initialize(self, vector_store, llm):
        self.vector_store = vector_store
        self.llm = llm
    
    def multi_query_search(self, original_query: str, intent_data: Dict[str, Any], k: int) -> List[Document]:
        """Perform multiple searches with different query formulations"""
        all_docs = []
        seen_content = set()
        
        search_queries = self._generate_contextual_search_queries(intent_data)
        
        for i, search_query in enumerate(search_queries):
            try:
                logger.info(f"Search {i+1}/{len(search_queries)}: {search_query}")
                docs = self.vector_store.similarity_search(search_query, k=k)
                
                for doc in docs:
                    content_hash = hash(doc.page_content[:100])
                    if content_hash not in seen_content:
                        all_docs.append(doc)
                        seen_content.add(content_hash)
                        
            except Exception as e:
                logger.error(f"Error in search '{search_query}': {e}")
                continue
        
        logger.info(f"Multi-query search found {len(all_docs)} unique documents")
        return all_docs

    def _generate_contextual_search_queries(self, intent_data: Dict[str, Any]) -> List[str]:
        """Generate multiple search queries based on the intent analysis"""
        queries = []
        strategy = intent_data.get("search_strategy", {})
        constraints = intent_data.get("constraints", {})
        preferences = intent_data.get("preferences", {})
        cancer_specific = intent_data.get("cancer_patient_specific", {})
        
        if strategy.get("enhanced_query"):
            queries.append(strategy["enhanced_query"])
        
        if constraints.get("ingredients_must_use") or constraints.get("ingredients_available"):
            ingredients = constraints.get("ingredients_must_use") or constraints.get("ingredients_available")
            queries.append(f"{' '.join(ingredients[:5])} recipes")
        
        if constraints.get("dietary_restrictions"):
            dietary_query = " ".join(constraints["dietary_restrictions"])
            if preferences.get("meal_types"):
                dietary_query += f" {preferences['meal_types'][0]}"
            queries.append(dietary_query)
        
        if constraints.get("max_ingredients"):
            queries.append(f"simple {constraints['max_ingredients']} ingredient recipes")
        
        if preferences.get("cuisine_types") or preferences.get("flavor_profiles"):
            cuisine_query = ""
            if preferences.get("cuisine_types"):
                cuisine_query = preferences["cuisine_types"][0]
            if preferences.get("flavor_profiles"):
                cuisine_query += f" {preferences['flavor_profiles'][0]}"
            if cuisine_query:
                queries.append(cuisine_query)
        
        queries = [q.strip() for q in queries if q and q.strip()]
        unique_queries = list(dict.fromkeys(queries))
        
        logger.info(f"Generated {len(unique_queries)} search queries")
        return unique_queries[:6]
    
    def rerank_with_constraint_filtering(self, docs: List[Document], query: str, intent_data: Dict[str, Any], top_k: int) -> List[Document]:
        """Use LLM to rerank with intelligent constraint filtering"""
        top_k = top_k or 8  # Default from your settings
        
        if not docs:
            return []
        
        try:
            doc_summaries = []
            for i, doc in enumerate(docs[:15]):
                name = self.safe_get_metadata(doc, "name")
                recipe_type = self.safe_get_metadata(doc, "type")
                doc_summaries.append(f"{i}. {name} ({recipe_type})")
            
            constraints = intent_data.get("constraints", {})
            
            constraints_text = "Requirements:\n"
            if constraints.get("max_ingredients"):
                constraints_text += f"- Max {constraints['max_ingredients']} ingredients\n"
            if constraints.get("dietary_restrictions"):
                constraints_text += f"- {', '.join(constraints['dietary_restrictions'])}\n"
            
            rerank_prompt = f"""Rank these nutritious recipes: "{query}"

{constraints_text}

Recipes:
{chr(10).join(doc_summaries)}

Return {top_k} best indices as JSON:
{{"selected_indices": [0, 3, 7, ...]}}
"""

            response = self.llm.predict(rerank_prompt)
            
            response = response.strip()
            if response.startswith("```json"):
                response = response[7:]
            elif response.startswith("```"):
                response = response[3:]
            if response.endswith("```"):
                response = response[:-3]
            response = response.strip()
            
            result = json.loads(response)
            selected_indices = result.get("selected_indices", [])
            
            reranked_docs = []
            for idx in selected_indices[:top_k]:
                if 0 <= idx < len(docs):
                    reranked_docs.append(docs[idx])
            
            logger.info(f"Reranked: selected {len(reranked_docs)} documents")
            return reranked_docs
            
        except Exception as e:
            logger.error(f"Error in reranking: {e}")
            return docs[:top_k]
    
    def extract_recipe_details(self, content: str) -> Dict[str, Any]:
        """Extract structured recipe details"""
        details = {
            "ingredients": [],
            "instructions": [],
            "description": "",
            "full_content": content,
            "needs_instruction_generation": False,
            "needs_dynamic_adaptation": False
        }
        
        try:
            if 'Ingredients:' in content:
                ingredients_section = content.split('Ingredients:')[1]
                if 'Directions:' in ingredients_section:
                    ingredients_section = ingredients_section.split('Directions:')[0]
                elif 'Instructions:' in ingredients_section:
                    ingredients_section = ingredients_section.split('Instructions:')[0]
                
                extracted_ingredients = []
                
                for line in ingredients_section.split('\n'):
                    cleaned = line.strip().lstrip('•-*').strip()
                    if (cleaned and len(cleaned) > 3 and
                        not any(keyword.lower() in cleaned.lower() for keyword in 
                               ['Recipe Name', 'Type:', 'Description:', 'Calories:', 'Notes:', 'Directions:', 'Instructions:'])):
                        extracted_ingredients.append(cleaned)
                
                if len(extracted_ingredients) <= 2 and any(len(ing) > 100 for ing in extracted_ingredients):
                    logger.info("Detected concatenated ingredients - splitting")
                    extracted_ingredients = self._split_concatenated_ingredients(ingredients_section)
                
                details["ingredients"] = extracted_ingredients[:30] if extracted_ingredients else []
            
            instructions_found = False
            for keyword in ['Directions:', 'Instructions:', 'Steps:']:
                if keyword in content:
                    directions_section = content.split(keyword)[1]
                    if 'Notes:' in directions_section:
                        directions_section = directions_section.split('Notes:')[0]
                    
                    extracted_instructions = []
                    for line in directions_section.split('\n'):
                        cleaned = line.strip()
                        if cleaned and len(cleaned) > 15:
                            cleaned = re.sub(r'^\d+[\.\)]\s*', '', cleaned)
                            cleaned = cleaned.lstrip('•-*').strip()
                            if cleaned:
                                extracted_instructions.append(cleaned)
                    
                    if len(extracted_instructions) >= 3:
                        details["instructions"] = [f"{i+1}. {inst}" for i, inst in enumerate(extracted_instructions[:8])]
                        instructions_found = True
                        break
            
            if not instructions_found:
                details["needs_instruction_generation"] = True
                details["instructions"] = []
            
            if 'Description:' in content:
                desc_section = content.split('Description:')[1]
                if 'Calories:' in desc_section:
                    desc_section = desc_section.split('Calories:')[0]
                elif 'Ingredients:' in desc_section:
                    desc_section = desc_section.split('Ingredients:')[0]
                details["description"] = desc_section.strip()
            
            if not details["ingredients"]:
                details["insufficient_data"] = True
                    
        except Exception as e:
            logger.warning(f"Error extracting recipe details: {e}")
            details["extraction_error"] = True
        
        return details
    
    def _split_concatenated_ingredients(self, text: str) -> List[str]:
        """Split concatenated ingredients using patterns"""
        pattern = r'(?:^|\s)(\d+(?:/\d+)?(?:\.\d+)?\s+(?:can|cup|tbsp|tsp|tablespoon|teaspoon|oz|ounce|lb|pound|g|kg|ml|l|bunch|clove|stalk|package|pkg)\S*\s+[^\.]+?)(?=\d+(?:/\d+)?(?:\.\d+)?\s+(?:can|cup|tbsp|tsp|tablespoon|teaspoon|oz|ounce|lb|pound|g|kg|ml|l|bunch|clove|stalk|package|pkg)|$)'
        
        matches = re.findall(pattern, text, re.IGNORECASE)
        if matches:
            return [m.strip() for m in matches if len(m.strip()) > 5][:20]
        
        parts = re.split(r'(?=\d+(?:/\d+)?(?:\.\d+)?\s+)', text)
        return [p.strip() for p in parts if p.strip() and len(p.strip()) > 5][:20]
    
    def safe_get_metadata(self, doc: Document, key: str, default: Any = "Unknown") -> Any:
        """Safely get metadata value"""
        try:
            value = doc.metadata.get(key, default)
            return value if value is not None and value != "" else default
        except Exception as e:
            logger.warning(f"Error getting metadata '{key}': {e}")
            return default

    def search_with_fallback(self, query: str, intent_data: Dict[str, Any], k: int, fallback_k: int = None) -> List[Document]:
        """Search with fallback to broader search if no results found"""
        fallback_k = fallback_k or k * 2
        
        # First attempt: multi-query search
        docs = self.multi_query_search(query, intent_data, k)
        
        if not docs:
            logger.warning("No results found in multi-query search, trying broader search")
            # Fallback: simple similarity search with larger k
            try:
                docs = self.vector_store.similarity_search(query, k=fallback_k)
                logger.info(f"Fallback search found {len(docs)} documents")
            except Exception as e:
                logger.error(f"Error in fallback search: {e}")
        
        return docs

    def get_search_statistics(self, docs: List[Document]) -> Dict[str, Any]:
        """Get statistics about search results"""
        if not docs:
            return {"total_documents": 0}
        
        recipe_types = {}
        sources = set()
        
        for doc in docs:
            recipe_type = self.safe_get_metadata(doc, "type")
            if recipe_type:
                recipe_types[recipe_type] = recipe_types.get(recipe_type, 0) + 1
            
            # Extract source from metadata if available
            source = self.safe_get_metadata(doc, "source", "")
            if source:
                sources.add(source)
        
        return {
            "total_documents": len(docs),
            "recipe_type_distribution": recipe_types,
            "sources": list(sources),
            "content_lengths": [len(doc.page_content) for doc in docs[:10]]  # Sample of content lengths
        }

    def filter_documents_by_metadata(self, docs: List[Document], metadata_filters: Dict[str, Any]) -> List[Document]:
        """Filter documents by metadata criteria"""
        filtered_docs = []
        
        for doc in docs:
            matches_all = True
            for key, value in metadata_filters.items():
                doc_value = self.safe_get_metadata(doc, key)
                if doc_value != value:
                    matches_all = False
                    break
            
            if matches_all:
                filtered_docs.append(doc)
        
        logger.info(f"Filtered {len(filtered_docs)} documents from {len(docs)} using metadata filters")
        return filtered_docs
