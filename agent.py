import asyncio
import logging
import random
import json
import os
import re
import time
import sys
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Tuple
from pathlib import Path
import uuid
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict, deque
import threading
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv
from livekit import agents
from livekit.agents import AgentSession, Agent
from livekit.plugins import google, noise_cancellation

# Load environment variables first
load_dotenv()

# Fix Windows Unicode issues
if sys.platform.startswith('win'):
    # Set UTF-8 encoding for Windows console
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except:
        pass

# Configure logging with Windows-safe formatting (no Unicode emojis)
class SafeFormatter(logging.Formatter):
    """Custom formatter that removes Unicode characters for Windows compatibility"""
    
    def format(self, record):
        # Replace Unicode emojis with safe ASCII equivalents
        msg = super().format(record)
        emoji_replacements = {
            '🚀': '[START]',
            '✅': '[OK]',
            '❌': '[ERROR]',
            '⚠️': '[WARN]',
            '📝': '[LOG]',
            '🎤': '[USER]',
            '🤖': '[DONNA]',
            '⚙️': '[SYSTEM]',
            '👥': '[SESSION]',
            '📊': '[STATS]',
            '🗜️': '[COMPRESS]',
            '🤔': '[THINKING]',
            '🗣️': '[SPEAKING]',
            '👋': '[END]',
            '💾': '[SAVE]',
            '👤': '[PROFILE]',
            '📚': '[LOAD]',
            '🧹': '[CLEANUP]',
            '📋': '[INFO]',
            '🌐': '[LANG]',
            '⏰': '[TIME]',
            '💬': '[CHAT]',
            '⏱️': '[DURATION]',
            '⚡': '[SPEED]',
            '📁': '[FILE]',
            'ℹ️': '[INFO]'
        }
        
        for emoji, replacement in emoji_replacements.items():
            msg = msg.replace(emoji, replacement)
        
        return msg

# Setup logging with safe formatter
log_formatter = SafeFormatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Create logs directory
Path("logs").mkdir(exist_ok=True)

# File handler
file_handler = logging.FileHandler('logs/agent.log', mode='a', encoding='utf-8')
file_handler.setFormatter(log_formatter)

# Console handler
console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)

# Configure root logger
logging.basicConfig(
    level=logging.INFO,
    handlers=[console_handler, file_handler]
)

logger = logging.getLogger("mailminds-voice-agent")

# Separate conversation logger for clean transcript display
conversation_logger = logging.getLogger("conversation")
conversation_handler = logging.StreamHandler()
conversation_handler.setFormatter(logging.Formatter('%(message)s'))
conversation_logger.addHandler(conversation_handler)
conversation_logger.setLevel(logging.INFO)
conversation_logger.propagate = False


class SupportedLanguage(Enum):
    """Supported languages for MailMinds Donna"""
    ENGLISH_US = "en-US"
    ENGLISH_UK = "en-GB"
    ENGLISH_AU = "en-AU"
    ENGLISH_IN = "en-IN"
    HINDI_IN = "hi-IN"


@dataclass
class ConversationMessage:
    """Structure for conversation messages"""
    timestamp: str
    speaker: str  # "User" or "Donna"
    content: str
    language: Optional[str] = None
    confidence: Optional[float] = None
    response_time: Optional[float] = None
    user_id: Optional[str] = None


@dataclass
class UserProfile:
    """User personalization profile"""
    user_id: str
    preferred_language: str = "en-US"
    formality_level: str = "professional"  # casual, professional, formal
    response_length: str = "concise"  # brief, concise, detailed
    filler_tolerance: str = "moderate"  # low, moderate, high
    email_preferences: Dict[str, Any] = field(default_factory=dict)
    conversation_patterns: Dict[str, Any] = field(default_factory=dict)
    last_updated: datetime = field(default_factory=datetime.now)
    total_interactions: int = 0
    avg_session_length: float = 0.0


class SmartContextCompressor:
    """
    Intelligent context management to prevent token overflow while preserving important information
    """
    
    def __init__(self, max_tokens: int = 4000):
        self.max_tokens = max_tokens
        self.importance_weights = {
            'email_related': 3.0,
            'user_preference': 2.5,
            'error_recovery': 2.0,
            'recent_context': 1.5,
            'general': 1.0
        }
    
    def classify_message_importance(self, message: str) -> Tuple[str, float]:
        """Classify message importance for context retention"""
        message_lower = message.lower()
        
        # Email-related messages are most important
        if any(word in message_lower for word in [
            'mail', 'email', 'message', 'inbox', 'send', 'compose', 
            'draft', 'read my', 'check my', 'mailbox', 'recipient'
        ]):
            return 'email_related', self.importance_weights['email_related']
        
        # User preferences and settings
        elif any(word in message_lower for word in [
            'prefer', 'like', 'want', 'need', 'always', 'never', 'usually'
        ]):
            return 'user_preference', self.importance_weights['user_preference']
        
        # Error recovery context
        elif any(word in message_lower for word in [
            'error', 'problem', 'issue', 'sorry', 'repeat', 'again'
        ]):
            return 'error_recovery', self.importance_weights['error_recovery']
        
        else:
            return 'general', self.importance_weights['general']
    
    def compress_context(self, context: List[str], recent_messages: int = 6) -> List[str]:
        """
        Intelligently compress context while preserving important information
        """
        if len(context) <= recent_messages:
            return context
        
        # Always keep the most recent messages
        recent_context = context[-recent_messages:]
        older_context = context[:-recent_messages]
        
        # Score and sort older messages by importance
        scored_messages = []
        for i, message in enumerate(older_context):
            msg_type, importance = self.classify_message_importance(message)
            # Add recency bonus (more recent = higher score)
            recency_bonus = i / len(older_context) * 0.5
            final_score = importance + recency_bonus
            scored_messages.append((message, final_score))
        
        # Sort by importance and take top messages
        scored_messages.sort(key=lambda x: x[1], reverse=True)
        
        # Calculate how many older messages we can keep
        estimated_tokens = len(' '.join(recent_context).split()) * 1.3  # Rough token estimate
        remaining_token_budget = self.max_tokens - estimated_tokens
        
        important_messages = []
        current_tokens = 0
        
        for message, score in scored_messages:
            message_tokens = len(message.split()) * 1.3
            if current_tokens + message_tokens < remaining_token_budget:
                important_messages.append(message)
                current_tokens += message_tokens
            else:
                break
        
        # Combine important older messages with recent context
        # Sort important messages by original order to maintain conversation flow
        older_indices = {msg: older_context.index(msg) for msg in important_messages}
        important_messages.sort(key=lambda x: older_indices[x])
        
        compressed_context = important_messages + recent_context
        
        logger.info(f"[COMPRESS] Context compressed: {len(context)} -> {len(compressed_context)} messages")
        return compressed_context


