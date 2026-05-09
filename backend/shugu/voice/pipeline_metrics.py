"""Métriques Prometheus du pipeline voice↔body — Sprint D PR D-10.

Bounded context séparé de :

- ``voice/metrics.py`` (``voice_turn_latency_seconds``) — métriques de
  TurnMetrics per-stage (TTFB pipeline complet).
- ``observability/metrics.py`` (``MetricsRecorder``) — compteurs agent-loop
  legacy (ticks, actions, denials, etc.).

Ce module ajoute les compteurs/histograms qui valident les cibles §7.2 du
spec voice-body-pipeline-design.md :

- Latence chunk publish LiveKit (``voice_publisher_publish_duration_ms``).
- Bridge sentences published / skipped (``voice_bridge_sentences_*``).
- Barge-in cut-off (``voice_cancel_speaking_*``).
- Drift audio↔expression (``director_audio_at_ms_distribution``).
- WS viewer connections + token refresh (``viewer_ws_*``).

Pourquoi un 3ᵉ module et pas un seul gros recorder ?

1. **Bounded contexts distincts** — voice turn metrics ont un cycle de vie
   par turn (1 objet TurnMetrics, GC après record_turn), pipeline metrics
   sont des counters/histograms incrémentaux process-wide. Mélanger les
   deux dans un même protocole obscurcit les invariants.
2. **Gating flag commun** — réutilise ``voice_metrics_enabled`` (pas un
   nouveau setting), donc l'enable est cohérent avec ``voice/metrics.py``.
3. **Isolation testabilité** — chaque test injecte un ``CollectorRegistry``
   frais dans ``PipelineMetricsRecorder`` sans interférer avec voice/metrics.

Pattern Null Object (cohérent avec les 2 autres modules) : tous les call
sites appellent les méthodes sans guard ``if recorder is not None``. Le
``NullPipelineMetricsRecorder`` absorbe silencieusement.

Injection registry
------------------
En production, ``app.py`` lifespan injecte ``app.state.prom_recorder.registry``
(pattern identique à voice/metrics.py et observability/metrics.py). Les
métriques apparaissent dans GET /metrics aux côtés des compteurs agent-loop
et voice_turn_latency_seconds.

Spec : ``docs/specs/2026-05-08-voice-body-pipeline-design.md`` §7.2.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

import structlog

if TYPE_CHECKING:
    # Audit Context7 fix : tighten type hints sur les paramètres `registry`
    # (avant : `object | None`, justifié à tort par "import lourd au top-level"
    # alors que prometheus_client est déjà importé localement dans __init__).
    # Pattern TYPE_CHECKING : 0 cost runtime + précision statique pour mypy/IDE.
    from prometheus_client import CollectorRegistry

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Buckets — alignés sur les cibles §7.2.
# ---------------------------------------------------------------------------

# Buckets en millisecondes pour les latences publish/cancel.
# Cibles : barge-in <200ms, publish chunk <100ms en moyenne. On garde une
# queue jusqu'à 5s pour détecter les dégradations majeures (Piper crash,
# LiveKit reconnect long).
_BUCKETS_MS_LATENCY = (5.0, 10.0, 25.0, 50.0, 100.0, 200.0, 500.0, 1000.0, 5000.0)

# Buckets pour le drift audio_at_ms (dans le payload scene.apply).
# Cible §7.2 : drift <100ms p95. Buckets serrés autour de la cible.
_BUCKETS_AUDIO_AT_MS = (0.0, 10.0, 25.0, 50.0, 100.0, 200.0, 500.0, 1000.0, 2000.0)

# Buckets pour la durée publish d'une phrase complète (Piper synth + LiveKit).
# Une phrase typique 5-15 mots = 1-3s à 22050 Hz. Buckets adaptés.
_BUCKETS_MS_SENTENCE = (
    50.0, 100.0, 250.0, 500.0, 1000.0, 2500.0, 5000.0, 10000.0, 30000.0,
)

# ---------------------------------------------------------------------------
# Whitelists labels — anti cardinality bombs.
# ---------------------------------------------------------------------------

# Reasons valides pour cancel_speaking. Doit matcher les sites d'appel
# (livekit_agent.cancel_speaking + on_speech_started).
_VALID_CANCEL_REASONS: frozenset[str] = frozenset({
    "barge_in",       # détection VAD utilisateur (cas nominal)
    "shutdown",       # _on_shutdown du worker
    "external",       # cancel programmatique extérieur (tests)
    "unknown",        # fallback
})

# Reasons valides pour bridge sentence skipped.
_VALID_SKIP_REASONS: frozenset[str] = frozenset({
    "empty",                  # phrase vide ou whitespace-only
    "tts_empty",              # Piper retourne b""
    "tts_failed",             # Piper raise
    "publish_failed",         # publisher raise
    "cancelled_pre_synth",    # _cancelled levé avant synth
    "cancelled_post_synth",   # _cancelled levé après synth
    "stream_iterator_failed", # iterator amont raise
    "unknown",
})

# Reasons valides pour ws_disconnects.
_VALID_WS_DISCONNECT_REASONS: frozenset[str] = frozenset({
    "client_close",   # WebSocketDisconnect normal
    "auth_failed",    # token rejeté
    "rate_limited",   # too many connections / token already in use
    "server_error",   # exception non-attendue
    "unknown",
})

# Outcomes valides pour token_refresh.
_VALID_REFRESH_OUTCOMES: frozenset[str] = frozenset({
    "success",        # nouveau token émis
    "expired_grace",  # expiré au-delà de la grace, refus 401
    "auth_failed",    # token invalide
    "missing_token",  # pas de Authorization header
    "unknown",
})

# Kinds valides pour audio_at_ms (only say_emotion + face en D-5).
_VALID_AUDIO_AT_MS_KINDS: frozenset[str] = frozenset({
    "say_emotion",
    "face",
    "unknown",
})


def _sanitize(value: str | None, whitelist: frozenset[str]) -> str:
    """Clamp un label sur la whitelist pour éviter une explosion de cardinalité.

    Si ``value`` est ``None`` ou hors whitelist, retourne ``"unknown"``.
    Pas de logging — l'appelant log si nécessaire (évite double-log).
    """
    if value is None:
        return "unknown"
    return value if value in whitelist else "unknown"


# ---------------------------------------------------------------------------
# Protocol — contrat commun
# ---------------------------------------------------------------------------


@runtime_checkable
class PipelineMetricsRecorder(Protocol):
    """Contrat minimal pour les métriques pipeline voice↔body.

    Toutes les méthodes sont synchrones (compteurs/histogrammes in-memory,
    thread-safe via prometheus_client). Aucun call site ne dépend d'une
    implémentation concrète.
    """

    # Publisher LiveKit (D-1) ----------------------------------------------

    def record_publisher_chunk(self, *, duration_ms: float) -> None:
        """Incrémente ``voice_publisher_chunks_published_total`` + observe
        ``voice_publisher_publish_duration_ms``.

        Appelé depuis ``LiveKitPublisher.publish_pcm`` après chaque chunk
        publié avec succès. ``duration_ms`` est le wall-clock du publish
        (de la 1ʳᵉ ``capture_frame`` à la dernière).
        """
        ...

    def record_publisher_drop(self) -> None:
        """Incrémente ``voice_publisher_chunks_dropped_total``.

        Appelé quand un chunk est droppé (PCM trop court, _ensure_published
        échoue, capture_frame raise mid-stream).
        """
        ...

    # Audio bridge (D-2) ----------------------------------------------------

    def record_bridge_sentence_published(self, *, duration_ms: float) -> None:
        """Incrémente ``voice_bridge_sentences_published_total`` + observe
        ``voice_bridge_publish_sentence_duration_ms``.

        Appelé après publish_sentence réussi. ``duration_ms`` couvre Piper
        synth + LiveKit publish.
        """
        ...

    def record_bridge_sentence_skipped(self, *, reason: str) -> None:
        """Incrémente ``voice_bridge_sentences_skipped_total{reason}``.

        ``reason`` doit être dans ``_VALID_SKIP_REASONS`` ou il est
        sanitized en ``"unknown"``.
        """
        ...

    # Barge-in (D-4) --------------------------------------------------------

    def record_cancel_speaking(self, *, reason: str, duration_ms: float) -> None:
        """Incrémente ``voice_cancel_speaking_total{reason}`` + observe
        ``voice_cancel_speaking_duration_ms``.

        Appelé à la fin de ``ShuguVoiceAgent.cancel_speaking`` (toutes
        étapes terminées). ``duration_ms`` mesure la latence cut-off
        complète : entrée méthode → fin de la dernière étape.
        Cible §7.2 : <200ms p95.
        """
        ...

    # Director audio sync (D-5) --------------------------------------------

    def record_audio_at_ms(self, *, kind: str, audio_at_ms: float) -> None:
        """Observe ``director_audio_at_ms_distribution{kind}``.

        Appelé par ``SayWorker`` / ``FaceWorker`` quand un payload
        ``scene.apply`` est enrichi avec ``audio_at_ms``. Permet de
        mesurer le drift réel audio↔anim côté backend (cible §7.2 :
        <100ms p95). Le frontend peut ensuite mesurer le delay
        d'application réel via Playwright/lighthouse.
        """
        ...

    # Viewer WS routes (D-3) ------------------------------------------------

    def record_viewer_connection(self) -> None:
        """Incrémente ``viewer_ws_connections_total``.

        Appelé après ``ws.accept()`` réussi dans ``viewer_events_ws``.
        Compte uniquement les connexions effectivement ouvertes (post-auth,
        post-rate-limit).
        """
        ...

    def record_viewer_disconnect(self, *, reason: str) -> None:
        """Incrémente ``viewer_ws_disconnects_total{reason}``.

        Appelé dans le ``finally`` de ``viewer_events_ws``. ``reason``
        capture la cause de la fermeture (client_close, auth_failed, etc.).
        """
        ...

    def record_viewer_token_refresh(self, *, outcome: str) -> None:
        """Incrémente ``viewer_token_refresh_total{outcome}``.

        Appelé dans ``voice_token_refresh`` route. ``outcome`` ∈
        {success, expired_grace, auth_failed, missing_token}. Utile pour
        distinguer une rotation saine d'un flot d'auth fail (attaque
        brute force JWT).
        """
        ...


# ---------------------------------------------------------------------------
# NullPipelineMetricsRecorder — no-op
# ---------------------------------------------------------------------------


class NullPipelineMetricsRecorder:
    """Implémentation no-op du Protocol — aucune dépendance prometheus_client.

    Utilisé quand ``voice_metrics_enabled=False``. Toutes les méthodes sont
    silent. Satisfait ``PipelineMetricsRecorder`` par structural typing.
    """

    def record_publisher_chunk(self, *, duration_ms: float) -> None:  # noqa: ARG002
        pass

    def record_publisher_drop(self) -> None:
        pass

    def record_bridge_sentence_published(self, *, duration_ms: float) -> None:  # noqa: ARG002
        pass

    def record_bridge_sentence_skipped(self, *, reason: str) -> None:  # noqa: ARG002
        pass

    def record_cancel_speaking(self, *, reason: str, duration_ms: float) -> None:  # noqa: ARG002
        pass

    def record_audio_at_ms(self, *, kind: str, audio_at_ms: float) -> None:  # noqa: ARG002
        pass

    def record_viewer_connection(self) -> None:
        pass

    def record_viewer_disconnect(self, *, reason: str) -> None:  # noqa: ARG002
        pass

    def record_viewer_token_refresh(self, *, outcome: str) -> None:  # noqa: ARG002
        pass


# Singleton global pour éviter d'allouer un objet par call site.
_NULL_PIPELINE_RECORDER = NullPipelineMetricsRecorder()


def get_null_pipeline_recorder() -> NullPipelineMetricsRecorder:
    """Retourne le singleton ``NullPipelineMetricsRecorder``."""
    return _NULL_PIPELINE_RECORDER


# ---------------------------------------------------------------------------
# PrometheusPipelineMetricsRecorder — implémentation Prometheus
# ---------------------------------------------------------------------------


class PrometheusPipelineMetricsRecorder:
    """Implémentation Prometheus du ``PipelineMetricsRecorder``.

    Chaque instance possède son propre ``CollectorRegistry`` (injection via
    paramètre). En production : passer ``app.state.prom_recorder.registry``
    pour que les métriques apparaissent dans GET /metrics aux côtés des
    counters agent-loop et voice_turn_latency_seconds.

    Paramètres
    ----------
    registry : CollectorRegistry | None
        Registre Prometheus. Si None, crée un ``CollectorRegistry()`` frais
        (isolation tests).
    """

    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        from prometheus_client import CollectorRegistry, Counter, Histogram

        self.registry = registry or CollectorRegistry()

        # ── Publisher LiveKit (D-1) ──────────────────────────────────────
        self._publisher_chunks_total = Counter(
            "voice_publisher_chunks_published_total",
            "Nombre de chunks PCM publiés avec succès vers LiveKit.",
            registry=self.registry,
        )
        self._publisher_chunks_dropped_total = Counter(
            "voice_publisher_chunks_dropped_total",
            "Nombre de chunks PCM droppés (PCM court, reconnect failed, "
            "capture_frame raise mid-stream).",
            registry=self.registry,
        )
        self._publisher_publish_duration_ms = Histogram(
            "voice_publisher_publish_duration_ms",
            "Latence du publish LiveKit d'un chunk PCM (ms wall-clock).",
            buckets=_BUCKETS_MS_LATENCY,
            registry=self.registry,
        )

        # ── Audio bridge (D-2) ────────────────────────────────────────────
        self._bridge_sentences_published_total = Counter(
            "voice_bridge_sentences_published_total",
            "Nombre de phrases TTS publiées via AudioBridge "
            "(synth Piper + publish LiveKit OK).",
            registry=self.registry,
        )
        self._bridge_sentences_skipped_total = Counter(
            "voice_bridge_sentences_skipped_total",
            "Nombre de phrases skipées par AudioBridge, par raison.",
            ["reason"],
            registry=self.registry,
        )
        self._bridge_publish_sentence_duration_ms = Histogram(
            "voice_bridge_publish_sentence_duration_ms",
            "Durée totale de publish_sentence (Piper synth + LiveKit "
            "publish), en ms.",
            buckets=_BUCKETS_MS_SENTENCE,
            registry=self.registry,
        )

        # ── Barge-in (D-4) ────────────────────────────────────────────────
        self._cancel_speaking_total = Counter(
            "voice_cancel_speaking_total",
            "Nombre de cancel_speaking déclenchés, par raison.",
            ["reason"],
            registry=self.registry,
        )
        self._cancel_speaking_duration_ms = Histogram(
            "voice_cancel_speaking_duration_ms",
            "Latence totale de cancel_speaking (cut-off barge-in). "
            "Cible §7.2 : <200ms p95.",
            buckets=_BUCKETS_MS_LATENCY,
            registry=self.registry,
        )

        # ── Director audio sync (D-5) ─────────────────────────────────────
        self._director_audio_at_ms = Histogram(
            "director_audio_at_ms_distribution",
            "Distribution du delta audio_at_ms côté backend "
            "(now_monotonic - chunk_started_at) lors du publish d'un "
            "scene.apply enrichi. Cible §7.2 : <100ms p95.",
            ["kind"],
            buckets=_BUCKETS_AUDIO_AT_MS,
            registry=self.registry,
        )

        # ── Viewer WS routes (D-3) ────────────────────────────────────────
        self._viewer_ws_connections_total = Counter(
            "viewer_ws_connections_total",
            "Nombre de connexions WS /ws/viewer/events ouvertes "
            "(post-auth, post-rate-limit).",
            registry=self.registry,
        )
        self._viewer_ws_disconnects_total = Counter(
            "viewer_ws_disconnects_total",
            "Nombre de déconnexions WS /ws/viewer/events, par raison.",
            ["reason"],
            registry=self.registry,
        )
        self._viewer_token_refresh_total = Counter(
            "viewer_token_refresh_total",
            "Nombre de tentatives de refresh de viewer token, par outcome.",
            ["outcome"],
            registry=self.registry,
        )

    # ─── Publisher ──────────────────────────────────────────────────────

    def record_publisher_chunk(self, *, duration_ms: float) -> None:
        self._publisher_chunks_total.inc()
        self._publisher_publish_duration_ms.observe(duration_ms)

    def record_publisher_drop(self) -> None:
        self._publisher_chunks_dropped_total.inc()

    # ─── Bridge ─────────────────────────────────────────────────────────

    def record_bridge_sentence_published(self, *, duration_ms: float) -> None:
        self._bridge_sentences_published_total.inc()
        self._bridge_publish_sentence_duration_ms.observe(duration_ms)

    def record_bridge_sentence_skipped(self, *, reason: str) -> None:
        safe = _sanitize(reason, _VALID_SKIP_REASONS)
        self._bridge_sentences_skipped_total.labels(reason=safe).inc()

    # ─── Cancel ─────────────────────────────────────────────────────────

    def record_cancel_speaking(self, *, reason: str, duration_ms: float) -> None:
        safe = _sanitize(reason, _VALID_CANCEL_REASONS)
        self._cancel_speaking_total.labels(reason=safe).inc()
        self._cancel_speaking_duration_ms.observe(duration_ms)

    # ─── Director audio sync ────────────────────────────────────────────

    def record_audio_at_ms(self, *, kind: str, audio_at_ms: float) -> None:
        safe = _sanitize(kind, _VALID_AUDIO_AT_MS_KINDS)
        self._director_audio_at_ms.labels(kind=safe).observe(audio_at_ms)

    # ─── Viewer WS ──────────────────────────────────────────────────────

    def record_viewer_connection(self) -> None:
        self._viewer_ws_connections_total.inc()

    def record_viewer_disconnect(self, *, reason: str) -> None:
        safe = _sanitize(reason, _VALID_WS_DISCONNECT_REASONS)
        self._viewer_ws_disconnects_total.labels(reason=safe).inc()

    def record_viewer_token_refresh(self, *, outcome: str) -> None:
        safe = _sanitize(outcome, _VALID_REFRESH_OUTCOMES)
        self._viewer_token_refresh_total.labels(outcome=safe).inc()


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def make_pipeline_recorder(
    enabled: bool,
    registry: CollectorRegistry | None = None,
) -> PipelineMetricsRecorder:
    """Factory — retourne ``PrometheusPipelineMetricsRecorder`` si enabled.

    Args:
        enabled: typiquement ``settings.voice_metrics_enabled``.
        registry: ``app.state.prom_recorder.registry`` en production
            pour partage du registry. None → CollectorRegistry isolé.

    Returns:
        PipelineMetricsRecorder concret (Prom ou Null singleton).
    """
    if enabled:
        return PrometheusPipelineMetricsRecorder(registry=registry)
    return _NULL_PIPELINE_RECORDER


__all__ = [
    "PipelineMetricsRecorder",
    "NullPipelineMetricsRecorder",
    "PrometheusPipelineMetricsRecorder",
    "get_null_pipeline_recorder",
    "make_pipeline_recorder",
]
