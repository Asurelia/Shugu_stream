"""Debouncer de triggers chat — Phase E2.5.

Rôle : accumuler les triggers `chat` dans une fenêtre temporelle puis
flusher un seul trigger batché. Réduit ~50% des appels LLM en collapsant
le spam de chat en début de stream.

## Principe

L'orchestrator appelle `submit(trigger)` pour chaque trigger `chat`.
Le debouncer :
1. Ajoute le trigger à la fenêtre courante.
2. Démarre un timer asyncio si c'est le 1er trigger de la fenêtre.
3. Si la fenêtre flush (timer expirée OU max_batch atteint), appelle le
   callback `on_flush` avec le trigger batché fusionné.
4. Sinon retourne `None` (trigger absorbé dans la fenêtre).

Les triggers `vip_arrival` bypass le debouncer (flush immédiat dans l'orchestrator).

## Timer auto-flush

Le debouncer maintient une `asyncio.Task` (`_timer_task`) qui:
- Est créée au premier trigger de chaque fenêtre.
- Dort `window_seconds` secondes puis appelle `on_flush(batched)`.
- Est annulée si la fenêtre est flushée avant expiration (max_batch atteint).
- Est arrêtée proprement par `stop()` — qui flushe aussi le buffer en attente.

Cela garantit qu'un message chat solitaire n'est jamais bloqué indéfiniment :
il sera dispatché au plus tard `window_seconds` après avoir été soumis.

## Thread-safety

Le debouncer est utilisé dans un contexte asyncio mono-thread (un seul
event loop). Le `asyncio.Lock` interne protège les mutations de `_window`
contre les cas où `submit()` et `_timer_task` se chevauchent.

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
from contextlib import suppress
from typing import Awaitable, Callable, Optional

from .triggers import TriggerEvent, TriggerKind

log = logging.getLogger(__name__)

# Kinds de triggers qui sont debounçables (uniquement chat).
DEBOUNCEABLE_KINDS: frozenset[TriggerKind] = frozenset({"chat"})


class TriggerDebouncer:
    """Accumule les triggers chat dans une fenêtre et flushe un trigger batché.

    Usage:
        async def on_flush(batched: TriggerEvent) -> None:
            await orchestrator._handle_batched_trigger(batched)

        debouncer = TriggerDebouncer(
            window_seconds=3.0,
            max_batch=10,
            on_flush=on_flush,
        )
        await debouncer.start()
        # ...
        await debouncer.stop()

    Vip_arrival : bypass direct dans l'orchestrator, pas dans le debouncer.
    """

    def __init__(
        self,
        window_seconds: float = 3.0,
        max_batch: int = 10,
        on_flush: Optional[Callable[[TriggerEvent], Awaitable[None]]] = None,
    ) -> None:
        """Init le debouncer.

        Args:
            window_seconds: Durée de la fenêtre d'accumulation (secondes).
            max_batch:      Nombre max de triggers avant flush forcé.
            on_flush:       Callback appelé quand la fenêtre flushe (timer ou
                            max_batch). Doit accepter un `TriggerEvent` batché.
                            Si None, le résultat du flush est simplement ignoré
                            (utile pour le mode submit()-only sans timer).
        """
        self._window_seconds = window_seconds
        self._max_batch = max_batch
        self._on_flush = on_flush
        self._window: list[TriggerEvent] = []
        self._lock: asyncio.Lock = asyncio.Lock()
        self._window_start: float = 0.0  # monotonic timestamp
        self._timer_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """Démarre le timer auto-flush.

        Idempotent : si le timer tourne déjà, pas d'effet.
        Doit être appelé depuis l'event loop (typiquement dans Orchestrator.start()).
        """
        # Le timer est créé à la demande par _schedule_timer_if_needed() ;
        # start() est un no-op ici — présent pour la symétrie avec stop().
        log.debug("director.debouncer_started", extra={"window_s": self._window_seconds})

    async def stop(self) -> None:
        """Annule le timer et flushe le buffer en attente.

        Appelle on_flush avec le batch résiduel si le buffer n'est pas vide.
        Doit être appelé avant l'arrêt de l'orchestrator pour ne pas perdre
        les triggers absorbés dans la fenêtre courante.
        """
        await self._cancel_timer()
        batched = await self._flush_now_locked()
        if batched is not None and self._on_flush is not None:
            try:
                await self._on_flush(batched)
            except Exception as exc:
                log.warning(
                    "director.debouncer_stop_flush_error",
                    extra={"error": repr(exc)},
                )
        log.debug("director.debouncer_stopped")

    async def submit(self, trigger: TriggerEvent) -> Optional[TriggerEvent]:
        """Soumet un trigger à la fenêtre.

        Args:
            trigger: Trigger à soumettre (doit être de kind "chat").

        Returns:
            Trigger batché si max_batch atteint (flush immédiat), `None` si
            trigger absorbé dans la fenêtre (le flush viendra via le timer).

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
                # Programme le flush automatique après window_seconds.
                self._schedule_timer_if_needed()
                return None  # absorbé dans la nouvelle fenêtre

            # Vérifie si la fenêtre est expirée.
            elapsed = now - self._window_start
            window_expired = elapsed >= self._window_seconds
            # On ajoute le trigger avant de vérifier le batch_full pour
            # s'assurer que le Nième trigger déclenche le flush (pas le N+1ième).
            self._window.append(trigger)
            batch_full = len(self._window) >= self._max_batch

            if window_expired or batch_full:
                # Flush immédiat : on batchise tous les triggers de la fenêtre.
                batched = _merge_chat_triggers(self._window)
                count = len(self._window)
                self._window = []
                self._window_start = 0.0
                # Annule le timer (il ne doit plus flusher pour cette fenêtre).
                self._cancel_timer_nowait()
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
        await self._cancel_timer()
        return await self._flush_now_locked()

    @property
    def window_size(self) -> int:
        """Nombre de triggers dans la fenêtre courante (thread-safe pour les tests)."""
        return len(self._window)

    # ─────────────────────────────────────────────────────────────────────────
    # Internals
    # ─────────────────────────────────────────────────────────────────────────

    def _schedule_timer_if_needed(self) -> None:
        """Programme le timer auto-flush (appelé sous _lock — pas de await)."""
        if self._timer_task is None or self._timer_task.done():
            self._timer_task = asyncio.create_task(
                self._timer_loop(), name="debouncer_timer"
            )

    async def _timer_loop(self) -> None:
        """Boucle timer : dort window_seconds puis flushe si buffer non vide."""
        try:
            await asyncio.sleep(self._window_seconds)
        except asyncio.CancelledError:
            return  # flush_now() ou stop() ont annulé le timer

        batched = await self._flush_now_locked()
        if batched is not None and self._on_flush is not None:
            try:
                await self._on_flush(batched)
            except Exception as exc:
                log.warning(
                    "director.debouncer_timer_flush_error",
                    extra={"error": repr(exc)},
                )
        # Nettoie la référence (la task est terminée).
        self._timer_task = None

    async def _flush_now_locked(self) -> Optional[TriggerEvent]:
        """Flush interne sous _lock."""
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

    def _cancel_timer_nowait(self) -> None:
        """Annule le timer sans await (appelé sous _lock depuis submit())."""
        if self._timer_task is not None and not self._timer_task.done():
            self._timer_task.cancel()
            self._timer_task = None

    async def _cancel_timer(self) -> None:
        """Annule le timer et attend sa terminaison."""
        if self._timer_task is not None and not self._timer_task.done():
            self._timer_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._timer_task
            self._timer_task = None


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
