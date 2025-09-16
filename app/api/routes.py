"""API endpoints for the Voice Assistant backend."""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from typing import Dict, Any, Optional
import asyncio
import json
import uuid
from datetime import datetime

from app.models.schemas import (
    VoiceAssistantRequest, 
    VoiceAssistantResponse,
    VoiceSession,
    TranscriptionResult,
    LLMResponse
)
from app.services.livekit_integration import livekit_session_manager
from app.services.speech_to_text import assemblyai_service, websocket_transcription_service
from app.services.llm_pipeline import conversation_manager
from app.utils.audio_processing import AudioProcessor
from app.utils.turn_detection import conversation_manager as turn_conversation_manager

router = APIRouter()
audio_processor = AudioProcessor()

# Active WebSocket connections
active_connections: Dict[str, WebSocket] = {}


@router.post("/sessions", response_model=Dict[str, Any])
async def create_session(user_id: Optional[str] = None):
    """Create a new voice assistant session."""
    try:
        session_id = str(uuid.uuid4())
        
        # Create LiveKit session
        session = await livekit_session_manager.create_voice_session(session_id, user_id)
        
        # Initialize conversation manager
        conversation_manager.create_session(session_id)
        
        # Initialize turn detector
        turn_conversation_manager.create_session(session_id)
        
        return {
            "session_id": session_id,
            "status": "created",
            "livekit_token": livekit_session_manager.livekit_service.generate_access_token(
                f"voice_session_{session_id}",
                f"user_{user_id or 'anonymous'}"
            ),
            "created_at": session.created_at.isoformat()
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/sessions/{session_id}")
async def end_session(session_id: str):
    """End a voice assistant session."""
    try:
        # End LiveKit session
        await livekit_session_manager.end_voice_session(session_id)
        
        # Cleanup conversation manager
        conversation_manager.remove_session(session_id)
        
        # Cleanup turn detector
        turn_conversation_manager.remove_session(session_id)
        
        # Close WebSocket if active
        if session_id in active_connections:
            await active_connections[session_id].close()
            del active_connections[session_id]
        
        return {"session_id": session_id, "status": "ended"}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    """Get session information."""
    session = livekit_session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Get turn detector state
    turn_detector = turn_conversation_manager.get_session(session_id)
    turn_state = turn_detector.get_state() if turn_detector else {}
    
    # Get conversation summary
    conversation_summary = conversation_manager.get_session_summary(session_id)
    
    return {
        "session": session.dict(),
        "turn_state": turn_state,
        "conversation": conversation_summary
    }


@router.get("/sessions")
async def list_sessions():
    """List all active sessions."""
    active_sessions = livekit_session_manager.get_active_sessions()
    return {
        "sessions": [session.dict() for session in active_sessions.values()],
        "count": len(active_sessions)
    }


@router.post("/sessions/{session_id}/process", response_model=VoiceAssistantResponse)
async def process_text_input(session_id: str, request: VoiceAssistantRequest):
    """Process text input through the LLM pipeline."""
    try:
        if not request.text_input:
            raise HTTPException(status_code=400, detail="Text input required")
        
        start_time = datetime.now()
        
        # Process through LLM
        llm_response = await conversation_manager.process_user_input(
            session_id, 
            request.text_input
        )
        
        processing_time = (datetime.now() - start_time).total_seconds()
        
        return VoiceAssistantResponse(
            session_id=session_id,
            transcription=request.text_input,
            llm_response=llm_response.response,
            status="success",
            processing_time=processing_time,
            metadata={
                "tokens_used": llm_response.tokens_used,
                "model": llm_response.model
            }
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.websocket("/sessions/{session_id}/ws")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    """WebSocket endpoint for real-time voice communication."""
    await websocket.accept()
    active_connections[session_id] = websocket
    
    # Set up transcription callbacks
    async def on_transcription(result: TranscriptionResult):
        """Handle transcription results."""
        if result.is_final and result.text.strip():
            # Process through LLM
            try:
                llm_response = await conversation_manager.process_user_input(
                    session_id, 
                    result.text
                )
                
                # Send response back through WebSocket
                await websocket.send_json({
                    "type": "llm_response",
                    "transcription": result.text,
                    "response": llm_response.response,
                    "session_id": session_id,
                    "timestamp": datetime.now().isoformat()
                })
                
            except Exception as e:
                await websocket.send_json({
                    "type": "error",
                    "message": str(e),
                    "session_id": session_id
                })
        else:
            # Send partial transcription
            await websocket.send_json({
                "type": "partial_transcription",
                "text": result.text,
                "session_id": session_id,
                "is_final": result.is_final
            })
    
    async def on_turn_event(event):
        """Handle turn detection events."""
        await websocket.send_json({
            "type": "turn_event",
            "event_type": event.event_type,
            "confidence": event.confidence,
            "audio_level": event.audio_level,
            "session_id": session_id,
            "timestamp": event.timestamp.isoformat()
        })
    
    # Set up callbacks
    assemblyai_service.add_callback("transcription", on_transcription)
    
    turn_detector = turn_conversation_manager.get_session(session_id)
    if turn_detector:
        turn_detector.add_callback("speech_start", on_turn_event)
        turn_detector.add_callback("speech_end", on_turn_event)
        turn_detector.add_callback("turn_end", on_turn_event)
        turn_detector.add_callback("silence_detected", on_turn_event)
    
    try:
        # Start transcription
        await assemblyai_service.start_transcription(session_id)
        
        while True:
            # Receive audio data or commands
            message = await websocket.receive()
            
            if message["type"] == "websocket.disconnect":
                break
            
            try:
                if "bytes" in message:
                    # Process audio data
                    audio_data = message["bytes"]
                    
                    # Process audio through pipeline
                    processed_audio, has_voice, audio_level = audio_processor.process_audio_chunk(audio_data)
                    
                    # Send to turn detector
                    if turn_detector:
                        turn_state = await turn_detector.process_audio_level(audio_level, has_voice)
                    
                    # Send to transcription if voice detected
                    if has_voice:
                        await assemblyai_service.send_audio(audio_data, session_id)
                    
                    # Send to LiveKit
                    await livekit_session_manager.send_audio_to_session(session_id, audio_data)
                
                elif "text" in message:
                    # Handle text commands
                    data = json.loads(message["text"])
                    command = data.get("command")
                    
                    if command == "start_transcription":
                        await assemblyai_service.start_transcription(session_id)
                    elif command == "stop_transcription":
                        await assemblyai_service.stop_transcription(session_id)
                    elif command == "reset_turn_detector":
                        if turn_detector:
                            turn_detector.reset()
                    elif command == "get_state":
                        state_data = {
                            "turn_state": turn_detector.get_state() if turn_detector else {},
                            "conversation": conversation_manager.get_session_summary(session_id)
                        }
                        await websocket.send_json({
                            "type": "state",
                            "data": state_data,
                            "session_id": session_id
                        })
                    
            except Exception as e:
                await websocket.send_json({
                    "type": "error",
                    "message": str(e),
                    "session_id": session_id
                })
    
    except WebSocketDisconnect:
        pass
    
    finally:
        # Cleanup
        if session_id in active_connections:
            del active_connections[session_id]
        
        # Stop transcription
        try:
            await assemblyai_service.stop_transcription(session_id)
        except:
            pass


@router.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "services": {
            "livekit": "available",
            "assemblyai": "available",
            "llm": "available"
        }
    }