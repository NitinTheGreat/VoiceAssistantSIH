"""LiveKit integration for real-time audio communication."""

import asyncio
from typing import Dict, Optional, Callable, Any
import json
import jwt
import time
from datetime import datetime, timedelta

from livekit import api, rtc
from livekit.api import AccessToken, VideoGrants

from app.config import settings
from app.models.schemas import VoiceSession, SessionStatus


class LiveKitService:
    """LiveKit service for real-time audio communication."""
    
    def __init__(self):
        self.api_key = settings.livekit_api_key
        self.api_secret = settings.livekit_api_secret
        self.ws_url = settings.livekit_ws_url
        
        # Room and participant management
        self.rooms: Dict[str, rtc.Room] = {}
        self.participants: Dict[str, rtc.Participant] = {}
        self.audio_sources: Dict[str, rtc.AudioSource] = {}
        
        # Event callbacks
        self.callbacks: Dict[str, Callable] = {}
    
    def generate_access_token(self, 
                            room_name: str, 
                            participant_name: str,
                            expires_in: int = 3600) -> str:
        """
        Generate access token for LiveKit room.
        
        Args:
            room_name: Name of the room
            participant_name: Name of the participant
            expires_in: Token expiration time in seconds
            
        Returns:
            Access token string
        """
        token = AccessToken(self.api_key, self.api_secret)
        token.with_identity(participant_name)
        token.with_name(participant_name)
        token.with_grants(VideoGrants(
            room_join=True,
            room=room_name,
            can_publish=True,
            can_subscribe=True,
            can_publish_data=True
        ))
        
        # Set expiration
        token.with_ttl(timedelta(seconds=expires_in))
        
        return token.to_jwt()
    
    async def create_room(self, room_name: str) -> bool:
        """
        Create a new LiveKit room.
        
        Args:
            room_name: Name of the room to create
            
        Returns:
            True if successful, False otherwise
        """
        try:
            room_client = api.LiveKitAPI(
                url=self.ws_url,
                api_key=self.api_key,
                api_secret=self.api_secret
            )
            
            room_info = await room_client.room.create_room(
                api.CreateRoomRequest(name=room_name)
            )
            
            print(f"Created LiveKit room: {room_info.name}")
            return True
            
        except Exception as e:
            print(f"Failed to create room: {e}")
            return False
    
    async def connect_to_room(self, 
                            room_name: str, 
                            participant_name: str,
                            session_id: str) -> Optional[rtc.Room]:
        """
        Connect to a LiveKit room.
        
        Args:
            room_name: Name of the room
            participant_name: Name of the participant
            session_id: Session identifier
            
        Returns:
            Room object if successful, None otherwise
        """
        try:
            # Generate access token
            token = self.generate_access_token(room_name, participant_name)
            
            # Create room instance
            room = rtc.Room()
            
            # Set up event handlers
            @room.on("participant_connected")
            def on_participant_connected(participant: rtc.RemoteParticipant):
                print(f"Participant connected: {participant.identity}")
                if "participant_connected" in self.callbacks:
                    self.callbacks["participant_connected"](participant, session_id)
            
            @room.on("participant_disconnected")
            def on_participant_disconnected(participant: rtc.RemoteParticipant):
                print(f"Participant disconnected: {participant.identity}")
                if "participant_disconnected" in self.callbacks:
                    self.callbacks["participant_disconnected"](participant, session_id)
            
            @room.on("track_published")
            def on_track_published(publication: rtc.RemoteTrackPublication, 
                                 participant: rtc.RemoteParticipant):
                print(f"Track published: {publication.sid}")
                if "track_published" in self.callbacks:
                    self.callbacks["track_published"](publication, participant, session_id)
            
            @room.on("track_subscribed")
            def on_track_subscribed(track: rtc.Track, 
                                  publication: rtc.RemoteTrackPublication,
                                  participant: rtc.RemoteParticipant):
                print(f"Track subscribed: {track.sid}")
                if "track_subscribed" in self.callbacks:
                    self.callbacks["track_subscribed"](track, publication, participant, session_id)
            
            @room.on("data_received")
            def on_data_received(data: bytes, participant: rtc.RemoteParticipant):
                if "data_received" in self.callbacks:
                    self.callbacks["data_received"](data, participant, session_id)
            
            # Connect to room
            await room.connect(self.ws_url, token)
            
            # Store room reference
            self.rooms[session_id] = room
            
            print(f"Connected to LiveKit room: {room_name}")
            return room
            
        except Exception as e:
            print(f"Failed to connect to room: {e}")
            return None
    
    async def publish_audio_track(self, session_id: str) -> Optional[rtc.LocalAudioTrack]:
        """
        Publish audio track to the room.
        
        Args:
            session_id: Session identifier
            
        Returns:
            Audio track if successful, None otherwise
        """
        try:
            room = self.rooms.get(session_id)
            if not room:
                print("No room found for session")
                return None
            
            # Create audio source
            audio_source = rtc.AudioSource(
                sample_rate=settings.sample_rate,
                num_channels=1
            )
            
            # Create audio track
            audio_track = rtc.LocalAudioTrack.create_audio_track(
                "microphone", 
                audio_source
            )
            
            # Publish track
            publication = await room.local_participant.publish_track(
                audio_track,
                rtc.TrackPublishOptions()
            )
            
            # Store references
            self.audio_sources[session_id] = audio_source
            
            print(f"Published audio track: {publication.sid}")
            return audio_track
            
        except Exception as e:
            print(f"Failed to publish audio track: {e}")
            return None
    
    async def send_audio_data(self, session_id: str, audio_data: bytes):
        """
        Send audio data through the published track.
        
        Args:
            session_id: Session identifier
            audio_data: Raw audio bytes
        """
        try:
            audio_source = self.audio_sources.get(session_id)
            if audio_source:
                # Convert bytes to audio frame
                audio_frame = rtc.AudioFrame(
                    data=audio_data,
                    sample_rate=settings.sample_rate,
                    num_channels=1,
                    samples_per_channel=len(audio_data) // 2  # 16-bit audio
                )
                
                await audio_source.capture_frame(audio_frame)
                
        except Exception as e:
            print(f"Failed to send audio data: {e}")
    
    async def send_data_message(self, session_id: str, data: Dict[str, Any]):
        """
        Send data message to room participants.
        
        Args:
            session_id: Session identifier
            data: Data to send
        """
        try:
            room = self.rooms.get(session_id)
            if room:
                message = json.dumps(data).encode('utf-8')
                await room.local_participant.publish_data(
                    message,
                    rtc.DataPacketKind.RELIABLE
                )
                
        except Exception as e:
            print(f"Failed to send data message: {e}")
    
    async def disconnect_from_room(self, session_id: str):
        """
        Disconnect from LiveKit room.
        
        Args:
            session_id: Session identifier
        """
        try:
            room = self.rooms.get(session_id)
            if room:
                await room.disconnect()
                del self.rooms[session_id]
            
            if session_id in self.audio_sources:
                del self.audio_sources[session_id]
            
            print(f"Disconnected from room for session: {session_id}")
            
        except Exception as e:
            print(f"Failed to disconnect from room: {e}")
    
    def add_callback(self, event_type: str, callback: Callable):
        """Add event callback."""
        self.callbacks[event_type] = callback
    
    def remove_callback(self, event_type: str):
        """Remove event callback."""
        if event_type in self.callbacks:
            del self.callbacks[event_type]
    
    async def list_rooms(self) -> list:
        """List all active rooms."""
        try:
            room_client = api.LiveKitAPI(
                url=self.ws_url,
                api_key=self.api_key,
                api_secret=self.api_secret
            )
            
            response = await room_client.room.list_rooms(api.ListRoomsRequest())
            return [room.name for room in response.rooms]
            
        except Exception as e:
            print(f"Failed to list rooms: {e}")
            return []
    
    async def get_room_participants(self, room_name: str) -> list:
        """Get participants in a room."""
        try:
            room_client = api.LiveKitAPI(
                url=self.ws_url,
                api_key=self.api_key,
                api_secret=self.api_secret
            )
            
            response = await room_client.room.list_participants(
                api.ListParticipantsRequest(room=room_name)
            )
            
            return [p.identity for p in response.participants]
            
        except Exception as e:
            print(f"Failed to get room participants: {e}")
            return []


