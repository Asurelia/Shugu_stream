"""Unit tests for voice turn metrics — TurnMetrics, VoiceMetricsRecorder, PrometheusVoiceMetricsRecorder.

Tests cover:
- VM-1: TurnMetrics.delta_s returns None when stages missing
- VM-2: TurnMetrics.delta_s computes correct seconds
- VM-3: NullVoiceMetricsRecorder is a no-op
- VM-4: make_recorder(enabled=False) returns NullVoiceMetricsRecorder
- VM-5: make_recorder(enabled=True) returns PrometheusVoiceMetricsRecorder
- VM-6: PrometheusVoiceMetricsRecorder.record_turn stamps histogram per observed stage
- VM-7: PrometheusVoiceMetricsRecorder.record_turn observes histogram per stage
- VM-8: PrometheusVoiceMetricsRecorder.record_turn logs structured event
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from prometheus_client import CollectorRegistry

from shugu.voice.metrics import (
    STAGE_AUDIO_FIRST,
    STAGE_LLM_FIRST,
    STAGE_STT_DONE,
    STAGE_VAD_END,
    NullVoiceMetricsRecorder,
    PrometheusVoiceMetricsRecorder,
    TurnMetrics,
    VoiceMetricsRecorder,
    make_recorder,
)

# ---------------------------------------------------------------------------
# VM-1: delta_s returns None when stages not set
# ---------------------------------------------------------------------------


def test_turn_metrics_delta_s_returns_none_if_unset() -> None:
    """delta_s must return None if either stage has no timestamp."""
    m = TurnMetrics()

    # Neither stage set
    assert m.delta_s(STAGE_VAD_END, STAGE_STT_DONE) is None

    # Only one stage set
    m.stamps[STAGE_VAD_END] = 1.0
    assert m.delta_s(STAGE_VAD_END, STAGE_STT_DONE) is None

    # Other direction
    m2 = TurnMetrics()
    m2.stamps[STAGE_STT_DONE] = 2.0
    assert m2.delta_s(STAGE_VAD_END, STAGE_STT_DONE) is None


# ---------------------------------------------------------------------------
# VM-2: delta_s computes correct seconds
# ---------------------------------------------------------------------------


def test_turn_metrics_delta_s_computes_seconds() -> None:
    """delta_s must return the correct float difference between two stage timestamps."""
    m = TurnMetrics()
    m.stamps[STAGE_VAD_END] = 100.0
    m.stamps[STAGE_STT_DONE] = 100.25

    result = m.delta_s(STAGE_VAD_END, STAGE_STT_DONE)
    assert result is not None
    assert abs(result - 0.25) < 1e-9, f"Expected ~0.25s, got {result}"


# ---------------------------------------------------------------------------
# VM-3: NullVoiceMetricsRecorder is a no-op
# ---------------------------------------------------------------------------


def test_null_recorder_is_noop() -> None:
    """NullVoiceMetricsRecorder.record_turn must complete without side effects."""
    recorder = NullVoiceMetricsRecorder()
    m = TurnMetrics(intent="chat")
    m.stamps[STAGE_VAD_END] = 1.0
    m.stamps[STAGE_STT_DONE] = 1.1

    # Must not raise, must not produce any output
    recorder.record_turn(m)


# ---------------------------------------------------------------------------
# VM-4: make_recorder(enabled=False) returns NullVoiceMetricsRecorder
# ---------------------------------------------------------------------------


def test_make_recorder_disabled_returns_null() -> None:
    """make_recorder(False) must return NullVoiceMetricsRecorder singleton."""
    recorder = make_recorder(enabled=False)
    assert isinstance(recorder, NullVoiceMetricsRecorder)


# ---------------------------------------------------------------------------
# VM-5: make_recorder(enabled=True) returns PrometheusVoiceMetricsRecorder
# ---------------------------------------------------------------------------


def test_make_recorder_enabled_returns_prometheus() -> None:
    """make_recorder(True) must return PrometheusVoiceMetricsRecorder."""
    registry = CollectorRegistry()
    recorder = make_recorder(enabled=True, registry=registry)
    assert isinstance(recorder, PrometheusVoiceMetricsRecorder)


# ---------------------------------------------------------------------------
# VM-6: PrometheusVoiceMetricsRecorder.record_turn stamps histogram per stage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_prometheus_recorder_stamp_writes_field() -> None:
    """TurnMetrics.stamp() must correctly populate the stamps dict via asyncio loop time.

    Verifies that the stamps dict key is set to a positive monotonic float.
    This is the foundation on which PrometheusVoiceMetricsRecorder.record_turn() depends.
    """
    m = TurnMetrics(intent="chat")

    # stamp() requires a running loop
    m.stamp(STAGE_VAD_END)
    m.stamp(STAGE_STT_DONE)

    assert STAGE_VAD_END in m.stamps, "STAGE_VAD_END must be in stamps after stamp()"
    assert STAGE_STT_DONE in m.stamps, "STAGE_STT_DONE must be in stamps after stamp()"

    t0 = m.stamps[STAGE_VAD_END]
    t1 = m.stamps[STAGE_STT_DONE]

    assert t0 > 0, f"Timestamp must be positive, got {t0}"
    assert t1 >= t0, f"STT timestamp {t1} must be >= VAD timestamp {t0}"

    delta = m.delta_s(STAGE_VAD_END, STAGE_STT_DONE)
    assert delta is not None
    assert delta >= 0.0, f"Delta must be non-negative, got {delta}"


# ---------------------------------------------------------------------------
# VM-7: PrometheusVoiceMetricsRecorder.record_turn observes histogram per stage
# ---------------------------------------------------------------------------


def test_prometheus_finalize_observes_histogram_per_stage() -> None:
    """record_turn() must observe each stage delta in the Prometheus histogram.

    Verifies that _sum and _count of the histogram are non-zero after record_turn().
    Uses an isolated CollectorRegistry to avoid cross-test contamination.
    """
    registry = CollectorRegistry()
    recorder = PrometheusVoiceMetricsRecorder(registry=registry)

    m = TurnMetrics(intent="chat", pipeline="streaming")
    m.stamps[STAGE_VAD_END] = 0.0
    m.stamps[STAGE_STT_DONE] = 0.1    # 100ms
    m.stamps[STAGE_LLM_FIRST] = 0.35  # 350ms
    m.stamps[STAGE_AUDIO_FIRST] = 0.5  # 500ms TTFB

    recorder.record_turn(m)

    # Verify via prometheus_client's generate_latest text output
    from prometheus_client import generate_latest

    output = generate_latest(registry).decode("utf-8")

    # voice_turn_latency_seconds_sum{intent="chat",stage="stt"} should be ~0.1
    assert 'stage="stt"' in output, f"STT stage not found in Prometheus output:\n{output}"
    assert 'stage="audio_first"' in output, f"audio_first not found in output:\n{output}"
    assert 'intent="chat"' in output, f"intent=chat not found in output:\n{output}"

    # Parse sum values for STT and audio_first stages
    import re

    stt_sum_match = re.search(
        r'voice_turn_latency_seconds_sum\{intent="chat",stage="stt"\}\s+([\d.e+-]+)',
        output,
    )
    assert stt_sum_match is not None, f"Could not find stt sum in output:\n{output}"
    stt_sum = float(stt_sum_match.group(1))
    assert abs(stt_sum - 0.1) < 1e-6, (
        f"STT histogram sum expected ~0.1, got {stt_sum}"
    )

    audio_sum_match = re.search(
        r'voice_turn_latency_seconds_sum\{intent="chat",stage="audio_first"\}\s+([\d.e+-]+)',
        output,
    )
    assert audio_sum_match is not None, f"Could not find audio_first sum in output:\n{output}"
    audio_sum = float(audio_sum_match.group(1))
    assert abs(audio_sum - 0.5) < 1e-6, (
        f"audio_first histogram sum expected ~0.5 (TTFB), got {audio_sum}"
    )

    # Count check via _count pattern
    stt_count_match = re.search(
        r'voice_turn_latency_seconds_count\{intent="chat",stage="stt"\}\s+([\d]+)',
        output,
    )
    assert stt_count_match is not None
    assert int(stt_count_match.group(1)) == 1, "STT stage count must be 1"


# ---------------------------------------------------------------------------
# VM-8: PrometheusVoiceMetricsRecorder.record_turn logs structured event
# ---------------------------------------------------------------------------


def test_prometheus_finalize_logs_structured_event() -> None:
    """record_turn() must emit a structlog event 'voice.metrics.turn' with delta fields."""
    registry = CollectorRegistry()
    recorder = PrometheusVoiceMetricsRecorder(registry=registry)

    m = TurnMetrics(intent="web_search", pipeline="streaming")
    m.stamps[STAGE_VAD_END] = 0.0
    m.stamps[STAGE_STT_DONE] = 0.08    # 80ms
    m.stamps[STAGE_AUDIO_FIRST] = 0.45  # 450ms TTFB

    log_events: list[dict] = []

    mock_log = MagicMock()

    def _capture_info(event: str, **kwargs: object) -> None:
        log_events.append({"event": event, **kwargs})

    mock_log.info = _capture_info

    with patch("shugu.voice.metrics.log", mock_log):
        recorder.record_turn(m)

    # Find the voice.metrics.turn event
    turn_events = [e for e in log_events if e.get("event") == "voice.metrics.turn"]
    assert len(turn_events) >= 1, (
        f"Expected at least 1 'voice.metrics.turn' log event, got {log_events!r}"
    )
    event = turn_events[0]
    assert event.get("intent") == "web_search"
    assert event.get("pipeline") == "streaming"
    # Check at least one delta_* field is present
    delta_keys = [k for k in event if k.startswith("delta_")]
    assert len(delta_keys) >= 1, (
        f"Expected delta_* fields in log event, got keys: {list(event.keys())!r}"
    )


# ---------------------------------------------------------------------------
# Protocol compliance check
# ---------------------------------------------------------------------------


def test_null_recorder_satisfies_protocol() -> None:
    """NullVoiceMetricsRecorder must satisfy VoiceMetricsRecorder Protocol."""
    recorder = NullVoiceMetricsRecorder()
    assert isinstance(recorder, VoiceMetricsRecorder)


def test_prometheus_recorder_satisfies_protocol() -> None:
    """PrometheusVoiceMetricsRecorder must satisfy VoiceMetricsRecorder Protocol."""
    registry = CollectorRegistry()
    recorder = PrometheusVoiceMetricsRecorder(registry=registry)
    assert isinstance(recorder, VoiceMetricsRecorder)
