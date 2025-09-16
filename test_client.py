"""Example client for testing Voice Assistant backend."""

import asyncio
import aiohttp
import json
import websockets
from typing import Dict, Any


class VoiceAssistantClient:
    """Simple client for interacting with the Voice Assistant backend."""
    
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.api_base = f"{base_url}/api/v1"
        self.session_id: str = None
        
    async def create_session(self, user_id: str = None) -> Dict[str, Any]:
        """Create a new voice session."""
        async with aiohttp.ClientSession() as session:
            payload = {}
            if user_id:
                payload["user_id"] = user_id
                
            async with session.post(
                f"{self.api_base}/sessions",
                json=payload
            ) as response:
                result = await response.json()
                self.session_id = result.get("session_id")
                return result
    
    async def get_session_info(self) -> Dict[str, Any]:
        """Get session information."""
        if not self.session_id:
            raise ValueError("No active session")
            
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{self.api_base}/sessions/{self.session_id}"
            ) as response:
                return await response.json()
    
    async def process_text(self, text: str) -> Dict[str, Any]:
        """Process text input through the LLM."""
        if not self.session_id:
            raise ValueError("No active session")
            
        async with aiohttp.ClientSession() as session:
            payload = {
                "session_id": self.session_id,
                "text_input": text
            }
            
            async with session.post(
                f"{self.api_base}/sessions/{self.session_id}/process",
                json=payload
            ) as response:
                return await response.json()
    
    async def connect_websocket(self):
        """Connect to WebSocket for real-time communication."""
        if not self.session_id:
            raise ValueError("No active session")
            
        ws_url = f"ws://localhost:8000/api/v1/sessions/{self.session_id}/ws"
        
        try:
            async with websockets.connect(ws_url) as websocket:
                print(f"Connected to WebSocket: {ws_url}")
                
                # Send a test command
                test_command = {
                    "command": "get_state"
                }
                await websocket.send(json.dumps(test_command))
                
                # Listen for responses
                try:
                    while True:
                        message = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                        data = json.loads(message)
                        print(f"Received: {data}")
                        
                except asyncio.TimeoutError:
                    print("WebSocket timeout - connection working!")
                    
        except Exception as e:
            print(f"WebSocket connection failed: {e}")
    
    async def end_session(self) -> Dict[str, Any]:
        """End the current session."""
        if not self.session_id:
            raise ValueError("No active session")
            
        async with aiohttp.ClientSession() as session:
            async with session.delete(
                f"{self.api_base}/sessions/{self.session_id}"
            ) as response:
                result = await response.json()
                self.session_id = None
                return result
    
    async def health_check(self) -> Dict[str, Any]:
        """Check backend health."""
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{self.api_base}/health") as response:
                return await response.json()


async def test_voice_assistant():
    """Test the voice assistant functionality."""
    print("🚀 Testing Voice Assistant Backend...")
    
    client = VoiceAssistantClient()
    
    try:
        # Health check
        print("\n1. Health Check...")
        health = await client.health_check()
        print(f"✅ Health Status: {health['status']}")
        
        # Create session
        print("\n2. Creating Session...")
        session_result = await client.create_session("test_user")
        print(f"✅ Session Created: {session_result['session_id']}")
        
        # Get session info
        print("\n3. Getting Session Info...")
        session_info = await client.get_session_info()
        print(f"✅ Session Status: {session_info['session']['status']}")
        
        # Process text input
        print("\n4. Processing Text Input...")
        response = await client.process_text("Hello, how are you?")
        print(f"✅ LLM Response: {response.get('llm_response', 'No response')}")
        
        # Test WebSocket connection
        print("\n5. Testing WebSocket Connection...")
        await client.connect_websocket()
        
        # End session
        print("\n6. Ending Session...")
        end_result = await client.end_session()
        print(f"✅ Session Ended: {end_result['status']}")
        
        print("\n🎉 All tests completed successfully!")
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        
        # Try to cleanup
        try:
            if client.session_id:
                await client.end_session()
        except:
            pass


if __name__ == "__main__":
    asyncio.run(test_voice_assistant())