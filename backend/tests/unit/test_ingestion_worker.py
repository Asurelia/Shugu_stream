"""Tests unitaires : IngestionWorker (PR 1 skeleton + PR 2 record_episode).

Scope :
1. test_ingestion_worker_subscribes_sense_raw_on_start — mock event_bus, vérifie subscribe appelé.
2. test_ingestion_worker_skips_if_memory_disabled — settings.memory_enabled=False → start no-op.
3. test_ingestion_worker_records_episode_on_receive — publish event, vérifie record_episode appelé.
4. test_ingestion_worker_stop_cleans_subscription — vérifie cancel propre + stop.
5. test_ingestion_worker_swallows_record_episode_exception — record_episode raise → worker survit.
6. test_ingestion_worker_swallows_malformed_event — payload sans 'subject' → log warning, pas crash.

Tous les tests sont 100% in-memory — aucune DB, aucun Redis, aucun embedder.
`MemoryServiceMock` satisfait `MemoryService` par structural typing.
"""
from __future__ import annotations

import asyncio
from typing import AsyncIterator
from unittest.mock import AsyncMock

import pytest

from shugu.config import Settings
from shugu.pipeline.ingestion_worker import IngestionWorker

# ─── Helpers / Mocks ────────────────────────────────────────────────────────


class MemoryServiceMock:
    """Mock structurel de MemoryService — satisfait le Protocol sans DB.

    PR 2 ajoute record_episode + recall_episodes côté Protocol — on les expose
    aussi pour que le mock satisfasse le contract complet.
    """

    def __init__(self) -> None:
        self.store = AsyncMock(return_value=None)
        self.recall = AsyncMock(return_value=[])
        self.maintenance = AsyncMock(return_value={})
        self.persona_get = AsyncMock(return_value={})
        self.persona_set = AsyncMock(return_value=None)
        self.record_episode = AsyncMock(return_value=None)
        self.recall_episodes = AsyncMock(return_value=[])


def _make_settings(memory_enabled: bool = True) -> Settings:
    """Construit un Settings isolé (pas de .env) avec le flag désiré.

    Sauvegarde/restaure les env vars modifiées pour ne pas polluer les tests
    suivants (isolation complète).
    """
    import os

    from shugu.config import get_settings

    get_settings.cache_clear()
    # Sauvegarde les valeurs originales avant override.
    old_env_file = os.environ.get("SHUGU_ENV_FILE")
    old_memory = os.environ.get("MEMORY_ENABLED")
    os.environ["SHUGU_ENV_FILE"] = "/nonexistent/.env"
    os.environ["MEMORY_ENABLED"] = "true" if memory_enabled else "false"
    try:
        settings = Settings()
    finally:
        # Restauration exacte (delete si la var n'existait pas avant).
        if old_memory is None:
            os.environ.pop("MEMORY_ENABLED", None)
        else:
            os.environ["MEMORY_ENABLED"] = old_memory
        if old_env_file is None:
            os.environ.pop("SHUGU_ENV_FILE", None)
        else:
            os.environ["SHUGU_ENV_FILE"] = old_env_file
        get_settings.cache_clear()
    return settings


class ControlledEventBus:
    """Bus minimal avec contrôle fin pour les tests : une seule queue par topic."""

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


# ─── Tests ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ingestion_worker_subscribes_sense_raw_on_start() -> None:
    """start() doit déclencher une subscription sur le topic 'sense.raw'."""
    bus = ControlledEventBus()
    memory = MemoryServiceMock()
    settings = _make_settings(memory_enabled=True)

    worker = IngestionWorker(event_bus=bus, memory=memory, settings=settings)
    await worker.start()

    # Laisse la coroutine s'exécuter un tick pour que subscribe soit appelé.
    await asyncio.sleep(0)

    assert "sense.raw" in bus.subscribe_calls, (
        "IngestionWorker n'a pas souscrit au topic 'sense.raw' après start()"
    )

    await worker.stop()


@pytest.mark.asyncio
async def test_ingestion_worker_skips_if_memory_disabled() -> None:
    """Si memory_enabled=False, start() est un no-op : aucune subscription."""
    bus = ControlledEventBus()
    memory = MemoryServiceMock()
    settings = _make_settings(memory_enabled=False)

    worker = IngestionWorker(event_bus=bus, memory=memory, settings=settings)
    await worker.start()

    # Laisse un tick pour voir si subscribe serait appelé.
    await asyncio.sleep(0)

    assert bus.subscribe_calls == [], (
        "IngestionWorker ne devrait PAS souscrire quand memory_enabled=False"
    )
    assert worker._task is None, (
        "Aucune task ne doit être créée quand memory_enabled=False"
    )