class SessionRecoveryManager:
    """
    Robust session management with automatic recovery and error handling
    """
    
    def __init__(self):
        self.recovery_attempts = {}
        self.max_retries = 3
        self.base_delay = 1.0
        self.session_health = {}
        self.last_successful_interaction = {}
    
    async def with_retry(self, operation, session_id: str, operation_name: str = "operation"):
        """Execute operation with exponential backoff retry"""
        if session_id not in self.recovery_attempts:
            self.recovery_attempts[session_id] = 0
        
        for attempt in range(self.max_retries):
            try:
                start_time = time.time()
                result = await operation()
                
                # Reset recovery attempts on success
                self.recovery_attempts[session_id] = 0
                self.last_successful_interaction[session_id] = datetime.now()
                self.session_health[session_id] = 'healthy'
                
                response_time = time.time() - start_time
                logger.info(f"[OK] {operation_name} succeeded in {response_time:.2f}s")
                
                return result
                
            except Exception as e:
                self.recovery_attempts[session_id] += 1
                logger.warning(f"[WARN] {operation_name} failed (attempt {attempt + 1}/{self.max_retries}): {e}")
                
                if attempt == self.max_retries - 1:
                    # Final attempt failed
                    self.session_health[session_id] = 'critical'
                    await self.handle_critical_failure(session_id, operation_name, e)
                    raise
                
                # Exponential backoff
                delay = self.base_delay * (2 ** attempt) + random.uniform(0, 1)
                await asyncio.sleep(delay)
        
        return None
    
    async def handle_critical_failure(self, session_id: str, operation_name: str, error: Exception):
        """Handle critical failures with user-friendly fallback"""
        logger.error(f"[ERROR] Critical failure in {operation_name} for session {session_id}: {error}")
        
        # Log the error for debugging
        error_log = {
            'session_id': session_id,
            'operation': operation_name,
            'error': str(error),
            'timestamp': datetime.now().isoformat(),
            'recovery_attempts': self.recovery_attempts.get(session_id, 0)
        }
        
        # Save error log
        await self.log_error(error_log)
        
        # Provide fallback response if possible
        fallback_messages = [
            "I'm experiencing a brief technical issue. Please give me a moment to recover.",
            "I'm having trouble processing that right now. Could you please try again?",
            "There seems to be a connection issue. Let me try to reconnect."
        ]
        
        return random.choice(fallback_messages)
    
    async def log_error(self, error_log: Dict):
        """Log errors for analysis and debugging"""
        error_file = Path("logs") / f"errors_{datetime.now().strftime('%Y%m%d')}.json"
        error_file.parent.mkdir(exist_ok=True)
        
        try:
            # Append error to daily error log
            with open(error_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(error_log) + '\n')
        except Exception as e:
            logger.error(f"Failed to log error: {e}")
    
    def get_session_health(self, session_id: str) -> str:
        """Get current session health status"""
        return self.session_health.get(session_id, 'unknown')
    
    async def health_check(self, session_id: str) -> bool:
        """Perform session health check"""
        last_interaction = self.last_successful_interaction.get(session_id)
        if not last_interaction:
            return False
        
        # Consider session unhealthy if no successful interaction in last 5 minutes
        time_since_last = datetime.now() - last_interaction
        return time_since_last < timedelta(minutes=5)


