"""Tests unit pour LoggingModeration (décorateur ModerationLayer).

Tests purement unit (pas de DB) :
- allowed → ne persist pas (pas d'appel session_scope)
- fail-open → une DB down ne brise pas le pipeline

Tests d'intégration (nécessitent Postgres) :
  → voir tests/integration/test_admin_moderation_routes.py
"""
from __future__ import annotations

import pytest

from shugu.adapters.moderation_logging import LoggingModeration
from shugu.core.identity import VisitorIdentity
from shugu.core.protocols import ModerationLayer, ModerationVerdict


class FakeInner(ModerationLayer):
    """Stub ModerationLayer retournant un verdict fixe."""

    def __init__(self, verdict: ModerationVerdict):
        self._verdict = verdict
        self.ingress_calls = 0
        self.egress_calls = 0

    async def check_ingress(self, text, identity):
        self.ingress_calls += 1
        return self._verdict

    async def check_egress(self, text, identity):
        self.egress_calls += 1
        return self._verdict


def _visitor() -> VisitorIdentity:
    return VisitorIdentity(ip_hash="a" * 64, session_id="sess-1")


@pytest.mark.asyncio
async def test_check_ingress_allowed_does_not_call_session_scope(monkeypatch):
    """allowed=True → _persist n'est jamais appelé, session_scope non touché."""
    calls: list = []

    from shugu.adapters import moderation_logging as mod

    class NeverSession:
        async def __aenter__(self):
            calls.append("entered")
            raise AssertionError("session_scope should not be called for allowed verdict")

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(mod, "session_scope", lambda: NeverSession())

    inner = FakeInner(ModerationVerdict(allowed=True))
    layer = LoggingModeration(inner)

    verdict = await layer.check_ingress("hello", _visitor())

    assert verdict.allowed is True
    assert inner.ingress_calls == 1
    assert calls == []


@pytest.mark.asyncio
async def test_check_egress_allowed_does_not_call_session_scope(monkeypatch):
    """egress allowed=True → session_scope non touché."""
    from shugu.adapters import moderation_logging as mod

    class NeverSession:
        async def __aenter__(self):
            raise AssertionError("should not persist allowed verdict")

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(mod, "session_scope", lambda: NeverSession())

    inner = FakeInner(ModerationVerdict(allowed=True))
    layer = LoggingModeration(inner)

    verdict = await layer.check_egress("response text", _visitor())

    assert verdict.allowed is True
    assert inner.egress_calls == 1


@pytest.mark.asyncio
async def test_persist_failure_does_not_break_pipeline(monkeypatch):
    """DB down → verdict quand même retourné + warning structlog émis."""
    from shugu.adapters import moderation_logging as mod

    class BoomSession:
        async def __aenter__(self):
            raise RuntimeError("db down")

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(mod, "session_scope", lambda: BoomSession())

    verdict = ModerationVerdict(allowed=False, reason="x", detector="profanity")
    layer = LoggingModeration(FakeInner(verdict))

    result = await layer.check_ingress("foo", _visitor())

    assert result.allowed is False  # pipeline non interrompu


@pytest.mark.asyncio
async def test_inner_verdict_returned_unchanged_for_refused(monkeypatch):
    """Le verdict refused est renvoyé tel quel même si persist réussit."""
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock, MagicMock

    from shugu.adapters import moderation_logging as mod

    @asynccontextmanager
    async def fake_scope():
        sess = MagicMock()
        sess.execute = AsyncMock()
        yield sess

    monkeypatch.setattr(mod, "session_scope", fake_scope)

    verdict = ModerationVerdict(allowed=False, reason="hate speech", detector="profanity")
    layer = LoggingModeration(FakeInner(verdict))

    result = await layer.check_ingress("bad text", _visitor())

    assert result is verdict  # même objet retourné


@pytest.mark.asyncio
async def test_inner_is_called_for_both_phases(monkeypatch):
    """check_ingress et check_egress délèguent bien à l'inner."""
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock, MagicMock

    from shugu.adapters import moderation_logging as mod

    @asynccontextmanager
    async def fake_scope():
        sess = MagicMock()
        sess.execute = AsyncMock()
        yield sess

    monkeypatch.setattr(mod, "session_scope", fake_scope)

    inner = FakeInner(ModerationVerdict(allowed=False, reason="test", detector="test"))
    layer = LoggingModeration(inner)

    await layer.check_ingress("text", _visitor())
    await layer.check_egress("text", _visitor())

    assert inner.ingress_calls == 1
    assert inner.egress_calls == 1
