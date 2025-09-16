"""Turn detection system for voice conversation management."""

import time
import asyncio
from typing import Dict, List, Callable, Optional
from datetime import datetime, timedelta
import numpy as np
from collections import deque

from app.config import settings
from app.models.schemas import TurnDetectionEvent


class TurnDetector:
    """
    Turn detection system that monitors audio activity to determine
    when a user starts/stops speaking and when to respond.
    """
    
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.silence_threshold = settings.silence_threshold
        self.min_speech_duration = settings.min_speech_duration
        self.max_silence_duration = settings.max_silence_duration
        
        # State tracking
        self.is_speaking = False
        self.speech_start_time: Optional[float] = None
        self.last_voice_time: Optional[float] = None
        self.audio_levels: deque = deque(maxlen=50)  # Keep last 50 audio levels
        
        # Event callbacks
        self.callbacks: Dict[str, List[Callable]] = {
            "speech_start": [],
            "speech_end": [],
            "turn_end": [],
            "silence_detected": []
        }
    
    def add_callback(self, event_type: str, callback: Callable):
        """Add callback for turn detection events."""
        if event_type in self.callbacks:
            self.callbacks[event_type].append(callback)
    
    def remove_callback(self, event_type: str, callback: Callable):
        """Remove callback for turn detection events."""
        if event_type in self.callbacks and callback in self.callbacks[event_type]:
            self.callbacks[event_type].remove(callback)
    
    async def _trigger_event(self, event_type: str, **kwargs):
        """Trigger all callbacks for a specific event type."""
        event = TurnDetectionEvent(
            session_id=self.session_id,
            event_type=event_type,
            timestamp=datetime.now(),
            confidence=kwargs.get('confidence', 1.0),
            audio_level=kwargs.get('audio_level', 0.0)
        )
        
        for callback in self.callbacks.get(event_type, []):
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(event)
                else:
                    callback(event)
            except Exception as e:
                print(f"Error in turn detection callback: {e}")
    
    def _calculate_adaptive_threshold(self) -> float:
        """Calculate adaptive silence threshold based on recent audio levels."""
        if len(self.audio_levels) < 10:
            return self.silence_threshold
        
        # Use percentile-based threshold
        levels = np.array(list(self.audio_levels))
        background_noise = np.percentile(levels, 25)
        adaptive_threshold = max(self.silence_threshold, background_noise * 1.5)
        
        return adaptive_threshold
    
    async def process_audio_level(self, audio_level: float, has_voice: bool = None) -> str:
        """
        Process audio level and detect turn events.
        
        Args:
            audio_level: Current audio RMS level
            has_voice: Optional VAD result
            
        Returns:
            Current turn state: "speaking", "silent", "turn_end"
        """
        current_time = time.time()
        self.audio_levels.append(audio_level)
        
        # Use adaptive threshold
        threshold = self._calculate_adaptive_threshold()
        
        # Determine if currently speaking (combine audio level and VAD if available)
        is_voice_detected = audio_level > threshold
        if has_voice is not None:
            is_voice_detected = is_voice_detected and has_voice
        
        # State transitions
        if is_voice_detected:
            self.last_voice_time = current_time
            
            if not self.is_speaking:
                # Speech started
                self.is_speaking = True
                self.speech_start_time = current_time
                await self._trigger_event(
                    "speech_start", 
                    confidence=0.9, 
                    audio_level=audio_level
                )
                return "speaking"
        
        else:
            # No voice detected
            if self.is_speaking and self.last_voice_time:
                silence_duration = current_time - self.last_voice_time
                speech_duration = current_time - (self.speech_start_time or current_time)
                
                # Check if we should end the turn
                should_end_turn = (
                    silence_duration >= self.max_silence_duration and 
                    speech_duration >= self.min_speech_duration
                )
                
                if should_end_turn:
                    # Turn ended
                    self.is_speaking = False
                    await self._trigger_event(
                        "speech_end", 
                        confidence=0.8, 
                        audio_level=audio_level
                    )
                    await self._trigger_event(
                        "turn_end", 
                        confidence=0.9, 
                        audio_level=audio_level
                    )
                    return "turn_end"
                
                elif silence_duration >= 0.5:  # Brief silence
                    await self._trigger_event(
                        "silence_detected", 
                        confidence=0.7, 
                        audio_level=audio_level
                    )
        
        return "speaking" if self.is_speaking else "silent"
    
    def reset(self):
        """Reset turn detector state."""
        self.is_speaking = False
        self.speech_start_time = None
        self.last_voice_time = None
        self.audio_levels.clear()
    
    def get_state(self) -> Dict:
        """Get current turn detector state."""
        current_time = time.time()
        return {
            "is_speaking": self.is_speaking,
            "speech_duration": (
                current_time - self.speech_start_time 
                if self.speech_start_time else 0
            ),
            "silence_duration": (
                current_time - self.last_voice_time 
                if self.last_voice_time else 0
            ),
            "average_audio_level": (
                float(np.mean(self.audio_levels)) 
                if self.audio_levels else 0.0
            ),
            "adaptive_threshold": self._calculate_adaptive_threshold()
        }


class ConversationManager:
    """
    Manages multiple turn detectors for different sessions
    and coordinates conversation flow.
    """
    
    def __init__(self):
        self.sessions: Dict[str, TurnDetector] = {}
        self.conversation_states: Dict[str, str] = {}
    
    def create_session(self, session_id: str) -> TurnDetector:
        """Create a new turn detector for a session."""
        detector = TurnDetector(session_id)
        self.sessions[session_id] = detector
        self.conversation_states[session_id] = "waiting"
        return detector
    
    def get_session(self, session_id: str) -> Optional[TurnDetector]:
        """Get turn detector for a session."""
        return self.sessions.get(session_id)
    
    def remove_session(self, session_id: str):
        """Remove session and cleanup."""
        if session_id in self.sessions:
            del self.sessions[session_id]
        if session_id in self.conversation_states:
            del self.conversation_states[session_id]
    
    async def process_session_audio(self, session_id: str, 
                                  audio_level: float, has_voice: bool = None) -> str:
        """Process audio for a specific session."""
        detector = self.get_session(session_id)
        if not detector:
            detector = self.create_session(session_id)
        
        turn_state = await detector.process_audio_level(audio_level, has_voice)
        self.conversation_states[session_id] = turn_state
        
        return turn_state
    
    def get_all_states(self) -> Dict[str, Dict]:
        """Get states for all active sessions."""
        states = {}
        for session_id, detector in self.sessions.items():
            states[session_id] = {
                "turn_state": self.conversation_states.get(session_id, "unknown"),
                "detector_state": detector.get_state()
            }
        return states


# Global conversation manager instance
conversation_manager = ConversationManager()