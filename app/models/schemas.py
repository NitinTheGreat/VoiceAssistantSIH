"""Data models for the Voice Assistant backend."""

from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


class SessionStatus(str, Enum):
    """Session status enumeration."""
    ACTIVE = "active"
    INACTIVE = "inactive"
    PROCESSING = "processing"
    ERROR = "error"


class AudioChunk(BaseModel):
    """Audio chunk data model."""
    session_id: str
    chunk_id: str
    audio_data: bytes
    timestamp: datetime
    sample_rate: int
    duration: float
    is_speech: bool = False


class TranscriptionResult(BaseModel):
    """Speech-to-text transcription result."""
    session_id: str
    text: str
    confidence: float
    start_time: float
    end_time: float
    is_final: bool = False


class LLMResponse(BaseModel):
    """Language model response."""
    session_id: str
    prompt: str
    response: str
    model: str
    timestamp: datetime
    tokens_used: int


class VoiceSession(BaseModel):
    """Voice assistant session."""
    session_id: str
    user_id: Optional[str] = None
    status: SessionStatus = SessionStatus.INACTIVE
    created_at: datetime
    last_activity: datetime
    conversation_history: List[Dict[str, Any]] = []
    audio_settings: Dict[str, Any] = {}


class TurnDetectionEvent(BaseModel):
    """Turn detection event."""
    session_id: str
    event_type: str  # "speech_start", "speech_end", "silence_detected"
    timestamp: datetime
    confidence: float
    audio_level: float


class NoiseReductionResult(BaseModel):
    """Noise reduction processing result."""
    processed_audio: bytes
    noise_level: float
    reduction_applied: float
    quality_score: float


class VoiceAssistantRequest(BaseModel):
    """Voice assistant API request."""
    session_id: str
    audio_data: Optional[bytes] = None
    text_input: Optional[str] = None
    settings: Optional[Dict[str, Any]] = None


class VoiceAssistantResponse(BaseModel):
    """Voice assistant API response."""
    session_id: str
    transcription: Optional[str] = None
    llm_response: Optional[str] = None
    audio_response: Optional[bytes] = None
    status: str
    processing_time: float
    metadata: Dict[str, Any] = {}