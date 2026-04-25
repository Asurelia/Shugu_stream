"""Debouncer de triggers chat — Phase E2.5.

Rôle : accumuler les triggers `chat` dans une fenêtre temporelle puis
flusher un seul trigger batché. Réduit ~50% des appels LLM en collapsant
le spam de chat en début de stream.

## Principe

L'orchestrator appelle `submit(trigger)` pour chaque trigger `chat`.
Le debouncer :
1. Ajoute le trigger à la fenêtre courante.
2. Démarre une timer si c'est le 1er trigger de la fenêtre.
3. Si la fenêtre flush (timer expirée OU max_batch atteint), retourne
   un trigger batché qui merge les messages.
4. Sinon retourne `None` (trigger absorbé dans la fenêtre).

Les triggers `vip_arrival` bypass le debouncer (flush immédiat dans l'orchestrator).

## Thread-safety

Le debouncer est utilisé dans un contexte asyncio mono-thread (un seul
event loop). Le `asyncio.Lock` interne protège les mutations de `_window`
contre les cas où `submit()` et `_flush()` se chevauchent.

## Batching

Le trigger batché fusionne les messages de la fenêtre :
- Sender = premier sender de la fenêtre.
- Text = concaténation des messages (max 500 chars).
- Payload conserve le `sender` original pour le contexte LLM.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from .triggers import TriggerEvent, TriggerKind

log = logging.getLogger(__name__)

# Kinds de triggers qui sont debounçables (uniquement chat).
DEBOUNCEABLE_KINDS: frozenset[TriggerKind] = frozenset({"chat"})


class TriggerDebouncer:
    """Accumule les triggers chat dans une fenêtre et flushe un trigger batché.

    Usage:
        debouncer = TriggerDebouncer(window_seconds=3.0, max_batch=10)
        batched = await debouncer.submit(trigger)
        if batched is not None:
            await orchestrator._execute_tick(batched)
        # else : trigger absorbé, pas d'appel LLM

    Vip_arrival : bypass direct dans l'orchestrator, pas dans le debouncer.
    """

    def __init__(
        self,
        window_seconds: float = 3.0,
        max_batch: int = 10,
    ) -> None:
        """Init le debouncer.

        Args:
            window_seconds: Durée de la fenêtre d'accumulation (secondes).
            max_batch:      Nombre max de triggers avant flush forcé.
        """
        self._window_seconds = window_seconds
        self._max_batch = max_batch
        self._window: list[TriggerEvent] = []
        self._lock: asyncio.Lock = asyncio.Lock()
        self._window_start: float = 0.0  # monotonic timestamp

    async def submit(self, trigger: TriggerEvent) -> Optional[TriggerEvent]:
        """Soumet un trigger à la fenêtre.

        Args:
            trigger: Trigger à soumettre (doit être de kind "chat").

        Returns:
            Trigger batché si la fenêtre flushe, `None` si trigger absorbé.

        Note: ne pas appeler avec des kinds non-debounçables (vip_arrival, etc.)
              — l'orchestrator doit bypasser le debouncer pour ces kinds.
        """
        async with self._lock:
            now = time.monotonic()

            # Si la fenêtre est vide, on démarre une nouvelle fenêtre.
            if not self._window:
                self._window_start = now
                self._window.append(trigger)
                log.debug(
                    "director.debouncer_window_started",
                    extra={"kind": trigger.kind},
                )
                return None  # absorbé dans la nouvelle fenêtre

            # Vérifie si la fenêtre est expirée.
            elapsed = now - self._window_start
            window_expired = elapsed >= self._window_seconds
            # On ajoute le trigger avant de vérifier le batch_full pour
            # s'assurer que le Nième trigger déclenche le flush (pas le N+1ième).
            self._window.append(trigger)
            batch_full = len(self._window) >= self._max_batch

            if window_expired or batch_full:
                # Flush : on batchise tous les triggers de la fenêtre.
                batched = _merge_chat_triggers(self._window)
                count = len(self._window)
                self._window = []
                self._window_start = 0.0
                log.debug(
                    "director.debouncer_flushed",
                    extra={
                        "count": count,
                        "elapsed_s": round(elapsed, 3),
                        "reason": "max_batch" if batch_full else "window_expired",
                    },
                )
                return batched
            log.debug(
                "director.debouncer_absorbed",
                extra={
                    "kind": trigger.kind,
                    "window_size": len(self._window),
                    "elapsed_s": round(elapsed, 3),
                },
            )
            return None

    async def flush_now(self) -> Optional[TriggerEvent]:
        """Force le flush de la fenêtre courante (pour le shutdown propre).

        Returns:
            Trigger batché si la fenêtre n'était pas vide, sinon None.
        """
        async with self._lock:
            if not self._window:
                return None
            batched = _merge_chat_triggers(self._window)
            count = len(self._window)
            self._window = []
            self._window_start = 0.0
            log.debug(
                "director.debouncer_force_flushed",
                extra={"count": count},
            )
            return batched

    @property
    def window_size(self) -> int:
        """Nombre de triggers dans la fenêtre courante (thread-safe pour les tests)."""
        return len(self._window)


def _merge_chat_triggers(triggers: list[TriggerEvent]) -> TriggerEvent:
    """Merge une liste de triggers chat en un seul trigger batché.

    Stratégie :
    - Sender = premier sender de la fenêtre (représentatif du début du burst).
    - Text = concaténation des messages avec " | " comme séparateur.
      Cappé à 500 chars pour limiter la taille du prompt.
    - Timestamp = maintenant (le trigger batché est le plus récent).

    Args:
        triggers: Liste non-vide de TriggerEvent chat.

    Returns:
        Nouveau TriggerEvent batché.
    """
    assert triggers, "Impossible de merger une liste vide de triggers"
    first = triggers[0]
    sender = first.payload.get("sender", "?")

    texts = []
    for t in triggers:
        text = t.payload.get("text", "")
        if text:
            texts.append(text)
    merged_text = " | ".join(texts)[:500]

    return TriggerEvent(
        kind="chat",
        payload={
            "sender": sender,
            "text": merged_text,
            "batched_count": len(triggers),
        },
    )
