"""Microsoft Edge TTS — free, no API key. Fallback when ElevenLabs is down/over-quota.

edge-tts emits MP3 directly and streams natively via `communicate.stream()`,
so both `synthesize()` (blob) and `synthesize_stream()` are cheap — the former
aggregates, the latter passes chunks through. Same duration-estimate helper
as ElevenLabsTTS.
"""
from __future__ import annotations

from typing import AsyncIterator

import edge_tts

from ..core.errors import TTSError
from ..core.protocols import TTSChunk, TTSResult
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
        voice = self._resolve_voice(voice_id)
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

    async def synthesize_stream(
        self, text: str, *, voice_id: str,
    ) -> AsyncIterator[TTSChunk]:
        """Pass-through streaming: yields edge-tts audio chunks as they arrive."""
        voice = self._resolve_voice(voice_id)
        try:
            communicate = edge_tts.Communicate(text, voice)
            seq = 0
            buffer: list[bytes] = []
            async for ev in communicate.stream():
                if ev.get("type") == "audio":
                    data = ev["data"]
                    if not data:
                        continue
                    buffer.append(data)
                    # Emit on every ~8KB to give the client continuous feed
                    # without drowning it in micro-chunks. edge-tts chunks are
                    # usually 1-4KB each, so this coalesces 2-8 of them.
                    if sum(len(b) for b in buffer) >= 8192:
                        yield TTSChunk(payload=b"".join(buffer), seq=seq, final=False, mime="audio/mpeg")
                        seq += 1
                        buffer.clear()
            if buffer:
                yield TTSChunk(payload=b"".join(buffer), seq=seq, final=True, mime="audio/mpeg")
            else:
                # Make sure we always emit a final marker, even if empty.
                yield TTSChunk(payload=b"", seq=seq, final=True, mime="audio/mpeg")
        except Exception as exc:
            raise TTSError(f"edge-tts: {exc}") from exc

    @classmethod
    def _resolve_voice(cls, voice_id: str) -> str:
        return voice_id if voice_id and "-" in voice_id and "Neural" in voice_id else cls.DEFAULT_VOICE
