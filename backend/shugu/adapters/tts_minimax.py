"""MiniMax TTS — speech-2.8-hd with French system voices.

API: POST https://api.minimax.io/v1/t2a_v2, Bearer auth, audio returned as hex
string under `data.audio`. Included in the user's MiniMax subscription (max-highspeed).
"""
from __future__ import annotations

import binascii

import httpx

from ..config import Settings
from ..core.errors import TTSError
from ..core.protocols import TTSResult
from .tts_elevenlabs import _estimate_mp3_duration_ms


class MiniMaxTTS:
    """Default voice = `French_MovieLeadFemale` (cinematic young adult FR).

    Emotion can be set per-call via `emotion` kwarg on synthesize, but the
    TTSAdapter protocol is emotion-agnostic — we default to "calm" and let
    the avatar's blendshape carry the emotional signal.
    """

    DEFAULT_VOICE = "French_MovieLeadFemale"

    def __init__(self, settings: Settings, http: httpx.AsyncClient):
        self._settings = settings
        self._http = http

    async def synthesize(self, text: str, *, voice_id: str) -> TTSResult:
        vid = voice_id or self._settings.minimax_voice_id or self.DEFAULT_VOICE
        payload = {
            "model": self._settings.minimax_tts_model,
            "text": text,
            "stream": False,
            "language_boost": "French",
            "voice_setting": {
                "voice_id": vid,
                "speed": self._settings.minimax_tts_speed,
                "emotion": "happy",
            },
            "audio_setting": {
                "format": "mp3",
                "sample_rate": 32000,
                "bitrate": 128000,
                "channel": 1,
            },
        }
        try:
            resp = await self._http.post(
                f"{self._settings.minimax_base_url}/t2a_v2",
                headers={"Authorization": f"Bearer {self._settings.minimax_api_key}",
                         "Content-Type": "application/json"},
                json=payload,
                timeout=90.0,
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as exc:
            raise TTSError(f"minimax: {exc}") from exc

        status = data.get("base_resp", {})
        if status.get("status_code") != 0:
            raise TTSError(f"minimax: {status.get('status_msg', 'unknown error')}")

        audio_hex = data.get("data", {}).get("audio", "")
        if not audio_hex:
            raise TTSError("minimax: empty audio")
        try:
            audio = binascii.unhexlify(audio_hex)
        except (binascii.Error, ValueError) as exc:
            raise TTSError(f"minimax: bad hex ({exc})") from exc

        return TTSResult(audio=audio, mime="audio/mpeg", duration_ms=_estimate_mp3_duration_ms(audio))
