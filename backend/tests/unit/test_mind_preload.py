"""Tests unit — pré-warm fallback Gemma (M-0 Task 9)."""
from __future__ import annotations

from shugu.mind.preload import should_preload_fallback


def test_no_preload_when_flag_off() -> None:
    assert should_preload_fallback(preload=False, provider="m3") is False


def test_preload_only_for_m3_provider() -> None:
    assert should_preload_fallback(preload=True, provider="m3") is True
    assert should_preload_fallback(preload=True, provider="minimax") is False
