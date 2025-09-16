# Voice Assistant Backend - SIH Project

A comprehensive voice assistant backend for Smart India Hackathon (SIH) featuring real-time audio processing, speech-to-text, natural language understanding, and advanced audio features like turn detection and noise cancellation.

## 🚀 Features

- **Real-time Audio Communication** - LiveKit integration for low-latency audio streaming
- **Speech-to-Text** - AssemblyAI integration for accurate transcription
- **LLM Pipeline** - OpenAI GPT integration for natural language processing
- **Turn Detection** - Intelligent conversation flow management
- **Noise Cancellation** - Advanced audio preprocessing and enhancement
- **WebSocket Support** - Real-time bidirectional communication
- **Session Management** - Multi-user session handling
- **RESTful API** - Complete REST API for all functionality

## 🏗️ Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Client App    │────│  FastAPI Server │────│    LiveKit      │
│  (Frontend)     │    │   (Backend)     │    │   (Audio)       │
└─────────────────┘    └─────────────────┘    └─────────────────┘
                              │
                              ├─────────────────┐
                              │                 │
                    ┌─────────────────┐  ┌─────────────────┐
                    │   AssemblyAI    │  │     OpenAI      │
                    │     (STT)       │  │     (LLM)       │
                    └─────────────────┘  └─────────────────┘
```

## 📋 Prerequisites

- Python 3.8 or higher
- Redis (for session management)
- LiveKit server (for audio streaming)
- API keys for:
  - LiveKit
  - AssemblyAI
  - OpenAI

## 🛠️ Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/NitinTheGreat/VoiceAssistantSIH.git
   cd VoiceAssistantSIH
   ```

2. **Create virtual environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment**
   ```bash
   cp .env.example .env
   # Edit .env with your API keys and configuration
   ```

5. **Start the server**
   ```bash
   ./start.sh
   # Or manually: python main.py
   ```

## ⚙️ Configuration

Edit the `.env` file with your configuration:

```env
# LiveKit Configuration
LIVEKIT_API_KEY=your_livekit_api_key
LIVEKIT_API_SECRET=your_livekit_api_secret
LIVEKIT_WS_URL=wss://your_livekit_url

# AssemblyAI Configuration
ASSEMBLYAI_API_KEY=your_assemblyai_api_key

# OpenAI Configuration
OPENAI_API_KEY=your_openai_api_key

# Redis Configuration
REDIS_URL=redis://localhost:6379

# Server Configuration
HOST=0.0.0.0
PORT=8000
DEBUG=true

# Audio Processing Configuration
SAMPLE_RATE=16000
CHUNK_SIZE=1024
NOISE_REDUCTION_STRENGTH=0.5
VAD_AGGRESSIVENESS=2
```

## 📚 API Documentation

### REST Endpoints

#### Create Session
```http
POST /api/v1/sessions
Content-Type: application/json

{
  "user_id": "optional_user_id"
}
```

#### Get Session Info
```http
GET /api/v1/sessions/{session_id}
```

#### End Session
```http
DELETE /api/v1/sessions/{session_id}
```

#### Process Text Input
```http
POST /api/v1/sessions/{session_id}/process
Content-Type: application/json

{
  "text_input": "Hello, how are you?"
}
```

### WebSocket Connection

Connect to the WebSocket for real-time communication:

```javascript
const ws = new WebSocket('ws://localhost:8000/api/v1/sessions/{session_id}/ws');

// Send audio data
ws.send(audioBuffer);

// Send commands
ws.send(JSON.stringify({
  "command": "start_transcription"
}));

// Receive responses
ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log('Received:', data);
};
```

## 🔧 Core Components

### Audio Processing Pipeline

```python
from app.utils.audio_processing import AudioProcessor

processor = AudioProcessor()

# Process audio chunk
processed_audio, has_voice, audio_level = processor.process_audio_chunk(audio_data)
```

### Turn Detection

```python
from app.utils.turn_detection import conversation_manager

# Create session
detector = conversation_manager.create_session(session_id)

# Process audio
turn_state = await detector.process_audio_level(audio_level, has_voice)
```

### Speech-to-Text

```python
from app.services.speech_to_text import assemblyai_service

# Start real-time transcription
await assemblyai_service.start_transcription(session_id)

# Send audio data
await assemblyai_service.send_audio(audio_data, session_id)
```

### LLM Pipeline

```python
from app.services.llm_pipeline import conversation_manager

# Process user input
response = await conversation_manager.process_user_input(session_id, user_text)
```

## 🎯 Usage Examples

### Basic Voice Session

```python
import asyncio
from app.services.livekit_integration import livekit_session_manager

async def create_voice_session():
    session = await livekit_session_manager.create_voice_session(
        session_id="example_session",
        user_id="user123"
    )
    print(f"Session created: {session.session_id}")
```

### Audio Processing

```python
from app.utils.audio_processing import AudioProcessor

processor = AudioProcessor()

# Apply noise reduction
clean_audio = processor.reduce_noise(noisy_audio_array)

# Detect voice activity
has_voice = processor.detect_voice_activity(audio_chunk)
```

## 🧪 Testing

Run the health check to verify all services:

```bash
curl http://localhost:8000/api/v1/health
```

Expected response:
```json
{
  "status": "healthy",
  "timestamp": "2024-01-01T12:00:00",
  "services": {
    "livekit": "available",
    "assemblyai": "available", 
    "llm": "available"
  }
}
```

## 📦 Project Structure

```
VoiceAssistantSIH/
├── app/
│   ├── api/
│   │   ├── __init__.py
│   │   └── routes.py          # API endpoints
│   ├── models/
│   │   ├── __init__.py
│   │   └── schemas.py         # Pydantic models
│   ├── services/
│   │   ├── __init__.py
│   │   ├── livekit_integration.py
│   │   ├── speech_to_text.py
│   │   └── llm_pipeline.py
│   ├── utils/
│   │   ├── __init__.py
│   │   ├── audio_processing.py
│   │   ├── turn_detection.py
│   │   └── logging.py
│   ├── __init__.py
│   └── config.py              # Configuration management
├── logs/                      # Application logs
├── .env.example               # Environment template
├── .gitignore
├── main.py                    # FastAPI application
├── requirements.txt           # Dependencies
├── start.sh                   # Startup script
└── README.md
```

## 🚀 Deployment

### Docker Deployment

1. Create `Dockerfile`:
```dockerfile
FROM python:3.9-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
EXPOSE 8000

CMD ["python", "main.py"]
```

2. Build and run:
```bash
docker build -t voice-assistant .
docker run -p 8000:8000 voice-assistant
```

### Production Considerations

- Set up proper logging and monitoring
- Configure CORS appropriately
- Use environment-specific configurations
- Implement rate limiting
- Set up SSL/TLS for HTTPS
- Configure Redis for session persistence
- Set up health checks and auto-scaling

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- [LiveKit](https://livekit.io/) for real-time communication
- [AssemblyAI](https://www.assemblyai.com/) for speech-to-text
- [OpenAI](https://openai.com/) for language models
- [FastAPI](https://fastapi.tiangolo.com/) for the web framework

## 📞 Support

For support and questions:
- Create an issue on GitHub
- Contact the development team
- Check the documentation at `/docs` endpoint

---

Built with ❤️ for Smart India Hackathon 2024
