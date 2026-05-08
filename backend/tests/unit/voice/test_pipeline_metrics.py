"""Tests unitaires pour ``pipeline_metrics.py`` — D-10A skeleton + D-10B wiring.

Couvre les contrats critiques du recorder Prometheus :

- Le ``NullPipelineMetricsRecorder`` est un no-op total (aucune dépendance
  prometheus_client n'est touchée — silent absorb).
- Le ``PrometheusPipelineMetricsRecorder`` incrémente bien les counters et
  observe les histograms attendus, sur le registry injecté.
- ``make_pipeline_recorder(enabled=False)`` retourne le singleton no-op
  (zéro allocation par call site).
- ``make_pipeline_recorder(enabled=True, registry=...)`` retourne le Prom
  recorder branché sur le registry partagé (production = registry du
  ``PrometheusMetricsRecorder`` agent-loop, donc visible dans /metrics).
- Les whitelists labels (``_VALID_*_REASONS`` / ``_VALID_*_OUTCOMES`` /
  ``_VALID_AUDIO_AT_MS_KINDS``) clampent les valeurs hors-liste sur
  ``"unknown"`` (anti cardinality bomb Prometheus).

Pas de mock prometheus_client — on instancie un ``CollectorRegistry`` frais
par test pour lire les compteurs réels (isolation parfaite, pas de fuite
cross-test).

Spec : ``docs/specs/2026-05-08-voice-body-pipeline-design.md`` §7.2.
"""
from __future__ import annotations

import pytest
from prometheus_client import CollectorRegistry

from shugu.voice.pipeline_metrics import (
    NullPipelineMetricsRecorder,
    PipelineMetricsRecorder,
    PrometheusPipelineMetricsRecorder,
    get_null_pipeline_recorder,
    make_pipeline_recorder,
)


# ---------------------------------------------------------------------------
# Helpers — extraction des compteurs Prometheus pour assertions
# ---------------------------------------------------------------------------


def _counter_value(
    registry: CollectorRegistry,
    name: str,
    labels: dict[str, str] | None = None,
) -> float:
    """Retourne la valeur courante du counter ``name`` (avec labels optionnels).

    Lit via ``registry.get_sample_value`` qui résout le ``_total`` suffix
    automatiquement. Retourne 0.0 si le sample n'existe pas (counter non touché).
    """
    sample_name = f"{name}_total"
    value = registry.get_sample_value(sample_name, labels or {})
    return value if value is not None else 0.0


def _histogram_count(
    registry: CollectorRegistry,
    name: str,
    labels: dict[str, str] | None = None,
) -> float:
    """Retourne le ``_count`` du histogram ``name`` (nombre d'observations)."""
    value = registry.get_sample_value(f"{name}_count", labels or {})
    return value if value is not None else 0.0


def _histogram_sum(
    registry: CollectorRegistry,
    name: str,
    labels: dict[str, str] | None = None,
) -> float:
    """Retourne le ``_sum`` du histogram ``name`` (somme des observations)."""
    value = registry.get_sample_value(f"{name}_sum", labels or {})
    return value if value is not None else 0.0


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fresh_registry() -> CollectorRegistry:
    """``CollectorRegistry`` isolé par test — anti-leak cross-test."""
    return CollectorRegistry()


@pytest.fixture
def prom_recorder(fresh_registry: CollectorRegistry) -> PrometheusPipelineMetricsRecorder:
    """``PrometheusPipelineMetricsRecorder`` branché sur registry frais."""
    return PrometheusPipelineMetricsRecorder(registry=fresh_registry)


# ---------------------------------------------------------------------------
# NullPipelineMetricsRecorder — no-op total
# ---------------------------------------------------------------------------


def test_null_recorder_is_no_op_total() -> None:
    """Toutes les méthodes du Null doivent passer sans exception, sans side-effect."""
    null = NullPipelineMetricsRecorder()
    null.record_publisher_chunk(duration_ms=42.0)
    null.record_publisher_drop()
    null.record_bridge_sentence_published(duration_ms=1500.0)
    null.record_bridge_sentence_skipped(reason="empty")
    null.record_cancel_speaking(reason="barge_in", duration_ms=120.0)
    null.record_audio_at_ms(kind="say_emotion", audio_at_ms=50.0)
    null.record_viewer_connection()
    null.record_viewer_disconnect(reason="client_close")
    null.record_viewer_token_refresh(outcome="success")
    # Pas d'assertion runtime — on vérifie juste qu'aucune exception ne fuit.


