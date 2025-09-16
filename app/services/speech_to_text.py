"""AssemblyAI speech-to-text service integration."""

import asyncio
import json
import websockets
import base64
from typing import Optional, Callable, Dict, Any
import assemblyai as aai

from app.config import settings
from app.models.schemas import TranscriptionResult


class AssemblyAIService:
    """AssemblyAI speech-to-text service."""
    
    def __init__(self):
        # Set API key
        aai.settings.api_key = settings.assemblyai_api_key
        
        # Transcription configuration
        self.config = aai.TranscriptionConfig(
            real_time=True,
            language_detection=True,
            punctuate=True,
            format_text=True,
            speaker_labels=False,  # Disable for single speaker
            auto_chapters=False,
            sentiment_analysis=False,
            entity_detection=False,
            word_boost=[],  # Can add domain-specific words
            boost_param="default"
        )
        
        self.transcriber = aai.RealtimeTranscriber(
            sample_rate=settings.sample_rate,
            on_data=self._on_data,
            on_error=self._on_error,
            on_open=self._on_open,
            on_close=self._on_close,
        )
        
        self.callbacks: Dict[str, Callable] = {}
        self.session_data: Dict[str, Any] = {}
        
    def add_callback(self, event_type: str, callback: Callable):
        """Add callback for transcription events."""
        self.callbacks[event_type] = callback
    
    def _on_open(self, session_opened: aai.RealtimeSessionOpened):
        """Handle session opened event."""
        print(f"AssemblyAI session opened: {session_opened.session_id}")
        if "session_opened" in self.callbacks:
            self.callbacks["session_opened"](session_opened)
    
    def _on_data(self, transcript: aai.RealtimeTranscript):
        """Handle transcription data."""
        if not transcript.text:
            return
            
        result = TranscriptionResult(
            session_id=getattr(transcript, 'session_id', 'unknown'),
            text=transcript.text,
            confidence=getattr(transcript, 'confidence', 0.9),
            start_time=0.0,  # Real-time doesn't provide exact timing
            end_time=0.0,
            is_final=isinstance(transcript, aai.RealtimeFinalTranscript)
        )
        
        if "transcription" in self.callbacks:
            self.callbacks["transcription"](result)
    
    def _on_error(self, error: aai.RealtimeError):
        """Handle transcription errors."""
        print(f"AssemblyAI error: {error}")
        if "error" in self.callbacks:
            self.callbacks["error"](error)
    
    def _on_close(self):
        """Handle session closed event."""
        print("AssemblyAI session closed")
        if "session_closed" in self.callbacks:
            self.callbacks["session_closed"]()
    
    async def start_transcription(self, session_id: str):
        """Start real-time transcription."""
        try:
            self.session_data[session_id] = {"active": True}
            await self.transcriber.connect()
            print(f"Started transcription for session: {session_id}")
        except Exception as e:
            print(f"Failed to start transcription: {e}")
            raise
    
    async def stop_transcription(self, session_id: str):
        """Stop real-time transcription."""
        try:
            if session_id in self.session_data:
                self.session_data[session_id]["active"] = False
                del self.session_data[session_id]
            
            await self.transcriber.close()
            print(f"Stopped transcription for session: {session_id}")
        except Exception as e:
            print(f"Failed to stop transcription: {e}")
    
    async def send_audio(self, audio_data: bytes, session_id: str):
        """Send audio data for transcription."""
        try:
            if session_id in self.session_data and self.session_data[session_id]["active"]:
                self.transcriber.stream(audio_data)
        except Exception as e:
            print(f"Failed to send audio: {e}")
    
    async def transcribe_file(self, audio_file_path: str) -> str:
        """Transcribe an audio file (non-real-time)."""
        try:
            transcriber = aai.Transcriber()
            transcript = transcriber.transcribe(audio_file_path, config=self.config)
            
            if transcript.status == aai.TranscriptStatus.error:
                raise Exception(f"Transcription failed: {transcript.error}")
            
            return transcript.text
        except Exception as e:
            print(f"File transcription failed: {e}")
            raise


class WebSocketTranscriptionService:
    """Alternative WebSocket-based transcription service for real-time streaming."""
    
    def __init__(self):
        self.api_key = settings.assemblyai_api_key
        self.sample_rate = settings.sample_rate
        self.websocket = None
        self.callbacks: Dict[str, Callable] = {}
    
    def add_callback(self, event_type: str, callback: Callable):
        """Add callback for transcription events."""
        self.callbacks[event_type] = callback
    
    async def connect(self, session_id: str):
        """Connect to AssemblyAI WebSocket."""
        url = "wss://api.assemblyai.com/v2/realtime/ws"
        
        try:
            self.websocket = await websockets.connect(
                url,
                extra_headers={"Authorization": self.api_key},
                ping_interval=5,
                ping_timeout=20
            )
            
            # Send session start message
            await self.websocket.send(json.dumps({
                "audio_data": None,
                "sample_rate": self.sample_rate
            }))
            
            # Start listening for responses
            asyncio.create_task(self._listen_for_transcripts(session_id))
            
            print(f"Connected to AssemblyAI WebSocket for session: {session_id}")
            
        except Exception as e:
            print(f"Failed to connect to AssemblyAI WebSocket: {e}")
            raise
    
    async def disconnect(self):
        """Disconnect from WebSocket."""
        if self.websocket:
            await self.websocket.close()
            self.websocket = None
    
    async def send_audio(self, audio_data: bytes, session_id: str):
        """Send audio data through WebSocket."""
        if not self.websocket:
            return
        
        try:
            # Encode audio data as base64
            audio_b64 = base64.b64encode(audio_data).decode('utf-8')
            
            message = json.dumps({
                "audio_data": audio_b64
            })
            
            await self.websocket.send(message)
            
        except Exception as e:
            print(f"Failed to send audio via WebSocket: {e}")
    
    async def _listen_for_transcripts(self, session_id: str):
        """Listen for transcription results."""
        try:
            async for message in self.websocket:
                data = json.loads(message)
                
                if "text" in data and data["text"]:
                    result = TranscriptionResult(
                        session_id=session_id,
                        text=data["text"],
                        confidence=data.get("confidence", 0.9),
                        start_time=0.0,
                        end_time=0.0,
                        is_final=data.get("message_type") == "FinalTranscript"
                    )
                    
                    if "transcription" in self.callbacks:
                        await self.callbacks["transcription"](result)
                
                elif "error" in data:
                    if "error" in self.callbacks:
                        await self.callbacks["error"](data["error"])
                        
        except websockets.exceptions.ConnectionClosed:
            print("AssemblyAI WebSocket connection closed")
        except Exception as e:
            print(f"Error listening for transcripts: {e}")


# Global service instances
assemblyai_service = AssemblyAIService()
websocket_transcription_service = WebSocketTranscriptionService()