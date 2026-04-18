"""Microsoft Edge TTS — free, no API key. Fallback when ElevenLabs is down/over-quota.

edge-tts emits MP3 directly. Same duration-estimate helper as ElevenLabsTTS.
"""
from __future__ import annotations

import edge_tts

from ..core.errors import TTSError
from ..core.protocols import TTSResult
from .tts_elevenlabs import _estimate_mp3_duration_ms


class EdgeTTS:
    """`voice_id` here is an Edge voice name e.g. `fr-FR-DeniseNeural`.

    French voices that work well for Shugu:
      fr-FR-DeniseNeural   (female)
      fr-FR-VivienneMultilingualNeural (female, multilingual)
      fr-FR-HenriNeural    (male)
    """

    DEFAULT_VOICE = "fr-FR-VivienneMultilingualNeural"

    async def synthesize(self, text: str, *, voice_id: str) -> TTSResult:
        voice = voice_id if voice_id and "-" in voice_id and "Neural" in voice_id else self.DEFAULT_VOICE
        try:
            communicate = edge_tts.Communicate(text, voice)
            chunks: list[bytes] = []
            async for ev in communicate.stream():
                if ev.get("type") == "audio":
                    chunks.append(ev["data"])
            audio = b"".join(chunks)
        except Exception as exc:
            raise TTSError(f"edge-tts: {exc}") from exc
        if not audio:
            raise TTSError("edge-tts: empty audio")
        return TTSResult(audio=audio, mime="audio/mpeg", duration_ms=_estimate_mp3_duration_ms(audio))