class LiveKitSessionManager:
    """Manages LiveKit sessions for voice assistant."""
    
    def __init__(self):
        self.livekit_service = LiveKitService()
        self.sessions: Dict[str, VoiceSession] = {}
        
        # Set up LiveKit callbacks
        self.livekit_service.add_callback("participant_connected", self._on_participant_connected)
        self.livekit_service.add_callback("participant_disconnected", self._on_participant_disconnected)
        self.livekit_service.add_callback("track_subscribed", self._on_track_subscribed)
        self.livekit_service.add_callback("data_received", self._on_data_received)
    
    async def create_voice_session(self, 
                                 session_id: str, 
                                 user_id: Optional[str] = None) -> VoiceSession:
        """
        Create a new voice session with LiveKit room.
        
        Args:
            session_id: Session identifier
            user_id: Optional user identifier
            
        Returns:
            VoiceSession object
        """
        # Create room name
        room_name = f"voice_session_{session_id}"
        participant_name = f"user_{user_id or 'anonymous'}"
        
        # Create LiveKit room
        await self.livekit_service.create_room(room_name)
        
        # Connect to room
        room = await self.livekit_service.connect_to_room(
            room_name, 
            participant_name, 
            session_id
        )
        
        if room:
            # Publish audio track
            await self.livekit_service.publish_audio_track(session_id)
            
            # Create session object
            session = VoiceSession(
                session_id=session_id,
                user_id=user_id,
                status=SessionStatus.ACTIVE,
                created_at=datetime.now(),
                last_activity=datetime.now(),
                audio_settings={
                    "room_name": room_name,
                    "participant_name": participant_name
                }
            )
            
            self.sessions[session_id] = session
            return session
        
        else:
            raise Exception("Failed to create LiveKit session")
    
    async def end_voice_session(self, session_id: str):
        """End a voice session and cleanup."""
        if session_id in self.sessions:
            await self.livekit_service.disconnect_from_room(session_id)
            
            session = self.sessions[session_id]
            session.status = SessionStatus.INACTIVE
            session.last_activity = datetime.now()
            
            del self.sessions[session_id]
    
    async def send_audio_to_session(self, session_id: str, audio_data: bytes):
        """Send audio data to a session."""
        if session_id in self.sessions:
            await self.livekit_service.send_audio_data(session_id, audio_data)
    
    def get_session(self, session_id: str) -> Optional[VoiceSession]:
        """Get session by ID."""
        return self.sessions.get(session_id)
    
    def get_active_sessions(self) -> Dict[str, VoiceSession]:
        """Get all active sessions."""
        return {sid: session for sid, session in self.sessions.items() 
                if session.status == SessionStatus.ACTIVE}
    
    async def _on_participant_connected(self, participant, session_id: str):
        """Handle participant connected event."""
        if session_id in self.sessions:
            session = self.sessions[session_id]
            session.last_activity = datetime.now()
    
    async def _on_participant_disconnected(self, participant, session_id: str):
        """Handle participant disconnected event."""
        if session_id in self.sessions:
            await self.end_voice_session(session_id)
    
    async def _on_track_subscribed(self, track, publication, participant, session_id: str):
        """Handle track subscribed event."""
        if session_id in self.sessions:
            session = self.sessions[session_id]
            session.last_activity = datetime.now()
    
    async def _on_data_received(self, data: bytes, participant, session_id: str):
        """Handle data received event."""
        try:
            message = json.loads(data.decode('utf-8'))
            print(f"Received data in session {session_id}: {message}")
            
        except Exception as e:
            print(f"Failed to parse received data: {e}")


# Global session manager instance
livekit_session_manager = LiveKitSessionManager()