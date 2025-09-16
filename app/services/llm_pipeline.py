"""LLM pipeline service for natural language processing."""

import openai
from typing import List, Dict, Any, Optional, AsyncGenerator
from datetime import datetime
import json

from app.config import settings
from app.models.schemas import LLMResponse


class LLMService:
    """OpenAI LLM service for conversation processing."""
    
    def __init__(self):
        self.client = openai.AsyncOpenAI(api_key=settings.openai_api_key)
        self.model = "gpt-3.5-turbo"  # Default model
        self.max_tokens = 150  # Suitable for voice responses
        self.temperature = 0.7
        
        # System prompt for voice assistant
        self.system_prompt = """You are a helpful voice assistant. Keep your responses:
- Concise and conversational (1-3 sentences)
- Natural for spoken conversation
- Helpful and friendly
- Avoid long explanations unless specifically asked
- Use simple language suitable for voice interaction
"""
    
    def set_model(self, model: str):
        """Set the LLM model to use."""
        self.model = model
    
    def set_parameters(self, max_tokens: int = None, temperature: float = None):
        """Set LLM parameters."""
        if max_tokens is not None:
            self.max_tokens = max_tokens
        if temperature is not None:
            self.temperature = temperature
    
    async def generate_response(self, 
                              prompt: str, 
                              conversation_history: List[Dict[str, str]] = None,
                              session_id: str = "default") -> LLMResponse:
        """
        Generate a response using the LLM.
        
        Args:
            prompt: User input text
            conversation_history: Previous conversation context
            session_id: Session identifier
            
        Returns:
            LLMResponse object with the generated text
        """
        try:
            # Build messages for the conversation
            messages = [{"role": "system", "content": self.system_prompt}]
            
            # Add conversation history
            if conversation_history:
                messages.extend(conversation_history[-10:])  # Keep last 10 exchanges
            
            # Add current user message
            messages.append({"role": "user", "content": prompt})
            
            # Generate response
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                stream=False
            )
            
            # Extract response text
            response_text = response.choices[0].message.content.strip()
            tokens_used = response.usage.total_tokens
            
            return LLMResponse(
                session_id=session_id,
                prompt=prompt,
                response=response_text,
                model=self.model,
                timestamp=datetime.now(),
                tokens_used=tokens_used
            )
            
        except Exception as e:
            print(f"LLM generation error: {e}")
            # Return fallback response
            return LLMResponse(
                session_id=session_id,
                prompt=prompt,
                response="I'm sorry, I'm having trouble processing that right now. Could you please try again?",
                model=self.model,
                timestamp=datetime.now(),
                tokens_used=0
            )
    
    async def generate_streaming_response(self, 
                                        prompt: str, 
                                        conversation_history: List[Dict[str, str]] = None,
                                        session_id: str = "default") -> AsyncGenerator[str, None]:
        """
        Generate a streaming response using the LLM.
        
        Args:
            prompt: User input text
            conversation_history: Previous conversation context
            session_id: Session identifier
            
        Yields:
            Partial response strings as they're generated
        """
        try:
            # Build messages for the conversation
            messages = [{"role": "system", "content": self.system_prompt}]
            
            # Add conversation history
            if conversation_history:
                messages.extend(conversation_history[-10:])
            
            # Add current user message
            messages.append({"role": "user", "content": prompt})
            
            # Generate streaming response
            stream = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                stream=True
            )
            
            async for chunk in stream:
                if chunk.choices[0].delta.content is not None:
                    yield chunk.choices[0].delta.content
                    
        except Exception as e:
            print(f"Streaming LLM error: {e}")
            yield "I'm sorry, I'm having trouble processing that right now."
    
    def create_conversation_context(self, user_text: str, assistant_text: str) -> List[Dict[str, str]]:
        """
        Create conversation context entries.
        
        Args:
            user_text: User's message
            assistant_text: Assistant's response
            
        Returns:
            List of message dictionaries
        """
        return [
            {"role": "user", "content": user_text},
            {"role": "assistant", "content": assistant_text}
        ]


class ConversationManager:
    """Manages conversation state and history for multiple sessions."""
    
    def __init__(self):
        self.llm_service = LLMService()
        self.conversations: Dict[str, List[Dict[str, str]]] = {}
        self.session_metadata: Dict[str, Dict[str, Any]] = {}
    
    def create_session(self, session_id: str, metadata: Dict[str, Any] = None):
        """Create a new conversation session."""
        self.conversations[session_id] = []
        self.session_metadata[session_id] = metadata or {}
    
    def get_conversation_history(self, session_id: str) -> List[Dict[str, str]]:
        """Get conversation history for a session."""
        return self.conversations.get(session_id, [])
    
    def add_to_conversation(self, session_id: str, user_text: str, assistant_text: str):
        """Add exchange to conversation history."""
        if session_id not in self.conversations:
            self.create_session(session_id)
        
        self.conversations[session_id].extend([
            {"role": "user", "content": user_text},
            {"role": "assistant", "content": assistant_text}
        ])
        
        # Keep conversation history manageable (last 20 exchanges)
        if len(self.conversations[session_id]) > 40:
            self.conversations[session_id] = self.conversations[session_id][-40:]
    
    async def process_user_input(self, session_id: str, user_text: str) -> LLMResponse:
        """
        Process user input and generate response.
        
        Args:
            session_id: Session identifier
            user_text: User's spoken/typed text
            
        Returns:
            LLMResponse with generated text
        """
        if session_id not in self.conversations:
            self.create_session(session_id)
        
        # Get conversation history
        history = self.get_conversation_history(session_id)
        
        # Generate response
        response = await self.llm_service.generate_response(
            prompt=user_text,
            conversation_history=history,
            session_id=session_id
        )
        
        # Add to conversation history
        self.add_to_conversation(session_id, user_text, response.response)
        
        return response
    
    async def process_user_input_streaming(self, session_id: str, user_text: str) -> AsyncGenerator[str, None]:
        """
        Process user input and generate streaming response.
        
        Args:
            session_id: Session identifier
            user_text: User's spoken/typed text
            
        Yields:
            Partial response strings
        """
        if session_id not in self.conversations:
            self.create_session(session_id)
        
        # Get conversation history
        history = self.get_conversation_history(session_id)
        
        # Collect full response for history
        full_response = ""
        
        # Generate streaming response
        async for chunk in self.llm_service.generate_streaming_response(
            prompt=user_text,
            conversation_history=history,
            session_id=session_id
        ):
            full_response += chunk
            yield chunk
        
        # Add complete exchange to history
        self.add_to_conversation(session_id, user_text, full_response)
    
    def clear_conversation(self, session_id: str):
        """Clear conversation history for a session."""
        if session_id in self.conversations:
            self.conversations[session_id] = []
    
    def remove_session(self, session_id: str):
        """Remove session and all associated data."""
        if session_id in self.conversations:
            del self.conversations[session_id]
        if session_id in self.session_metadata:
            del self.session_metadata[session_id]
    
    def get_session_summary(self, session_id: str) -> Dict[str, Any]:
        """Get summary of session state."""
        history = self.get_conversation_history(session_id)
        metadata = self.session_metadata.get(session_id, {})
        
        return {
            "session_id": session_id,
            "message_count": len(history),
            "last_activity": metadata.get("last_activity"),
            "created_at": metadata.get("created_at"),
            "user_id": metadata.get("user_id")
        }


# Global conversation manager instance
conversation_manager = ConversationManager()