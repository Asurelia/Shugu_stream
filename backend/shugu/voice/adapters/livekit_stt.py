"""LiveKit STT adapter — wraps WhisperSTT for AgentSession.

Adapter that exposes WhisperSTT (whisper.cpp subprocess) as a livekit-agents
STT base class so AgentSession can drive the pipeline natively.

AgentSession provides AudioBuffer (list[rtc.AudioFrame] | rtc.AudioFrame) per
utterance after VAD/endpointing. We resample 48 kHz → 16 kHz, concatenate,
call WhisperSTT.transcribe(), and return a single FINAL_TRANSCRIPT SpeechEvent.
"""
from __future__ import annotations

import uuid

from livekit import rtc
from livekit.agents import stt as agents_stt
from livekit.agents.language import LanguageCode
from livekit.agents.types import NOT_GIVEN, APIConnectOptions, NotGivenOr
from livekit.agents.utils import AudioBuffer

from ..stt_local import WhisperSTT

_INPUT_SAMPLE_RATE: int = 48_000
_OUTPUT_SAMPLE_RATE: int = WhisperSTT._WAV_SAMPLE_RATE  # 16_000


class LiveKitWhisperSTT(agents_stt.STT):
    """Adapter wrapping WhisperSTT to expose livekit-agents STT interface.

    AgentSession owns the audio-frames pipeline; this adapter is called per
    utterance with a buffer of PCM frames. We accumulate, resample 48k → 16k,
    transcribe via whisper-cli subprocess, and emit a single FINAL_TRANSCRIPT
    SpeechEvent.

    Capabilities: non-streaming, no interim results (whisper-cli is batch).
    """

    def __init__(self, whisper: WhisperSTT) -> None:
        super().__init__(
            capabilities=agents_stt.STTCapabilities(
                streaming=False,
                interim_results=False,
            ),
        )
        self._whisper = whisper

    async def _recognize_impl(
        self,
        buffer: AudioBuffer,
        *,
        language: NotGivenOr[str] = NOT_GIVEN,
        conn_options: APIConnectOptions,
    ) -> agents_stt.SpeechEvent:
        """Resample 48k → 16k mono, transcribe, emit FINAL_TRANSCRIPT."""
        frames: list[rtc.AudioFrame] = (
            buffer if isinstance(buffer, list) else [buffer]
        )

        if not frames:
            return _empty_speech_event()

        resampler = rtc.AudioResampler(
            input_rate=_INPUT_SAMPLE_RATE,
            output_rate=_OUTPUT_SAMPLE_RATE,
            num_channels=1,
        )

        frames_16k: list[rtc.AudioFrame] = []
        for frame in frames:
            frames_16k.extend(resampler.push(frame))
        frames_16k.extend(resampler.flush())

        if not frames_16k:
            return _empty_speech_event()

        combined = rtc.combine_audio_frames(frames_16k)
        pcm_bytes = bytes(combined.data)

        lang_str: str = language if isinstance(language, str) else "fr"
        text = await self._whisper.transcribe(pcm_bytes, language=lang_str)

        lc = LanguageCode(lang_str)
        return agents_stt.SpeechEvent(
            type=agents_stt.SpeechEventType.FINAL_TRANSCRIPT,
            request_id=str(uuid.uuid4()),
            alternatives=[
                agents_stt.SpeechData(language=lc, text=text or ""),
            ],
        )


def _empty_speech_event() -> agents_stt.SpeechEvent:
    """Return an empty FINAL_TRANSCRIPT event (no audio / no-op path)."""
    return agents_stt.SpeechEvent(
        type=agents_stt.SpeechEventType.FINAL_TRANSCRIPT,
        request_id=str(uuid.uuid4()),
        alternatives=[agents_stt.SpeechData(language=LanguageCode("fr"), text="")],
    )
