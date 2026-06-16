import logging
import re
from typing import Dict, Any, List
from functools import lru_cache

logger = logging.getLogger(__name__)

class AICRGuidelinesService:
    """
    AICR (American Institute for Cancer Research) Guidelines Service
    
    Data-driven approach: All guidelines are structured data, not hardcoded prompts.
    Source: AICR.org - Verified cancer patient nutrition guidelines
    Last verified: January 2024
    """
    
    def __init__(self):
        self._guidelines = None
        self._initialized = False
    
    @lru_cache(maxsize=1)
    def get_guidelines(self) -> Dict[str, Any]:
        """
        Get structured AICR guidelines (cached for performance).
        
        Returns:
            Dict containing all AICR guidelines with source attribution
        """
        if self._guidelines:
            return self._guidelines
        
        self._guidelines = self._load_verified_guidelines()
        self._initialized = True
        logger.info("AICR guidelines loaded successfully")
        return self._guidelines
    
    def _load_verified_guidelines(self) -> Dict[str, Any]:
        """
        Load verified AICR guidelines.
        
        Source: https://www.aicr.org/patients-survivors/
        These are core, verified facts from AICR, not assumptions.
        """
        return {
            "metadata": {
                "source": "AICR.org - Cancer Patients & Survivors Nutrition",
                "last_verified": "2024-01",
                "version": "1.0",
                "url": "https://www.aicr.org/patients-survivors/"
            },
            
            "nutrition_priorities": {
                "protein": {
                    "importance": "critical",
                    "target_per_meal": "Include protein source at each meal",
                    "target_grams": "20-30g per meal for most adults",
                    "reasoning": "Protein helps repair tissue, maintain muscle mass, and support immune function during treatment",
                    "recommended_sources": [
                        "chicken", "turkey", "fish", "eggs", "greek yogurt",
                        "cottage cheese", "tofu", "tempeh", "beans", "lentils"
                    ],
                    "cooking_tips": "Cook thoroughly to safe internal temperatures"
                },
                "calories": {
                    "importance": "high",
                    "reasoning": "Adequate calories prevent unintended weight loss and maintain strength",
                    "strategies": [
                        "Choose nutrient-dense foods",
                        "Eat small frequent meals if needed",
                        "Add healthy fats for extra calories"
                    ]
                },
                "hydration": {
                    "importance": "critical",
                    "goal": "Stay well hydrated throughout treatment",
                    "sources": ["water", "broths", "herbal teas", "smoothies", "soups"],
                    "reasoning": "Prevents dehydration, helps manage side effects"
                }
            },
            
            "food_safety": {
                "priority": "critical",
                "rules": {
                    "cook_thoroughly": {
                        "requirement": "All meat, poultry, eggs, and fish must be fully cooked",
                        "internal_temps": {
                            "poultry": "165°F (74°C)",
                            "ground_meats": "160°F (71°C)",
                            "fish": "145°F (63°C)",
                            "eggs": "Cook until yolk and white are firm"
                        },
                        "reasoning": "Weakened immune system increases infection risk"
                    },
                    "avoid_high_risk": {
                        "items": [
                            "raw or undercooked eggs",
                            "raw fish (sushi, sashimi)",
                            "raw shellfish",
                            "unpasteurized dairy products",
                            "unpasteurized juices",
                            "raw sprouts",
                            "deli meats (unless heated to steaming)"
                        ],
                        "reasoning": "High risk of foodborne illness"
                    },
                    "proper_storage": {
                        "refrigerate": "Within 2 hours of cooking",
                        "use_within": "3-4 days for leftovers",
                        "thaw_safely": "In refrigerator or microwave, never on counter"
                    }
                }
            },
            
            "symptom_management": {
                "nausea": {
                    "helpful_approaches": [
                        "Eat small frequent meals",
                        "Choose bland, easy-to-digest foods",
                        "Try cold or room temperature foods",
                        "Avoid strong food odors",
                        "Sip liquids slowly between meals"
                    ],
                    "helpful_foods": [
                        "crackers", "toast", "rice", "bananas",
                        "applesauce", "ginger tea", "clear broths"
                    ],
                    "foods_to_avoid": [
                        "very sweet foods", "very greasy or fried foods",
                        "spicy foods", "foods with strong odors"
                    ]
                },
                "mouth_sores": {
                    "helpful_textures": ["soft", "moist", "lukewarm", "smooth"],
                    "helpful_foods": [
                        "scrambled eggs", "mashed potatoes", "yogurt",
                        "smoothies", "oatmeal", "pureed soups", "cottage cheese"
                    ],
                    "foods_to_avoid": [
                        "acidic (citrus, tomatoes)", "spicy", "salty",
                        "rough or crunchy", "very hot temperature"
                    ],
                    "tips": [
                        "Use a straw for liquids",
                        "Cut food into small pieces",
                        "Add gravy or sauce to moisten foods"
                    ]
                },
                "taste_changes": {
                    "strategies": [
                        "Try cold foods if metallic taste present",
                        "Use plastic utensils if metal taste is issue",
                        "Rinse mouth before eating",
                        "Try tart foods if tolerated (lemon water)"
                    ],
                    "protein_alternatives": [
                        "If meat tastes bad: try beans, eggs, dairy, fish"
                    ]
                },
                "difficulty_swallowing": {
                    "safe_textures": ["pureed", "ground", "soft", "moist"],
                    "helpful_additions": ["gravies", "sauces", "broths"],
                    "foods_to_avoid": ["dry", "crumbly", "sticky", "tough"],
                    "tips": [
                        "Take small bites",
                        "Chew thoroughly",
                        "Sit upright while eating"
                    ]
                },
                "low_appetite": {
                    "strategies": [
                        "Eat when you feel best (often morning)",
                        "Keep easy snacks available",
                        "Eat small amounts frequently",
                        "Make meals visually appealing"
                    ],
                    "calorie_boosters": [
                        "Add olive oil to foods",
                        "Use whole milk instead of low-fat",
                        "Add nut butters to smoothies",
                        "Top foods with cheese or avocado"
                    ]
                }
            },
            
            "foods_to_emphasize": {
                "vegetables": {
                    "recommendation": "Variety of colorful vegetables",
                    "preparation": "Cooked when needed for easier digestion",
                    "benefits": "Vitamins, minerals, phytonutrients"
                },
                "fruits": {
                    "recommendation": "Variety of fruits, soft when needed",
                    "benefits": "Vitamins, antioxidants, natural sugars for energy"
                },
                "whole_grains": {
                    "note": "May need refined grains during active treatment",
                    "examples": ["oatmeal", "brown rice (when tolerated)", "quinoa"],
                    "alternatives": ["white rice", "white bread", "pasta when digestion is sensitive"]
                },
                "lean_proteins": {
                    "sources": ["poultry", "fish", "eggs", "legumes", "tofu"],
                    "importance": "Essential for healing and maintaining strength"
                },
                "healthy_fats": {
                    "sources": ["olive oil", "avocado", "nuts/seeds (when tolerated)"],
                    "benefits": "Calories, vitamin absorption, heart health"
                }
            },
            
            "foods_to_limit": {
                "processed_meats": {
                    "items": ["bacon", "sausage", "hot dogs", "deli meats"],
                    "recommendation": "Limit or avoid",
                    "reasoning": "AICR recommends limiting for cancer prevention"
                },
                "high_sodium": {
                    "recommendation": "Watch sodium intake",
                    "reasoning": "Can cause fluid retention, increase blood pressure",
                    "tips": [
                        "Choose low-sodium versions",
                        "Rinse canned foods",
                        "Use herbs and spices instead of salt"
                    ]
                },
                "alcohol": {
                    "recommendation": "Avoid during treatment",
                    "reasoning": "Can interfere with treatment, dehydrate, interact with medications"
                },
                "excessive_sugar": {
                    "recommendation": "Limit added sugars",
                    "reasoning": "Provides calories without nutrients, can affect appetite for healthy foods"
                }
            },
            
            "general_principles": [
                "Eat when you feel best - often in the morning",
                "Keep easy, ready-to-eat snacks available",
                "Don't force eating if nauseated - try again later",
                "Stay flexible - food preferences may change daily",
                "Focus on protein and calories first during treatment",
                "Small frequent meals often better than 3 large meals",
                "Listen to your body",
                "Work with registered dietitian for personalized advice",
                "Maintain food safety to prevent infections"
            ]
        }
    
    def get_prompt_context(self, focus_areas: List[str] = None) -> str:
        """
        Generate structured prompt context from guidelines.
        
        Args:
            focus_areas: Specific symptom areas to emphasize (e.g., ['nausea', 'protein'])
        
        Returns:
            Formatted string for LLM prompts
        """
        guidelines = self.get_guidelines()
        
        sections = [
            "# AICR Cancer Patient Nutrition Guidelines",
            f"Source: {guidelines['metadata']['source']}",
            ""
        ]
        
        # Always include food safety (critical)
        sections.append("## CRITICAL: Food Safety")
        food_safety = guidelines["food_safety"]["rules"]
        sections.append(f"- {food_safety['cook_thoroughly']['requirement']}")
        sections.append(f"  Reason: {food_safety['cook_thoroughly']['reasoning']}")
        sections.append(f"- Avoid: {', '.join(food_safety['avoid_high_risk']['items'][:5])}")
        sections.append("")
        
        # Always include protein (critical for cancer patients)
        sections.append("## Protein Requirements (CRITICAL)")
        protein = guidelines["nutrition_priorities"]["protein"]
        sections.append(f"- Target: {protein['target_grams']}")
        sections.append(f"- Why: {protein['reasoning']}")
        sections.append(f"- Sources: {', '.join(protein['recommended_sources'][:6])}")
        sections.append("")
        
        # Add symptom management if focus areas specified
        if focus_areas:
            symptom_mgmt = guidelines["symptom_management"]
            for area in focus_areas:
                if area in symptom_mgmt:
                    symptom_info = symptom_mgmt[area]
                    sections.append(f"## Managing {area.replace('_', ' ').title()}")
                    
                    if "helpful_foods" in symptom_info:
                        sections.append(f"- Helpful: {', '.join(symptom_info['helpful_foods'][:5])}")
                    if "helpful_textures" in symptom_info:
                        sections.append(f"- Textures: {', '.join(symptom_info['helpful_textures'])}")
                    if "foods_to_avoid" in symptom_info:
                        sections.append(f"- Avoid: {', '.join(symptom_info['foods_to_avoid'][:3])}")
                    sections.append("")
        
        # Foods to limit
        sections.append("## Foods to Limit")
        foods_to_limit = guidelines["foods_to_limit"]
        sections.append(f"- {foods_to_limit['processed_meats']['recommendation']}: {', '.join(foods_to_limit['processed_meats']['items'])}")
        sections.append(f"- {foods_to_limit['high_sodium']['recommendation']}")
        sections.append("")
        
        # Key principles
        sections.append("## Key Principles")
        for principle in guidelines["general_principles"][:5]:
            sections.append(f"- {principle}")
        
        return "\n".join(sections)
    
    def validate_recipe_compliance(self, recipe: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate a recipe against AICR guidelines.
        
        Args:
            recipe: Recipe dictionary with 'ingredients' list
        
        Returns:
            Compliance report with score, warnings, recommendations
        """
        guidelines = self.get_guidelines()
        
        compliance_report = {
            "overall_compliant": True,
            "warnings": [],
            "recommendations": [],
            "score": 100,
            "details": {}
        }
        
        ingredients = recipe.get("ingredients", [])
        if not ingredients:
            compliance_report["warnings"].append("No ingredients to validate")
            compliance_report["score"] = 50
            return compliance_report
        
        ingredients_lower = [ing.lower() for ing in ingredients]
        
        # Check for high-risk raw items
        avoid_raw = guidelines["food_safety"]["rules"]["avoid_high_risk"]["items"]
        for raw_item in avoid_raw:
            if self._matches_high_risk_item(raw_item, ingredients_lower):
                compliance_report["warnings"].append(
                    f"Contains '{raw_item}' - ensure fully cooked or pasteurized"
                )
                compliance_report["score"] -= 15
        
        # Check for processed meats
        processed_meats = guidelines["foods_to_limit"]["processed_meats"]["items"]
        for processed in processed_meats:
            if any(processed.lower() in ing for ing in ingredients_lower):
                compliance_report["warnings"].append(
                    f"Contains {processed} - AICR recommends limiting processed meats"
                )
                compliance_report["score"] -= 10
        
        # Check for protein source
        protein_sources = guidelines["nutrition_priorities"]["protein"]["recommended_sources"]
        has_protein = False
        for protein_source in protein_sources:
            if any(protein_source.lower() in ing for ing in ingredients_lower):
                has_protein = True
                compliance_report["details"]["protein_source"] = protein_source
                break
        
        if not has_protein:
            compliance_report["recommendations"].append(
                self._build_protein_recommendation(recipe, ingredients_lower)
            )
            compliance_report["score"] -= 15
        
        # Check for high sodium ingredients
        high_sodium_keywords = ["soy sauce", "canned soup", "bouillon", "seasoning packet"]
        for keyword in high_sodium_keywords:
            if any(keyword in ing for ing in ingredients_lower):
                compliance_report["warnings"].append(
                    f"High sodium ingredient detected - consider low-sodium alternative"
                )
                compliance_report["score"] -= 5
                break

        # Recommend lower-sodium canned beans when standard canned beans are used
        canned_bean_terms = ["canned beans", "black beans", "kidney beans", "pinto beans", "chickpeas", "garbanzo beans", "white beans", "cannellini beans"]
        has_regular_canned_beans = any(
            ("canned" in ing or "can " in ing or "beans," in ing or "beans)" in ing)
            and any(bean_term in ing for bean_term in canned_bean_terms)
            and "low-sodium" not in ing
            and "low sodium" not in ing
            and "no-salt-added" not in ing
            and "no salt added" not in ing
            for ing in ingredients_lower
        )

        if has_regular_canned_beans:
            compliance_report["recommendations"].append(
                "If using canned beans, choose low-sodium or no-salt-added when available. If using regular canned beans, rinse and drain them well to reduce sodium."
            )
        
        # Set overall compliance
        compliance_report["overall_compliant"] = compliance_report["score"] >= 70
        
        return compliance_report

    def _matches_high_risk_item(self, raw_item: str, ingredients_lower: List[str]) -> bool:
        item = raw_item.lower()

        if item == "raw or undercooked eggs":
            return any(
                "raw egg" in ing
                or "undercooked egg" in ing
                or ("egg" in ing and any(keyword in ing for keyword in ["raw", "runny", "undercooked", "soft yolk"]))
                for ing in ingredients_lower
            )

        if item == "raw fish (sushi, sashimi)":
            return any(
                ("raw fish" in ing)
                or ("sushi" in ing)
                or ("sashimi" in ing)
                for ing in ingredients_lower
            )

        if item == "raw shellfish":
            shellfish_terms = ("raw shellfish", "raw oyster", "raw clam", "raw mussel", "raw scallop", "ceviche")
            return any(any(term in ing for term in shellfish_terms) for ing in ingredients_lower)

        if item == "unpasteurized dairy products":
            return any("unpasteurized" in ing and any(term in ing for term in ["milk", "cheese", "yogurt", "dairy"]) for ing in ingredients_lower)

        if item == "unpasteurized juices":
            return any("unpasteurized" in ing and "juice" in ing for ing in ingredients_lower)

        if item == "raw sprouts":
            return any(any(term in ing for term in ["raw sprouts", "alfalfa sprouts", "bean sprouts", "sprouts"]) for ing in ingredients_lower)

        if item == "deli meats (unless heated to steaming)":
            deli_terms = ("deli meat", "cold cuts", "turkey slices", "ham slices", "salami", "prosciutto")
            return any(any(term in ing for term in deli_terms) for ing in ingredients_lower)

        escaped = re.escape(item)
        return any(re.search(rf"\b{escaped}\b", ing) for ing in ingredients_lower)

    def _build_protein_recommendation(self, recipe: Dict[str, Any], ingredients_lower: List[str]) -> str:
        if self._is_vegetarian_recipe(recipe, ingredients_lower):
            return "Add a vegetarian protein source such as tofu, tempeh, beans, lentils, Greek yogurt, cottage cheese, or eggs."

        return (
            "Add a protein source such as tofu, tempeh, beans, lentils, Greek yogurt, cottage cheese, or eggs; "
            "animal-based options like chicken, turkey, or fish can also work if they fit the recipe."
        )

    def _is_vegetarian_recipe(self, recipe: Dict[str, Any], ingredients_lower: List[str]) -> bool:
        text_parts = [
            recipe.get("name", ""),
            recipe.get("type", ""),
            recipe.get("description", "")
        ]
        combined_text = " ".join(str(part).lower() for part in text_parts)

        if "vegetarian" in combined_text:
            return True

        red_or_animal_meat_terms = [
            "chicken", "turkey", "fish", "salmon", "tuna", "shrimp", "beef", "pork", "lamb",
            "bacon", "ham", "sausage", "anchovy"
        ]
        has_meat_or_fish = any(any(term in ing for term in red_or_animal_meat_terms) for ing in ingredients_lower)
        return not has_meat_or_fish
    
    def extract_focus_areas_from_intent(self, intent_data: Dict[str, Any]) -> List[str]:
        """
        Extract which symptom areas to focus on from intent data.
        
        Args:
            intent_data: Intent analysis dictionary
        
        Returns:
            List of symptom areas to emphasize
        """
        focus_areas = []
        
        # Map symptoms to guideline sections
        symptom_mapping = {
            "nausea": "nausea",
            "vomit": "nausea",
            "queasy": "nausea",
            "mouth sore": "mouth_sores",
            "sore mouth": "mouth_sores",
            "sore throat": "mouth_sores",
            "swallow": "difficulty_swallowing",
            "dysphagia": "difficulty_swallowing",
            "taste": "taste_changes",
            "metallic": "taste_changes",
            "appetite": "low_appetite",
            "not hungry": "low_appetite"
        }
        
        # Check cancer-specific symptoms
        cancer_symptoms = intent_data.get("cancer_patient_specific", {}).get("symptoms", [])
        for symptom in cancer_symptoms:
            symptom_lower = symptom.lower()
            for keyword, mapped_area in symptom_mapping.items():
                if keyword in symptom_lower and mapped_area not in focus_areas:
                    focus_areas.append(mapped_area)
        
        # Check texture requirements
        texture_reqs = intent_data.get("cancer_patient_specific", {}).get("texture_requirements", [])
        for texture in texture_reqs:
            texture_lower = texture.lower()
            if "soft" in texture_lower or "smooth" in texture_lower or "easy" in texture_lower:
                if "mouth_sores" not in focus_areas:
                    focus_areas.append("mouth_sores")
        
        # Check preferences
        texture_prefs = intent_data.get("preferences", {}).get("texture_preferences", [])
        for pref in texture_prefs:
            pref_lower = pref.lower()
            if "soft" in pref_lower and "mouth_sores" not in focus_areas:
                focus_areas.append("mouth_sores")
        
        return focus_areas


# Global singleton instance
aicr_service = AICRGuidelinesService()