@pytest.mark.asyncio
async def test_ingestion_worker_records_episode_on_receive() -> None:
    """PR 2 : un event sense.raw bien formé doit appeler memory.record_episode().

    Le worker construit un MemoryEpisode depuis le payload du bus puis
    invoque l'API publique de l'agent. On vérifie l'appel via le mock.
    """
    bus = ControlledEventBus()
    memory = MemoryServiceMock()
    settings = _make_settings(memory_enabled=True)

    worker = IngestionWorker(event_bus=bus, memory=memory, settings=settings)
    await worker.start()

    # Laisse la subscription s'établir.
    await asyncio.sleep(0)
    assert "sense.raw" in bus.subscribe_calls

    # Event sense.raw conforme au format documenté côté T5 (senses).
    test_event = {
        "subject": "visitor:abc123",
        "event_type": "chat_in",
        "actor": "viewer:spoukie",
        "payload": {"text": "salut !", "ts": "2026-04-24T12:00:00Z"},
        "session_id": "01HX0000000000000000000000",
    }
    await bus.publish("sense.raw", test_event)
    await asyncio.sleep(0.05)

    assert memory.record_episode.await_count == 1, (
        f"record_episode aurait dû être appelé 1 fois, "
        f"got {memory.record_episode.await_count}"
    )
    # Vérifie que l'episode passé a bien les valeurs attendues.
    args, _ = memory.record_episode.call_args
    episode = args[0]
    assert episode.subject == "visitor:abc123"
    assert episode.event_type == "chat_in"
    assert episode.actor == "viewer:spoukie"
    assert episode.payload == {"text": "salut !", "ts": "2026-04-24T12:00:00Z"}
    assert episode.session_id == "01HX0000000000000000000000"
    assert episode.id  # ULID généré par la factory
    assert episode.ts.tzinfo is not None  # tz-aware

    await worker.stop()


@pytest.mark.asyncio
async def test_ingestion_worker_stop_cleans_subscription() -> None:
    """stop() doit annuler la task et retirer la subscription du bus."""
    bus = ControlledEventBus()
    memory = MemoryServiceMock()
    settings = _make_settings(memory_enabled=True)

    worker = IngestionWorker(event_bus=bus, memory=memory, settings=settings)
    await worker.start()

    # Laisse la subscription s'établir.
    await asyncio.sleep(0)
    assert "sense.raw" in bus.subscribe_calls

    # La queue doit exister dans le bus pendant le run.
    assert "sense.raw" in bus._queues

    # Stop propre.
    await worker.stop()

    # Après stop, la task interne ne doit plus tourner.
    assert worker._task is None or worker._task.done(), (
        "La task interne du worker doit être terminée après stop()"
    )

    # La queue a été retirée par le finally du générateur subscribe().
    assert "sense.raw" not in bus._queues, (
        "La subscription sense.raw doit être retirée du bus après stop()"
    )


@pytest.mark.asyncio
async def test_ingestion_worker_swallows_record_episode_exception() -> None:
    """Si record_episode raise, le worker log warning et continue à consommer.

    Best-effort ingestion : un crash DB sur un event ne tue pas la pipeline.
    Le worker doit rester up et traiter les events suivants.
    """
    bus = ControlledEventBus()
    memory = MemoryServiceMock()
    # Premier appel raise, deuxième passe.
    memory.record_episode.side_effect = [RuntimeError("DB down"), None]
    settings = _make_settings(memory_enabled=True)

    worker = IngestionWorker(event_bus=bus, memory=memory, settings=settings)
    await worker.start()
    await asyncio.sleep(0)

    # Premier event — record_episode raise, mais worker swallow.
    await bus.publish("sense.raw", {
        "subject": "visitor:x",
        "event_type": "chat_in",
        "actor": "viewer:x",
        "payload": {"text": "first"},
    })
    await asyncio.sleep(0.05)

    # Deuxième event — record_episode passe, prouve que le worker est encore up.
    await bus.publish("sense.raw", {
        "subject": "visitor:y",
        "event_type": "chat_in",
        "actor": "viewer:y",
        "payload": {"text": "second"},
    })
    await asyncio.sleep(0.05)

    assert memory.record_episode.await_count == 2, (
        f"Worker devrait avoir tenté record_episode sur les 2 events "
        f"(swallow + retry suivant), got {memory.record_episode.await_count}"
    )
    # La task interne doit toujours tourner (pas crash).
    assert worker._task is not None and not worker._task.done()

    await worker.stop()


@pytest.mark.asyncio
async def test_ingestion_worker_swallows_malformed_event() -> None:
    """Un event sans champ obligatoire (subject/event_type/actor) doit être loggué + skip.

    Le worker doit rester up et traiter les events bien formés suivants.
    """
    bus = ControlledEventBus()
    memory = MemoryServiceMock()
    settings = _make_settings(memory_enabled=True)

    worker = IngestionWorker(event_bus=bus, memory=memory, settings=settings)
    await worker.start()
    await asyncio.sleep(0)

    # Event mal formé — manque 'subject'.
    await bus.publish("sense.raw", {
        "event_type": "chat_in",
        "actor": "viewer:x",
        "payload": {"text": "broken"},
    })
    await asyncio.sleep(0.05)
    assert memory.record_episode.await_count == 0, (
        "record_episode ne devrait PAS être appelé pour un event mal formé"
    )

    # Event bien formé suivant — prouve que le worker est encore up.
    await bus.publish("sense.raw", {
        "subject": "visitor:ok",
        "event_type": "chat_in",
        "actor": "viewer:ok",
        "payload": {"text": "good"},
    })
    await asyncio.sleep(0.05)
    assert memory.record_episode.await_count == 1

    await worker.stop()
