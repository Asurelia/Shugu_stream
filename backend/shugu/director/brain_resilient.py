# backend/shugu/director/brain_resilient.py
"""Chaîne de résilience du cerveau : primary (M3) → fallback (Ollama) → canned.

Conforme au Protocol `DirectorBrain`. État : compteur d'échecs consécutifs du
primary ; au-delà de `failure_threshold`, on court-circuite le primary pendant
`reprobe_after_s` (re-sonde ensuite). Garantit qu'une réponse est TOUJOURS
retournée (canned en dernier ressort) — le stream ne meurt jamais.

Note : le re-probe temporel utilise une horloge injectée (`now`) pour la
testabilité ; en prod, `time.monotonic`.
"""
from __future__ import annotations

import logging
import time
from typing import Callable

from .brain_provider import DirectorBrain, DirectorBrainError
from ..mind.metrics import MindMetricsRecorder, get_null_mind_recorder

log = logging.getLogger(__name__)


class ResilientDirectorBrain:
    def __init__(
        self,
        *,
        primary: DirectorBrain,
        fallback: DirectorBrain,
        canned: DirectorBrain,
        failure_threshold: int = 2,
        reprobe_after_s: float = 60.0,
        now: Callable[[], float] = time.monotonic,
        metrics: MindMetricsRecorder | None = None,
    ) -> None:
        self._primary = primary
        self._fallback = fallback
        self._canned = canned
        self._threshold = failure_threshold
        self._reprobe_after_s = reprobe_after_s
        self._now = now
        self._metrics = metrics or get_null_mind_recorder()
        self._consecutive_failures = 0
        self._primary_disabled_until: float | None = None

    def __repr__(self) -> str:
        return "<ResilientDirectorBrain m3→ollama→canned>"

    def _primary_available(self) -> bool:
        if self._primary_disabled_until is None:
            return True
        if self._now() >= self._primary_disabled_until:
            self._primary_disabled_until = None
            self._consecutive_failures = 0
            return True
        return False

    async def complete(self, *, system: str, user: str) -> str:
        if self._primary_available():
            try:
                text = await self._primary.complete(system=system, user=user)
                self._consecutive_failures = 0
                return text
            except DirectorBrainError as exc:
                self._consecutive_failures += 1
                log.warning("mind.brain_primary_failed", extra={"error": repr(exc),
                            "consecutive": self._consecutive_failures})
                if self._consecutive_failures >= self._threshold:
                    self._primary_disabled_until = self._now() + self._reprobe_after_s
                self._metrics.record_brain_fallback(reason="primary_error", tier="ollama")

        try:
            return await self._fallback.complete(system=system, user=user)
        except DirectorBrainError as exc:
            log.warning("mind.brain_fallback_failed", extra={"error": repr(exc)})
            self._metrics.record_brain_fallback(reason="fallback_error", tier="canned")
            return await self._canned.complete(system=system, user=user)
