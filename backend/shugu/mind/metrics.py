# backend/shugu/mind/metrics.py
"""Recorder métriques Mind — Protocol + Null (pattern voice/metrics.py).

L'impl Prometheus sera ajoutée à la consolidation observabilité (M-6).
En M-0/M-1, le Null recorder + structlog suffisent et restent testables.
"""
from __future__ import annotations

from typing import Protocol


class MindMetricsRecorder(Protocol):
    def record_brain_fallback(self, *, reason: str, tier: str) -> None: ...


class NullMindMetricsRecorder:
    def record_brain_fallback(self, *, reason: str, tier: str) -> None:  # noqa: ARG002
        return None


def get_null_mind_recorder() -> NullMindMetricsRecorder:
    return NullMindMetricsRecorder()
