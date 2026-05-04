"""Voice turn metrics — structlog + Prometheus Histogram per pipeline stage.

Bounded context separate from observability/metrics.py (agent-loop counters).
Voice turn metrics have different lifecycle (1 object per turn, GC after record),
different labels (stage, intent, pipeline), and histograms rather than counters.

Usage:
    # In entrypoint()
    voice_metrics = make_recorder(settings.voice_metrics_enabled, registry=None)

    # In _process_utterance() / _handle_turn_streaming()
    m = TurnMetrics(pipeline="streaming")
    m.stamp(STAGE_VAD_END)
    ...
    m.stamp(STAGE_STT_DONE)
    ...
    voice_metrics.record_turn(m)
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

import structlog

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Stage key constants — chronological order of the voice pipeline.
# Used as stamps dict keys and as Prometheus `stage=` label values.
# ---------------------------------------------------------------------------

STAGE_VAD_END = "vad_end"                # t0: END_OF_SPEECH event received
STAGE_STT_DONE = "stt"                   # t1: Whisper transcribe done
STAGE_INTENT_DONE = "intent"             # t2: intent_classifier.classify() done
STAGE_WEB_DONE = "websearch"             # t3: web_search.search() done (WEB_SEARCH only)
STAGE_LLM_FIRST = "llm_first_token"     # t4: first LLM token received
STAGE_SENTENCE_FIRST = "sentence_first"  # t5: first sentence from SentenceChunker
STAGE_TTS_FIRST = "tts_first_frame"     # t6: first PCM frame from Piper
STAGE_AUDIO_FIRST = "audio_first"       # t7: first AudioFrame published (TTFB voice)

# Stages always present (path-independent)
_MANDATORY_STAGES = (
    STAGE_VAD_END,
    STAGE_STT_DONE,
    STAGE_INTENT_DONE,
    STAGE_LLM_FIRST,
    STAGE_TTS_FIRST,
    STAGE_AUDIO_FIRST,
)

# Stages present only on WEB_SEARCH intent
_WEB_STAGES = (STAGE_WEB_DONE,)

# Whitelist of valid intent label values to prevent Prometheus cardinality explosion.
# Must stay in sync with regie/intent_classifier.Intent enum values.
_VALID_INTENT_LABELS: frozenset[str] = frozenset(
    {"chat", "web_search", "emotion", "emote", "unknown"}
)


def _sanitize_intent(intent: str) -> str:
    """Clamp intent label to whitelist to prevent cardinality bombs."""
    return intent if intent in _VALID_INTENT_LABELS else "unknown"


# ---------------------------------------------------------------------------
# TurnMetrics dataclass — one per voice turn
# ---------------------------------------------------------------------------


@dataclass
class TurnMetrics:
    """Timestamps and deltas for a complete voice turn.

    One TurnMetrics is created at the start of _process_utterance() and passed
    through _handle_turn_streaming() and _resample_and_publish(). Never shared
    between tasks (one per turn, GC after record_turn()).

    stamps: monotonic float from asyncio.get_running_loop().time()
    stamp(stage): records the current timestamp for the given stage key.
    to_dict(): serializes all deltas in ms for structlog/JSON output.
    """

    intent: str = "unknown"
    pipeline: str = "streaming"
    stamps: dict[str, float] = field(default_factory=dict)

    def stamp(self, stage: str) -> None:
        """Record monotonic timestamp for the given stage key.

        Must be called from an asyncio coroutine (uses get_running_loop()).
        """
        self.stamps[stage] = asyncio.get_running_loop().time()

    def delta_s(self, from_stage: str, to_stage: str) -> float | None:
        """Delta between two stages in seconds. None if either stage missing or zero."""
        t0 = self.stamps.get(from_stage)
        t1 = self.stamps.get(to_stage)
        if t0 is None or t1 is None:
            return None
        return t1 - t0

    def delta_ms(self, from_stage: str, to_stage: str) -> float | None:
        """Delta between two stages in milliseconds. None if either stage missing."""
        s = self.delta_s(from_stage, to_stage)
        return s * 1000.0 if s is not None else None

    def ttfb_ms(self) -> float | None:
        """End-to-end TTFB: VAD END_OF_SPEECH → first AudioSource frame published."""
        return self.delta_ms(STAGE_VAD_END, STAGE_AUDIO_FIRST)

    def to_dict(self) -> dict[str, object]:
        """Serialize all computed deltas as ms floats for structlog.

        Format: {intent, pipeline, delta_<stage>_ms: float, ttfb_ms: float}.
        All deltas are relative to STAGE_VAD_END (t0 baseline).
        All values are JSON-serializable (str or float).
        """
        base = self.stamps.get(STAGE_VAD_END, 0.0)
        out: dict[str, object] = {
            "intent": self.intent,
            "pipeline": self.pipeline,
        }
        for stage, ts in self.stamps.items():
            key = f"delta_{stage}_ms"
            out[key] = round((ts - base) * 1000.0, 1)
        ttfb = self.ttfb_ms()
        if ttfb is not None:
            out["ttfb_ms"] = round(ttfb, 1)
        return out


# ---------------------------------------------------------------------------
# Protocol — VoiceMetricsRecorder
# ---------------------------------------------------------------------------


@runtime_checkable
class VoiceMetricsRecorder(Protocol):
    """Contract for voice turn metrics recording.

    Three implementations:
    - NullVoiceMetricsRecorder  : no-op (metrics disabled)
    - PrometheusVoiceMetricsRecorder : structlog + Prometheus Histogram
    """

    def record_turn(self, metrics: TurnMetrics) -> None:
        """Log the completed turn metrics and update Prometheus histograms."""
        ...


# ---------------------------------------------------------------------------
# NullVoiceMetricsRecorder — no-op for disabled / test paths
# ---------------------------------------------------------------------------


class NullVoiceMetricsRecorder:
    """No-op implementation — used when voice_metrics_enabled=False.

    Satisfies VoiceMetricsRecorder protocol by structural typing.
    No prometheus_client dependency at runtime.
    """

    def record_turn(self, metrics: TurnMetrics) -> None:  # noqa: ARG002
        pass


# ---------------------------------------------------------------------------
# PrometheusVoiceMetricsRecorder — structlog + Prometheus Histogram
# ---------------------------------------------------------------------------


class PrometheusVoiceMetricsRecorder:
    """Structlog + Prometheus Histogram recorder for voice turn stage latencies.

    Histograms preserve p50/p95/p99 distribution (not just the last value).
    One histogram `voice_turn_latency_seconds{stage, intent}` covers all stages
    including TTFB (stage="audio_first") — enables cross-stage PromQL in one query.

    Registry injection:
    - In production: pass the shared registry from app.state.prom_recorder
      so histograms appear in GET /metrics alongside agent-loop counters.
    - In tests: pass CollectorRegistry() fresh for isolation.

    Buckets (seconds): [0.005, 0.025, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0]
    Target TTFB = 0.2-0.3s → p50 should land in [0.1, 0.25] bucket.
    """

    # Histogram buckets in seconds — user-confirmed values (D-ARB-3).
    _BUCKETS = [0.005, 0.025, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0]

    def __init__(self, registry: object | None = None) -> None:
        from prometheus_client import CollectorRegistry, Histogram

        self.registry = registry or CollectorRegistry()
        self._latency = Histogram(
            "voice_turn_latency_seconds",
            "Voice pipeline stage delta from VAD END_OF_SPEECH (seconds). "
            "Label stage=audio_first is the E2E TTFB voice metric.",
            ["stage", "intent"],
            buckets=self._BUCKETS,
            registry=self.registry,
        )

    def record_turn(self, metrics: TurnMetrics) -> None:
        """Log voice.metrics.turn via structlog and observe all stage histograms.

        All deltas are computed from STAGE_VAD_END (t0 baseline).
        STAGE_VAD_END itself is skipped (delta would be 0s).
        Intent label is sanitized against whitelist to prevent cardinality bombs.
        """
        log.info("voice.metrics.turn", **metrics.to_dict())
        base = metrics.stamps.get(STAGE_VAD_END, 0.0)
        safe_intent = _sanitize_intent(metrics.intent)
        for stage, ts in metrics.stamps.items():
            if stage == STAGE_VAD_END:
                continue
            delta_s = ts - base
            self._latency.labels(stage=stage, intent=safe_intent).observe(delta_s)


# ---------------------------------------------------------------------------
# Module-level singleton Null recorder
# ---------------------------------------------------------------------------

_NULL_VOICE_RECORDER = NullVoiceMetricsRecorder()


def get_null_recorder() -> NullVoiceMetricsRecorder:
    """Singleton NullVoiceMetricsRecorder — zero overhead when metrics disabled."""
    return _NULL_VOICE_RECORDER


def make_recorder(
    enabled: bool,
    registry: object | None = None,
) -> VoiceMetricsRecorder:
    """Factory — returns PrometheusVoiceMetricsRecorder if enabled, else Null.

    Args:
        enabled: value of settings.voice_metrics_enabled
        registry: the shared CollectorRegistry from app.state.prom_recorder in production.
                  If None and enabled=True, creates an isolated registry (dev/test).

    Called from entrypoint() after lifespan initializes app.state.prom_recorder.
    """
    if enabled:
        return PrometheusVoiceMetricsRecorder(registry=registry)
    return _NULL_VOICE_RECORDER


__all__ = [
    "TurnMetrics",
    "VoiceMetricsRecorder",
    "NullVoiceMetricsRecorder",
    "PrometheusVoiceMetricsRecorder",
    "get_null_recorder",
    "make_recorder",
    "STAGE_VAD_END",
    "STAGE_STT_DONE",
    "STAGE_INTENT_DONE",
    "STAGE_WEB_DONE",
    "STAGE_LLM_FIRST",
    "STAGE_SENTENCE_FIRST",
    "STAGE_TTS_FIRST",
    "STAGE_AUDIO_FIRST",
]
