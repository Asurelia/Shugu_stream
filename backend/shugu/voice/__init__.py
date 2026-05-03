"""Voice realtime subsystem — LiveKit Agents + local AI inference.

Stack:
- LiveKit self-hosted (Docker, port 7880)
- Ollama + Gemma 4 26B-A4B (Vulkan AMD)
- whisper.cpp + Vulkan (STT)
- Piper TTS (CPU/ONNX)

See docs/setup/voice-realtime-windows-amd.md for the install guide.
"""
