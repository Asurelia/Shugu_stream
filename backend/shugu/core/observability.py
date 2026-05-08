"""Lightweight observability primitives — in-memory counters.

Intentionally tiny: no Prometheus client, no pushgateway. We only need to:
  1. Keep rolling counters the admin panel can render as a small dashboard.

Everything lives in process memory. If we ever scale past one backend node
we'll need a Redis-backed variant — but v4 is mono-node.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Deque

# ─── Metrics collector ───────────────────────────────────────────────────────

@dataclass
class Metrics:
    tts_ttfb_samples_ms: Deque[int] = field(default_factory=lambda: deque(maxlen=50))
    stream_interrupts: int = 0
    barge_ins: int = 0

    def record_tts_ttfb(self, ms: int) -> None:
        self.tts_ttfb_samples_ms.append(int(ms))

    def record_interrupt(self) -> None:
        self.stream_interrupts += 1

    def record_barge_in(self) -> None:
        self.barge_ins += 1

    def snapshot(self) -> dict:
        samples = list(self.tts_ttfb_samples_ms)
        ttfb = {
            "count": len(samples),
            "p50_ms": _percentile(samples, 0.5),
            "p90_ms": _percentile(samples, 0.9),
            "p99_ms": _percentile(samples, 0.99),
        }
        return {
            "tts_ttfb": ttfb,
            "stream_interrupts_total": self.stream_interrupts,
            "barge_ins_total": self.barge_ins,
        }


def _percentile(values: list[int], p: float) -> int | None:
    if not values:
        return None
    s = sorted(values)
    idx = min(len(s) - 1, int(p * len(s)))
    return s[idx]
