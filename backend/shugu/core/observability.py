"""Lightweight observability primitives — in-memory counters + rate limits.

Intentionally tiny: no Prometheus client, no pushgateway. We only need to:
  1. Track per-tool_call rate so Hermes can't spam the stage with 50 scene
     changes in a minute.
  2. Keep rolling counters the admin panel can render as a small dashboard.

Everything lives in process memory. If we ever scale past one backend node
we'll need a Redis-backed variant — but v4 is mono-node.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Deque

# ─── Rate limiter ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class RateRule:
    """max_calls per window_s — sliding window."""
    max_calls: int
    window_s: float


# Default rules per body.* tool. Conservative — the LLM agent can still do
# plenty of work per minute, just not 50 scene changes in 3s.
DEFAULT_RULES: dict[str, RateRule] = {
    "body.say":                  RateRule(max_calls=30, window_s=60),
    "body.gesture":              RateRule(max_calls=20, window_s=60),
    "body.scene":                RateRule(max_calls=5,  window_s=60),
    "body.look_at":              RateRule(max_calls=30, window_s=60),
    "body.expression":           RateRule(max_calls=30, window_s=60),
    "body.mood":                 RateRule(max_calls=10, window_s=60),
    "body.emote":                RateRule(max_calls=25, window_s=60),
    "body.shot":                 RateRule(max_calls=10, window_s=60),
}


class SlidingRateLimiter:
    """One-process sliding-window limiter. O(1) amortized per call thanks to
    deque pruning."""

    def __init__(self, rules: dict[str, RateRule] | None = None):
        self._rules = {**DEFAULT_RULES, **(rules or {})}
        self._hits: dict[str, Deque[float]] = defaultdict(deque)

    def check_and_record(self, tool_name: str) -> tuple[bool, float]:
        """Returns (allowed, retry_after_s). Records the hit when allowed."""
        rule = self._rules.get(tool_name)
        if rule is None:
            return True, 0.0
        now = time.monotonic()
        cutoff = now - rule.window_s
        hits = self._hits[tool_name]
        while hits and hits[0] < cutoff:
            hits.popleft()
        if len(hits) >= rule.max_calls:
            retry = (hits[0] + rule.window_s) - now
            return False, max(0.0, retry)
        hits.append(now)
        return True, 0.0

    def snapshot(self) -> dict[str, dict]:
        """Current usage counts per tool, for the metrics endpoint."""
        now = time.monotonic()
        out: dict[str, dict] = {}
        for name, rule in self._rules.items():
            hits = self._hits.get(name)
            if not hits:
                out[name] = {"used": 0, "cap": rule.max_calls, "window_s": rule.window_s}
                continue
            cutoff = now - rule.window_s
            while hits and hits[0] < cutoff:
                hits.popleft()
            out[name] = {"used": len(hits), "cap": rule.max_calls, "window_s": rule.window_s}
        return out


# ─── Metrics collector ───────────────────────────────────────────────────────

@dataclass
class Metrics:
    # Rolling body events per minute (capacity 120 entries = 2min window)
    body_events: Deque[float] = field(default_factory=lambda: deque(maxlen=500))
    desktop_events: Deque[float] = field(default_factory=lambda: deque(maxlen=500))
    tts_ttfb_samples_ms: Deque[int] = field(default_factory=lambda: deque(maxlen=50))
    stream_interrupts: int = 0
    barge_ins: int = 0

    def record_body(self) -> None:
        self.body_events.append(time.monotonic())

    def record_desktop(self) -> None:
        self.desktop_events.append(time.monotonic())

    def record_tts_ttfb(self, ms: int) -> None:
        self.tts_ttfb_samples_ms.append(int(ms))

    def record_interrupt(self) -> None:
        self.stream_interrupts += 1

    def record_barge_in(self) -> None:
        self.barge_ins += 1

    def snapshot(self) -> dict:
        now = time.monotonic()
        win = 60.0
        body_min = sum(1 for t in self.body_events if t > now - win)
        desk_min = sum(1 for t in self.desktop_events if t > now - win)
        samples = list(self.tts_ttfb_samples_ms)
        ttfb = {
            "count": len(samples),
            "p50_ms": _percentile(samples, 0.5),
            "p90_ms": _percentile(samples, 0.9),
            "p99_ms": _percentile(samples, 0.99),
        }
        return {
            "body_events_per_min": body_min,
            "desktop_events_per_min": desk_min,
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