class PersonalizationEngine:
    """
    Learn user preferences and adapt responses for personalized experience
    """
    
    def __init__(self):
        self.user_profiles: Dict[str, UserProfile] = {}
        self.interaction_history: Dict[str, List[Dict]] = defaultdict(list)
        self.learning_enabled = True
        self.profiles_file = Path("user_profiles.json")
        self.load_user_profiles()
    
    def load_user_profiles(self):
        """Load user profiles from persistent storage"""
        if self.profiles_file.exists():
            try:
                with open(self.profiles_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for user_id, profile_data in data.items():
                        # Convert datetime strings back to datetime objects
                        if 'last_updated' in profile_data:
                            profile_data['last_updated'] = datetime.fromisoformat(profile_data['last_updated'])
                        self.user_profiles[user_id] = UserProfile(**profile_data)
                logger.info(f"[LOAD] Loaded {len(self.user_profiles)} user profiles")
            except Exception as e:
                logger.error(f"Error loading user profiles: {e}")
    
    async def save_user_profiles(self):
        """Save user profiles to persistent storage"""
        try:
            # Convert datetime objects to strings for JSON serialization
            serializable_profiles = {}
            for user_id, profile in self.user_profiles.items():
                profile_dict = profile.__dict__.copy()
                profile_dict['last_updated'] = profile.last_updated.isoformat()
                serializable_profiles[user_id] = profile_dict
            
            with open(self.profiles_file, 'w', encoding='utf-8') as f:
                json.dump(serializable_profiles, f, indent=2)
            
            logger.info(f"[SAVE] Saved {len(self.user_profiles)} user profiles")
        except Exception as e:
            logger.error(f"Error saving user profiles: {e}")
    
    def get_or_create_profile(self, user_id: str) -> UserProfile:
        """Get existing user profile or create new one"""
        if user_id not in self.user_profiles:
            self.user_profiles[user_id] = UserProfile(user_id=user_id)
            logger.info(f"[PROFILE] Created new user profile: {user_id}")
        
        return self.user_profiles[user_id]
    
    async def learn_from_interaction(self, user_id: str, user_input: str, response_time: float, 
                                   user_satisfaction: Optional[float] = None):
        """Learn from user interaction to improve personalization"""
        if not self.learning_enabled:
            return
        
        profile = self.get_or_create_profile(user_id)
        profile.total_interactions += 1
        profile.last_updated = datetime.now()
        
        # Record interaction
        interaction = {
            'timestamp': datetime.now().isoformat(),
            'user_input': user_input,
            'response_time': response_time,
            'user_satisfaction': user_satisfaction,
            'input_length': len(user_input.split()),
            'query_type': self.classify_query_type(user_input)
        }
        
        self.interaction_history[user_id].append(interaction)
        
        # Keep only recent interactions (last 100)
        if len(self.interaction_history[user_id]) > 100:
            self.interaction_history[user_id] = self.interaction_history[user_id][-100:]
        
        # Update conversation patterns
        await self.update_conversation_patterns(user_id, interaction)
        
        # Save profiles periodically
        if profile.total_interactions % 10 == 0:
            await self.save_user_profiles()
    
    def classify_query_type(self, user_input: str) -> str:
        """Classify user query type for pattern analysis"""
        user_lower = user_input.lower()
        
        if any(word in user_lower for word in ['mail', 'email', 'message', 'inbox']):
            return 'email_related'
        elif any(word in user_lower for word in ['what', 'who', 'where', 'when', 'how']):
            return 'question'
        elif any(word in user_lower for word in ['calculate', 'plus', 'minus', '+', '-']):
            return 'calculation'
        elif any(word in user_lower for word in ['help', 'assist', 'support']):
            return 'help_request'
        else:
            return 'general'
    
    async def update_conversation_patterns(self, user_id: str, interaction: Dict):
        """Update user's conversation patterns based on interaction"""
        profile = self.user_profiles[user_id]
        
        # Analyze response time preferences
        if interaction['response_time'] < 1.0 and interaction.get('user_satisfaction', 0.5) > 0.7:
            # User seems to prefer quick responses
            profile.conversation_patterns['prefers_quick_responses'] = True
        
        # Analyze query complexity preferences
        if interaction['input_length'] > 10:
            profile.conversation_patterns['uses_detailed_queries'] = True
        
        # Analyze query type preferences
        query_type = interaction['query_type']
        if 'preferred_query_types' not in profile.conversation_patterns:
            profile.conversation_patterns['preferred_query_types'] = defaultdict(int)
        profile.conversation_patterns['preferred_query_types'][query_type] += 1
        
        # Update formality level based on user language
        user_input = interaction['user_input']
        if any(word in user_input.lower() for word in ['please', 'thank you', 'could you']):
            profile.formality_level = 'formal'
        elif any(word in user_input.lower() for word in ['hey', 'yo', 'sup', 'cool']):
            profile.formality_level = 'casual'
    
    def get_personalized_instructions(self, user_id: str) -> str:
        """Generate personalized instructions for the AI model"""
        profile = self.get_or_create_profile(user_id)
        
        base_instructions = f"""
        User Profile Adaptation:
        - Formality Level: {profile.formality_level}
        - Preferred Response Length: {profile.response_length}
        - Language: {profile.preferred_language}
        - Total Interactions: {profile.total_interactions}
        """
        
        # Add specific adaptations based on learned patterns
        if profile.conversation_patterns.get('prefers_quick_responses'):
            base_instructions += "\n- User prefers quick, efficient responses"
        
        if profile.conversation_patterns.get('uses_detailed_queries'):
            base_instructions += "\n- User tends to provide detailed context, respond accordingly"
        
        # Add preferred query types
        preferred_types = profile.conversation_patterns.get('preferred_query_types', {})
        if preferred_types:
            most_common = max(preferred_types.items(), key=lambda x: x[1])
            base_instructions += f"\n- User frequently asks {most_common[0]} questions"
        
        return base_instructions


class MultiUserManager:
    """
    Handle multiple concurrent users with session isolation and resource management
    """
    
    def __init__(self):
        self.active_sessions: Dict[str, Dict] = {}
        self.session_lock = threading.RLock()
        self.max_concurrent_sessions = 50
        self.session_timeout = timedelta(minutes=30)
        self.cleanup_task = None
        self.executor = ThreadPoolExecutor(max_workers=10)
    
    async def create_user_session(self, user_id: str, session: AgentSession, 
                                language: SupportedLanguage) -> str:
        """Create a new user session with proper isolation"""
        session_id = f"{user_id}_{uuid.uuid4().hex[:8]}"
        
        with self.session_lock:
            # Check session limits
            if len(self.active_sessions) >= self.max_concurrent_sessions:
                await self.cleanup_expired_sessions()
                
                if len(self.active_sessions) >= self.max_concurrent_sessions:
                    raise Exception("Maximum concurrent sessions reached")
            
            # Create session data
            session_data = {
                'session_id': session_id,
                'user_id': user_id,
                'session': session,
                'language': language,
                'created_at': datetime.now(),
                'last_activity': datetime.now(),
                'transcript_manager': TranscriptManager(user_id=user_id),
                'filler_manager': SmartFillerManager(),
                'context_compressor': SmartContextCompressor(),
                'conversation_context': [],
                'status': 'active'
            }
            
            self.active_sessions[session_id] = session_data
            
            logger.info(f"[SESSION] Created session {session_id} for user {user_id}")
            logger.info(f"[STATS] Active sessions: {len(self.active_sessions)}")
        
        # Start cleanup task if not running
        if not self.cleanup_task or self.cleanup_task.done():
            self.cleanup_task = asyncio.create_task(self.periodic_cleanup())
        
        return session_id
    
    async def get_session(self, session_id: str) -> Optional[Dict]:
        """Get session data with activity update"""
        with self.session_lock:
            if session_id in self.active_sessions:
                session_data = self.active_sessions[session_id]
                session_data['last_activity'] = datetime.now()
                return session_data
            return None
    
    async def end_session(self, session_id: str):
        """End a user session and cleanup resources"""
        with self.session_lock:
            if session_id in self.active_sessions:
                session_data = self.active_sessions[session_id]
                
                # End transcript
                if 'transcript_manager' in session_data:
                    session_data['transcript_manager'].end_conversation()
                
                # Update status
                session_data['status'] = 'ended'
                session_data['ended_at'] = datetime.now()
                
                # Remove from active sessions
                del self.active_sessions[session_id]
                
                logger.info(f"[END] Ended session {session_id}")
                logger.info(f"[STATS] Active sessions: {len(self.active_sessions)}")
    
    async def cleanup_expired_sessions(self):
        """Clean up expired sessions"""
        current_time = datetime.now()
        expired_sessions = []
        
        with self.session_lock:
            for session_id, session_data in self.active_sessions.items():
                last_activity = session_data['last_activity']
                if current_time - last_activity > self.session_timeout:
                    expired_sessions.append(session_id)
        
        # Clean up expired sessions
        for session_id in expired_sessions:
            logger.info(f"[CLEANUP] Cleaning up expired session: {session_id}")
            await self.end_session(session_id)
    
    async def periodic_cleanup(self):
        """Periodic cleanup task"""
        while True:
            try:
                await asyncio.sleep(300)  # Run every 5 minutes
                await self.cleanup_expired_sessions()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in periodic cleanup: {e}")
    
    def get_session_stats(self) -> Dict:
        """Get statistics about active sessions"""
        with self.session_lock:
            stats = {
                'total_active_sessions': len(self.active_sessions),
                'sessions_by_user': defaultdict(int),
                'average_session_duration': 0,
                'oldest_session_age': 0
            }
            
            if self.active_sessions:
                current_time = datetime.now()
                total_duration = timedelta()
                oldest_age = timedelta()
                
                for session_data in self.active_sessions.values():
                    user_id = session_data['user_id']
                    stats['sessions_by_user'][user_id] += 1
                    
                    session_duration = current_time - session_data['created_at']
                    total_duration += session_duration
                    
                    if session_duration > oldest_age:
                        oldest_age = session_duration
                
                stats['average_session_duration'] = total_duration.total_seconds() / len(self.active_sessions)
                stats['oldest_session_age'] = oldest_age.total_seconds()
            
            return stats


class TranscriptManager:
    """
    Enhanced transcript management with console display and file storage - BULLETPROOF VERSION
    """
    
    def __init__(self, base_dir: str = "transcripts", user_id: str = None):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(exist_ok=True)
        self.user_id = user_id
        
        self.conversation_id: Optional[str] = None
        self.transcript_file: Optional[Path] = None
        self.messages: List[ConversationMessage] = []
        self.session_metadata: Dict[str, Any] = {}
        
        # Console display settings
        self.show_console = True
        self.console_format = "detailed"  # simple, detailed
        self.session_started = False
        
        # Windows-safe display characters
        self.safe_chars = {
            'user_icon': '[USER]',
            'donna_icon': '[DONNA]',
            'system_icon': '[SYSTEM]',
            'separator': '=' * 60,
            'line': '-' * 60
        }
    
    def start_conversation(self, user_id: str = None, language: str = "en-US") -> str:
        """Start a new conversation with unique ID"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            unique_id = str(uuid.uuid4())[:8]
            
            if user_id:
                self.conversation_id = f"{user_id}_{timestamp}_{unique_id}"
                self.user_id = user_id
            else:
                self.conversation_id = f"guest_{timestamp}_{unique_id}"
            
            self.transcript_file = self.base_dir / f"transcript_{self.conversation_id}.txt"
            
            # Initialize session metadata
            self.session_metadata = {
                "conversation_id": self.conversation_id,
                "start_time": datetime.now().isoformat(),
                "language": language,
                "user_id": user_id or "guest"
            }
            
            # Write header to file
            self._write_header()
            
            # Display console header
            if self.show_console:
                self._display_console_header()
            
            self.session_started = True
            logger.info(f"[LOG] Started conversation: {self.conversation_id}")
            return self.conversation_id
            
        except Exception as e:
            logger.error(f"Error starting conversation: {e}")
            # Fallback conversation ID
            self.conversation_id = f"fallback_{int(time.time())}"
            self.session_started = True
            return self.conversation_id
    
    def _write_header(self):
        """Write conversation header to file"""
        try:
            with open(self.transcript_file, 'w', encoding='utf-8') as f:
                f.write(self.safe_chars['separator'] + "\n")
                f.write("MailMinds Voice Conversation Transcript\n")
                f.write(self.safe_chars['separator'] + "\n")
                f.write(f"Conversation ID: {self.conversation_id}\n")
                f.write(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"Language: {self.session_metadata.get('language', 'en-US')}\n")
                f.write(f"Agent: Donna (MailMinds AI Assistant)\n")
                f.write(f"User: {self.session_metadata.get('user_id', 'Guest')}\n")
                f.write(f"Platform: LiveKit + Gemini Live API\n")
                f.write(self.safe_chars['separator'] + "\n\n")
                f.flush()
        except Exception as e:
            logger.error(f"Error writing transcript header: {e}")
    
    def _display_console_header(self):
        """Display conversation header in console"""
        try:
            print("\n" + self.safe_chars['separator'])
            print("[CHAT] MAILMINDS DONNA - LIVE CONVERSATION")
            print(self.safe_chars['separator'])
            print(f"[INFO] Conversation ID: {self.conversation_id}")
            print(f"[USER] User: {self.session_metadata.get('user_id', 'Guest')}")
            print(f"[LANG] Language: {self.session_metadata.get('language', 'en-US')}")
            print(f"[TIME] Started: {datetime.now().strftime('%H:%M:%S')}")
            print(self.safe_chars['separator'])
            print("[CHAT] Live Transcript (Console + File):")
            print(self.safe_chars['line'])
        except Exception as e:
            logger.error(f"Error displaying console header: {e}")
            # Fallback simple header
            print("\n=== MAILMINDS DONNA - LIVE CONVERSATION ===")
    
    def log_message(self, speaker: str, content: str, language: str = None, 
                   confidence: float = None, response_time: float = None):
        """Log a message with both console display and file storage - BULLETPROOF"""
        try:
            if not self.session_started:
                logger.warning("Transcript session not started, starting now...")
                self.start_conversation(self.user_id)
            
            timestamp = datetime.now().strftime("%H:%M:%S")
            
            message = ConversationMessage(
                timestamp=timestamp,
                speaker=speaker,
                content=content,
                language=language,
                confidence=confidence,
                response_time=response_time,
                user_id=self.user_id
            )
            
            self.messages.append(message)
            
            # Console display with safe formatting
            if self.show_console:
                self._display_console_message_safe(message)
            
            # File logging
            if self.transcript_file:
                self._write_file_message_safe(message)
                
        except Exception as e:
            logger.error(f"Error logging message: {e}")
            # Fallback logging
            try:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] {speaker}: {content}")
            except:
                pass
    
    def _display_console_message_safe(self, message: ConversationMessage):
        """Display message in console with safe formatting (no Unicode)"""
        try:
            # Safe speaker icons
            if message.speaker == "User":
                speaker_icon = self.safe_chars['user_icon']
            elif message.speaker == "Donna":
                speaker_icon = self.safe_chars['donna_icon']
            else:
                speaker_icon = self.safe_chars['system_icon']
            
            # Format message based on console format setting
            if self.console_format == "detailed":
                # Detailed format with metadata
                metadata_parts = []
                if message.confidence:
                    metadata_parts.append(f"conf: {message.confidence:.2f}")
                if message.response_time:
                    metadata_parts.append(f"time: {message.response_time:.2f}s")
                if message.language:
                    metadata_parts.append(f"lang: {message.language}")
                
                metadata_str = f" ({', '.join(metadata_parts)})" if metadata_parts else ""
                
                print(f"[{message.timestamp}] {speaker_icon} {message.speaker}{metadata_str}:")
                print(f"  {message.content}")
                
            else:
                # Simple format
                print(f"{speaker_icon} {message.speaker}: {message.content}")
            
            print()  # Add spacing between messages
            
        except Exception as e:
            logger.error(f"Error in console message display: {e}")
            # Fallback to simple print
            try:
                print(f"[{message.timestamp}] {message.speaker}: {message.content}")
            except:
                pass
    
    def _write_file_message_safe(self, message: ConversationMessage):
        """Write message to file with safe error handling"""
        try:
            with open(self.transcript_file, 'a', encoding='utf-8') as f:
                # Build metadata string
                metadata_parts = []
                if message.confidence:
                    metadata_parts.append(f"confidence: {message.confidence:.2f}")
                if message.response_time:
                    metadata_parts.append(f"response_time: {message.response_time:.2f}s")
                if message.language:
                    metadata_parts.append(f"language: {message.language}")
                
                metadata_str = f" ({', '.join(metadata_parts)})" if metadata_parts else ""
                
                f.write(f"[{message.timestamp}] {message.speaker}{metadata_str}: {message.content}\n")
                f.flush()  # Ensure immediate write to disk
        except Exception as e:
            logger.error(f"Error writing to transcript file: {e}")
    
    def log_system_event(self, event: str):
        """Log system events to both console and file"""
        try:
            if not self.session_started:
                logger.warning("Transcript session not started, starting now...")
                self.start_conversation(self.user_id)
            
            timestamp = datetime.now().strftime("%H:%M:%S")
            
            # Console display
            if self.show_console:
                print(f"[{timestamp}] {self.safe_chars['system_icon']} SYSTEM: {event}")
                print()
            
            # File logging
            if self.transcript_file:
                with open(self.transcript_file, 'a', encoding='utf-8') as f:
                    f.write(f"[{timestamp}] SYSTEM: {event}\n")
                    f.flush()
            
            logger.info(f"SYSTEM: {event}")
            
        except Exception as e:
            logger.error(f"Error logging system event: {e}")
    
    def end_conversation(self):
        """End conversation and write summary to both console and file"""
        try:
            if not self.transcript_file or not self.session_started:
                return
            
            end_time = datetime.now()
            duration = end_time - datetime.fromisoformat(self.session_metadata["start_time"])
            
            # Calculate statistics
            user_messages = len([m for m in self.messages if m.speaker == "User"])
            donna_messages = len([m for m in self.messages if m.speaker == "Donna"])
            avg_response_time = 0
            
            response_times = [m.response_time for m in self.messages if m.response_time]
            if response_times:
                avg_response_time = sum(response_times) / len(response_times)
            
            # Console summary
            if self.show_console:
                print("\n" + self.safe_chars['separator'])
                print("[STATS] CONVERSATION SUMMARY")
                print(self.safe_chars['separator'])
                print(f"[DURATION] Duration: {str(duration).split('.')[0]}")
                print(f"[CHAT] Total messages: {len(self.messages)}")
                print(f"[USER] User messages: {user_messages}")
                print(f"[DONNA] Donna messages: {donna_messages}")
                if avg_response_time > 0:
                    print(f"[SPEED] Avg response time: {avg_response_time:.2f}s")
                print(f"[FILE] Saved to: {self.transcript_file}")
                print(self.safe_chars['separator'])
            
            # File summary
            with open(self.transcript_file, 'a', encoding='utf-8') as f:
                f.write(f"\n" + self.safe_chars['separator'] + "\n")
                f.write(f"Conversation ended: {end_time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"Duration: {str(duration).split('.')[0]}\n")
                f.write(f"Total messages: {len(self.messages)}\n")
                f.write(f"User messages: {user_messages}\n")
                f.write(f"Donna messages: {donna_messages}\n")
                if avg_response_time > 0:
                    f.write(f"Average response time: {avg_response_time:.2f}s\n")
                f.write(self.safe_chars['separator'] + "\n")
                f.flush()
            
            logger.info(f"[LOG] Conversation ended: {self.conversation_id} (Duration: {duration})")
            
        except Exception as e:
            logger.error(f"Error ending conversation: {e}")


class SmartFillerManager:
    """
    Enhanced filler speech manager with parallel processing capabilities
    """
    
    def __init__(self):
        self.is_active = False
        self.current_task = None
        self.session = None
        self.user_id = None
        
        # Context-aware thinking fillers
        self.thinking_fillers = {
            'general_knowledge': [
                "Umm, let me think about that",
                "Oh, I'll get that for you", 
                "Let me see, hmm",
                "Give me a moment to recall that",
                "Okay, let me look that up",
                "Right, I'll find that information for you"
            ],
            'calculation': [
                "Let me calculate that for you",
                "Umm, let me work that out",
                "Give me a second to figure that out",
                "Let me do the math on that"
            ],
            'mail_related': [
                "Let me check your emails",
                "Okay, I'll look into your mailbox",
                "Sure, let me access your mail",
                "Alright, checking your emails now"
            ],
            'clarification': [
                "I'm sorry, could you repeat that?",
                "I didn't quite catch that, could you say it again?",
                "Could you please clarify what you meant?",
                "I'm not sure I understood, could you rephrase that?"
            ],
            'general': [
                "Let me help you with that",
                "Okay, I'll get that information",
                "Sure, give me just a moment"
            ]
        }
    
    def set_session(self, session, user_id: str = None):
        """Set the agent session reference"""
        self.session = session
        self.user_id = user_id
    
    def classify_query_type(self, user_input: str) -> str:
        """Classify user query for appropriate filler selection"""
        if not user_input or len(user_input.strip()) < 3:
            return 'clarification'
        
        user_lower = user_input.lower()
        
        # Mail-related keywords
        if any(word in user_lower for word in [
            'mail', 'email', 'message', 'inbox', 'send', 'compose', 
            'draft', 'read my', 'check my', 'mailbox'
        ]):
            return 'mail_related'
        
        # General knowledge questions
        elif any(phrase in user_lower for phrase in [
            'what is', 'who is', 'where is', 'when is', 'how is',
            'what are', 'who are', 'where are', 'capital', 'president'
        ]):
            return 'general_knowledge'
        
        # Math/calculation
        elif any(word in user_lower for word in [
            'calculate', 'plus', 'minus', 'multiply', 'divide', 
            '+', '-', '*', '/', 'equals'
        ]):
            return 'calculation'
        
        else:
            return 'general'
    
    def get_thinking_filler(self, user_input: str) -> str:
        """Get appropriate thinking filler based on query type"""
        query_type = self.classify_query_type(user_input)
        fillers = self.thinking_fillers.get(query_type, self.thinking_fillers['general'])
        return random.choice(fillers)
    
    async def play_thinking_sound(self, user_input: str = ""):
        """
        Play a brief, natural filler while processing (parallel with main processing)
        """
        if self.is_active:
            return
            
        self.is_active = True
        
        try:
            # Minimal delay to avoid cutting off user
            await asyncio.sleep(0.2)
            
            if not self.is_active:  # Check if cancelled
                return
            
            # Create contextual filler
            filler_text = self.get_thinking_filler(user_input)
            logger.info(f"[THINKING] Playing contextual filler: '{filler_text}'")
            
            # This will be handled by the session's generate_reply method
            if self.session:
                await self.session.generate_reply(
                    instructions=f"Say this brief filler phrase naturally: '{filler_text}'. Keep it under 2 seconds."
                )
            
        except asyncio.CancelledError:
            logger.info("Filler cancelled")
        except Exception as e:
            logger.error(f"Error in filler manager: {e}")
        finally:
            self.is_active = False
    
    def stop_filler(self):
        """Immediately stop any filler activity"""
        if self.is_active:
            self.is_active = False
            if self.current_task and not self.current_task.done():
                self.current_task.cancel()
            logger.info("Filler stopped")


class MailMindsAssistant(Agent):
    """
    Enhanced MailMinds voice assistant with all advanced features integrated - BULLETPROOF VERSION
    """
    
    def __init__(self, language: SupportedLanguage = SupportedLanguage.ENGLISH_US, 
                 user_id: str = None, multi_user_manager: MultiUserManager = None):
        self.language = language
        self.user_id = user_id or f"user_{uuid.uuid4().hex[:8]}"
        self.session_id = None
        
        # Initialize managers
        self.multi_user_manager = multi_user_manager
        self.personalization_engine = PersonalizationEngine()
        self.session_recovery = SessionRecoveryManager()
        self.context_compressor = SmartContextCompressor()
        
        # Session-specific managers (will be set when session starts)
        self.filler_manager = None
        self.transcript_manager = None
        self.conversation_context = []
        self.last_user_input = ""
        
        # Performance tracking
        self.interaction_start_time = None
        self.greeting_sent = False
        
        # Get personalized instructions
        personalized_instructions = self.personalization_engine.get_personalized_instructions(self.user_id)
        
        # Enhanced system instructions
        super().__init__(
            instructions=f"""You are Donna, the AI voice assistant for MailMinds - a cutting-edge online email management platform.

CORE IDENTITY:
- You are Donna, a professional, warm, and intelligent female AI assistant
- You work within MailMinds, an advanced cloud-based email management software
- You help users control their entire email experience through natural voice commands
- You communicate in {language.value} with natural, human-like conversation

MAILMINDS PLATFORM:
- MailMinds is a comprehensive online email management solution
- Users can send, read, organize, search, and manage emails entirely through voice
- Features include: smart email composition, intelligent summarization, advanced search, scheduling, contact management
- You are the built-in voice interface that makes email management effortless and intuitive

CONVERSATION STYLE:
- Always sound natural and human-like with appropriate filler words and pauses
- For general knowledge questions: Start with thinking fillers like "Umm, let me get that for you..."
- Then provide the answer and offer email assistance: "Do you need help with any of your emails?"
- For email queries: Acknowledge naturally and help with their email needs
- If you can't understand something clearly, ask for clarification rather than assuming
- Use conversational, warm tone with professional competence
- Keep responses concise but complete (aim for 10-30 words for simple queries)
- For complex queries, break information into digestible chunks

{personalized_instructions}

RESPONSE PATTERNS:
General Knowledge: "Umm, let me think about that... [answer]. Do you need help with any of your emails?"
Email Tasks: "Sure, let me [action] for you." or "Let me check your [email aspect]."
Clarification: "I'm sorry, could you repeat that?" or "Could you clarify what you meant?"

CAPABILITIES:
- Voice-controlled email composition and sending
- Email reading and intelligent summarization
- Advanced email search and filtering
- Contact management and organization
- Email scheduling and reminders
- Inbox organization and management
- Integration with calendar and tasks

Always be helpful, efficient, and maintain a warm, professional tone that makes users feel comfortable and supported."""
        )
    
    async def on_session_started(self, session: AgentSession):
        """Initialize session with all advanced features"""
        try:
            logger.info(f"[START] MailMinds Donna session started for user: {self.user_id}")
            
            # Create session in multi-user manager
            if self.multi_user_manager:
                self.session_id = await self.multi_user_manager.create_user_session(
                    self.user_id, session, self.language
                )
                
                # Get session-specific managers
                session_data = await self.multi_user_manager.get_session(self.session_id)
                if session_data:
                    self.transcript_manager = session_data['transcript_manager']
                    self.filler_manager = session_data['filler_manager']
                    self.context_compressor = session_data['context_compressor']
                    self.conversation_context = session_data['conversation_context']
            else:
                # Fallback for single-user mode
                self.transcript_manager = TranscriptManager(user_id=self.user_id)
                self.filler_manager = SmartFillerManager()
                self.context_compressor = SmartContextCompressor()
            
            # Start conversation tracking
            conversation_id = self.transcript_manager.start_conversation(
                user_id=self.user_id,
                language=self.language.value
            )
            
            # Set up filler manager with session reference
            self.filler_manager.set_session(session, self.user_id)
            
            self.transcript_manager.log_system_event(
                f"LiveKit session started with Gemini Live API (Session ID: {self.session_id})"
            )
            
            # Send personalized initial greeting - IMPROVED
            await self.send_initial_greeting(session)
            
        except Exception as e:
            logger.error(f"Error in session startup: {e}")
            # Ensure basic functionality even if advanced features fail
            self.transcript_manager = TranscriptManager(user_id=self.user_id)
            self.filler_manager = SmartFillerManager()
            self.context_compressor = SmartContextCompressor()
    
    async def send_initial_greeting(self, session: AgentSession):
        """Send initial greeting with improved noise handling"""
        try:
            profile = self.personalization_engine.get_or_create_profile(self.user_id)
            
            if profile.total_interactions == 0:
                # First-time user - concise greeting
                greeting_text = "Hi! I'm Donna, your MailMinds voice assistant. How can I help you today?"
            else:
                # Returning user - personalized greeting
                greeting_text = "Welcome back! I'm Donna. What can I help you with today?"
            
            # Log the greeting
            self.transcript_manager.log_message("Donna", greeting_text, self.language.value)
            
            # Send greeting with explicit instructions
            await session.generate_reply(
                instructions=f"""Say exactly this greeting in a warm, professional tone: "{greeting_text}"
                
                IMPORTANT:
                - Speak clearly and at a moderate pace
                - Wait for the user to respond before saying anything else
                - Do not add any additional text or explanations
                - Keep the tone warm but professional
                - Ignore any background noise while speaking
                """
            )
            
            self.greeting_sent = True
            logger.info(f"[OK] Initial greeting sent: {greeting_text}")
            
        except Exception as e:
            logger.error(f"Error sending initial greeting: {e}")
            # Fallback greeting
            try:
                fallback_greeting = "Hi! I'm Donna, your voice assistant. How can I help you?"
                await session.generate_reply(
                    instructions=f"Say: '{fallback_greeting}'"
                )
                self.transcript_manager.log_message("Donna", fallback_greeting, self.language.value)
                self.greeting_sent = True
                logger.info("[OK] Fallback greeting sent")
            except Exception as fallback_error:
                logger.error(f"Fallback greeting also failed: {fallback_error}")
    
    async def on_user_speech_committed(self, user_speech: str):
        """
        Enhanced handler with parallel processing and advanced features
        """
        try:
            self.interaction_start_time = time.time()
            
            logger.info(f"[USER] User input: '{user_speech}' (User: {self.user_id})")
            self.last_user_input = user_speech
            
            # Update conversation context with compression
            self.conversation_context.append(f"User: {user_speech}")
            self.conversation_context = self.context_compressor.compress_context(self.conversation_context)
            
            # Log to transcript
            self.transcript_manager.log_message("User", user_speech, self.language.value)
            
            # Start parallel processing
            await self._process_user_input_parallel(user_speech)
            
        except Exception as e:
            logger.error(f"Error processing user speech: {e}")
    
    async def _process_user_input_parallel(self, user_speech: str):
        """Process user input with parallel filler and preprocessing"""
        try:
            # Start filler immediately (non-blocking)
            filler_task = asyncio.create_task(
                self.filler_manager.play_thinking_sound(user_speech)
            )
            
            # Start preprocessing in parallel
            preprocessing_task = asyncio.create_task(
                self._preprocess_user_input(user_speech)
            )
            
            # Wait for preprocessing while filler plays
            try:
                preprocessed_data = await preprocessing_task
                # Preprocessing complete, filler will be stopped when agent responds
            except Exception as e:
                logger.error(f"Error in preprocessing: {e}")
                # Cancel filler if preprocessing fails
                filler_task.cancel()
                
        except Exception as e:
            logger.error(f"Error in parallel processing: {e}")
    
    async def _preprocess_user_input(self, user_speech: str) -> Dict:
        """Preprocess user input for faster response"""
        try:
            return {
                'query_type': self.filler_manager.classify_query_type(user_speech),
                'input_length': len(user_speech.split()),
                'contains_email_keywords': any(word in user_speech.lower() 
                                             for word in ['mail', 'email', 'message']),
                'timestamp': datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"Error in preprocessing: {e}")
            return {}
    
    async def on_agent_speech_started(self):
        """Stop any filler when agent starts responding"""
        try:
            logger.info("[SPEAKING] Donna response starting")
            self.filler_manager.stop_filler()
        except Exception as e:
            logger.error(f"Error in speech started handler: {e}")
    
    async def on_user_speech_started(self):
        """Stop filler immediately when user starts talking"""
        try:
            logger.info("[USER] User started speaking")
            self.filler_manager.stop_filler()
        except Exception as e:
            logger.error(f"Error in user speech started handler: {e}")
    
    async def on_agent_speech_committed(self, agent_speech: str):
        """Track conversation and learn from interaction"""
        try:
            response_time = None
            if self.interaction_start_time:
                response_time = time.time() - self.interaction_start_time
                self.interaction_start_time = None
            
            logger.info(f"[DONNA] Donna: {agent_speech} (Response time: {response_time:.2f}s)" if response_time else f"[DONNA] Donna: {agent_speech}")
            
            # Update conversation context with compression
            self.conversation_context.append(f"Donna: {agent_speech}")
            self.conversation_context = self.context_compressor.compress_context(self.conversation_context)
            
            # Log to transcript with response time
            self.transcript_manager.log_message("Donna", agent_speech, self.language.value, 
                                               response_time=response_time)
            
            # Learn from interaction
            if self.last_user_input:
                await self.personalization_engine.learn_from_interaction(
                    self.user_id, self.last_user_input, response_time or 0
                )
                
        except Exception as e:
            logger.error(f"Error in agent speech committed handler: {e}")
    
    async def on_session_ended(self):
        """Clean up when session ends"""
        try:
            logger.info(f"[END] MailMinds Donna session ended for user: {self.user_id}")
            
            # End transcript
            if self.transcript_manager:
                self.transcript_manager.end_conversation()
            
            # Stop filler
            if self.filler_manager:
                self.filler_manager.stop_filler()
            
            # End session in multi-user manager
            if self.multi_user_manager and self.session_id:
                await self.multi_user_manager.end_session(self.session_id)
            
            # Save user profiles
            await self.personalization_engine.save_user_profiles()
            
        except Exception as e:
            logger.error(f"Error in session cleanup: {e}")


# Global multi-user manager instance
multi_user_manager = MultiUserManager()


def setup_environment():
    """Setup environment and check requirements"""
    print("MailMinds Donna Voice Agent - Enhanced Edition")
    print("=" * 50)
    print("Platform: LiveKit + Gemini Live API")
    print("Audio: Half-Cascade Architecture")
    print("Service: MailMinds Email Management")
    print("Features: Multi-User + AI Personalization")
    print("Noise Cancellation: Gemini Live API + LiveKit BVC")
    print()
    
    # Create required directories
    directories = ["transcripts", "logs", "debug_audio"]
    for directory in directories:
        Path(directory).mkdir(exist_ok=True)
    
    # Check if .env exists, create if not
    if not os.path.exists('.env'):
        print("Creating .env file template...")
        print("ERROR: Please edit .env file with your API keys!")
        print()
        print("Get your keys from:")
        print("- Google API: https://aistudio.google.com/app/apikey")
        print("- LiveKit: https://cloud.livekit.io")
        print()
        print("Then run: python agent.py")
        return False
    
    # Check API keys
    google_api_key = os.getenv("GOOGLE_API_KEY")
    livekit_url = os.getenv("LIVEKIT_URL")
    
    if not google_api_key or google_api_key == "your-google-api-key-here":
        print("ERROR: Please set your GOOGLE_API_KEY in the .env file!")
        return False
    
    if not livekit_url or livekit_url == "wss://your-livekit-server.livekit.cloud":
        print("ERROR: Please set your LiveKit configuration in the .env file!")
        return False
    
    print("Configuration loaded successfully")
    
    # Display configuration
    language = os.getenv("LANGUAGE", "en-US")
    model_name = os.getenv("GEMINI_MODEL", "gemini-live-2.5-flash-preview")
    voice_name = os.getenv("VOICE_NAME", "Aoede")
    max_sessions = int(os.getenv("MAX_CONCURRENT_SESSIONS", "50"))
    noise_cancellation_enabled = os.getenv("ENABLE_NOISE_CANCELLATION", "true").lower() == "true"
    
    print()
    print("Configuration:")
    print(f"- Agent: Donna (MailMinds AI Assistant)")
    print(f"- Model: {model_name}")
    print(f"- Voice: {voice_name} (Female)")
    print(f"- Language: {language}")
    print(f"- Platform: LiveKit + Gemini Live API")
    print(f"- Noise Cancellation: {'Enabled (BVC + Gemini)' if noise_cancellation_enabled else 'Disabled'}")
    print(f"- Max Sessions: {max_sessions}")
     
    print(f"- User Profiles: ./user_profiles.json")
    print()
    
    print("Starting Enhanced MailMinds Donna...")
    print("Advanced Features:")
    print("- Multi-user session management")
    print("- AI-powered personalization & learning")
    print("- Smart context compression")
    
    
    return True


async def entrypoint(ctx: agents.JobContext):
    """
    Enhanced entry point with multi-user support and advanced features - BULLETPROOF VERSION
    """
    try:
        logger.info("[START] Starting Enhanced MailMinds Voice Agent")
        
        # Get configuration from environment
        language = SupportedLanguage(os.getenv("LANGUAGE", "en-US"))
        model_name = os.getenv("GEMINI_MODEL", "gemini-live-2.5-flash-preview")  # Updated model
        voice_name = os.getenv("VOICE_NAME", "Aoede")
        temperature = float(os.getenv("TEMPERATURE", "0.7"))
        
        # Generate unique user ID for this session
        user_id = f"livekit_user_{uuid.uuid4().hex[:8]}"
        
        logger.info(f"Language: {language.value}")
        logger.info(f"Model: {model_name} (Latest Gemini Live)")
        logger.info(f"Voice: {voice_name}")
        logger.info(f"User ID: {user_id}")
        
        # Create assistant instance with multi-user support
        assistant = MailMindsAssistant(
            language=language, 
            user_id=user_id,
            multi_user_manager=multi_user_manager
        )
        
        # Create session with Gemini Live API integration
        try:
            session = AgentSession(
                llm=google.beta.realtime.RealtimeModel(
                    model=model_name,
                    voice=voice_name,
                    temperature=temperature,
                    instructions=f"""You are Donna, the AI voice assistant for MailMinds email management platform.

ENHANCED INSTRUCTIONS:
- Communicate in {language.value} with natural, human-like conversation
- Use contextual filler words appropriately based on query type
- For general knowledge: Start with "Umm, let me think about that..." then answer and offer email help
- For email tasks: Use natural acknowledgments like "Sure, let me check your emails"
- For unclear input: Ask for clarification politely
- Keep responses concise but complete
- Always maintain warm, professional tone
- End complex responses with helpful follow-ups

MAILMINDS CONTEXT:
You help users with comprehensive email management through voice commands including:
- Email composition, reading, and organization
- Smart search and filtering
- Contact management
- Scheduling and reminders
- Integration with calendar and tasks

PERSONALIZATION:
- Adapt your responses based on user interaction patterns
- Remember user preferences and communication style
- Provide increasingly personalized assistance over time

NOISE HANDLING:
- Ignore background noise and focus on clear speech
- If you hear unclear audio, politely ask for clarification
- Wait for complete user input before responding
- Filter out ambient sounds like typing, air conditioning, etc.
- Focus only on clear human speech patterns

Remember: You're having a natural conversation, not giving a presentation.""",
                    
                    # Optimized modalities for voice interaction
                    modalities=["AUDIO"],  # Audio-only for fastest response
                ),
            )
            logger.info("[OK] Gemini Live API session created successfully")
            
        except Exception as e:
            logger.error(f"[ERROR] Failed to create Gemini Live API session: {e}")
            logger.error("Make sure GOOGLE_API_KEY environment variable is set")
            logger.error("Get your API key from: https://aistudio.google.com/app/apikey")
            raise
        
        # Connect to the LiveKit room first
        await ctx.connect()
        logger.info("[OK] Connected to LiveKit room")
        
        # Start session with enhanced noise cancellation
        try:
            # Apply noise cancellation to the room's audio track
            if ctx.room.local_participant:
                # Enable noise cancellation on the microphone input
                await ctx.room.local_participant.set_microphone_track(
                    noise_cancellation.BVC()  # Better Voice Clarity
                )
                logger.info("[OK] Noise cancellation (BVC) enabled on microphone")
        except Exception as e:
            logger.warning(f"[WARN] Could not enable noise cancellation: {e}")
            logger.info("[INFO] Continuing without hardware noise cancellation")
        
        # Start the agent session
        await session.start(
            room=ctx.room,
            agent=assistant,
        )
        
        logger.info("Enhanced MailMinds Donna is ready for voice interaction!")
        logger.info("[INFO] Noise cancellation: Gemini Live API + LiveKit BVC")
        
        # Display session statistics
        stats = multi_user_manager.get_session_stats()
        logger.info(f"[STATS] Session Stats: {stats['total_active_sessions']} active sessions")
        
    except Exception as e:
        logger.error(f"[ERROR] Critical error in entrypoint: {e}")
        raise


if __name__ == "__main__":
    # Setup environment and check configuration
    if not setup_environment():
        exit(1)
    
    # Run the agent with standard worker options
    try:
        agents.cli.run_app(
            agents.WorkerOptions(
                entrypoint_fnc=entrypoint,
            )
        )
    except Exception as e:
        logger.error(f"[ERROR] Failed to start agent: {e}")
        exit(1)
