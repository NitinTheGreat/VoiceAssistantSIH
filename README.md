# VoiceAssistantSIH
Voice assistant backend for SIH hackathon project

The system processes user interactions through a sophisticated pipeline:

```plaintext
User Speech Input
       ↓
Audio Capture (LiveKit)
       ↓
Parallel Processing Branch
   ├── Contextual Filler Generation
   └── Speech-to-Text Conversion
       ↓
Context Compression & Analysis
       ↓
Personalization Engine Processing
       ↓
AI Response Generation (Gemini)
       ↓
Text-to-Speech Synthesis
       ↓
Audio Output & Transcript Logging
```