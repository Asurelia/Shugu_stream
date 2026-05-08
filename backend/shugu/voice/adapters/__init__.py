"""livekit-agents adapter layer for Shugu local STT/TTS/LLM components.

PR3 Voie A: wraps WhisperSTT, PiperTTS, LocalLLM into livekit-agents
base classes so AgentSession can own the full pipeline when
voice_use_agentsession=True.
"""
from .livekit_llm import LiveKitLocalLLM
from .livekit_stt import LiveKitWhisperSTT
from .livekit_tts import LiveKitPiperTTS

__all__ = ["LiveKitWhisperSTT", "LiveKitPiperTTS", "LiveKitLocalLLM"]