def test_null_recorder_is_singleton_via_factory() -> None:
    """``get_null_pipeline_recorder()`` retourne TOUJOURS la même instance."""
    a = get_null_pipeline_recorder()
    b = get_null_pipeline_recorder()
    assert a is b


def test_null_recorder_satisfies_protocol() -> None:
    """Structural typing : Null implémente bien ``PipelineMetricsRecorder``."""
    null = NullPipelineMetricsRecorder()
    assert isinstance(null, PipelineMetricsRecorder)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def test_make_pipeline_recorder_disabled_returns_null_singleton() -> None:
    """``enabled=False`` → singleton Null (zéro allocation par call site)."""
    rec = make_pipeline_recorder(enabled=False)
    assert rec is get_null_pipeline_recorder()


def test_make_pipeline_recorder_enabled_returns_prom_with_registry(
    fresh_registry: CollectorRegistry,
) -> None:
    """``enabled=True`` + registry → Prom recorder branché sur ce registry."""
    rec = make_pipeline_recorder(enabled=True, registry=fresh_registry)
    assert isinstance(rec, PrometheusPipelineMetricsRecorder)
    assert rec.registry is fresh_registry


def test_make_pipeline_recorder_enabled_creates_isolated_registry_when_none() -> None:
    """``enabled=True`` + registry=None → recorder avec registry isolé frais."""
    rec = make_pipeline_recorder(enabled=True, registry=None)
    assert isinstance(rec, PrometheusPipelineMetricsRecorder)
    # Registry doit exister (pas le défaut prometheus_client.REGISTRY global).
    assert rec.registry is not None


# ---------------------------------------------------------------------------
# Publisher metrics (D-1)
# ---------------------------------------------------------------------------


def test_record_publisher_chunk_increments_counter_and_observes_duration(
    prom_recorder: PrometheusPipelineMetricsRecorder,
    fresh_registry: CollectorRegistry,
) -> None:
    """``record_publisher_chunk`` incrémente counter ET observe histogram."""
    prom_recorder.record_publisher_chunk(duration_ms=42.5)
    prom_recorder.record_publisher_chunk(duration_ms=87.0)

    assert _counter_value(fresh_registry, "voice_publisher_chunks_published") == 2.0
    assert _histogram_count(fresh_registry, "voice_publisher_publish_duration_ms") == 2.0
    assert _histogram_sum(fresh_registry, "voice_publisher_publish_duration_ms") == pytest.approx(
        42.5 + 87.0
    )


def test_record_publisher_drop_increments_counter(
    prom_recorder: PrometheusPipelineMetricsRecorder,
    fresh_registry: CollectorRegistry,
) -> None:
    """``record_publisher_drop`` incrémente le compteur drops."""
    prom_recorder.record_publisher_drop()
    prom_recorder.record_publisher_drop()
    prom_recorder.record_publisher_drop()
    assert _counter_value(fresh_registry, "voice_publisher_chunks_dropped") == 3.0


# ---------------------------------------------------------------------------
# Bridge metrics (D-2)
# ---------------------------------------------------------------------------


def test_record_bridge_sentence_published_increments_and_observes(
    prom_recorder: PrometheusPipelineMetricsRecorder,
    fresh_registry: CollectorRegistry,
) -> None:
    prom_recorder.record_bridge_sentence_published(duration_ms=1200.0)
    assert _counter_value(fresh_registry, "voice_bridge_sentences_published") == 1.0
    assert _histogram_count(
        fresh_registry, "voice_bridge_publish_sentence_duration_ms"
    ) == 1.0
    assert _histogram_sum(
        fresh_registry, "voice_bridge_publish_sentence_duration_ms"
    ) == pytest.approx(1200.0)


