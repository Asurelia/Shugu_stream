# backend/tests/unit/test_brain_resilient.py
"""Tests unit — ResilientDirectorBrain (M-0 Task 6)."""
from __future__ import annotations

from shugu.director.brain_provider import DirectorBrainError
from shugu.director.brain_resilient import ResilientDirectorBrain


class _StubBrain:
    def __init__(self, *, text=None, error=False):
        self._text = text
        self._error = error
        self.calls = 0

    async def complete(self, *, system: str, user: str) -> str:
        self.calls += 1
        if self._error:
            raise DirectorBrainError("stub fail")
        return self._text


async def test_uses_primary_when_ok() -> None:
    primary = _StubBrain(text="m3 ok")
    fallback = _StubBrain(text="ollama")
    canned = _StubBrain(text="canned")
    brain = ResilientDirectorBrain(primary=primary, fallback=fallback, canned=canned)
    assert await brain.complete(system="s", user="u") == "m3 ok"
    assert fallback.calls == 0


async def test_falls_back_to_ollama_after_threshold() -> None:
    primary = _StubBrain(error=True)
    fallback = _StubBrain(text="ollama")
    canned = _StubBrain(text="canned")
    brain = ResilientDirectorBrain(
        primary=primary, fallback=fallback, canned=canned, failure_threshold=2
    )
    # 1er échec : tente quand même le primary, tombe sur fallback
    assert await brain.complete(system="s", user="u") == "ollama"
    # après le seuil, on saute directement le primary
    await brain.complete(system="s", user="u")
    calls_before = primary.calls
    await brain.complete(system="s", user="u")
    assert primary.calls == calls_before  # primary court-circuité


async def test_falls_back_to_canned_when_all_fail() -> None:
    brain = ResilientDirectorBrain(
        primary=_StubBrain(error=True),
        fallback=_StubBrain(error=True),
        canned=_StubBrain(text="[say_emotion:neutral] hmm"),
    )
    assert "neutral" in await brain.complete(system="s", user="u")
