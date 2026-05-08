"""LiveKit TTS adapter — wraps PiperTTS for AgentSession.

Adapter that exposes PiperTTS (piper.exe subprocess) as a livekit-agents TTS
base class so AgentSession can drive the pipeline natively.

ChunkedStream._run receives an AudioEmitter that AgentSession uses to push
audio frames to the room. We call PiperTTS.synthesize(), then feed the raw
PCM blob to AudioEmitter (raw PCM path, mime_type="audio/pcm") so
AudioEmitter's internal AudioByteStream handles chunking into fixed-size
frames at the correct sample rate.
"""
from __future__ import annotations

import uuid

from livekit.agents import tts as agents_tts
from livekit.agents.types import APIConnectOptions

from ..tts_local import PiperTTS

_DEFAULT_CONN_OPTIONS = APIConnectOptions()


class _PiperChunkedStream(agents_tts.ChunkedStream):
    """Streams Piper PCM output to AgentSession AudioEmitter.

    Pushes the full PCM blob to AudioEmitter with mime_type="audio/pcm" so
    AudioEmitter's internal AudioByteStream handles frame splitting (200ms
    default). end_input() signals completion; AgentSession iterates frames.
    """

    def __init__(
        self,
        tts: agents_tts.TTS,
        input_text: str,
        conn_options: APIConnectOptions,
    ) -> None:
        super().__init__(tts=tts, input_text=input_text, conn_options=conn_options)
        self._piper: PiperTTS = tts._piper  # type: ignore[attr-defined]

    async def _run(self, output_emitter: agents_tts.AudioEmitter) -> None:
        """Synthesize via Piper, push raw PCM to AudioEmitter."""
        pcm = await self._piper.synthesize(self.input_text)
        output_emitter.initialize(
            request_id=str(uuid.uuid4()),
            sample_rate=LiveKitPiperTTS.NATIVE_SAMPLE_RATE,
            num_channels=1,
            mime_type="audio/pcm",
        )
        if not pcm:
            return
        output_emitter.push(pcm)


class LiveKitPiperTTS(agents_tts.TTS):
    """Adapter wrapping PiperTTS for livekit-agents AgentSession.

    Exposes PiperTTS one-shot synthesis as a ChunkedStream so AgentSession
    can iterate audio frames and push them to the room AudioSource.
    """

    NATIVE_SAMPLE_RATE: int = PiperTTS.NATIVE_SAMPLE_RATE  # 22_050

    def __init__(self, piper: PiperTTS) -> None:
        super().__init__(
            capabilities=agents_tts.TTSCapabilities(streaming=False),
            sample_rate=self.NATIVE_SAMPLE_RATE,
            num_channels=1,
        )
        self._piper = piper

    def synthesize(
        self,
        text: str,
        *,
        conn_options: APIConnectOptions = _DEFAULT_CONN_OPTIONS,
    ) -> agents_tts.ChunkedStream:
        """Return ChunkedStream — AgentSession iterates and pushes to AudioSource."""
        return _PiperChunkedStream(tts=self, input_text=text, conn_options=conn_options)