def test_record_bridge_sentence_skipped_uses_reason_label(
    prom_recorder: PrometheusPipelineMetricsRecorder,
    fresh_registry: CollectorRegistry,
) -> None:
    """Chaque ``reason`` whitelist devient un label distinct."""
    prom_recorder.record_bridge_sentence_skipped(reason="empty")
    prom_recorder.record_bridge_sentence_skipped(reason="empty")
    prom_recorder.record_bridge_sentence_skipped(reason="tts_failed")

    assert _counter_value(
        fresh_registry, "voice_bridge_sentences_skipped", {"reason": "empty"}
    ) == 2.0
    assert _counter_value(
        fresh_registry, "voice_bridge_sentences_skipped", {"reason": "tts_failed"}
    ) == 1.0


def test_record_bridge_sentence_skipped_unknown_reason_clamped_to_unknown(
    prom_recorder: PrometheusPipelineMetricsRecorder,
    fresh_registry: CollectorRegistry,
) -> None:
    """``reason`` hors whitelist → clamp ``"unknown"`` (anti cardinality bomb)."""
    prom_recorder.record_bridge_sentence_skipped(reason="some_random_reason")
    assert _counter_value(
        fresh_registry, "voice_bridge_sentences_skipped", {"reason": "unknown"}
    ) == 1.0
    # La valeur originale ne doit PAS apparaître comme label.
    assert _counter_value(
        fresh_registry,
        "voice_bridge_sentences_skipped",
        {"reason": "some_random_reason"},
    ) == 0.0


# ---------------------------------------------------------------------------
# Cancel metrics (D-4)
# ---------------------------------------------------------------------------


def test_record_cancel_speaking_increments_per_reason_and_observes(
    prom_recorder: PrometheusPipelineMetricsRecorder,
    fresh_registry: CollectorRegistry,
) -> None:
    prom_recorder.record_cancel_speaking(reason="barge_in", duration_ms=80.0)
    prom_recorder.record_cancel_speaking(reason="barge_in", duration_ms=140.0)
    prom_recorder.record_cancel_speaking(reason="external", duration_ms=200.0)

    assert _counter_value(
        fresh_registry, "voice_cancel_speaking", {"reason": "barge_in"}
    ) == 2.0
    assert _counter_value(
        fresh_registry, "voice_cancel_speaking", {"reason": "external"}
    ) == 1.0

    # Histogram is global (pas de label par reason)
    assert _histogram_count(fresh_registry, "voice_cancel_speaking_duration_ms") == 3.0
    assert _histogram_sum(fresh_registry, "voice_cancel_speaking_duration_ms") == pytest.approx(
        80.0 + 140.0 + 200.0
    )


def test_record_cancel_speaking_invalid_reason_clamped(
    prom_recorder: PrometheusPipelineMetricsRecorder,
    fresh_registry: CollectorRegistry,
) -> None:
    prom_recorder.record_cancel_speaking(reason="not_in_whitelist", duration_ms=50.0)
    assert _counter_value(
        fresh_registry, "voice_cancel_speaking", {"reason": "unknown"}
    ) == 1.0


# ---------------------------------------------------------------------------
# Audio sync metrics (D-5)
# ---------------------------------------------------------------------------


def test_record_audio_at_ms_observes_per_kind(
    prom_recorder: PrometheusPipelineMetricsRecorder,
    fresh_registry: CollectorRegistry,
) -> None:
    prom_recorder.record_audio_at_ms(kind="say_emotion", audio_at_ms=42.0)
    prom_recorder.record_audio_at_ms(kind="face", audio_at_ms=87.0)
    prom_recorder.record_audio_at_ms(kind="face", audio_at_ms=66.0)

    assert _histogram_count(
        fresh_registry, "director_audio_at_ms_distribution", {"kind": "say_emotion"}
    ) == 1.0
    assert _histogram_count(
        fresh_registry, "director_audio_at_ms_distribution", {"kind": "face"}
    ) == 2.0
    assert _histogram_sum(
        fresh_registry, "director_audio_at_ms_distribution", {"kind": "face"}
    ) == pytest.approx(87.0 + 66.0)


