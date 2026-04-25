"""Tests unitaires : ExtractionWorker (PR 3 Mémoire).

Scope (≥7 tests) :
1. test_extraction_worker_subscribes_episode_stored_on_start
   — start() déclenche une subscription sur 'memory.episode_stored'.
2. test_extraction_worker_skips_if_fact_extractor_disabled
   — fact_extractor_enabled=False → start() no-op.
3. test_extraction_worker_skips_if_memory_disabled
   — memory_enabled=False → start() no-op.
4. test_extraction_worker_extracts_and_stores_facts_on_chat_in
   — event chat_in avec texte → fact_extractor.extract() appelé,
   memory.store() appelé pour chaque fact retourné.
5. test_extraction_worker_skip_event_without_text
   — event sans champ 'text' dans le payload → skip silencieux, aucun store.
6. test_extraction_worker_skip_non_text_event_type
   — event_type=tool_call → skip silencieux (pas de langage naturel libre).
7. test_extraction_worker_exception_in_extractor_does_not_crash_worker
   — fact_extractor.extract() raise → warning loggué, worker reste up.
8. test_extraction_worker_stop_cleans_subscription
   — stop() annule la task et retire la subscription.
9. test_extraction_worker_uses_redacted_payload_over_raw
   — si 'redacted_payload' présent dans l'event, c'est lui qui est prioritaire.
10. test_extraction_worker_voice_in_event_type_extracted
    — event_type=voice_in est traité comme chat_in.

Tous 100% in-memory — aucune DB, aucun Redis, aucun embedder.
"""
from __future__ import annotations

import asyncio
import os
from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest

from shugu.config import Settings
from shugu.memory.extractors.pipeline import FactExtractor
from shugu.memory.types import MemoryItem
from shugu.pipeline.extraction_worker import ExtractionWorker

# ─── Helpers / Mocks ────────────────────────────────────────────────────────


class MemoryServiceMock:
    """Mock structurel de MemoryService — satisfait le Protocol sans DB."""

    def __init__(self) -> None:
        self.store = AsyncMock(return_value=None)
        self.recall = AsyncMock(return_value=[])
        self.maintenance = AsyncMock(return_value={})
        self.persona_get = AsyncMock(return_value={})
        self.persona_set = AsyncMock(return_value=None)
        self.record_episode = AsyncMock(return_value=None)
        self.recall_episodes = AsyncMock(return_value=[])


class ControlledEventBus:
    """Bus minimal avec contrôle fin — une seule queue par topic."""

    def __init__(self) -> None:
        self._queues: dict[str, asyncio.Queue] = {}
        self.subscribe_calls: list[str] = []

    async def subscribe(self, topic: str) -> AsyncIterator[dict]:
        self.subscribe_calls.append(topic)
        q: asyncio.Queue = asyncio.Queue()
        self._queues[topic] = q
        try:
            while True:
                ev = await q.get()
                yield ev
        finally:
            self._queues.pop(topic, None)

    async def publish(self, topic: str, event: dict) -> None:
        if topic in self._queues:
            await self._queues[topic].put(event)

    async def close(self) -> None:
        pass


def _make_settings(memory_enabled: bool = True, fact_extractor_enabled: bool = True) -> Settings:
    """Construit un Settings isolé avec les flags désirés."""
    from shugu.config import get_settings

    get_settings.cache_clear()
    old_env_file = os.environ.get("SHUGU_ENV_FILE")
    old_memory = os.environ.get("MEMORY_ENABLED")
    old_fact = os.environ.get("FACT_EXTRACTOR_ENABLED")
    os.environ["SHUGU_ENV_FILE"] = "/nonexistent/.env"
    os.environ["MEMORY_ENABLED"] = "true" if memory_enabled else "false"
    os.environ["FACT_EXTRACTOR_ENABLED"] = "true" if fact_extractor_enabled else "false"
    # ip_hash_salt requis en non-ci env ; on simule ci.
    os.environ.setdefault("ENV", "ci")
    os.environ.setdefault("IP_HASH_SALT", "ci-test-salt-not-secret")
    try:
        settings = Settings()
    finally:
        if old_memory is None:
            os.environ.pop("MEMORY_ENABLED", None)
        else:
            os.environ["MEMORY_ENABLED"] = old_memory
        if old_fact is None:
            os.environ.pop("FACT_EXTRACTOR_ENABLED", None)
        else:
            os.environ["FACT_EXTRACTOR_ENABLED"] = old_fact
        if old_env_file is None:
            os.environ.pop("SHUGU_ENV_FILE", None)
        else:
            os.environ["SHUGU_ENV_FILE"] = old_env_file
        get_settings.cache_clear()
    return settings


