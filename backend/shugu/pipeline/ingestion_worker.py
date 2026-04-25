"""IngestionWorker — récolte les events `sense.raw` et les transforme en épisodes mémoire.

PR 2 (cette version) : appelle `MemoryAgent.record_episode()` pour persister
chaque event dans `memory_episodes`. La redaction Phase 2.6 est appliquée
côté agent, pas ici.

Design :
- Même pattern lifecycle que `AmbientDaemon` : `start()` / `run()` / `stop()`.
- Si `settings.memory_enabled is False`, `start()` est un no-op silencieux.
- Pas d'état persistant côté worker : la mémoire vit dans `MemoryAgent`/DB.
- L'annulation de la task asyncio déclenche le `finally` du générateur
  `subscribe()` qui retire proprement la queue du bus (garantie par les deux
  impls `InProcessEventBus` et `RedisEventBus`).
- Une exception sur record_episode (DB down, payload corrompu) est loguée en
  warning et SWALLOWED — on ne casse pas la consommation pour autant. Le
  worker reste up et continue à consommer le bus (best-effort ingestion).
"""
from __future__ import annotations

import asyncio
from typing import Optional

import structlog

from ..config import Settings
from ..core.protocols import EventBus, MemoryService
from ..memory.episodes import MemoryEpisode

log = structlog.get_logger(__name__)

_TOPIC_SENSE_RAW = "sense.raw"


class IngestionWorker:
    """Récolte les events `sense.raw` du bus et les persiste comme épisodes mémoire."""

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
        """Boucle principale : consume les events sense.raw et appelle record_episode.

        Format d'event attendu (publié par les senses, cf. T5) :
            {
                "subject": "visitor:abc",
                "event_type": "chat_in",
                "actor": "viewer:alice",
                "payload": {"text": "...", "ts": "..."},
                "session_id": "01HX...",                # optionnel
                "performance_id": "01HX...",            # optionnel
            }
        """
        log.info("memory.ingestion_worker_started", topic=_TOPIC_SENSE_RAW)
        try:
            async for event in self._event_bus.subscribe(_TOPIC_SENSE_RAW):
                if not self._running:
                    break
                await self._on_sense_raw(event)
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

    async def _on_sense_raw(self, event: dict) -> None:
        """Callback subscriber sense.raw — transforme en MemoryEpisode et persiste.

        Best-effort : toute exception est loguée en warning et swallowed
        pour que le worker continue à consommer le bus. Un payload mal
        formé (champ manquant) ne tue jamais la pipeline d'ingestion.
        """
        try:
            episode = MemoryEpisode.new(
                subject=event["subject"],
                event_type=event["event_type"],
                actor=event["actor"],
                payload=event.get("payload", {}),
                session_id=event.get("session_id"),
                performance_id=event.get("performance_id"),
            )
            await self._memory.record_episode(episode)
            log.info(
                "memory.ingestion_worker_event_recorded",
                episode_id=episode.id,
                subject=episode.subject,
                event_type=episode.event_type,
            )
        except KeyError as exc:
            # Payload mal formé — on log explicitement pour aider au debug
            # sans casser la consommation.
            log.warning(
                "memory.ingestion_worker_malformed_event",
                missing_field=str(exc),
                event_keys=sorted(event.keys()) if isinstance(event, dict) else None,
            )
        except Exception as exc:
            log.warning(
                "memory.ingestion_worker_record_episode_failed",
                error=repr(exc),
            )

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
