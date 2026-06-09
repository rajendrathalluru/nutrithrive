# app/main.py
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import logging
import threading
from typing import List, Optional

from app.models.schemas import (
    RecipeRequest, 
    RecipeResponse, 
    SearchResponse,
    HealthCheck
)
from app.core.config import settings
from app.services.rag_service import rag_service

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
startup_error: Optional[str] = None
startup_in_progress = False

# ============= NEW: Conversation Context Models =============
from pydantic import BaseModel

class ChatMessage(BaseModel):
    role: str
    content: str

class ConversationQueryRequest(RecipeRequest):
    """Extended request with conversation history"""
    conversation_history: Optional[List[ChatMessage]] = None

# ============= END NEW MODELS =============

app = FastAPI(
    title="Cancer Patient Recipe RAG API",
    description="AI-powered recipe recommendation system for cancer patients with dynamic adaptation",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

def _initialize_rag_system():
    global startup_error, startup_in_progress
    try:
        rag_service.initialize()
        startup_error = None
        logger.info("✅ RAG system initialized successfully")
    except Exception as e:
        startup_error = str(e)
        logger.error(f"❌ Failed to initialize RAG system: {e}")
    finally:
        startup_in_progress = False


@app.on_event("startup")
async def startup_event():
    global startup_in_progress
    if rag_service.is_initialized or startup_in_progress:
        return

    startup_in_progress = True
    threading.Thread(target=_initialize_rag_system, daemon=True).start()

@app.get("/health", response_model=HealthCheck)
async def health_check():
    """Check system health and status"""
    system_info = rag_service.get_system_info()
    return HealthCheck(
        status="healthy" if system_info["initialized"] else "unhealthy",
        message=(
            "Service is running"
            if system_info["initialized"]
            else "Service initialization in progress"
            if startup_in_progress
            else "Service initialization failed"
        ),
        model_loaded=system_info["initialized"],
        recipes_count=system_info["recipes_loaded"],
        initialization_error=system_info.get("initialization_error"),
        instruction_cache_size=system_info.get("instruction_cache_size", 0),
        supports_dynamic_adaptation=system_info.get("supports_dynamic_adaptation", True),
        supports_constraint_based_search=system_info.get("supports_constraint_based_search", True)
    )

@app.get("/")
async def root():
    """API information"""
    return {
        "message": "Cancer Patient Recipe RAG API v2.0",
        "version": "2.0.0",
        "features": [
            "Dynamic recipe adaptation based on constraints",
            "Budget-aware recipe recommendations", 
            "Equipment-specific cooking instructions",
            "Ingredient-based recipe search",
            "Symptom-aware recipe suggestions",
            "Auto-generated cooking instructions",
            "Conversation context awareness"  # NEW FEATURE
        ],
        "endpoints": {
            "/health": "System health check",
            "/search": "Quick recipe search (no adaptations)",
            "/ask": "Full intelligent query with dynamic adaptations (RECOMMENDED)"
        }
    }

@app.post("/search", response_model=SearchResponse)
async def search_recipes(request: RecipeRequest):
    """
    Quick recipe search without full adaptations.
    Faster but less personalized than /ask endpoint.
    
    Use this when you need:
    - Fast response times
    - Simple keyword search
    - No special adaptations needed
    """
    try:
        if not rag_service.is_initialized:
            raise HTTPException(status_code=503, detail="RAG system not initialized")
            
        results = rag_service.search_recipes(request.query, request.k)
        return SearchResponse(
            query=request.query,
            results=results,
            total_found=len(results)
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in search: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/ask", response_model=RecipeResponse)
async def ask_question(request: ConversationQueryRequest):  # UPDATED: Use new request model
    """
    Main endpoint for intelligent recipe queries with full dynamic adaptation.
    
    This endpoint:
    - Understands complex queries (budget, time, equipment, ingredients, symptoms)
    - Dynamically adapts recipes to user constraints
    - Generates/adapts cooking instructions as needed
    - Provides personalized recommendations with tips
    - Maintains conversation context across queries  # NEW FEATURE
    
    Example queries:
    - "I only have $10 for groceries. What can I make?"
    - "I feel nauseous and only have a microwave"
    - "Quick meal under 20 minutes with chicken and broccoli"
    - "I have eggs, spinach, and beans. What can I cook?"
    - "Easy to swallow recipes for sore throat"
    
    Conversation examples:
    - User: "Find me microwave recipes"
    - User: "Now show me vegetarian options" (understands context)
    - User: "Which ones are high in protein?" (understands previous context)
    """
    try:
        if not rag_service.is_initialized:
            raise HTTPException(
                status_code=503, 
                detail="RAG system not initialized. Please try again in a moment."
            )
        
        logger.info(f"Processing query: {request.query}")
        logger.info(f"Conversation history length: {len(request.conversation_history) if request.conversation_history else 0}")
        
        # Convert conversation history to the format expected by RAG service
        conv_history = None
        if request.conversation_history:
            conv_history = [
                {"role": msg.role, "content": msg.content}
                for msg in request.conversation_history
            ]
            logger.info(f"Using conversation context with {len(conv_history)} messages")
        
        # Get the full response from RAG service with conversation context
        response_data = rag_service.ask_question(
            query=request.query, 
            mode=request.mode,
            conversation_history=conv_history  # NEW: Pass conversation history
        )
        
        # Add conversation context info to response
        if conv_history:
            response_data["conversation_context_used"] = True
            response_data["previous_messages_considered"] = len(conv_history)
        else:
            response_data["conversation_context_used"] = False
        
        # Log what we're returning
        logger.info(f"Returning {response_data.get('matches_found', 0)} recipes")
        logger.info(f"Source documents count: {len(response_data.get('source_documents', []))}")
        logger.info(f"Conversation context used: {response_data.get('conversation_context_used', False)}")
        
        # Return the complete response - FastAPI will validate against RecipeResponse
        return response_data
        
    except ValueError as ve:
        logger.error(f"Validation error: {ve}")
        raise HTTPException(status_code=400, detail=str(ve))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in ask_question: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, 
            detail=f"Internal server error: {str(e)}"
        )

# ============= NEW: Backward Compatibility Endpoint =============
@app.post("/ask/v1", response_model=RecipeResponse)
async def ask_question_v1(request: RecipeRequest):
    """
    Legacy endpoint for backward compatibility.
    Use this if you don't need conversation context.
    """
    try:
        if not rag_service.is_initialized:
            raise HTTPException(
                status_code=503, 
                detail="RAG system not initialized. Please try again in a moment."
            )
        
        logger.info(f"Processing query (v1): {request.query}")
        
        # Get response without conversation context
        response_data = rag_service.ask_question(request.query, request.mode)
        
        # Mark as no conversation context
        response_data["conversation_context_used"] = False
        
        logger.info(f"Returning {response_data.get('matches_found', 0)} recipes")
        
        return response_data
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in ask_question_v1: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/system/info")
async def system_info():
    """Get detailed system information"""
    info = rag_service.get_system_info()
    # Add conversation context capability info
    info["supports_conversation_context"] = True
    info["max_conversation_history"] = 6  # Last 3 exchanges
    info["initialization_error"] = startup_error
    info["startup_in_progress"] = startup_in_progress
    return info

@app.get("/cache/stats")
async def cache_stats():
    """Get cache statistics"""
    return rag_service.get_cache_stats()

@app.post("/cache/clear")
async def clear_cache():
    """Clear all caches (useful for testing)"""
    rag_service.clear_caches()
    return {"message": "All caches cleared successfully"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app, 
        host=settings.API_HOST, 
        port=settings.API_PORT,
        log_level="info"
    )