def _make_fact_extractor_mock(items=None):
    """Retourne un mock de FactExtractor avec une valeur de retour contrôlée."""
    mock = MagicMock(spec=FactExtractor)
    mock.extract = AsyncMock(return_value=items or [])
    return mock


def _make_memory_item(text: str = "name: Alice", subject: str = "visitor:test") -> MemoryItem:
    """Construit un MemoryItem minimal pour les tests."""
    from datetime import datetime, timezone

    from ulid import ULID
    return MemoryItem(
        id=str(ULID()),
        kind="fact",
        subject=subject,
        text=text,
        confidence=0.6,
        source="extraction_regex",
        created_at=datetime.now(timezone.utc),
    )


# ─── Tests ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_extraction_worker_subscribes_episode_stored_on_start() -> None:
    """start() doit déclencher une subscription sur 'memory.episode_stored'."""
    bus = ControlledEventBus()
    memory = MemoryServiceMock()
    extractor = _make_fact_extractor_mock()
    settings = _make_settings()

    worker = ExtractionWorker(
        event_bus=bus, memory=memory, fact_extractor=extractor, settings=settings
    )
    await worker.start()

    # Laisse la coroutine s'exécuter un tick pour que subscribe soit appelé.
    await asyncio.sleep(0)

    assert "memory.episode_stored" in bus.subscribe_calls, (
        "ExtractionWorker n'a pas souscrit au topic 'memory.episode_stored' après start()"
    )

    await worker.stop()


@pytest.mark.asyncio
async def test_extraction_worker_skips_if_fact_extractor_disabled() -> None:
    """fact_extractor_enabled=False → start() no-op, aucune subscription."""
    bus = ControlledEventBus()
    memory = MemoryServiceMock()
    extractor = _make_fact_extractor_mock()
    settings = _make_settings(fact_extractor_enabled=False)

    worker = ExtractionWorker(
        event_bus=bus, memory=memory, fact_extractor=extractor, settings=settings
    )
    await worker.start()
    await asyncio.sleep(0)

    assert bus.subscribe_calls == [], (
        "ExtractionWorker ne devrait PAS souscrire quand fact_extractor_enabled=False"
    )
    assert worker._task is None


@pytest.mark.asyncio
async def test_extraction_worker_skips_if_memory_disabled() -> None:
    """memory_enabled=False → start() no-op, aucune subscription."""
    bus = ControlledEventBus()
    memory = MemoryServiceMock()
    extractor = _make_fact_extractor_mock()
    settings = _make_settings(memory_enabled=False, fact_extractor_enabled=True)

    worker = ExtractionWorker(
        event_bus=bus, memory=memory, fact_extractor=extractor, settings=settings
    )
    await worker.start()
    await asyncio.sleep(0)

    assert bus.subscribe_calls == [], (
        "ExtractionWorker ne devrait PAS souscrire quand memory_enabled=False"
    )
    assert worker._task is None


@pytest.mark.asyncio
async def test_extraction_worker_extracts_and_stores_facts_on_chat_in() -> None:
    """event chat_in avec texte → extractor appelé + memory.store pour chaque fact."""
    bus = ControlledEventBus()
    memory = MemoryServiceMock()
    item = _make_memory_item("name: Alice")
    extractor = _make_fact_extractor_mock(items=[item])
    settings = _make_settings()

    worker = ExtractionWorker(
        event_bus=bus, memory=memory, fact_extractor=extractor, settings=settings
    )
    await worker.start()
    await asyncio.sleep(0)

    event = {
        "episode_id": "01HX0000000000000000000000",
        "subject": "visitor:abc123",
        "event_type": "chat_in",
        "actor": "viewer:alice",
        "ts": "2026-04-24T12:00:00Z",
        "had_redaction": False,
        "payload": {"text": "je m'appelle Alice", "ts": "2026-04-24T12:00:00Z"},
        "redacted_payload": {"text": "je m'appelle Alice", "ts": "2026-04-24T12:00:00Z"},
    }
    await bus.publish("memory.episode_stored", event)
    await asyncio.sleep(0.05)

    # fact_extractor.extract doit avoir été appelé avec le bon texte et subject.
    extractor.extract.assert_called_once()
    call_kwargs = extractor.extract.call_args
    assert call_kwargs[0][0] == "je m'appelle Alice"
    assert call_kwargs[1]["subject"] == "visitor:abc123"

    # memory.store doit avoir été appelé pour le seul fact retourné.
    assert memory.store.await_count == 1
    stored_item = memory.store.call_args[0][0]
    assert stored_item.text == "name: Alice"

    await worker.stop()


