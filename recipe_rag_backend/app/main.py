# app/main.py
import asyncio
import base64
from io import BytesIO
import json
from pathlib import Path
from fastapi import FastAPI, File, HTTPException, Request, Response, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
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
import openai
import requests

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

frontend_build_dir = Path(__file__).resolve().parents[1] / "frontend-build"
frontend_static_dir = frontend_build_dir / "static"
frontend_index_file = frontend_build_dir / "index.html"

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

if frontend_static_dir.exists():
    app.mount("/static", StaticFiles(directory=frontend_static_dir), name="frontend-static")


def _guess_audio_filename(content_type: str) -> str:
    normalized_type = (content_type or "audio/webm").split(";")[0].strip().lower()
    extension_map = {
        "audio/webm": "webm",
        "audio/mp4": "mp4",
        "audio/mpeg": "mp3",
        "audio/mp3": "mp3",
        "audio/wav": "wav",
        "audio/x-wav": "wav",
        "audio/mpga": "mp3",
        "audio/ogg": "ogg",
        "audio/opus": "opus",
        "application/octet-stream": "webm",
    }
    extension = extension_map.get(normalized_type, "webm")
    return f"voice-input.{extension}"


def _transcribe_audio_bytes(audio_bytes: bytes, content_type: str) -> str:
    audio_file = BytesIO(audio_bytes)
    audio_file.name = _guess_audio_filename(content_type)

    transcription = openai.Audio.transcribe(
        model="whisper-1",
        file=audio_file,
        response_format="json",
    )

    return (transcription.get("text") or "").strip()


def _create_realtime_transcription_session(offer_sdp: str) -> str:
    session_config = {
        "type": "transcription",
        "audio": {
            "input": {
                "transcription": {
                    "model": "gpt-realtime-whisper",
                    "language": "en",
                    "delay": "minimal",
                },
                "turn_detection": None,
            }
        },
    }

    response = requests.post(
        "https://api.openai.com/v1/realtime/calls",
        headers={
            "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
        },
        files={
            "sdp": (None, offer_sdp),
            "session": (None, json.dumps(session_config)),
        },
        timeout=45,
    )

    if not response.ok:
        raise RuntimeError(
            f"Realtime session creation failed: {response.status_code} {response.text}"
        )

    return response.text

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
    """Serve the frontend app when available, otherwise return API information."""
    if frontend_index_file.exists():
        return FileResponse(frontend_index_file)

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


@app.post("/realtime/session")
async def create_realtime_session(request: Request):
    """Create a browser WebRTC transcription session via the unified Realtime interface."""
    try:
        raw_body = await request.body()
        offer_sdp = raw_body.decode("utf-8")
        if not offer_sdp:
            raise HTTPException(status_code=400, detail="Missing SDP offer.")

        logger.info("Received realtime SDP offer (%s bytes)", len(raw_body))

        answer_sdp = await asyncio.to_thread(_create_realtime_transcription_session, offer_sdp)
        return Response(content=answer_sdp, media_type="application/sdp")
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Failed to create realtime transcription session: {exc}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Unable to initialize live voice session."
        )


@app.post("/transcribe")
async def transcribe_audio(file: UploadFile = File(...)):
    """Transcribe recorded voice input into text for the chat composer."""
    raw_content_type = (file.content_type or "").strip().lower()
    normalized_content_type = raw_content_type.split(";")[0].strip()
    allowed_types = {
        "audio/webm",
        "audio/mp4",
        "audio/mpeg",
        "audio/mp3",
        "audio/wav",
        "audio/x-wav",
        "audio/mpga",
        "audio/ogg",
        "audio/opus",
        "application/octet-stream",
    }

    logger.info(
        "Received transcription upload: filename=%s content_type=%s normalized_content_type=%s",
        file.filename,
        file.content_type,
        normalized_content_type or "<empty>",
    )

    if normalized_content_type and normalized_content_type not in allowed_types and not normalized_content_type.startswith("audio/"):
        raise HTTPException(
            status_code=400,
            detail="Unsupported audio format. Please try recording again."
        )

    try:
        audio_bytes = await file.read()
        if not audio_bytes:
            raise HTTPException(status_code=400, detail="Empty audio upload received.")

        transcript_text = _transcribe_audio_bytes(
            audio_bytes=audio_bytes,
            content_type=normalized_content_type or "audio/webm",
        )
        if not transcript_text:
            raise HTTPException(status_code=422, detail="No speech was detected in the recording.")

        return {"text": transcript_text}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Voice transcription failed: {exc}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Voice transcription is temporarily unavailable."
        )


@app.websocket("/ws/transcribe")
async def transcribe_audio_stream(websocket: WebSocket):
    """Provide live, incremental transcription updates using rolling audio snapshots."""
    await websocket.accept()

    current_content_type = "audio/webm"
    latest_transcript = ""

    try:
        await websocket.send_json({
            "type": "ready",
            "message": "Voice transcription session ready",
        })

        while True:
            message = await websocket.receive_json()
            message_type = message.get("type")

            if message_type == "start":
                requested_content_type = (message.get("mimeType") or "").strip()
                if requested_content_type:
                    current_content_type = requested_content_type
                latest_transcript = ""
                await websocket.send_json({"type": "started"})
                continue

            if message_type == "snapshot":
                encoded_audio = message.get("audio") or ""
                requested_content_type = (message.get("mimeType") or "").strip()
                if requested_content_type:
                    current_content_type = requested_content_type

                if not encoded_audio:
                    continue

                try:
                    audio_bytes = base64.b64decode(encoded_audio)
                except Exception:
                    await websocket.send_json({
                        "type": "error",
                        "message": "Unable to decode recorded audio snapshot.",
                    })
                    continue

                if not audio_bytes:
                    continue

                try:
                    transcript_text = await asyncio.to_thread(
                        _transcribe_audio_bytes,
                        audio_bytes,
                        current_content_type,
                    )
                except Exception as exc:
                    logger.error(f"Live voice transcription failed: {exc}", exc_info=True)
                    await websocket.send_json({
                        "type": "error",
                        "message": "Live voice transcription is temporarily unavailable.",
                    })
                    continue

                transcript_changed = False
                if transcript_text and transcript_text != latest_transcript:
                    latest_transcript = transcript_text
                    transcript_changed = True

                await websocket.send_json({
                    "type": "snapshot_result",
                    "text": latest_transcript,
                    "changed": transcript_changed,
                })
                continue

            if message_type == "stop":
                await websocket.send_json({
                    "type": "final",
                    "text": latest_transcript,
                })
                break

            await websocket.send_json({
                "type": "error",
                "message": "Unsupported transcription event.",
            })
    except WebSocketDisconnect:
        logger.info("Voice transcription websocket disconnected")
    finally:
        if websocket.client_state.name != "DISCONNECTED":
            await websocket.close()

@app.get("/{full_path:path}")
async def frontend_app(full_path: str):
    """Serve React build assets and client-side routes from the same domain."""
    requested_file = frontend_build_dir / full_path

    if requested_file.is_file():
        return FileResponse(requested_file)

    if frontend_index_file.exists():
        return FileResponse(frontend_index_file)

    raise HTTPException(status_code=404, detail="Not found")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app, 
        host=settings.API_HOST, 
        port=settings.API_PORT,
        log_level="info"
    )
