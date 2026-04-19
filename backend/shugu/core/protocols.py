"""Core protocols — the modular seams of the app.

Every adapter (brain, TTS, STT, moderation) conforms to one of these.
Adding a new implementation = one file under `adapters/` + one entry in
`app.py`'s dependency wiring. No other file changes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import AsyncIterator, Literal, Optional, Protocol

from .identity import Identity


Emotion = Literal["neutral", "happy", "angry", "sad", "relaxed"]


@dataclass(slots=True)
class Turn:
    role: Literal["user", "assistant"]
    content: str


@dataclass(slots=True)
class BrainDelta:
    """One streamed token chunk from a brain."""
    text: str
    done: bool = False


@dataclass(slots=True)
class TTSResult:
    audio: bytes
    mime: str              # "audio/mpeg" | "audio/wav"
    duration_ms: int
    # Optional viseme timing (ElevenLabs alignment). None = Web Audio RMS lip-sync on client.
    visemes: Optional[list[dict]] = None


@dataclass(slots=True)
class TTSChunk:
    """One streaming audio chunk from a TTS backend.

    `payload` is raw audio bytes matching `mime`. The very first chunk must be
    self-describing (contains MP3 frame header or AAC ADTS) so the client's
    Media Source Extensions SourceBuffer can start decoding immediately.
    `seq` is 0-indexed and strictly increasing. `final=True` signals the last
    chunk of this synthesis — the client ends the MSE segment + closes.
    """
    payload: bytes
    seq: int
    final: bool = False
    mime: str = "audio/mpeg"


@dataclass(slots=True)
class ModerationVerdict:
    allowed: bool
    reason: str = ""
    detector: str = ""
    rewrite_to: Optional[str] = None   # if populated, pipeline uses this instead


@dataclass(slots=True)
class PersonalityDoc:
    system_prompt: str
    voice_id: str
    style_hints: dict = field(default_factory=dict)
    mtime: float = 0.0


class BrainAdapter(Protocol):
    """LLM backend. Implementations: ShuguPersonaBrain (MiniMax persona),
    HermesAgentBrain (HTTP to Hermes api_server), FilterBrain (MiniMax + filter prompt)."""
    name: str

    async def respond(
        self,
        *,
        prompt: str,
        history: list[Turn],
        identity: Identity,
    ) -> AsyncIterator[BrainDelta]:
        """Stream response deltas. Raises BrainError on upstream failure."""
        ...


class TTSAdapter(Protocol):
    """Text → audio. v1 returns whole blob (client does lip-sync)."""

    async def synthesize(self, text: str, *, voice_id: str) -> TTSResult: ...


class TTSStreamAdapter(Protocol):
    """Text → async chunks of audio. Adapters that support this fulfill both
    `TTSAdapter.synthesize` (blocking blob) and `synthesize_stream` (progressive).

    The picker prefers `synthesize_stream` when available: it can start
    broadcasting chunks to the client ~500-800ms after the request instead of
    waiting 3-6s for the whole blob. Adapters that can't stream (e.g. non-WS
    backends) simply don't implement this protocol; `FallbackTTS` detects the
    absence and wraps the blob as a single `final=True` chunk."""

    async def synthesize_stream(
        self, text: str, *, voice_id: str,
    ) -> "AsyncIterator[TTSChunk]": ...


class STTAdapter(Protocol):
    """Audio → text. Phase 5 — operator voice input."""

    async def transcribe(self, audio: bytes, *, mime: str) -> str: ...


class ModerationLayer(Protocol):
    """Composable filter. Called on user input (ingress) and on LLM output (egress)."""

    async def check_ingress(self, text: str, identity: Identity) -> ModerationVerdict: ...
    async def check_egress(self, text: str, identity: Identity) -> ModerationVerdict: ...


class PersonalityLoader(Protocol):
    """Hot-reloadable system prompts. Backed by markdown files polled by mtime.

    Known personas: "shugu", "filter", "hermes_public", "hermes_private".
    The loader accepts any string — the Literal is informational only so new
    personas can be added by dropping a markdown file without touching code."""

    def get(self, persona: str) -> PersonalityDoc: ...


class EventBus(Protocol):
    """Pub/sub for WS broadcast. v1 = in-process asyncio. v2 = Redis pub/sub."""

    async def publish(self, topic: str, event: dict) -> None: ...

    def subscribe(self, topic: str) -> "AsyncIterator[dict]": ...

    async def close(self) -> None: ...
