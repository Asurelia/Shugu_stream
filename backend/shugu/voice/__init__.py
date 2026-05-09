"""Voice realtime subsystem — LiveKit Agents + local AI inference.

Stack:
- LiveKit self-hosted (Docker, port 7880)
- Ollama + Gemma 4 26B-A4B (Vulkan AMD)
- whisper.cpp + Vulkan (STT)
- Piper TTS (CPU/ONNX)

See docs/setup/voice-realtime-windows-amd.md for the install guide.
"""
from .audio_bridge import AudioBridge
from .livekit_publisher import LiveKitPublisher
from .tts_local import LocalTTS, PiperTTS

__all__ = [
    "AudioBridge",
    "LiveKitPublisher",
    "LocalTTS",
    "PiperTTS",
]
