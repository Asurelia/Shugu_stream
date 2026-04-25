"""ExtractionWorker — consomme les events `memory.episode_stored` et extrait des facts.

PR 3 Mémoire : câble le pipeline épisode → fact.

Pipeline :
    1. Subscribe topic `memory.episode_stored`.
    2. Filtre sur `event_type` ∈ {chat_in, voice_in, response_out} — seuls ces types
       portent du texte libre intéressant pour l'extraction de facts.
    3. Extrait le texte depuis le champ `redacted_payload` (prioritaire, secrets nettoyés)
       ou `payload` en fallback. Le champ `text` du payload contient le message.
    4. `fact_extractor.extract(text, subject=subject)` → liste de MemoryItem.
    5. Pour chaque fact : `await memory.store(item)`.
    6. Best-effort : toute exception est loguée en warning et swallowed — le worker
       reste up et continue à consommer le bus.

Design :
    - Pattern start/run/stop calqué sur IngestionWorker (Mémoire PR 1+2).
    - `start()` est un no-op silencieux si `settings.fact_extractor_enabled is False`
      OU si `settings.memory_enabled is False`.
    - Single-writer rule respectée : SEUL `MemoryAgent.store()` INSERT dans
      `memory_facts`. Ce worker ne crée jamais de row directement.
    - Concurrence : un seul `asyncio.Task` séquentiel par instance → pas de
      race condition interne. Les doublons éventuels (deux events pour le même
      subject) sont gérés par la maintenance Phase 2.7 (dedupe sémantique).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from ..config import Settings
from ..core.protocols import EventBus, MemoryService
from ..memory.extractors.pipeline import FactExtractor

log = logging.getLogger(__name__)

_TOPIC_EPISODE_STORED = "memory.episode_stored"

# event_type qui portent du texte libre exploitable pour l'extraction de facts.
# tool_call / ambient / stream_event / vip_event sont exclus — leurs payloads
# sont structurés (tags, metadata) et non des messages utilisateur libres.
_TEXT_EVENT_TYPES = frozenset({"chat_in", "voice_in", "response_out"})


class ExtractionWorker:
    """Worker qui consomme `memory.episode_stored` et extrait des facts mémoire.

    Inject :
        event_bus      — bus d'événements (inproc ou Redis, peu importe).
        memory         — MemoryService (MemoryAgent) pour le store() des facts.
        fact_extractor — FactExtractor prêt à l'emploi (regex ± LLM).
        settings       — Settings de l'app (guards fact_extractor_enabled).
    """

    def __init__(
        self,
        *,
        event_bus: EventBus,
        memory: MemoryService,
        fact_extractor: FactExtractor,
        settings: Settings,
    ) -> None:
        self._event_bus = event_bus
        self._memory = memory
        self._fact_extractor = fact_extractor
        self._settings = settings
        self._running = False
        self._task: Optional[asyncio.Task] = None  # type: ignore[type-arg]

    # ─── Lifecycle ──────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Démarre la subscription au topic `memory.episode_stored`.

        No-op silencieux si `settings.memory_enabled is False` ou
        `settings.fact_extractor_enabled is False`.
        """
        if not self._settings.memory_enabled:
            log.info(
                "memory.extraction_worker_disabled: reason=memory_enabled=False",
            )
            return
        if not self._settings.fact_extractor_enabled:
            log.info(
                "memory.extraction_worker_disabled: reason=fact_extractor_enabled=False",
            )
            return
        if self._task is not None:
            # Déjà démarré — idempotent.
            return
        self._running = True
        self._task = asyncio.create_task(self.run(), name="extraction_worker")

    async def run(self) -> None:
        """Boucle principale : consume les events memory.episode_stored et extrait des facts."""
        log.info("memory.extraction_worker_started topic=%s", _TOPIC_EPISODE_STORED)
        try:
            async for event in self._event_bus.subscribe(_TOPIC_EPISODE_STORED):
                if not self._running:
                    break
                await self._on_episode_stored(event)
        except asyncio.CancelledError:
            # Propagation propre — le finally du générateur subscribe() nettoie.
            raise
        except Exception as exc:
            log.exception(
                "memory.extraction_worker_error error=%s", str(exc),
            )
        finally:
            log.info("memory.extraction_worker_stopped")

    async def _on_episode_stored(self, event: dict) -> None:
        """Callback subscriber memory.episode_stored — extrait des facts et les store.

        Stratégie de texte :
        - Filtre d'abord sur `event_type` ∈ {chat_in, voice_in, response_out}.
          Les autres types (tool_call, ambient…) ne contiennent pas de langage
          naturel à extraire.
        - Lit le texte depuis `redacted_payload` (prioritaire : secrets nettoyés)
          ou `payload` (fallback). Le champ `text` du payload contient le message.
        - Si `text` absent ou vide → skip silencieux (log debug).

        Best-effort : toute exception est loguée en warning et swallowed pour
        que le worker reste up et continue à consommer le bus.
        """
        try:
            subject: str = event["subject"]
            event_type: str = event.get("event_type", "")

            # Filtre sur les event_types porteurs de texte libre.
            if event_type not in _TEXT_EVENT_TYPES:
                log.debug(
                    "memory.extraction_worker_skip_event_type event_type=%s subject=%s",
                    event_type, subject,
                )
                return

            # Récupère le texte depuis le payload enrichi (PR 3 T2).
            # Priorité : redacted_payload (secrets nettoyés) > payload brut.
            payload: dict = event.get("redacted_payload") or event.get("payload") or {}
            text: str = (payload.get("text") or "").strip()

            if not text:
                log.debug(
                    "memory.extraction_worker_skip_no_text event_type=%s subject=%s",
                    event_type, subject,
                )
                return

            # Extraction des facts.
            items = await self._fact_extractor.extract(text, subject=subject)
            if not items:
                log.debug(
                    "memory.extraction_worker_no_facts text_len=%d subject=%s",
                    len(text), subject,
                )
                return

            # Store chaque fact via la single-writer rule (MemoryAgent.store).
            for item in items:
                await self._memory.store(item)

            log.info(
                "memory.extraction_worker_facts_stored count=%d subject=%s event_type=%s",
                len(items), subject, event_type,
            )
        except KeyError as exc:
            # Payload mal formé — log explicitement sans casser la consommation.
            log.warning(
                "memory.extraction_worker_malformed_event missing_field=%s event_keys=%s",
                str(exc),
                sorted(event.keys()) if isinstance(event, dict) else None,
            )
        except Exception as exc:
            log.warning(
                "memory.extraction_worker_extract_failed error=%s", repr(exc),
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


__all__ = ["ExtractionWorker"]
