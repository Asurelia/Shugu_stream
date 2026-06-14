"""Tests unit — fonctions pures de bench_m3 (M-0 Task 8)."""
from __future__ import annotations

from tools.bench_m3 import cost_usd, summarize


def test_cost_usd_under_512k() -> None:
    # 1M input @ 0.30, 1M output @ 1.20
    assert round(cost_usd(in_tokens=1_000_000, out_tokens=0), 4) == 0.30
    assert round(cost_usd(in_tokens=0, out_tokens=1_000_000), 4) == 1.20


def test_summarize_computes_p50() -> None:
    samples = [{"ttfb_s": 1.0, "in": 10, "out": 5},
               {"ttfb_s": 3.0, "in": 10, "out": 5},
               {"ttfb_s": 2.0, "in": 10, "out": 5}]
    s = summarize(samples)
    assert s["ttfb_p50_s"] == 2.0
    assert s["n"] == 3
