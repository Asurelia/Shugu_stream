"""Adapter LiveKit autour de `FasterWhisperSTT` (batch).

Permet d'exposer notre Whisper local sous l'interface `livekit.agents.stt.STT`
pour qu'un `VoicePipelineAgent` puisse l'utiliser comme n'importe quel
provider STT (Deepgram, AssemblyAI, etc.).

## Streaming VS batch

Notre `FasterWhisperSTT` est **batch-only** (on lui file un PCM16 complet,
il rend le transcript une fois). Pour du streaming, LiveKit fournit
`stt.StreamAdapter` qui wrappe une STT batch + un VAD (Silero par défaut)
pour découper les tours automatiquement.

## Usage

```python
from shugu.adapters.stt_streaming import FasterWhisperSTT, STTSettings
from shugu.adapters.stt_livekit_adapter import ShuguWhisperSTT

whisper = FasterWhisperSTT(STTSettings(model_name="base", language="fr"))
lk_stt = ShuguWhisperSTT(whisper)  # batch

# Pour VoicePipelineAgent (streaming) :
from livekit.plugins import silero
vad = silero.VAD.load()
streaming_stt = stt.StreamAdapter(stt=lk_stt, vad=vad)
```
"""
from __future__ import annotations

import structlog
from livekit.agents import stt, utils
from livekit.agents.stt import (
    SpeechData,
    SpeechEvent,
    SpeechEventType,
    STTCapabilities,
)

from ..core.errors import STTError
from .stt_streaming import FasterWhisperSTT

log = structlog.get_logger(__name__)


class ShuguWhisperSTT(stt.STT):
    """Adapter batch-STT. Offload Whisper sur un thread, pas d'interim transcripts.

    Le wrapping en streaming se fait via `stt.StreamAdapter` côté caller
    (voir docstring module). Ici on se contente de satisfaire l'interface
    `_recognize_impl`.
    """

    def __init__(
        self,
        whisper: FasterWhisperSTT,
        *,
        language: str = "fr",
    ) -> None:
        super().__init__(
            capabilities=STTCapabilities(streaming=False, interim_results=False),
        )
        self._whisper = whisper
        self._language = language

    async def _recognize_impl(
        self,
        buffer: utils.AudioBuffer,
        *,
        language=None,
        conn_options=None,  # noqa: ARG002 — requis par la signature mais inutile en local
    ) -> SpeechEvent:
        # `buffer` peut être un AudioFrame seul OU list[AudioFrame]. `combine_frames`
        # renvoie toujours un AudioFrame unique (concaténé).
        frame = utils.combine_frames(buffer)

        # Whisper attend du PCM16 mono. On suppose que LiveKit fournit déjà ce
        # format (c'est la norme du SDK). Si non, on laisse Whisper gérer la
        # conversion numpy côté FasterWhisperSTT.
        pcm: bytes = bytes(frame.data)
        sample_rate: int = int(frame.sample_rate)

        lang_in = language if isinstance(language, str) and language else self._language

        # Audit Pass 2 P1.B2 : avant ce raise, un crash Whisper (STTError)
        # générait silencieusement un FINAL_TRANSCRIPT vide — LiveKit le
        # considérait comme un transcript valide. Maintenant on raise pour
        # que LiveKit puisse remonter l'erreur en haut de la stack vocale
        # (le worker VIP est censé gérer les exceptions STT côté agents).
        try:
            text = await self._whisper.transcribe_pcm16(
                pcm,
                sample_rate=sample_rate,
                language=lang_in,
            )
        except STTError:
            log.warning("stt_lk.transcribe_failed_propagating")
            raise
        except Exception as exc:
            log.exception("stt_lk.unexpected_error", error=str(exc))
            raise STTError(f"livekit stt unexpected: {exc}") from exc

        return SpeechEvent(
            type=SpeechEventType.FINAL_TRANSCRIPT,
            alternatives=[
                SpeechData(
                    language=lang_in,
                    text=text or "",
                    confidence=1.0 if text else 0.0,
                ),
            ],
        )

    async def aclose(self) -> None:
        # Rien à fermer côté Whisper — le modèle reste chargé pour la vie du process.
        pass
