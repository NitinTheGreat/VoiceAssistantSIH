"""Configuration management for the Voice Assistant backend."""

import os
from pydantic import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Server Configuration
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False
    
    # LiveKit Configuration
    livekit_api_key: str
    livekit_api_secret: str
    livekit_ws_url: str
    
    # AssemblyAI Configuration
    assemblyai_api_key: str
    
    # OpenAI Configuration
    openai_api_key: str
    
    # Redis Configuration
    redis_url: str = "redis://localhost:6379"
    
    # Audio Processing Configuration
    sample_rate: int = 16000
    chunk_size: int = 1024
    noise_reduction_strength: float = 0.5
    vad_aggressiveness: int = 2
    
    # Turn Detection Configuration
    silence_threshold: float = 0.01
    min_speech_duration: float = 0.5
    max_silence_duration: float = 2.0
    
    class Config:
        env_file = ".env"
        case_sensitive = False


# Global settings instance
settings = Settings()