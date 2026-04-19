"""Streaming STT via faster-whisper + webrtcvad.

Operator voice duplex flow:
  client mic → 16kHz mono PCM frames (20ms each) → WebSocket → this module
  → webrtcvad (voice activity detector) → accumulate speech → run Whisper
  → final transcript (fed to HermesEmbodiedBrain)

MiniMax has no open ASR, so we run Whisper locally. `small` is the default
because it handles French well (WER ~8-10%) while staying CPU-friendly for
a VPS without GPU. The model is loaded lazily on first transcription and
cached for the process lifetime.

VAD is used for turn segmentation (when is the operator done speaking?) and
for barge-in detection (is the operator starting to speak while Shugu talks?).
We keep the two uses separate — see voice_duplex.py for the state machine.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Optional

import structlog


log = structlog.get_logger(__name__)


# Valid frame lengths for webrtcvad at 16kHz: 10, 20, 30 ms → 160, 320, 480 samples
# (320 bytes, 640 bytes, 960 bytes of int16 PCM).
VAD_SAMPLE_RATE = 16000
VAD_FRAME_MS = 20
VAD_FRAME_BYTES = int(VAD_SAMPLE_RATE * (VAD_FRAME_MS / 1000) * 2)  # 640 for 20ms @ 16kHz int16


@dataclass(slots=True)
class STTSettings:
    model_name: str = "small"           # tiny | base | small | medium | large-v3
    compute_type: str = "int8"          # int8 | int8_float16 | float16 | float32
    device: str = "auto"                # auto | cpu | cuda
    language: str = "fr"                # ISO code; None = auto-detect
    beam_size: int = 3                  # lower = faster, less accurate
    vad_aggressiveness: int = 2         # 0..3 — 3 is the most aggressive (fewer false positives)


class FasterWhisperSTT:
    """Wraps faster-whisper with lazy model loading + VAD helpers.

    Thread note: the underlying CTranslate2 model is safe to call from a
    worker thread (we offload via `asyncio.to_thread`). We never call it
    twice concurrently — the state machine serializes turns.
    """

    def __init__(self, settings: STTSettings | None = None):
        self._settings = settings or STTSettings()
        self._model = None                # lazy
        self._model_lock = asyncio.Lock()
        self._vad = None                  # lazy

    async def _ensure_model(self):
        if self._model is not None:
            return
        async with self._model_lock:
            if self._model is not None:
                return
            log.info("stt.loading_model",
                     name=self._settings.model_name,
                     compute_type=self._settings.compute_type,
                     device=self._settings.device)
            from faster_whisper import WhisperModel
            self._model = await asyncio.to_thread(
                WhisperModel,
                self._settings.model_name,
                device=self._settings.device,
                compute_type=self._settings.compute_type,
            )
            log.info("stt.model_ready")

    def _ensure_vad(self):
        if self._vad is None:
            import webrtcvad
            self._vad = webrtcvad.Vad(self._settings.vad_aggressiveness)
        return self._vad

    def is_speech(self, frame_pcm16: bytes) -> bool:
        """Return True if a 20ms frame (16kHz mono int16 PCM) contains speech."""
        if len(frame_pcm16) != VAD_FRAME_BYTES:
            # Tolerant: try 30ms (960 bytes) or 10ms (320 bytes) if exactly matched.
            if len(frame_pcm16) not in (320, 640, 960):
                return False
        vad = self._ensure_vad()
        try:
            return vad.is_speech(frame_pcm16, VAD_SAMPLE_RATE)
        except Exception:   # webrtcvad is picky about frame length
            return False

    async def transcribe_pcm16(
        self,
        pcm: bytes,
        *,
        sample_rate: int = VAD_SAMPLE_RATE,
        language: Optional[str] = None,
    ) -> str:
        """Transcribe a raw 16-bit mono PCM buffer. Returns '' for short/empty input."""
        # Need at least ~250ms of audio to be worth a pass — otherwise noise.
        min_bytes = int(sample_rate * 0.25 * 2)
        if len(pcm) < min_bytes:
            return ""

        await self._ensure_model()
        lang = language or self._settings.language

        def _run() -> str:
            import numpy as np
            audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
            segments, _info = self._model.transcribe(  # type: ignore[union-attr]
                audio,
                language=lang,
                beam_size=self._settings.beam_size,
                vad_filter=False,           # we already did VAD upstream
                condition_on_previous_text=False,
                no_speech_threshold=0.4,
            )
            return " ".join(s.text.strip() for s in segments if s.text).strip()

        try:
            text = await asyncio.to_thread(_run)
        except Exception as exc:
            log.exception("stt.transcribe_error", error=str(exc))
            return ""
        return text
