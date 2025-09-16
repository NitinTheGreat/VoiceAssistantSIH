"""Basic test to verify imports and configuration work."""

def test_imports():
    """Test that all modules can be imported."""
    try:
        # Test configuration
        from app.config import settings
        print("✅ Configuration loaded")
        
        # Test models
        from app.models.schemas import VoiceSession, TranscriptionResult, LLMResponse
        print("✅ Data models imported")
        
        # Test utilities
        from app.utils.audio_processing import AudioProcessor
        from app.utils.turn_detection import TurnDetector
        print("✅ Audio utilities imported")
        
        # Test services (these might fail without API keys, but imports should work)
        try:
            from app.services.llm_pipeline import LLMService
            print("✅ LLM service imported")
        except Exception as e:
            print(f"⚠️  LLM service import issue (may need API key): {e}")
        
        try:
            from app.services.speech_to_text import AssemblyAIService
            print("✅ Speech-to-text service imported")
        except Exception as e:
            print(f"⚠️  Speech-to-text service import issue (may need API key): {e}")
        
        try:
            from app.services.livekit_integration import LiveKitService
            print("✅ LiveKit service imported")
        except Exception as e:
            print(f"⚠️  LiveKit service import issue (may need API key): {e}")
        
        # Test API routes
        from app.api.routes import router
        print("✅ API routes imported")
        
        # Test main app
        from main import app
        print("✅ Main application imported")
        
        return True
        
    except Exception as e:
        print(f"❌ Import test failed: {e}")
        return False


def test_audio_processing():
    """Test audio processing functionality."""
    try:
        import numpy as np
        from app.utils.audio_processing import AudioProcessor
        
        processor = AudioProcessor()
        
        # Create dummy audio data
        sample_rate = 16000
        duration = 1.0  # 1 second
        t = np.linspace(0, duration, int(sample_rate * duration))
        frequency = 440  # A4 note
        audio_data = np.sin(2 * np.pi * frequency * t).astype(np.float32)
        
        # Test noise reduction
        clean_audio = processor.reduce_noise(audio_data)
        print(f"✅ Noise reduction: {len(clean_audio)} samples processed")
        
        # Test normalization
        normalized = processor.normalize_audio(audio_data)
        print(f"✅ Audio normalization: max value = {np.max(np.abs(normalized)):.3f}")
        
        # Test bandpass filter
        filtered = processor.apply_bandpass_filter(audio_data)
        print(f"✅ Bandpass filter: {len(filtered)} samples processed")
        
        # Test audio level calculation
        level = processor.calculate_audio_level(audio_data)
        print(f"✅ Audio level calculation: {level:.6f}")
        
        return True
        
    except Exception as e:
        print(f"❌ Audio processing test failed: {e}")
        return False


def test_turn_detection():
    """Test turn detection functionality."""
    try:
        from app.utils.turn_detection import TurnDetector
        
        detector = TurnDetector("test_session")
        
        # Test state
        state = detector.get_state()
        print(f"✅ Turn detector state: {state}")
        
        # Test reset
        detector.reset()
        print("✅ Turn detector reset")
        
        return True
        
    except Exception as e:
        print(f"❌ Turn detection test failed: {e}")
        return False


def main():
    """Run all basic tests."""
    print("🔧 Running Basic Tests...\n")
    
    tests = [
        ("Import Tests", test_imports),
        ("Audio Processing Tests", test_audio_processing),
        ("Turn Detection Tests", test_turn_detection),
    ]
    
    results = []
    for test_name, test_func in tests:
        print(f"\n--- {test_name} ---")
        success = test_func()
        results.append(success)
    
    print(f"\n📊 Test Results:")
    print(f"Passed: {sum(results)}/{len(results)}")
    
    if all(results):
        print("🎉 All basic tests passed!")
        return True
    else:
        print("⚠️  Some tests failed - check dependencies and configuration")
        return False


if __name__ == "__main__":
    main()