@pytest.mark.asyncio
async def test_extraction_worker_skip_event_without_text() -> None:
    """Event sans champ 'text' dans le payload → skip silencieux, aucun store."""
    bus = ControlledEventBus()
    memory = MemoryServiceMock()
    extractor = _make_fact_extractor_mock(items=[_make_memory_item()])
    settings = _make_settings()

    worker = ExtractionWorker(
        event_bus=bus, memory=memory, fact_extractor=extractor, settings=settings
    )
    await worker.start()
    await asyncio.sleep(0)

    # Payload de type tool_call — pas de champ 'text'.
    event = {
        "episode_id": "01HX0000000000000000000001",
        "subject": "visitor:abc123",
        "event_type": "chat_in",
        "actor": "viewer:alice",
        "ts": "2026-04-24T12:00:00Z",
        "had_redaction": False,
        "payload": {"gesture": "wave", "intensity": 0.8},
        "redacted_payload": {"gesture": "wave", "intensity": 0.8},
    }
    await bus.publish("memory.episode_stored", event)
    await asyncio.sleep(0.05)

    extractor.extract.assert_not_called()
    assert memory.store.await_count == 0

    await worker.stop()


@pytest.mark.asyncio
async def test_extraction_worker_skip_non_text_event_type() -> None:
    """event_type=tool_call → skip silencieux (pas de langage naturel libre)."""
    bus = ControlledEventBus()
    memory = MemoryServiceMock()
    extractor = _make_fact_extractor_mock(items=[_make_memory_item()])
    settings = _make_settings()

    worker = ExtractionWorker(
        event_bus=bus, memory=memory, fact_extractor=extractor, settings=settings
    )
    await worker.start()
    await asyncio.sleep(0)

    event = {
        "episode_id": "01HX0000000000000000000002",
        "subject": "shugu",
        "event_type": "tool_call",
        "actor": "hermes",
        "ts": "2026-04-24T12:00:00Z",
        "had_redaction": False,
        "payload": {"text": "body.gesture wave", "tool": "gesture"},
        "redacted_payload": {"text": "body.gesture wave", "tool": "gesture"},
    }
    await bus.publish("memory.episode_stored", event)
    await asyncio.sleep(0.05)

    extractor.extract.assert_not_called()
    assert memory.store.await_count == 0

    await worker.stop()


@pytest.mark.asyncio
async def test_extraction_worker_exception_in_extractor_does_not_crash_worker() -> None:
    """Exception dans fact_extractor.extract → warning + worker reste up.

    Best-effort : un crash sur un event ne tue pas la pipeline. Le worker
    doit rester up et traiter les events suivants.
    """
    bus = ControlledEventBus()
    memory = MemoryServiceMock()
    item_ok = _make_memory_item("preference: matcha")
    extractor = _make_fact_extractor_mock()
    # Premier appel raise, deuxième retourne un item.
    extractor.extract.side_effect = [RuntimeError("LLM timeout"), [item_ok]]
    settings = _make_settings()

    worker = ExtractionWorker(
        event_bus=bus, memory=memory, fact_extractor=extractor, settings=settings
    )
    await worker.start()
    await asyncio.sleep(0)

    # Event 1 — extractor raise.
    event_base = {
        "episode_id": "01HX0000000000000000000003",
        "subject": "visitor:abc123",
        "event_type": "chat_in",
        "actor": "viewer:alice",
        "ts": "2026-04-24T12:00:00Z",
        "had_redaction": False,
        "payload": {"text": "premier message"},
        "redacted_payload": {"text": "premier message"},
    }
    await bus.publish("memory.episode_stored", event_base)
    await asyncio.sleep(0.05)
    assert memory.store.await_count == 0

    # Event 2 — extractor retourne un item, prouve que le worker est encore up.
    event_ok = {**event_base, "episode_id": "01HX0000000000000000000004",
                "payload": {"text": "deuxième message"},
                "redacted_payload": {"text": "deuxième message"}}
    await bus.publish("memory.episode_stored", event_ok)
    await asyncio.sleep(0.05)
    assert memory.store.await_count == 1

    # Task doit toujours tourner.
    assert worker._task is not None and not worker._task.done()

    await worker.stop()


