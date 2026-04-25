"""Orchestrator LLM Shugu Soul — Phase E2.3.

Boucle principale du Director :
  trigger → prompt → LLM → tags → workers (parallèle) → state delta → broadcast

# Architecture Soul/Shell

```text
TriggerBus ──→  Orchestrator.tick(trigger)
                  │
                  ├─ 1. DirectorStateStore.get()   → SceneStateSnapshot
                  ├─ 2. build_prompt(state, trigger) → (system, user)
                  ├─ 3. DirectorLLMClient.complete() → texte + tags
                  │     └─ timeout 3s → fallback [say_emotion:neutral]
                  ├─ 4. parse_tags(text)             → list[ParsedTag]
                  ├─ 5. strip_tags(text)             → texte TTS
                  ├─ 6. asyncio.gather(worker.apply per tag) → list[StateDelta]
                  ├─ 7. state_store.update(merged_patch)
                  └─ 8. event_bus.publish("editor:broadcast", {scene.tick envelope})
```

# Guard Rails

- **Rate limit** : 1 tick / 2s max (timestamp monotonic `_last_tick_at`).
  Exception : `vip_arrival` bypass immédiat (on ne veut pas rater l'accueil VIP).
- **Max 10 tags** : géré dans `tag_parser.parse_tags(max_tags=10)`.
- **Timeout LLM 3s** : `asyncio.wait_for` → fallback déterministe
  `[say_emotion:neutral]`, pas de mutation d'état.
- **Feature flag** : `settings.director_enabled=False` → `tick()` est un no-op.
- **Lifecycle** : `start()` subscribe au `TriggerBus`, `stop()` unsubscribe
  et attend la fin du tick courant s'il y en a un.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Optional

from ..config import Settings
from .llm_client import DirectorLLMClient, LLMClientError
from .prompt import build_prompt
from .scene_state import SceneStateSnapshot
from .state_store import DirectorStateStore
from .tag_parser import ParsedTag, parse_tags, strip_tags
from .triggers import TriggerBus, TriggerEvent
from .workers import EDITOR_BROADCAST_TOPIC
from .workers.base import DIRECTOR_SCENE_ID_SENTINEL, StateDelta, Worker

log = logging.getLogger(__name__)

# Délai minimum entre deux ticks (rate limit). Valeur spec §5.2 E2.5.
TICK_MIN_INTERVAL_S = 2.0

# Fallback déterministe quand le LLM timeout ou échoue.
_FALLBACK_TAG = ParsedTag(kind="say_emotion", value="neutral")


class Orchestrator:
    """Cerveau Soul du Director — dispatch LLM + workers Shell.

    Lifecycle :
        await orchestrator.start(trigger_bus)  # subscribe + prêt
        # ... le bus dispatch les triggers via _on_trigger() ...
        await orchestrator.stop()              # unsubscribe + cleanup propre

    Thread-safety :
        `tick()` est protégé par `_tick_lock` (asyncio.Lock) pour s'assurer
        qu'un seul tick tourne à la fois. Le rate limit garantit qu'on ne
        surcharge pas le LLM même en cas de burst de triggers.
    """

    def __init__(
        self,
        state_store: DirectorStateStore,
        workers: dict[str, Worker],
        llm_client: DirectorLLMClient,
        event_bus,   # shugu.core.protocols.EventBus — type fluide pour éviter l'import circulaire
        settings: Settings,
    ) -> None:
        self._store = state_store
        self._workers = workers
        self._llm_client = llm_client
        self._event_bus = event_bus
        self._settings = settings

        self._last_tick_at: float = 0.0   # monotonic timestamp du dernier tick
        self._tick_lock: asyncio.Lock = asyncio.Lock()
        self._dispose: Optional[callable] = None  # unsubscribe handle du TriggerBus
        self._current_task: Optional[asyncio.Task] = None

    async def tick(self, trigger: TriggerEvent) -> None:
        """Une réaction Shugu à un trigger.

        Séquence complète :
        1. Pull scene state
        2. Build prompt
        3. Call LLM avec timeout 3s
        4. Parse tags + strip text pour TTS
        5. Dispatch workers en parallèle (asyncio.gather), récupère StateDeltas
        6. Merge deltas dans state_store
        7. Publish state delta sur RedisEventBus topic editor:broadcast

        Guard rails :
        - Feature flag OFF → no-op silencieux.
        - Rate limit 2s → skip (sauf vip_arrival).
        - Un seul tick concurrent (asyncio.Lock).
        - Timeout LLM 3s → fallback [say_emotion:neutral] sans mutation d'état.
        """
        if not self._settings.director_enabled:
            return

        # Rate limit — vip_arrival bypass immédiat pour ne jamais rater l'accueil.
        is_vip = trigger.kind == "vip_arrival"
        now = time.monotonic()
        if not is_vip and (now - self._last_tick_at) < TICK_MIN_INTERVAL_S:
            log.debug(
                "director.orchestrator_tick_rate_limited",
                extra={"kind": trigger.kind, "elapsed_s": round(now - self._last_tick_at, 3)},
            )
            return

        # Un seul tick à la fois — si un tick tourne déjà, on skip
        # (pas de queue : les triggers sont des signaux, pas des tâches).
        if self._tick_lock.locked():
            log.debug(
                "director.orchestrator_tick_skipped_busy",
                extra={"kind": trigger.kind},
            )
            return

        async with self._tick_lock:
            self._last_tick_at = time.monotonic()
            await self._execute_tick(trigger)

    async def _execute_tick(self, trigger: TriggerEvent) -> None:
        """Corps interne du tick — appelé sous `_tick_lock`."""
        # 1. Pull scene state
        state = await self._store.get()

        # 2. Build prompt
        system, user = build_prompt(state, trigger)

        # 3. Call LLM avec timeout 3s
        llm_text: Optional[str] = None
        tags: list[ParsedTag]
        tts_text: str

        try:
            llm_text = await asyncio.wait_for(
                self._llm_client.complete(system=system, user=user),
                timeout=3.0,
            )
            # 4. Parse tags + strip pour TTS
            tags = parse_tags(llm_text, max_tags=10, state=state)
            tts_text = strip_tags(llm_text)
        except TimeoutError:
            log.warning(
                "director.orchestrator_llm_timeout",
                extra={"kind": trigger.kind, "timeout_s": 3.0},
            )
            tags = [_FALLBACK_TAG]
            tts_text = ""
        except LLMClientError as exc:
            log.warning(
                "director.orchestrator_llm_error",
                extra={"kind": trigger.kind, "error": repr(exc)},
            )
            tags = [_FALLBACK_TAG]
            tts_text = ""

        if not tags:
            # LLM a répondu mais sans tags valides — on ne mute pas l'état.
            log.debug(
                "director.orchestrator_no_tags",
                extra={"kind": trigger.kind, "llm_text_len": len(llm_text or "")},
            )
            # On broadcast quand même le texte pour que le pipeline TTS puisse
            # parler (même sans tag on peut vouloir un say_emotion:neutral).
            await self._broadcast_tick(tts_text=tts_text, patch={}, trigger=trigger)
            return

        # 5. Dispatch workers en parallèle
        deltas = await self._dispatch_workers(tags, state)

        # 6. Merge deltas dans state_store
        merged_patch = _merge_deltas(deltas)
        if merged_patch:
            await self._store.update(merged_patch)

        # 7. Publish state delta sur editor:broadcast
        await self._broadcast_tick(tts_text=tts_text, patch=merged_patch, trigger=trigger)

    async def _dispatch_workers(
        self,
        tags: list[ParsedTag],
        state: SceneStateSnapshot,
    ) -> list[StateDelta]:
        """Dispatche chaque tag vers son worker en parallèle.

        Les workers inconnus (kind pas dans le registry) sont loggués et ignorés.
        Les exceptions par worker sont swallowed (return_exceptions=True) —
        un worker bugué ne bloque pas les autres.
        """
        tasks = []
        active_tags = []

        for tag in tags:
            worker = self._workers.get(tag.kind)
            if worker is None:
                log.warning(
                    "director.orchestrator_no_worker_for_kind",
                    extra={"kind": tag.kind},
                )
                continue
            tasks.append(worker.apply(tag.value, state))
            active_tags.append(tag)

        if not tasks:
            return []

        results = await asyncio.gather(*tasks, return_exceptions=True)

        deltas: list[StateDelta] = []
        for tag, result in zip(active_tags, results):
            if isinstance(result, Exception):
                log.warning(
                    "director.orchestrator_worker_failed",
                    extra={"kind": tag.kind, "value": tag.value, "error": repr(result)},
                )
            else:
                deltas.append(result)

        return deltas

    async def _broadcast_tick(
        self,
        *,
        tts_text: str,
        patch: dict,
        trigger: TriggerEvent,
    ) -> None:
        """Publie un envelope `scene.tick` sur `editor:broadcast`.

        Le payload `scene.tick` permet au frontend / pipeline TTS de voir :
        - Le texte nettoyé (pour TTS).
        - Le patch d'état agrégé (delta de la scène après ce tick).
        - Le kind du trigger (pour debug/analytics côté client).
        """
        payload = {
            "type": "scene.tick",
            "version": 1,
            "trigger_kind": trigger.kind,
            "tts_text": tts_text,
            "patch": patch,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        envelope = {
            "scene_id": DIRECTOR_SCENE_ID_SENTINEL,
            "origin": "director",
            "payload": payload,
        }
        try:
            await self._event_bus.publish(EDITOR_BROADCAST_TOPIC, envelope)
        except Exception as exc:
            log.warning(
                "director.orchestrator_broadcast_failed",
                extra={"trigger_kind": trigger.kind, "error": repr(exc)},
            )

    async def start(self, trigger_bus: TriggerBus) -> None:
        """Subscribe au TriggerBus — prêt à recevoir les triggers.

        Idempotent : si déjà démarré, on unsubscribe d'abord puis re-subscribe.
        """
        if self._dispose is not None:
            self._dispose()
        self._dispose = trigger_bus.subscribe(self._on_trigger)
        log.info("director.orchestrator_started")

    async def stop(self) -> None:
        """Unsubscribe et attend la fin du tick courant.

        Doit être appelé AVANT `director_bg.stop()` et AVANT `event_bus.close()`
        dans le lifespan finally — l'orchestrator peut encore publier pendant
        le tick en cours.
        """
        if self._dispose is not None:
            self._dispose()
            self._dispose = None

        # Attend que le lock soit libéré (tick en cours terminé).
        # On acquiert puis relâche immédiatement — juste pour s'assurer
        # qu'aucun tick ne tourne au moment du stop().
        async with self._tick_lock:
            pass

        log.info("director.orchestrator_stopped")

    async def _on_trigger(self, event: TriggerEvent) -> None:
        """Callback subscriber — appelé par TriggerBus.publish().

        On délègue à tick() qui gère le rate limit et la concurrence.
        Les exceptions sont swallowed ici pour ne pas casser le bus
        (pattern identique à wiring.publish_chat_trigger).
        """
        try:
            await self.tick(event)
        except Exception as exc:
            log.warning(
                "director.orchestrator_tick_unhandled",
                extra={"kind": event.kind, "error": repr(exc)},
            )


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _merge_deltas(deltas: list[StateDelta]) -> dict:
    """Fusionne plusieurs `StateDelta` en un seul patch dict.

    Merge shallow : les clés du dernier delta gagnent en cas de conflit.
    Pour `active_vfx` (liste) le dernier delta est pris tel quel — les workers
    construisent déjà leur liste en partant du snapshot courant.

    Un patch vide `{}` est retourné si tous les deltas sont vides.
    """
    merged: dict = {}
    for delta in deltas:
        merged.update(delta.patch)
    return merged
