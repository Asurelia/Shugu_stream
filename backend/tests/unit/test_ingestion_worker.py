"""Tests unitaires : IngestionWorker skeleton (PR 1 Mémoire).

Scope :
1. test_ingestion_worker_subscribes_sense_raw_on_start — mock event_bus, vérifie subscribe appelé.
2. test_ingestion_worker_skips_if_memory_disabled — settings.memory_enabled=False → start no-op.
3. test_ingestion_worker_logs_event_on_receive — publish event, vérifie log.
4. test_ingestion_worker_stop_cleans_subscription — vérifie cancel propre + stop.

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
    """Mock structurel de MemoryService — satisfait le Protocol sans DB."""

    def __init__(self) -> None:
        self.store = AsyncMock(return_value=None)
        self.recall = AsyncMock(return_value=[])
        self.maintenance = AsyncMock(return_value={})
        self.persona_get = AsyncMock(return_value={})
        self.persona_set = AsyncMock(return_value=None)


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
async def test_ingestion_worker_logs_event_on_receive(capfd) -> None:
    """Un event publié sur sense.raw doit être loggué par le worker.

    Note : structlog écrit via ses propres processors (pas stdlib logging).
    On capture stdout pour vérifier que la clef de log apparaît bien.
    """
    bus = ControlledEventBus()
    memory = MemoryServiceMock()
    settings = _make_settings(memory_enabled=True)

    worker = IngestionWorker(event_bus=bus, memory=memory, settings=settings)
    await worker.start()

    # Laisse la subscription s'établir.
    await asyncio.sleep(0)
    assert "sense.raw" in bus.subscribe_calls

    # Publie un event et laisse le worker le consommer.
    test_event = {"type": "chat_message", "text": "bonjour"}
    await bus.publish("sense.raw", test_event)
    await asyncio.sleep(0.05)

    # Capture stdout (structlog écrit ici via ConsoleRenderer).
    captured = capfd.readouterr()
    combined = captured.out + captured.err
    assert "ingestion_worker_event_received" in combined or "sense.raw" in combined, (
        f"Le worker n'a pas loggué l'event reçu. Sortie capturée : {combined!r}"
    )

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