@pytest.mark.asyncio
async def test_extraction_worker_stop_cleans_subscription() -> None:
    """stop() annule la task et retire la subscription du bus."""
    bus = ControlledEventBus()
    memory = MemoryServiceMock()
    extractor = _make_fact_extractor_mock()
    settings = _make_settings()

    worker = ExtractionWorker(
        event_bus=bus, memory=memory, fact_extractor=extractor, settings=settings
    )
    await worker.start()
    await asyncio.sleep(0)

    assert "memory.episode_stored" in bus._queues

    await worker.stop()

    assert worker._task is None or worker._task.done()
    assert "memory.episode_stored" not in bus._queues, (
        "La subscription memory.episode_stored doit être retirée du bus après stop()"
    )


@pytest.mark.asyncio
async def test_extraction_worker_uses_redacted_payload_over_raw() -> None:
    """redacted_payload présent → prioritaire sur payload brut pour l'extraction."""
    bus = ControlledEventBus()
    memory = MemoryServiceMock()
    extractor = _make_fact_extractor_mock()
    extractor.extract = AsyncMock(return_value=[])
    settings = _make_settings()

    worker = ExtractionWorker(
        event_bus=bus, memory=memory, fact_extractor=extractor, settings=settings
    )
    await worker.start()
    await asyncio.sleep(0)

    event = {
        "episode_id": "01HX0000000000000000000005",
        "subject": "visitor:abc123",
        "event_type": "chat_in",
        "actor": "viewer:alice",
        "ts": "2026-04-24T12:00:00Z",
        "had_redaction": True,
        # payload brut contient le secret, redacted_payload est nettoyé.
        "payload": {"text": "my key is sk-ant-api03-XXXX and I love matcha"},
        "redacted_payload": {"text": "my key is [REDACTED:ANTHROPIC_API_KEY] and I love matcha"},
    }
    await bus.publish("memory.episode_stored", event)
    await asyncio.sleep(0.05)

    # Le texte passé à extract doit être celui du redacted_payload, pas du payload brut.
    extractor.extract.assert_called_once()
    text_arg = extractor.extract.call_args[0][0]
    assert "[REDACTED:ANTHROPIC_API_KEY]" in text_arg, (
        f"Expected redacted text, got: {text_arg!r}"
    )

    await worker.stop()


@pytest.mark.asyncio
async def test_extraction_worker_voice_in_event_type_extracted() -> None:
    """event_type=voice_in est traité comme chat_in (transcript STT)."""
    bus = ControlledEventBus()
    memory = MemoryServiceMock()
    item = _make_memory_item("preference: matcha")
    extractor = _make_fact_extractor_mock(items=[item])
    settings = _make_settings()

    worker = ExtractionWorker(
        event_bus=bus, memory=memory, fact_extractor=extractor, settings=settings
    )
    await worker.start()
    await asyncio.sleep(0)

    event = {
        "episode_id": "01HX0000000000000000000006",
        "subject": "operator:alice",
        "event_type": "voice_in",
        "actor": "operator:alice",
        "ts": "2026-04-24T12:00:00Z",
        "had_redaction": False,
        "payload": {"text": "j'adore le matcha", "ts": "2026-04-24T12:00:00Z"},
        "redacted_payload": {"text": "j'adore le matcha", "ts": "2026-04-24T12:00:00Z"},
    }
    await bus.publish("memory.episode_stored", event)
    await asyncio.sleep(0.05)

    extractor.extract.assert_called_once()
    assert memory.store.await_count == 1

    await worker.stop()
