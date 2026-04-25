"""`TriggerBus` — bus intra-process de triggers du Director.

Rôle Phase E1 :
- Centralise les signaux externes (chat, vip_arrival, scene_change, silence,
  viewer_milestone) dans un pub/sub local.
- Ne remplace PAS `RedisEventBus` : ce dernier reste le canal cross-process
  (WS broadcast, stage events). Le `TriggerBus` est un canal intra-process
  dédié au Director — ses consommateurs (E2: `LLMOrchestrator`) vivent dans
  le même process que les émetteurs (WS handlers, scene_change listener,
  silence timer).
- Subscribe-based, `publish()` appelle tous les callbacks en concurrence
  (`asyncio.gather`) avec `return_exceptions=True` pour qu'un subscriber
  buggé ne fasse pas tomber les autres.

Contrat :
- `TriggerEvent` est `frozen=True` → immutable, hashable, safe à stocker
  dans des logs ou structures partagées.
- `subscribe()` retourne un dispose callable pour unsubscribe sans garder
  une référence sur le callback original.
- `close()` clear les subscribers et set un flag : les publish ultérieurs
  sont no-op (log debug, pas d'exception — Phase E1 évite les crashs en
  shutdown alors que des handlers WS en vol pourraient encore publish).
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Awaitable, Callable, Literal, Optional

log = logging.getLogger(__name__)

TriggerKind = Literal[
    "chat",
    "vip_arrival",
    "scene_change",
    "silence",
    "viewer_milestone",
]

TriggerCallback = Callable[["TriggerEvent"], Awaitable[None]]


@dataclass(slots=True, frozen=True)
class TriggerEvent:
    """Event immutable publié sur le `TriggerBus`.

    Champs :
    - `kind`    discriminator (chat | vip_arrival | scene_change | silence
                | viewer_milestone).
    - `payload` dict libre, contrat par `kind` :
        - chat              : {"sender": str, "text": str}
        - vip_arrival       : {"sender": str}
        - scene_change      : {"slug": str, ...} (peut inclure d'autres champs
                              relayés depuis le topic `stage`).
        - silence           : {"duration_s": int}
        - viewer_milestone  : {"count": int}
    - `ts`     horodatage UTC auto-renseigné à la construction.

    `frozen=True` garantit qu'un caller ne peut pas muter un event une fois
    publié — le bus peut donc le relayer à N subscribers sans risque.
    """

    kind: TriggerKind
    payload: dict
    ts: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class TriggerBus:
    """Bus local de triggers pour le Director.

    API :
        bus = get_trigger_bus()
        dispose = bus.subscribe(on_event)
        await bus.publish(TriggerEvent(kind="chat", payload={...}))
        dispose()            # unsubscribe
        await bus.close()    # shutdown — clear + refuse les publish
    """

    def __init__(self) -> None:
        self._subscribers: list[TriggerCallback] = []
        self._lock: asyncio.Lock = asyncio.Lock()
        self._closed: bool = False

    def subscribe(self, callback: TriggerCallback) -> Callable[[], None]:
        """Ajoute un subscriber. Retourne un callable qui unsubscribe.

        Le dispose est idempotent : un 2e appel est un no-op. Permet aux
        callers de s'inscrire sans conserver une ref sur leur propre
        callback pour plus tard.
        """
        # Pas besoin du lock pour `append` (GIL) mais on veut être cohérent
        # avec les autres mutations du registre — `publish` snapshot la
        # liste sous lock.
        self._subscribers.append(callback)

        disposed = False

        def _dispose() -> None:
            nonlocal disposed
            if disposed:
                return
            disposed = True
            try:
                self._subscribers.remove(callback)
            except ValueError:
                # Déjà retiré (ex: `close()` a clear tout). Idempotent.
                pass

        return _dispose

    async def publish(self, event: TriggerEvent) -> None:
        """Dispatch `event` à tous les subscribers (asyncio.gather).

        `return_exceptions=True` isolent les subscribers buggés — on log
        l'exception en warning, les autres callbacks voient l'event quand
        même. Post-`close()`, la méthode est un no-op (log debug).
        """
        if self._closed:
            log.debug("trigger_bus.publish_after_close", kind=event.kind)
            return
        # Snapshot la liste sous lock pour tolérer un subscribe/unsubscribe
        # concurrent pendant le dispatch.
        async with self._lock:
            callbacks = list(self._subscribers)
        if not callbacks:
            return
        results = await asyncio.gather(
            *(cb(event) for cb in callbacks),
            return_exceptions=True,
        )
        for cb, result in zip(callbacks, results):
            if isinstance(result, Exception):
                log.warning(
                    "trigger_bus.subscriber_failed",
                    extra={
                        "kind": event.kind,
                        "callback": getattr(cb, "__qualname__", repr(cb)),
                        "error": repr(result),
                    },
                )

    async def close(self) -> None:
        """Shutdown : flag `closed=True` + clear subscribers.

        Idempotent. Les `publish()` ultérieurs deviennent no-op. Les dispose
        handles retournés par `subscribe()` restent valides (no-op car le
        callback n'est plus dans la liste).
        """
        async with self._lock:
            self._closed = True
            self._subscribers.clear()


# ───────────────────────────────────────────────────────────────────────
# Factory singleton pour DI FastAPI / wiring app.py.
# ───────────────────────────────────────────────────────────────────────

_instance: Optional[TriggerBus] = None


def get_trigger_bus() -> TriggerBus:
    """Retourne le `TriggerBus` singleton process-wide.

    Instancié paresseusement au 1er appel — le lock interne est créé à la
    même occasion. Les tests qui veulent un bus frais doivent appeler
    `_reset_for_tests()` AVANT le 1er `get_trigger_bus()`.
    """
    global _instance
    if _instance is None:
        _instance = TriggerBus()
    return _instance


def _reset_for_tests() -> None:
    """Détruit le singleton pour isoler les tests."""
    global _instance
    _instance = None
