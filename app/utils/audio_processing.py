"""Audio processing utilities for noise cancellation and audio enhancement."""

import numpy as np
import librosa
import noisereduce as nr
import webrtcvad
from scipy import signal
from typing import Tuple, Optional
import io
from pydub import AudioSegment
import soundfile as sf

from app.config import settings


class AudioProcessor:
    """Audio processing utility class for noise cancellation and enhancement."""
    
    def __init__(self):
        self.sample_rate = settings.sample_rate
        self.vad = webrtcvad.Vad(settings.vad_aggressiveness)
        
    def reduce_noise(self, audio_data: np.ndarray, noise_strength: float = None) -> np.ndarray:
        """
        Apply noise reduction to audio data using spectral gating.
        
        Args:
            audio_data: Audio signal as numpy array
            noise_strength: Noise reduction strength (0.0 to 1.0)
            
        Returns:
            Noise-reduced audio signal
        """
        if noise_strength is None:
            noise_strength = settings.noise_reduction_strength
            
        # Apply noise reduction
        reduced_audio = nr.reduce_noise(
            y=audio_data,
            sr=self.sample_rate,
            prop_decrease=noise_strength
        )
        
        return reduced_audio
    
    def normalize_audio(self, audio_data: np.ndarray) -> np.ndarray:
        """
        Normalize audio to prevent clipping and ensure consistent levels.
        
        Args:
            audio_data: Audio signal as numpy array
            
        Returns:
            Normalized audio signal
        """
        # Normalize to [-1, 1] range
        max_val = np.max(np.abs(audio_data))
        if max_val > 0:
            normalized = audio_data / max_val
        else:
            normalized = audio_data
            
        return normalized
    
    def apply_bandpass_filter(self, audio_data: np.ndarray, 
                            low_freq: float = 300, high_freq: float = 3400) -> np.ndarray:
        """
        Apply bandpass filter to focus on speech frequencies.
        
        Args:
            audio_data: Audio signal as numpy array
            low_freq: Low cutoff frequency in Hz
            high_freq: High cutoff frequency in Hz
            
        Returns:
            Filtered audio signal
        """
        nyquist = self.sample_rate / 2
        low = low_freq / nyquist
        high = high_freq / nyquist
        
        b, a = signal.butter(4, [low, high], btype='band')
        filtered_audio = signal.filtfilt(b, a, audio_data)
        
        return filtered_audio
    
    def detect_voice_activity(self, audio_chunk: bytes, 
                            frame_duration: int = 30) -> bool:
        """
        Detect voice activity in audio chunk using WebRTC VAD.
        
        Args:
            audio_chunk: Raw audio bytes
            frame_duration: Frame duration in ms (10, 20, or 30)
            
        Returns:
            True if voice activity detected, False otherwise
        """
        try:
            # Convert bytes to proper format for VAD
            audio_segment = AudioSegment(
                data=audio_chunk,
                sample_width=2,  # 16-bit
                frame_rate=self.sample_rate,
                channels=1
            )
            
            # Ensure we have the right frame size
            frame_size = int(self.sample_rate * frame_duration / 1000)
            frames = [audio_segment[i:i+frame_duration] 
                     for i in range(0, len(audio_segment), frame_duration)]
            
            voice_frames = 0
            total_frames = 0
            
            for frame in frames:
                if len(frame.raw_data) == frame_size * 2:  # 16-bit = 2 bytes
                    is_voice = self.vad.is_speech(frame.raw_data, self.sample_rate)
                    if is_voice:
                        voice_frames += 1
                    total_frames += 1
            
            if total_frames == 0:
                return False
                
            # Return True if more than 30% of frames contain voice
            return (voice_frames / total_frames) > 0.3
            
        except Exception:
            return False
    
    def calculate_audio_level(self, audio_data: np.ndarray) -> float:
        """
        Calculate RMS audio level.
        
        Args:
            audio_data: Audio signal as numpy array
            
        Returns:
            RMS audio level
        """
        return np.sqrt(np.mean(audio_data ** 2))
    
    def convert_audio_format(self, audio_data: bytes, 
                           input_format: str = "wav",
                           output_format: str = "wav") -> bytes:
        """
        Convert audio between different formats.
        
        Args:
            audio_data: Input audio bytes
            input_format: Input audio format
            output_format: Output audio format
            
        Returns:
            Converted audio bytes
        """
        # Load audio using pydub
        audio_segment = AudioSegment.from_file(
            io.BytesIO(audio_data), 
            format=input_format
        )
        
        # Ensure mono and correct sample rate
        audio_segment = audio_segment.set_channels(1).set_frame_rate(self.sample_rate)
        
        # Export in desired format
        output_buffer = io.BytesIO()
        audio_segment.export(output_buffer, format=output_format)
        
        return output_buffer.getvalue()
    
    def process_audio_chunk(self, audio_chunk: bytes) -> Tuple[np.ndarray, bool, float]:
        """
        Complete audio processing pipeline for a single chunk.
        
        Args:
            audio_chunk: Raw audio bytes
            
        Returns:
            Tuple of (processed_audio, has_voice, audio_level)
        """
        # Convert to numpy array
        audio_data, _ = librosa.load(
            io.BytesIO(audio_chunk), 
            sr=self.sample_rate, 
            mono=True
        )
        
        # Apply noise reduction
        audio_data = self.reduce_noise(audio_data)
        
        # Apply bandpass filter
        audio_data = self.apply_bandpass_filter(audio_data)
        
        # Normalize
        audio_data = self.normalize_audio(audio_data)
        
        # Detect voice activity
        has_voice = self.detect_voice_activity(audio_chunk)
        
        # Calculate audio level
        audio_level = self.calculate_audio_level(audio_data)
        
        return audio_data, has_voice, audio_level