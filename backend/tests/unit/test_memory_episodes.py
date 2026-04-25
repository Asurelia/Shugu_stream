"""Tests unitaires : MemoryEpisode dataclass + MemoryAgent.record_episode/recall_episodes.

Scope (Mémoire PR 2 — L2 épisodique) :
1. test_memory_episode_new_generates_ulid_and_utc_ts — factory `.new()` OK.
2. test_memory_episode_new_defensive_copy_payload — pas de mutation surprise.
3. test_record_episode_applies_redaction_on_payload_text — redaction Phase 2.6.
4. test_record_episode_inserts_row — INSERT côté session.
5. test_record_episode_publishes_memory_episode_stored — publish bus.
6. test_record_episode_skips_publish_when_no_event_bus — bus None safe.
7. test_record_episode_swallows_event_bus_publish_failure — best-effort.
8. test_redact_payload_walker_handles_nested_dicts_and_lists — helper.
9. test_recall_episodes_basic_filter — limit=0 / window_hours=0 short-circuit.

Tous les tests sont 100% in-memory — aucune DB réelle, on mock le
session_factory pour capturer les calls SQLAlchemy.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from shugu.memory.agent import MemoryAgent, _redact_payload
from shugu.memory.episodes import MemoryEpisode

# ─── Helpers ────────────────────────────────────────────────────────────────


class _FakeSession:
    """Mock minimal d'une AsyncSession pour capturer add() + execute()."""

    def __init__(self) -> None:
        self.added: list = []
        self.executed: list = []
        self.scalar_result_rows: list = []

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        # Rien à committer — la fake ne persiste rien. Le code `async with
        # self._session_factory() as session:` côté agent gère le commit
        # via le contextmanager session_scope ; ici on simule juste le
        # contract sortie sans write réel.
        return None

    def add(self, obj) -> None:
        self.added.append(obj)

    async def execute(self, stmt):
        self.executed.append(stmt)

        class _Result:
            def __init__(self, rows):
                self._rows = rows

            def scalars(self):
                class _Scalars:
                    def __init__(self, rows):
                        self._rows = rows

                    def all(self):
                        return list(self._rows)

                return _Scalars(self._rows)

        return _Result(self.scalar_result_rows)


def _session_factory_with(session: _FakeSession):
    """Construit un session_factory callable retournant `session` à chaque appel."""
    def factory():
        return session
    return factory


# ─── Tests dataclass ────────────────────────────────────────────────────────


def test_memory_episode_new_generates_ulid_and_utc_ts() -> None:
    """Factory `.new()` doit produire un ULID 26-char et un ts UTC tz-aware."""
    ep = MemoryEpisode.new(
        subject="visitor:abc",
        event_type="chat_in",
        actor="viewer:alice",
        payload={"text": "hi"},
    )
    assert isinstance(ep.id, str)
    assert len(ep.id) == 26  # ULID
    assert ep.ts.tzinfo is not None
    # tz-aware UTC : offset == 0
    assert ep.ts.utcoffset().total_seconds() == 0
    assert ep.subject == "visitor:abc"
    assert ep.event_type == "chat_in"
    assert ep.actor == "viewer:alice"
    assert ep.session_id is None
    assert ep.performance_id is None
    assert ep.archived is False
    assert ep.redacted_payload is None


def test_memory_episode_new_defensive_copy_payload() -> None:
    """La factory doit copier le payload pour éviter les mutations surprises."""
    src = {"text": "hi"}
    ep = MemoryEpisode.new(
        subject="x", event_type="chat_in", actor="a", payload=src,
    )
    src["text"] = "MUTATED"
    assert ep.payload == {"text": "hi"}, (
        "MemoryEpisode.new() doit défensivement copier le payload"
    )


