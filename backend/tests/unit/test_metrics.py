"""Tests TDD Phase 8.2 — MetricsRecorder + PrometheusMetricsRecorder.

T1 metrics_recorder_record_tick_increments_counter
T2 metrics_recorder_record_action_with_label
T3 metrics_recorder_record_tool_with_label
T4 metrics_recorder_record_policy_deny_with_labels
T5 generate_latest_returns_prometheus_format
"""
from __future__ import annotations

from prometheus_client import CollectorRegistry

from shugu.observability.metrics import (
    NullMetricsRecorder,
    PrometheusMetricsRecorder,
)


def _recorder() -> PrometheusMetricsRecorder:
    """Crée un recorder isolé avec son propre registre — aucun leak inter-test."""
    return PrometheusMetricsRecorder(registry=CollectorRegistry())


# ---------------------------------------------------------------------------
# T1 — record_tick incrémente agent_runner_ticks_total
# ---------------------------------------------------------------------------


def test_metrics_recorder_record_tick_increments_counter() -> None:
    """record_tick() doit incrémenter agent_runner_ticks_total de 1."""
    rec = _recorder()
    rec.record_tick()
    output = rec.generate_latest().decode()
    assert "agent_runner_ticks_total 1.0" in output


# ---------------------------------------------------------------------------
# T2 — record_action avec label action_kind
# ---------------------------------------------------------------------------


def test_metrics_recorder_record_action_with_label() -> None:
    """record_action(kind) doit incrémenter le counter avec label action_kind."""
    rec = _recorder()
    rec.record_action("set_pose")
    output = rec.generate_latest().decode()
    assert 'action_kind="set_pose"' in output
    assert "agent_runner_actions_applied_total" in output


# ---------------------------------------------------------------------------
# T3 — record_tool avec label tool_name
# ---------------------------------------------------------------------------


def test_metrics_recorder_record_tool_with_label() -> None:
    """record_tool(name) doit incrémenter le counter avec label tool_name."""
    rec = _recorder()
    rec.record_tool("say")
    output = rec.generate_latest().decode()
    assert 'tool_name="say"' in output
    assert "agent_runner_tools_dispatched_total" in output


# ---------------------------------------------------------------------------
# T4 — record_policy_deny avec labels mode + capability
# ---------------------------------------------------------------------------


def test_metrics_recorder_record_policy_deny_with_labels() -> None:
    """record_policy_deny doit incrémenter avec labels mode + capability."""
    rec = _recorder()
    rec.record_policy_deny(mode="emergency_mute", capability="world_mutation")
    output = rec.generate_latest().decode()
    assert 'mode="emergency_mute"' in output
    assert 'capability="world_mutation"' in output
    assert "agent_runner_policy_denials_total" in output


# ---------------------------------------------------------------------------
# T5 — generate_latest retourne le format texte Prometheus
# ---------------------------------------------------------------------------


def test_generate_latest_returns_prometheus_format() -> None:
    """generate_latest() doit retourner des bytes au format texte Prometheus 0.0.4."""
    rec = _recorder()
    rec.record_tick()
    rec.record_world_delta()
    raw = rec.generate_latest()
    assert isinstance(raw, bytes)
    # Le format commence par des lignes HELP / TYPE (convention Prometheus)
    text = raw.decode()
    assert "# HELP" in text
    assert "# TYPE" in text
    assert "world_delta_published_total" in text


# ---------------------------------------------------------------------------
# Bonus — NullMetricsRecorder ne lève pas d'exception
# ---------------------------------------------------------------------------


def test_null_metrics_recorder_is_noop() -> None:
    """NullMetricsRecorder ne doit jamais lever d'exception."""
    rec = NullMetricsRecorder()
    rec.record_tick()
    rec.record_action("wave")
    rec.record_tool("say")
    rec.record_policy_deny("operator_only", "chat_egress")
    rec.record_world_delta()
    rec.record_sense_event("chat")
    # Aucune exception = succès
