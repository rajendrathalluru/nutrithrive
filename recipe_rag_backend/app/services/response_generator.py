import logging
import json
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

class ResponseGenerator:
    def __init__(self):
        self.llm = None
        
    def initialize(self, llm):
        self.llm = llm
    
    def generate_personalized_response(self, query: str, source_docs: List[Dict], intent_data: Dict[str, Any]) -> str:
        """
        Generate sensitive response focusing on nutrition without emphasizing cancer
        """
        if not source_docs:
            return "I couldn't find recipes matching your needs."
        
        try:
            recipe_count = len(source_docs)
            constraints = intent_data.get("constraints", {})
            constraint_mentions = []
            
            if constraints.get("max_ingredients"):
                constraint_mentions.append(f"{constraints['max_ingredients']} ingredients or less")
            if constraints.get("min_ingredients"):
                constraint_mentions.append(f"at least {constraints['min_ingredients']} ingredients")
            if constraints.get("dietary_restrictions"):
                constraint_mentions.append(f"{', '.join(constraints['dietary_restrictions'])} diet")
            
            constraint_text = ", ".join(constraint_mentions) if constraint_mentions else ""
            
            # Recipe info without cancer-focused language
            highlighted_docs = source_docs[:min(3, recipe_count)]
            recipe_info = []
            for i, doc in enumerate(highlighted_docs):
                info = f"Recipe {i+1}: {doc['name']} - {len(doc.get('ingredients', []))} ingredients"
                
                # Add AICR compliance info
                aicr_compliance = doc.get("aicr_compliance", {})
                if aicr_compliance.get("overall_compliant"):
                    info += " (nutrition-optimized)"
                
                # Add protein info if available
                if doc.get("protein_grams"):
                    info += f", {doc['protein_grams']}g protein"
                
                recipe_info.append(info)
            
            # More sensitive prompt focusing on nutrition and wellness
            response_prompt = f"""Create a warm, encouraging response for someone looking for nutritious recipes.

Query: "{query}"
Constraints: {constraint_text or 'flexible'}
Total recipes found: {recipe_count}

Highlighted recipes:
{chr(10).join(recipe_info)}

Brief response (under 150 words):
1. Acknowledge their recipe needs positively
2. State the exact total number of recipes found using this exact number: {recipe_count}
3. Highlight up to the first {min(3, recipe_count)} recipes with nutritional benefits (protein, easy to prepare, nourishing)
3. Mention these follow evidence-based nutrition guidelines
4. Brief encouragement about enjoying wholesome, satisfying meals
5. Do not mention any recipe count other than {recipe_count}

Focus on:
- Nutritional benefits and flavor
- Ease of preparation 
- Wholesome ingredients
- Positive eating experience
Avoid medical terminology or health condition references.
"""

            response = self.llm.predict(response_prompt)

            return response.strip()[:1200]
            
        except Exception as e:
            logger.error(f"Error generating response: {e}")
            highlighted_names = ", ".join([d['name'] for d in source_docs[:3]])
            return (
                f"I found {len(source_docs)} recipe{'s' if len(source_docs) != 1 else ''} "
                f"that match your request. Highlights include {highlighted_names}."
            )
    
    def generate_helpful_no_results_message(self, query: str, intent_data: Dict[str, Any]) -> str:
        """Generate a helpful message when no recipes can be found or generated"""
        constraints = intent_data.get("constraints", {})
        
        constraint_summary = []
        if constraints.get("max_ingredients"):
            constraint_summary.append(f"maximum {constraints['max_ingredients']} ingredients")
        if constraints.get("min_ingredients"):
            constraint_summary.append(f"at least {constraints['min_ingredients']} ingredients")
        if constraints.get("dietary_restrictions"):
            constraint_summary.append(f"{', '.join(constraints['dietary_restrictions'])} diet")
        if constraints.get("equipment_only"):
            constraint_summary.append(f"using only {', '.join(constraints['equipment_only'])}")
        
        if constraint_summary:
            return f"I couldn't find or generate AICR-compliant recipes that meet all your requirements ({', '.join(constraint_summary)}). This combination might be too specific. Could you try:\n\n• Relaxing some constraints\n• Changing ingredient count requirements\n• Asking about different types of recipes\n• Being more flexible with dietary restrictions"
        else:
            return "I couldn't find recipes matching your query. Could you try rephrasing or providing more details about what you're looking for?"

    def generate_error_response(self, error: Exception, query: str) -> str:
        """Generate user-friendly error response"""
        logger.error(f"Error processing query '{query}': {error}")
        
        error_responses = [
            "I apologize, but I'm having trouble accessing our recipe database right now. Please try again in a moment.",
            "I'm experiencing some technical difficulties. Could you please rephrase your question or try again shortly?",
            "I'm unable to process your request at the moment. This might be a temporary issue - please try again soon.",
            "There seems to be a connection issue with our recipe system. Please try your question again in a few moments."
        ]
        
        import random
        return random.choice(error_responses)

    def generate_welcome_message(self) -> str:
        """Generate welcome message for new conversations"""
        welcome_messages = [
            "Hi! I'm here to help you find personalized recipes for your nutrition journey. Tell me about your dietary needs, preferences, or what type of meal you're looking for.",
            "Hello! I'm your nutrition recipe assistant. I can help you find recipes that match your dietary preferences, available ingredients, or cooking equipment. What would you like to cook today?",
            "Welcome! I specialize in finding nutritious recipes tailored to your needs. Whether you're looking for quick meals, specific ingredients, or dietary-friendly options, I'm here to help. What are you in the mood for?"
        ]
        
        import random
        return random.choice(welcome_messages)

    def generate_followup_suggestions(self, current_query: str, found_recipes: List[Dict]) -> str:
        """Generate follow-up suggestions based on current results"""
        if not found_recipes:
            return ""
        
        suggestions = []
        
        # Check for equipment constraints
        equipment_used = set()
        for recipe in found_recipes:
            if recipe.get("verification_details", {}).get("constraint_violations"):
                for violation in recipe["verification_details"]["constraint_violations"]:
                    if "equipment" in violation.lower():
                        equipment = violation.split("equipment")[-1].strip()
                        if equipment:
                            equipment_used.add(equipment)
        
        if equipment_used:
            suggestions.append(f"• Try different cooking methods like stovetop or oven recipes")
        
        # Check for ingredient constraints
        ingredient_counts = [len(recipe.get("ingredients", [])) for recipe in found_recipes]
        if ingredient_counts and max(ingredient_counts) > 10:
            suggestions.append("• Look for simpler recipes with fewer ingredients")
        
        # Check for dietary restrictions
        dietary_options = ["vegetarian", "vegan", "gluten-free", "dairy-free"]
        suggestions.append(f"• Explore {', '.join(dietary_options[:2])} options")
        
        if suggestions:
            return "\n\n💡 **You might also like:**\n" + "\n".join(suggestions[:3])
        
        return ""

    def format_recipe_details(self, recipe: Dict[str, Any]) -> str:
        """Format individual recipe details for display"""
        details = []
        
        # Basic info
        details.append(f"**{recipe.get('name', 'Unknown Recipe')}**")
        details.append(f"*Type:* {recipe.get('type', 'General')}")
        
        # Nutrition info
        if recipe.get('calories'):
            details.append(f"*Calories:* {recipe['calories']}")
        if recipe.get('protein_grams'):
            details.append(f"*Protein:* {recipe['protein_grams']}g")
        
        # AICR compliance
        aicr_compliance = recipe.get("aicr_compliance", {})
        if aicr_compliance.get("overall_compliant"):
            details.append("✓ Nutrition-optimized")
        
        # Key ingredients (first 5)
        ingredients = recipe.get("ingredients", [])
        if ingredients:
            key_ingredients = ", ".join(ingredients[:5])
            if len(ingredients) > 5:
                key_ingredients += f" and {len(ingredients) - 5} more"
            details.append(f"*Ingredients:* {key_ingredients}")
        
        return "\n".join(details)

    def get_response_statistics(self, source_docs: List[Dict]) -> Dict[str, Any]:
        """Get statistics about the response for analytics"""
        if not source_docs:
            return {"total_recipes": 0}
        
        stats = {
            "total_recipes": len(source_docs),
            "database_recipes": sum(1 for doc in source_docs if not doc.get("generated_by_llm")),
            "generated_recipes": sum(1 for doc in source_docs if doc.get("generated_by_llm")),
            "enhanced_recipes": sum(1 for doc in source_docs if doc.get("dynamically_adapted")),
            "aicr_compliant": sum(1 for doc in source_docs if doc.get("aicr_compliance", {}).get("overall_compliant")),
            "average_ingredients": 0,
            "protein_sources": set()
        }
        
        # Calculate average ingredients
        ingredient_counts = [len(doc.get("ingredients", [])) for doc in source_docs]
        if ingredient_counts:
            stats["average_ingredients"] = round(sum(ingredient_counts) / len(ingredient_counts), 1)
        
        # Collect protein sources
        for doc in source_docs:
            aicr_details = doc.get("aicr_compliance", {}).get("details", {})
            if aicr_details.get("protein_source"):
                stats["protein_sources"].add(aicr_details["protein_source"])
        
        stats["protein_sources"] = list(stats["protein_sources"])
        
        return stats