def test_record_audio_at_ms_invalid_kind_clamped(
    prom_recorder: PrometheusPipelineMetricsRecorder,
    fresh_registry: CollectorRegistry,
) -> None:
    """Kind hors whitelist → ``"unknown"``."""
    prom_recorder.record_audio_at_ms(kind="anim", audio_at_ms=10.0)
    assert _histogram_count(
        fresh_registry, "director_audio_at_ms_distribution", {"kind": "unknown"}
    ) == 1.0


# ---------------------------------------------------------------------------
# Viewer routes metrics (D-3)
# ---------------------------------------------------------------------------


def test_record_viewer_connection_increments(
    prom_recorder: PrometheusPipelineMetricsRecorder,
    fresh_registry: CollectorRegistry,
) -> None:
    prom_recorder.record_viewer_connection()
    prom_recorder.record_viewer_connection()
    assert _counter_value(fresh_registry, "viewer_ws_connections") == 2.0


def test_record_viewer_disconnect_uses_reason_label(
    prom_recorder: PrometheusPipelineMetricsRecorder,
    fresh_registry: CollectorRegistry,
) -> None:
    prom_recorder.record_viewer_disconnect(reason="client_close")
    prom_recorder.record_viewer_disconnect(reason="auth_failed")
    prom_recorder.record_viewer_disconnect(reason="auth_failed")

    assert _counter_value(
        fresh_registry, "viewer_ws_disconnects", {"reason": "client_close"}
    ) == 1.0
    assert _counter_value(
        fresh_registry, "viewer_ws_disconnects", {"reason": "auth_failed"}
    ) == 2.0


def test_record_viewer_disconnect_invalid_reason_clamped(
    prom_recorder: PrometheusPipelineMetricsRecorder,
    fresh_registry: CollectorRegistry,
) -> None:
    prom_recorder.record_viewer_disconnect(reason="weird_reason")
    assert _counter_value(
        fresh_registry, "viewer_ws_disconnects", {"reason": "unknown"}
    ) == 1.0


def test_record_viewer_token_refresh_uses_outcome_label(
    prom_recorder: PrometheusPipelineMetricsRecorder,
    fresh_registry: CollectorRegistry,
) -> None:
    prom_recorder.record_viewer_token_refresh(outcome="success")
    prom_recorder.record_viewer_token_refresh(outcome="success")
    prom_recorder.record_viewer_token_refresh(outcome="auth_failed")

    assert _counter_value(
        fresh_registry, "viewer_token_refresh", {"outcome": "success"}
    ) == 2.0
    assert _counter_value(
        fresh_registry, "viewer_token_refresh", {"outcome": "auth_failed"}
    ) == 1.0


def test_record_viewer_token_refresh_invalid_outcome_clamped(
    prom_recorder: PrometheusPipelineMetricsRecorder,
    fresh_registry: CollectorRegistry,
) -> None:
    prom_recorder.record_viewer_token_refresh(outcome="some_other")
    assert _counter_value(
        fresh_registry, "viewer_token_refresh", {"outcome": "unknown"}
    ) == 1.0


# ---------------------------------------------------------------------------
# Cardinality safety — un seul exemple de stress test
# ---------------------------------------------------------------------------


def test_invalid_labels_dont_explode_cardinality(
    prom_recorder: PrometheusPipelineMetricsRecorder,
    fresh_registry: CollectorRegistry,
) -> None:
    """100 reasons aléatoires → 1 seule série supplémentaire (``unknown``).

    Régression test : si quelqu'un retire ``_sanitize`` par mégarde, ce test
    explose (il faudrait 100 séries au lieu de 1) ou détecte ça via le sample
    count.
    """
    for i in range(100):
        prom_recorder.record_bridge_sentence_skipped(reason=f"rand_{i}")

    assert _counter_value(
        fresh_registry, "voice_bridge_sentences_skipped", {"reason": "unknown"}
    ) == 100.0
    # Aucun des labels invalides ne doit créer de série dédiée.
    for i in range(0, 100, 25):
        assert _counter_value(
            fresh_registry,
            "voice_bridge_sentences_skipped",
            {"reason": f"rand_{i}"},
        ) == 0.0
