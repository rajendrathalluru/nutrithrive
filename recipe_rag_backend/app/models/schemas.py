# app/models/schemas.py
from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import List, Optional, Dict, Any

class RecipeRequest(BaseModel):
    query: str
    mode: Optional[str] = "auto"
    k: Optional[int] = Field(default=8, ge=1, le=20)

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Query must not be empty.")
        return normalized

class RecipeDocument(BaseModel):
    """Individual recipe with full details and adaptations"""
    name: str
    type: str
    calories: Optional[int] = 0
    description: Optional[str] = ""
    content: Optional[str] = ""
    youtube_link: Optional[str] = ""
    
    # Recipe details
    ingredients: List[str] = Field(default_factory=list)
    instructions: List[str] = Field(default_factory=list)
    
    # Dynamic adaptations (the magic!)
    ingredient_adaptations: Optional[List[str]] = None
    helpful_tips: Optional[List[str]] = None
    
    # Flags
    dynamically_adapted: Optional[bool] = False
    instructions_generated: Optional[bool] = False
    instructions_adapted: Optional[bool] = False
    needs_instruction_generation: Optional[bool] = False
    
    model_config = ConfigDict(extra="allow")

class IntentAnalysis(BaseModel):
    """User query intent analysis"""
    query_type: str
    constraints: Dict[str, Any] = Field(default_factory=dict)
    preferences: Dict[str, Any] = Field(default_factory=dict)
    cancer_patient_specific: Dict[str, Any] = Field(default_factory=dict)
    search_strategy: Dict[str, Any] = Field(default_factory=dict)
    
    model_config = ConfigDict(extra="allow")

class RecipeResponse(BaseModel):
    """Complete response with AI summary and detailed recipes"""
    query: str
    response: str  # AI-generated personalized response
    source: str
    matches_found: int
    mode: str
    
    # The key field that was missing!
    source_documents: List[Dict[str, Any]] = Field(default_factory=list)
    
    # Optional fields
    intent_analysis: Optional[Dict[str, Any]] = None
    dynamically_adapted: Optional[bool] = False
    instructions_generated: Optional[bool] = False
    verification_details: Optional[Dict[str, Any]] = None
    
    model_config = ConfigDict(extra="allow")

class SearchResponse(BaseModel):
    """Quick search response"""
    query: str
    results: List[Dict[str, Any]]
    total_found: int

class HealthCheck(BaseModel):
    status: str
    message: str
    model_loaded: bool
    recipes_count: int
    startup_in_progress: Optional[bool] = False
    initialization_error: Optional[str] = None
    
    # Add more info
    instruction_cache_size: Optional[int] = 0
    supports_dynamic_adaptation: Optional[bool] = True
    supports_constraint_based_search: Optional[bool] = True
