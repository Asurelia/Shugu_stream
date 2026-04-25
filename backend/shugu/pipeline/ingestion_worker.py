"""IngestionWorker — récolte les events `sense.raw` et les transforme en épisodes mémoire.

PR 1 : skeleton. Subscribe le topic `sense.raw`, logue chaque event reçu.
PR 2 ajoutera : `await self._memory.store(...)` via `record_episode`.

Design :
- Même pattern lifecycle que `AmbientDaemon` : `start()` / `run()` / `stop()`.
- Si `settings.memory_enabled is False`, `start()` est un no-op silencieux.
- Pas d'état persistant côté worker : la mémoire vit dans `MemoryAgent`/DB.
- L'annulation de la task asyncio déclenche le `finally` du générateur
  `subscribe()` qui retire proprement la queue du bus (garantie par les deux
  impls `InProcessEventBus` et `RedisEventBus`).
"""
from __future__ import annotations

import asyncio
from typing import Optional

import structlog

from ..config import Settings
from ..core.protocols import EventBus, MemoryService

log = structlog.get_logger(__name__)

_TOPIC_SENSE_RAW = "sense.raw"


class IngestionWorker:
    """Récolte les events `sense.raw` du bus et les transforme en épisodes mémoire.

    PR 1 : skeleton, log uniquement. PR 2 ajoutera record_episode.
    """

    def __init__(
        self,
        *,
        event_bus: EventBus,
        memory: MemoryService,
        settings: Settings,
    ) -> None:
        self._event_bus = event_bus
        self._memory = memory
        self._settings = settings
        self._running = False
        self._task: Optional[asyncio.Task] = None  # type: ignore[type-arg]

    # ─── Lifecycle ──────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Démarre la subscription au topic sense.raw.

        No-op silencieux si `settings.memory_enabled is False`.
        """
        if not self._settings.memory_enabled:
            log.info(
                "memory.ingestion_worker_disabled",
                reason="memory_enabled=False",
            )
            return
        if self._task is not None:
            # Déjà démarré — idempotent.
            return
        self._running = True
        self._task = asyncio.create_task(self.run(), name="ingestion_worker")

    async def run(self) -> None:
        """Boucle principale : consume les events sense.raw.

        PR 1 : logue chaque event reçu (WARN en debug, INFO en prod).
        PR 2 ajoutera : await self._memory.store(...)  via record_episode.
        """
        log.info("memory.ingestion_worker_started", topic=_TOPIC_SENSE_RAW)
        try:
            async for event in self._event_bus.subscribe(_TOPIC_SENSE_RAW):
                if not self._running:
                    break
                # PR 1 : log uniquement — pas encore de storage.
                # PR 2 ajoutera record_episode ici.
                log.info(
                    "memory.ingestion_worker_event_received",
                    topic=_TOPIC_SENSE_RAW,
                    event_type=event.get("type"),
                )
        except asyncio.CancelledError:
            # Propagation propre — le finally du générateur subscribe() nettoie.
            raise
        except Exception as exc:
            log.exception(
                "memory.ingestion_worker_error",
                error=str(exc),
            )
        finally:
            log.info("memory.ingestion_worker_stopped")

    async def stop(self) -> None:
        """Cleanup propre du subscriber.

        Met `_running=False` puis annule la task. Le `finally` du générateur
        `subscribe()` retire automatiquement la queue du bus.
        """
        self._running = False
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        self._task = None


__all__ = ["IngestionWorker"]