# ─── Tests record_episode ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_record_episode_applies_redaction_on_payload_text() -> None:
    """Phase 2.6 redaction doit nettoyer le payload côté record_episode.

    On injecte une clé Anthropic dans le payload — record_episode doit
    générer un `redacted_payload` non-None contenant `[REDACTED:...]`.
    """
    session = _FakeSession()
    agent = MemoryAgent(session_factory=_session_factory_with(session))
    ep = MemoryEpisode.new(
        subject="visitor:x",
        event_type="chat_in",
        actor="viewer:x",
        payload={"text": "key=sk-ant-api03-" + "x" * 90},
    )
    await agent.record_episode(ep)

    assert len(session.added) == 1
    row = session.added[0]
    # Payload brut conservé pour audit.
    assert "sk-ant-api03-" in row.payload["text"]
    # Redacted payload nettoyé.
    assert row.redacted_payload is not None
    assert "[REDACTED:ANTHROPIC_API_KEY]" in row.redacted_payload["text"]


@pytest.mark.asyncio
async def test_record_episode_inserts_row() -> None:
    """L'épisode doit être ajouté en session via session.add()."""
    session = _FakeSession()
    agent = MemoryAgent(session_factory=_session_factory_with(session))
    ep = MemoryEpisode.new(
        subject="visitor:abc",
        event_type="chat_in",
        actor="viewer:alice",
        payload={"text": "hi"},
        session_id="01HX0000000000000000000000",
    )
    await agent.record_episode(ep)

    assert len(session.added) == 1
    row = session.added[0]
    assert row.id == ep.id
    assert row.subject == "visitor:abc"
    assert row.event_type == "chat_in"
    assert row.actor == "viewer:alice"
    assert row.payload == {"text": "hi"}
    assert row.session_id == "01HX0000000000000000000000"
    # Pas de secrets → redacted_payload None (NULL côté DB = identique).
    assert row.redacted_payload is None


@pytest.mark.asyncio
async def test_record_episode_publishes_memory_episode_stored() -> None:
    """Après l'INSERT, l'agent doit publier `memory.episode_stored` sur le bus."""
    session = _FakeSession()
    bus = MagicMock()
    bus.publish = AsyncMock(return_value=None)
    agent = MemoryAgent(
        session_factory=_session_factory_with(session),
        event_bus=bus,
    )
    ep = MemoryEpisode.new(
        subject="visitor:bob",
        event_type="chat_in",
        actor="viewer:bob",
        payload={"text": "hello"},
    )
    await agent.record_episode(ep)

    assert bus.publish.await_count == 1
    args, _ = bus.publish.call_args
    topic, payload = args
    assert topic == "memory.episode_stored"
    assert payload["episode_id"] == ep.id
    assert payload["subject"] == "visitor:bob"
    assert payload["event_type"] == "chat_in"
    assert payload["actor"] == "viewer:bob"
    assert payload["had_redaction"] is False  # pas de secrets


@pytest.mark.asyncio
async def test_record_episode_skips_publish_when_no_event_bus() -> None:
    """Si event_bus=None (mode test sans bus), record_episode doit fonctionner sans publish."""
    session = _FakeSession()
    agent = MemoryAgent(session_factory=_session_factory_with(session))  # event_bus=None par défaut
    ep = MemoryEpisode.new(
        subject="x", event_type="chat_in", actor="a", payload={"text": "hi"},
    )
    # Ne doit pas raise.
    await agent.record_episode(ep)
    assert len(session.added) == 1


@pytest.mark.asyncio
async def test_record_episode_swallows_event_bus_publish_failure() -> None:
    """Si bus.publish raise, record_episode log warning + ne re-raise PAS.

    L'INSERT a déjà eu lieu (row dans session.added), un crash bus ne doit
    pas casser l'ingestion.
    """
    session = _FakeSession()
    bus = MagicMock()
    bus.publish = AsyncMock(side_effect=RuntimeError("redis down"))
    agent = MemoryAgent(
        session_factory=_session_factory_with(session),
        event_bus=bus,
    )
    ep = MemoryEpisode.new(
        subject="x", event_type="chat_in", actor="a", payload={"text": "hi"},
    )
    # Ne doit pas raise.
    await agent.record_episode(ep)
    # L'INSERT a bien eu lieu malgré le crash bus.
    assert len(session.added) == 1
    assert bus.publish.await_count == 1


