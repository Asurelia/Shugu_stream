"""Orchestrator LLM Shugu Soul — Phase E2.5 (refactoré depuis E2.3).

Boucle principale du Director :
  trigger → [debouncer] → [canned] → [cache sémantique] → LLM → tags → workers → state → broadcast

# Architecture Soul/Shell refactorisée (Phase E2.5)

```text
TriggerBus ──→  Orchestrator.tick(trigger)
                  │
                  ├─ 1. Feature flag + Rate limit + Cap horaire (guards)
                  ├─ 2. Debouncer (chat only) → batch ou absorbe
                  ├─ 3. Canned responses (silence/milestone/scene_change)
                  │     → skip LLM si canned disponible
                  ├─ 4. Cache sémantique pgvector (DirectorStateStore.get + embed)
                  │     → skip LLM si hit cosine ≥ 0.92
                  ├─ 5. DirectorBrain.complete() → texte + tags (LLM call)
                  │     └─ timeout 3s → fallback [say_emotion:neutral]
                  ├─ 6. parse_tags(text)             → list[ParsedTag]
                  ├─ 7. strip_tags(text)             → texte TTS
                  ├─ 8. tick_cache.store()           → cache le résultat LLM
                  ├─ 9. asyncio.gather(worker.apply per tag) → list[StateDelta]
                  ├─ 10. state_store.update(merged_patch)
                  └─ 11. event_bus.publish("editor:broadcast", {scene.tick envelope})
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

# Cost Reduction (Phase E2.5)

- **Debouncer** : collapse les bursts chat (fenêtre 3s, max 10) → ~50% LLM reduction.
- **Canned** : silence/milestone/scene_change utilisent des réponses pré-définies → ~15% reduction.
- **Cache sémantique** : triggers sémantiquement similaires réutilisent la réponse → ~60-80% reduction.
- Objectif global : ~43k → 5-8k appels LLM/jour.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Callable, Optional

from ..config import Settings
from ..memory.types import RecallQuery
from .brain_provider import DirectorBrain

if TYPE_CHECKING:
    from ..core.protocols import MemoryService
from .canned_responses import CANNED_ELIGIBLE_KINDS, CannedResponse, pick_canned
from .debouncer import DEBOUNCEABLE_KINDS, TriggerDebouncer
from .prompt import build_prompt
from .scene_state import SceneStateSnapshot
from .state_store import DirectorStateStore
from .tag_parser import ParsedTag, parse_tags, strip_tags
from .tick_cache import TickCache, format_trigger_for_cache
from .triggers import TriggerBus, TriggerEvent
from .workers import EDITOR_BROADCAST_TOPIC
from .workers.base import DIRECTOR_SCENE_ID_SENTINEL, StateDelta, Worker

log = logging.getLogger(__name__)

# Délai minimum entre deux ticks (rate limit). Valeur spec §5.2 E2.5.
TICK_MIN_INTERVAL_S = 2.0

# Fallback déterministe quand le LLM timeout ou échoue.
_FALLBACK_TAG = ParsedTag(kind="say_emotion", value="neutral")


class _TickRateCounter:
    """Compteur atomique fenêtre glissante 1h pour cap coût LLM.

    Permet de limiter le nombre de ticks par heure pour borner la consommation
    API LLM. Utilise une fenêtre glissante (les timestamps expirés sont
    trimés après chaque check).

    Note : les canned responses et les cache hits ne comptent PAS comme tick
    (ils n'appellent pas le LLM). Seuls les appels LLM réels sont comptés.
    """

    def __init__(self, max_per_hour: int) -> None:
        """Init le compteur.

        Args:
            max_per_hour: Max ticks par heure. Si <= 0, pas de limite.
        """
        self._max = max_per_hour
        self._timestamps: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def try_acquire(self) -> bool:
        """Essaie d'acquérir une slot de tick.

        Retourne True si la slot est accordée (count < max), False si on a
        atteint le cap.

        Thread-safe (asyncio.Lock).
        """
        async with self._lock:
            now = time.monotonic()
            # Trim entries plus vieilles que 3600s (1 heure).
            while self._timestamps and now - self._timestamps[0] > 3600:
                self._timestamps.popleft()
            # Si max_per_hour <= 0, pas de limite.
            if self._max <= 0:
                self._timestamps.append(now)
                return True
            # Si on a atteint le cap, refuser.
            if len(self._timestamps) >= self._max:
                return False
            # Sinon, ajouter le timestamp et accorder.
            self._timestamps.append(now)
            return True


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

    Cost reduction (Phase E2.5) :
        Le pipeline tick() passe successivement par :
        1. Debouncer (chat) → batch les messages rapprochés.
        2. Canned responses → évite le LLM pour silence/milestone/scene_change.
        3. Cache sémantique → évite le LLM pour les triggers similaires récents.
        4. LLM call (en dernier recours).
    """

    def __init__(
        self,
        state_store: DirectorStateStore,
        workers: dict[str, Worker],
        llm_client: DirectorBrain,
        event_bus,   # shugu.core.protocols.EventBus — type fluide pour éviter l'import circulaire
        settings: Settings,
        tick_cache: Optional[TickCache] = None,
        debouncer: Optional[TriggerDebouncer] = None,
        memory_agent: Optional["MemoryService"] = None,
    ) -> None:
        self._store = state_store
        self._workers = workers
        self._llm_client = llm_client
        self._event_bus = event_bus
        self._settings = settings
        # Phase E4 H2 — MemoryService pour recall VIP/chat avant build_prompt.
        # Si None (memory_enabled=False ou agent absent), skip silencieux.
        self._memory_agent: Optional["MemoryService"] = memory_agent

        self._last_tick_at: float = 0.0   # monotonic timestamp du dernier tick
        self._tick_lock: asyncio.Lock = asyncio.Lock()
        self._dispose: Optional[Callable[[], None]] = None  # unsubscribe handle du TriggerBus
        self._current_task: Optional[asyncio.Task] = None
        # Compteur horaire pour le cap coût LLM.
        self._tick_rate_counter = _TickRateCounter(settings.director_max_ticks_per_hour)

        # Phase E2.5 — cache sémantique + debouncer.
        # Un StubTickCache/StubDebouncer peut être injecté pour les tests.
        self._tick_cache: TickCache = tick_cache  # type: ignore[assignment]
        if debouncer is not None:
            # Si un debouncer externe est injecté (tests ou lifespan), on branche
            # on_flush s'il n'en a pas encore — évite de perdre les triggers solitaires.
            if debouncer._on_flush is None:
                debouncer._on_flush = self._handle_batched_trigger
            self._debouncer: TriggerDebouncer = debouncer
        else:
            self._debouncer = TriggerDebouncer(
                window_seconds=settings.director_debounce_window_seconds,
                max_batch=settings.director_debounce_max_batch,
                on_flush=self._handle_batched_trigger,
            )

        # Déduplication des canned responses — IDs des N dernières utilisées.
        self._recent_canned_ids: set[str] = set()
        self._recent_canned_history: deque[str] = deque(maxlen=8)

    async def tick(self, trigger: TriggerEvent) -> None:
        """Une réaction Shugu à un trigger.

        Pipeline Phase E2.5 :
        1. Guards (feature flag + rate limit + cap horaire)
        2. Debouncer (chat only) — absorbe ou flushe un batch
        3. Canned response — skip LLM pour silence/milestone/scene_change
        4. Cache sémantique — skip LLM si hit cosine ≥ threshold
        5. LLM call — construit le prompt, appelle le brain, store le cache
        6. Dispatch workers + state update + broadcast

        Guard rails :
        - Feature flag OFF → no-op silencieux.
        - Rate limit 2s → skip (sauf vip_arrival).
        - Cap horaire → skip avec warning si max ticks/h atteint.
        - Un seul tick concurrent (asyncio.Lock).
        - Timeout LLM 3s → fallback [say_emotion:neutral].
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

        # Cap horaire ticks. VIP bypasse aussi ce check.
        if not is_vip:
            can_tick = await self._tick_rate_counter.try_acquire()
            if not can_tick:
                log.warning(
                    "director.orchestrator_tick_rate_capped_hourly",
                    extra={"kind": trigger.kind, "max_per_hour": self._settings.director_max_ticks_per_hour},
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
        """Corps interne du tick — appelé sous `_tick_lock`.

        Pipeline complet E2.5 : debounce → canned → cache → LLM.
        """
        # 2. Debouncer pour chat (batch les messages rapprochés).
        if trigger.kind in DEBOUNCEABLE_KINDS and self._debouncer is not None:
            batched = await self._debouncer.submit(trigger)
            if batched is None:
                # Trigger absorbé dans la fenêtre debounce — pas d'appel LLM.
                # Le debouncer appellera on_flush (= _handle_batched_trigger)
                # quand la fenêtre expirera via le timer.
                log.debug(
                    "director.orchestrator_trigger_debounced",
                    extra={"kind": trigger.kind},
                )
                return
            trigger = batched

        await self._execute_tick_post_debounce(trigger)

    async def _execute_tick_post_debounce(self, trigger: TriggerEvent) -> None:
        """Pipeline post-debounce : canned → cache → LLM.

        Appelé depuis `_execute_tick` (après le debouncer) ET depuis
        `_handle_batched_trigger` (timer auto-flush, trigger déjà batché).

        Doit être appelé sous `_tick_lock`.
        """
        # 3. Canned responses pour les triggers à faible variabilité.
        if self._settings.director_canned_enabled and trigger.kind in CANNED_ELIGIBLE_KINDS:
            canned = pick_canned(
                trigger.kind,
                trigger.payload,
                recent_canned_ids=self._recent_canned_ids,
            )
            if canned is not None:
                log.debug(
                    "director.orchestrator_canned_response",
                    extra={"kind": trigger.kind, "canned_id": canned.id},
                )
                self._register_canned(canned)
                await self._execute_from_text(canned.text, trigger, source="canned")
                return  # SKIP LLM

        # 4. Cache sémantique pgvector.
        state = await self._store.get()
        trigger_text = format_trigger_for_cache(
            trigger.kind,
            trigger.payload,
            scene_slug=state.scene,
            face=state.face,
        )

        if self._tick_cache is not None and self._settings.director_cache_enabled:
            cached = await self._tick_cache.lookup(trigger_text)
            if cached is not None:
                log.debug(
                    "director.orchestrator_cache_hit",
                    extra={
                        "kind": trigger.kind,
                        "similarity": round(cached.similarity, 4),
                    },
                )
                await self._execute_from_text(cached.llm_text, trigger, source="cache")
                return  # SKIP LLM

        # 5. Memory recall pour les triggers chat/vip_arrival (Phase E4 H2).
        # Le recall est fait AVANT build_prompt pour injecter les faits VIP
        # dans le system prompt. Si l'agent est absent ou échoue, skip silencieux.
        memory_facts: list[str] = []
        if self._memory_agent is not None and trigger.kind in {"chat", "vip_arrival"}:
            sender = trigger.payload.get("sender")
            if sender:
                # Convention subject : "vip:<sender_lc>" pour vip_arrival,
                # "vip:<sender_lc>" aussi pour chat (le wiring lowercase déjà).
                # On query par subject uniquement (text="" → "last N by subject").
                subject = f"vip:{sender.lower()}"
                try:
                    recalled = await self._memory_agent.recall(
                        RecallQuery(text="", subject=subject, limit=5)
                    )
                    memory_facts = [item.text for item in recalled if item.text]
                except Exception as exc:
                    log.warning(
                        "director.orchestrator_memory_recall_failed",
                        extra={"sender": sender, "error": repr(exc)},
                    )

        # 6. LLM call (en dernier recours).
        system, user = build_prompt(state, trigger, memory_facts=memory_facts or None)

        llm_text: Optional[str] = None
        tags: list[ParsedTag]
        tts_text: str

        try:
            llm_text = await asyncio.wait_for(
                self._llm_client.complete(system=system, user=user),
                timeout=3.0,
            )
            # 7. Parse tags + strip pour TTS.
            tags = parse_tags(llm_text, max_tags=10, state=state)
            tts_text = strip_tags(llm_text)
        except TimeoutError:
            log.warning(
                "director.orchestrator_llm_timeout",
                extra={"kind": trigger.kind, "timeout_s": 3.0},
            )
            tags = [_FALLBACK_TAG]
            tts_text = ""
        except Exception as exc:
            log.warning(
                "director.orchestrator_llm_error",
                extra={"kind": trigger.kind, "error": repr(exc)},
            )
            tags = [_FALLBACK_TAG]
            tts_text = ""

        # 7. Store dans le cache si on a un résultat LLM valide.
        if llm_text and self._tick_cache is not None and self._settings.director_cache_enabled:
            await self._tick_cache.store(trigger_text, llm_text, tags)

        if not tags:
            # LLM a répondu mais sans tags valides — on ne mute pas l'état.
            log.debug(
                "director.orchestrator_no_tags",
                extra={"kind": trigger.kind, "llm_text_len": len(llm_text or "")},
            )
            await self._broadcast_tick(tts_text=tts_text, patch={}, trigger=trigger)
            return

        # 8. Dispatch workers + 9. state update + 10. broadcast.
        await self._dispatch_and_publish(tags, tts_text, trigger)

    async def _execute_from_text(
        self,
        text: str,
        trigger: TriggerEvent,
        source: str = "llm",
    ) -> None:
        """Execute le pipeline depuis un texte (canned ou cache) — sans LLM call.

        Parse les tags, dispatch les workers, update le state, broadcast.
        """
        state = await self._store.get()
        tags = parse_tags(text, max_tags=10, state=state)
        tts_text = strip_tags(text)

        if not tags:
            log.debug(
                "director.orchestrator_no_tags_from_text",
                extra={"kind": trigger.kind, "source": source},
            )
            await self._broadcast_tick(tts_text=tts_text, patch={}, trigger=trigger)
            return

        await self._dispatch_and_publish(tags, tts_text, trigger)

    async def _dispatch_and_publish(
        self,
        tags: list[ParsedTag],
        tts_text: str,
        trigger: TriggerEvent,
    ) -> None:
        """Dispatch workers, merge deltas, update state, broadcast."""
        state = await self._store.get()
        deltas = await self._dispatch_workers(tags, state)
        merged_patch = _merge_deltas(deltas)
        if merged_patch:
            await self._store.update(merged_patch)
        await self._broadcast_tick(tts_text=tts_text, patch=merged_patch, trigger=trigger)

    def _register_canned(self, canned: CannedResponse) -> None:
        """Enregistre une canned response utilisée pour la déduplication."""
        self._recent_canned_history.append(canned.id)
        self._recent_canned_ids = set(self._recent_canned_history)

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
        Démarre aussi le timer auto-flush du debouncer pour que les triggers
        chat solitaires ne restent pas coincés indéfiniment dans la fenêtre.
        """
        if self._dispose is not None:
            self._dispose()
        self._dispose = trigger_bus.subscribe(self._on_trigger)
        if self._debouncer is not None:
            await self._debouncer.start()
        log.info("director.orchestrator_started")

    async def stop(self) -> None:
        """Unsubscribe, draine le debouncer, attend la fin du tick courant.

        Doit être appelé AVANT `director_bg.stop()` et AVANT `event_bus.close()`
        dans le lifespan finally — l'orchestrator peut encore publier pendant
        le tick en cours.

        stop() flushe aussi le buffer debouncer résiduel via debouncer.stop()
        pour éviter de perdre les triggers absorbés en fin de session.
        """
        if self._dispose is not None:
            self._dispose()
            self._dispose = None

        # Drainer le debouncer AVANT d'attendre le lock — stop() peut déclencher
        # un dernier tick (le flush du buffer résiduel). Unsubscribe déjà fait
        # ci-dessus, donc ce tick ne peut pas créer de nouveaux triggers entrants.
        if self._debouncer is not None:
            await self._debouncer.stop()

        # Attend que le lock soit libéré (tick en cours terminé).
        log.info("director.orchestrator_waiting_tick_drain")
        async with self._tick_lock:
            pass

        log.info("director.orchestrator_stopped")

    async def _handle_batched_trigger(self, trigger: TriggerEvent) -> None:
        """Callback appelé par le debouncer quand une fenêtre flushe via timer.

        Identique à tick() mais SANS passer par le debouncer (le trigger est
        déjà un batch consolidé). Respecte le rate limit, le cap horaire et
        le tick_lock — seule l'étape debouncer est court-circuitée.

        Appelé depuis la task asyncio interne du debouncer (_timer_loop ou stop()).
        """
        if not self._settings.director_enabled:
            return

        is_vip = trigger.kind == "vip_arrival"
        now = time.monotonic()
        if not is_vip and (now - self._last_tick_at) < TICK_MIN_INTERVAL_S:
            log.debug(
                "director.orchestrator_batched_trigger_rate_limited",
                extra={"kind": trigger.kind, "elapsed_s": round(now - self._last_tick_at, 3)},
            )
            return

        if not is_vip:
            can_tick = await self._tick_rate_counter.try_acquire()
            if not can_tick:
                log.warning(
                    "director.orchestrator_batched_trigger_rate_capped",
                    extra={"kind": trigger.kind, "max_per_hour": self._settings.director_max_ticks_per_hour},
                )
                return

        if self._tick_lock.locked():
            log.debug(
                "director.orchestrator_batched_trigger_skipped_busy",
                extra={"kind": trigger.kind},
            )
            return

        async with self._tick_lock:
            self._last_tick_at = time.monotonic()
            # On passe directement à _execute_tick_post_debounce pour éviter
            # de re-soumettre le batch au debouncer.
            await self._execute_tick_post_debounce(trigger)

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
