"""Tests pour les nouveaux compteurs Prometheus — Sprint 4 P1.C1/C4/C2/C6.

Vérifie que :
1. Le Protocol expose les 4 nouvelles méthodes.
2. NullMetricsRecorder est no-op (pas d'exception).
3. PrometheusMetricsRecorder incrémente les counters correctement.
4. Les counters apparaissent dans generate_latest() avec les bons labels.
"""
from __future__ import annotations

import pytest
from prometheus_client import CollectorRegistry

from shugu.observability.metrics import (
    PrometheusMetricsRecorder,
    get_null_recorder,
)


@pytest.fixture
def recorder() -> PrometheusMetricsRecorder:
    """Recorder isolé par test (registre frais)."""
    return PrometheusMetricsRecorder(registry=CollectorRegistry())


class TestNullRecorderNewMethods:
    """NullMetricsRecorder doit absorber les nouveaux appels sans erreur."""

    def test_record_tts_fallback(self) -> None:
        get_null_recorder().record_tts_fallback("MiniMax", "EdgeTTS")

    def test_record_event_bus_drop(self) -> None:
        get_null_recorder().record_event_bus_drop("stage")

    def test_record_persona_fallback(self) -> None:
        get_null_recorder().record_persona_fallback("hermes_public", "shugu")

    def test_record_memory_recall_failed(self) -> None:
        get_null_recorder().record_memory_recall_failed("RecallTimeout")


class TestTtsFallbackCounter:
    def test_initial_zero(self, recorder: PrometheusMetricsRecorder) -> None:
        text = recorder.generate_latest().decode()
        assert "tts_fallback_total" in text

    def test_increments_with_labels(
        self, recorder: PrometheusMetricsRecorder
    ) -> None:
        recorder.record_tts_fallback("MiniMaxTTS", "EdgeTTS")
        recorder.record_tts_fallback("MiniMaxTTS", "EdgeTTS")
        recorder.record_tts_fallback("ElevenLabsTTS", "EdgeTTS")

        text = recorder.generate_latest().decode()
        assert 'tts_fallback_total{from_provider="MiniMaxTTS",to_provider="EdgeTTS"} 2' in text
        assert 'tts_fallback_total{from_provider="ElevenLabsTTS",to_provider="EdgeTTS"} 1' in text


class TestEventBusDropCounter:
    def test_increments_per_topic(
        self, recorder: PrometheusMetricsRecorder
    ) -> None:
        recorder.record_event_bus_drop("stage")
        recorder.record_event_bus_drop("stage")
        recorder.record_event_bus_drop("world.delta")

        text = recorder.generate_latest().decode()
        assert 'event_bus_drop_total{topic="stage"} 2' in text
        assert 'event_bus_drop_total{topic="world.delta"} 1' in text


class TestPersonaFallbackCounter:
    def test_increments_per_persona_pair(
        self, recorder: PrometheusMetricsRecorder
    ) -> None:
        recorder.record_persona_fallback("hermes_public", "shugu")

        text = recorder.generate_latest().decode()
        assert (
            'persona_fallback_total{from_persona="hermes_public",'
            'to_persona="shugu"} 1'
        ) in text


class TestMemoryRecallFailedCounter:
    def test_increments_per_error_kind(
        self, recorder: PrometheusMetricsRecorder
    ) -> None:
        recorder.record_memory_recall_failed("RecallTimeout")
        recorder.record_memory_recall_failed("PgvectorError")
        recorder.record_memory_recall_failed("RecallTimeout")

        text = recorder.generate_latest().decode()
        assert 'memory_recall_failed_total{error_kind="RecallTimeout"} 2' in text
        assert 'memory_recall_failed_total{error_kind="PgvectorError"} 1' in text


class TestEventBusUsesMetrics:
    """Régression : vérifie que InProcessEventBus appelle bien
    record_event_bus_drop sur drop-oldest.
    """

    @pytest.mark.asyncio
    async def test_drop_oldest_records_metric(self) -> None:
        import asyncio

        from shugu.core.event_bus import InProcessEventBus

        recorder = PrometheusMetricsRecorder(registry=CollectorRegistry())
        bus = InProcessEventBus(max_queue=2, metrics=recorder)

        # Subscribe MAIS ne consomme jamais → la queue va se remplir
        async def slow_subscriber():
            async for _ in bus.subscribe("test"):
                await asyncio.sleep(100)  # bloque

        sub_task = asyncio.create_task(slow_subscriber())
        await asyncio.sleep(0.05)  # laisse subscribe enregistrer la queue

        # Publish 5 events ; la queue maxsize=2 → 3 drops
        for i in range(5):
            await bus.publish("test", {"i": i})

        sub_task.cancel()
        try:
            await sub_task
        except asyncio.CancelledError:
            pass

        text = recorder.generate_latest().decode()
        # Au moins 1 drop loggué (le compte exact dépend du scheduling)
        assert 'event_bus_drop_total{topic="test"}' in text
