"""LoggingModeration — décorateur ModerationLayer persistant les refus en DB.

Volume cible : ~5 % du trafic (uniquement allowed=False). Le chemin chaud
n'est pas interrompu : un INSERT PostgreSQL ~1-5 ms est acceptable, mais une
erreur d'INSERT N'INTERROMPT JAMAIS le pipeline moderation.

Pattern fail-open : en cas d'exception dans `_persist`, on log via structlog
et on laisse le verdict remonter au caller sans modification.
"""
from __future__ import annotations

import structlog
from sqlalchemy import insert

from ..core.protocols import ModerationLayer, ModerationVerdict
from ..db.models import ModerationEvent
from ..db.session import session_scope

log = structlog.get_logger(__name__)

_TEXT_EXCERPT_LEN = 80


class LoggingModeration(ModerationLayer):
    """Décorateur qui persiste les verdicts refusés dans `moderation_events`."""

    def __init__(self, inner: ModerationLayer) -> None:
        self._inner = inner

    async def check_ingress(self, text, identity):
        verdict = await self._inner.check_ingress(text, identity)
        if not verdict.allowed:
            await self._persist("ingress", verdict, identity, text)
        return verdict

    async def check_egress(self, text, identity):
        verdict = await self._inner.check_egress(text, identity)
        if not verdict.allowed:
            await self._persist("egress", verdict, identity, text)
        return verdict

    async def _persist(self, phase: str, verdict: ModerationVerdict, identity, text) -> None:
        """Insère une ligne dans moderation_events. Fail-open sur exception."""
        try:
            details = {
                "reason": verdict.reason,
                "identity_kind": identity.role,
                "ip_hash": getattr(identity, "ip_hash", None) or None,
                "text_excerpt": (text or "")[:_TEXT_EXCERPT_LEN],
                "text_len": len(text or ""),
            }
            async with session_scope() as s:
                await s.execute(
                    insert(ModerationEvent).values(
                        phase=phase,
                        detector=verdict.detector or "unknown",
                        verdict="refused",
                        details=details,
                    )
                )
        except Exception as exc:
            log.warning(
                "moderation_event.persist_failed",
                phase=phase,
                detector=verdict.detector,
                error=str(exc),
            )
