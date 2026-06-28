# backend/tests/unit/test_brain_canned.py
"""Tests unit — CannedFallbackBrain (M-0 Task 5)."""
from __future__ import annotations

from shugu.adapters.brain_canned import CannedFallbackBrain
from shugu.director.brain_provider import DirectorBrain


async def test_canned_returns_safe_tag() -> None:
    brain = CannedFallbackBrain()
    assert isinstance(brain, DirectorBrain)
    text = await brain.complete(system="s", user="u")
    assert "[say_emotion:neutral]" in text


async def test_canned_is_deterministic_per_call_rotation() -> None:
    brain = CannedFallbackBrain()
    first = await brain.complete(system="s", user="u")
    second = await brain.complete(system="s", user="u")
    # Rotation pour éviter la répétition exacte consécutive.
    assert first != second
