"""ElevenLabs TTS. Returns MP3 bytes + approximate duration_ms."""
from __future__ import annotations

import httpx

from ..config import Settings
from ..core.errors import TTSError
from ..core.protocols import TTSResult


def _estimate_mp3_duration_ms(mp3: bytes) -> int:
    """Coarse MP3 duration estimate — parses first frame header.

    Good enough for picker sync. A 20% over-estimate is fine (we wait a bit longer
    between performances). For exact timing we'd need a decoder or rely on the
    client's `performance.end` ACK, but we keep it server-side to avoid RTT drift.
    """
    # Find first MP3 frame sync (0xFFE0..0xFFFF in first 2 bytes)
    for i in range(len(mp3) - 3):
        if mp3[i] == 0xFF and (mp3[i+1] & 0xE0) == 0xE0:
            header = int.from_bytes(mp3[i:i+4], "big")
            # version_id (bits 19-20), layer (17-18), bitrate_idx (12-15), sample_rate_idx (10-11)
            version_id = (header >> 19) & 0x3
            layer = (header >> 17) & 0x3
            bitrate_idx = (header >> 12) & 0xF
            sample_rate_idx = (header >> 10) & 0x3
            if bitrate_idx == 0 or bitrate_idx == 0xF or sample_rate_idx == 0x3:
                continue
            # MPEG 1 Layer III bitrate table
            bitrate_table = [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320]
            sample_rate_table_v1 = [44100, 48000, 32000]
            sample_rate_table_v2 = [22050, 24000, 16000]
            if version_id == 3:       # MPEG 1
                sample_rate = sample_rate_table_v1[sample_rate_idx]
            else:
                sample_rate = sample_rate_table_v2[sample_rate_idx]
            bitrate_kbps = bitrate_table[bitrate_idx]
            if bitrate_kbps == 0:
                continue
            bitrate_bps = bitrate_kbps * 1000
            duration_s = (len(mp3) * 8) / bitrate_bps
            return int(duration_s * 1000)
    # Fallback: rough estimate at 128 kbps
    return int((len(mp3) * 8 / 128_000) * 1000)


class ElevenLabsTTS:
    def __init__(self, settings: Settings, http: httpx.AsyncClient):
        self._settings = settings
        self._http = http

    async def synthesize(self, text: str, *, voice_id: str) -> TTSResult:
        vid = voice_id or self._settings.shugu_voice_id
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{vid}"
        payload = {
            "text": text,
            "model_id": self._settings.elevenlabs_model_id,
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75, "speed": 1.0},
        }
        try:
            resp = await self._http.post(
                url,
                headers={
                    "xi-api-key": self._settings.elevenlabs_api_key,
                    "Content-Type": "application/json",
                    "Accept": "audio/mpeg",
                },
                json=payload,
                timeout=90.0,
            )
            resp.raise_for_status()
            audio = resp.content
        except httpx.HTTPError as exc:
            raise TTSError(f"elevenlabs: {exc}") from exc
        return TTSResult(audio=audio, mime="audio/mpeg", duration_ms=_estimate_mp3_duration_ms(audio))