# ─── Tests _redact_payload helper ──────────────────────────────────────────


def test_redact_payload_walker_handles_nested_dicts_and_lists() -> None:
    """Le helper doit traverser les structures imbriquées et redacter les strings."""
    payload = {
        "outer": {
            "text": "ma clé sk-ant-api03-" + "x" * 90,
            "nested": [
                "ssh-rsa AAAA" + "x" * 30,
                {"deep": "rien à voir"},
                42,
                None,
            ],
        },
        "harmless": 123,
    }
    cleaned, cats = _redact_payload(payload)
    assert "ANTHROPIC_API_KEY" in cats
    assert "SSH_PUBLIC_KEY" in cats
    assert "[REDACTED:ANTHROPIC_API_KEY]" in cleaned["outer"]["text"]
    assert "[REDACTED:SSH_PUBLIC_KEY]" in cleaned["outer"]["nested"][0]
    # Structure préservée (dicts imbriqués + types non-string passthrough).
    assert cleaned["outer"]["nested"][1] == {"deep": "rien à voir"}
    assert cleaned["outer"]["nested"][2] == 42
    assert cleaned["outer"]["nested"][3] is None
    assert cleaned["harmless"] == 123


def test_redact_payload_no_secrets_returns_empty_categories() -> None:
    """Pas de secret = pas de catégories. Cleaned doit être structurellement égal."""
    payload = {"text": "hi", "nested": ["bonjour", 1]}
    cleaned, cats = _redact_payload(payload)
    assert cats == []
    assert cleaned == payload
    # Mais cleaned est une copie défensive — on peut muter sans toucher payload.
    cleaned["text"] = "MUTATED"
    assert payload["text"] == "hi"


# ─── Tests recall_episodes ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_recall_episodes_short_circuits_on_zero_limit() -> None:
    """limit=0 → retour immédiat sans toucher la DB."""
    session = _FakeSession()
    agent = MemoryAgent(session_factory=_session_factory_with(session))
    out = await agent.recall_episodes("visitor:x", limit=0)
    assert out == []
    assert session.executed == []


@pytest.mark.asyncio
async def test_recall_episodes_short_circuits_on_zero_window() -> None:
    """window_hours=0 → retour immédiat sans toucher la DB.

    Garde-fou : un caller qui passe `0` par erreur ne doit pas DDOS la DB
    avec une fenêtre vide qui scannerait toute la table.
    """
    session = _FakeSession()
    agent = MemoryAgent(session_factory=_session_factory_with(session))
    out = await agent.recall_episodes("visitor:x", window_hours=0)
    assert out == []
    assert session.executed == []


@pytest.mark.asyncio
async def test_recall_episodes_returns_dataclasses_from_rows() -> None:
    """Avec des rows mockées, recall_episodes doit retourner des MemoryEpisode."""
    from shugu.memory.models import MemoryEpisodeRow

    # Construction d'une row mock (attribute access uniquement, pas d'INSERT).
    row = MemoryEpisodeRow(
        id="01HX0000000000000000000000",
        ts=datetime(2026, 4, 24, 12, 0, 0, tzinfo=timezone.utc),
        subject="visitor:x",
        session_id=None,
        event_type="chat_in",
        actor="viewer:x",
        payload={"text": "hi"},
        redacted_payload=None,
        performance_id=None,
        archived=False,
    )
    session = _FakeSession()
    session.scalar_result_rows = [row]
    agent = MemoryAgent(session_factory=_session_factory_with(session))

    out = await agent.recall_episodes("visitor:x", window_hours=24, limit=10)
    assert len(out) == 1
    assert isinstance(out[0], MemoryEpisode)
    assert out[0].id == "01HX0000000000000000000000"
    assert out[0].subject == "visitor:x"
    assert out[0].event_type == "chat_in"
    assert out[0].payload == {"text": "hi"}
    assert out[0].ts.tzinfo is not None
