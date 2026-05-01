"""Moderation layer — rate limit + length + profanity + injection heuristics + bans.

Injection heuristics log-only by design (visitors can't reach Hermes anyway,
see core/identity.py). Strong signals auto-ban to cut repeat offenders.
"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

import redis.asyncio as aioredis
import structlog

from ..config import Settings
from ..core.identity import Identity, VisitorIdentity
from ..core.protocols import ModerationLayer, ModerationVerdict
from .injection_detector import aggregate_weight, scan

if TYPE_CHECKING:
    from ..observability.metrics import MetricsRecorder

_MAX_TEXT_LEN = 500
_INJECTION_HARD_BAN_SCORE = 10   # ≥10 = temporary ban (1h)

log = structlog.get_logger(__name__)


class BasicModeration(ModerationLayer):
    def __init__(
        self,
        settings: Settings,
        redis: aioredis.Redis,
        *,
        metrics: "MetricsRecorder | None" = None,
    ):
        self._settings = settings
        self._redis = redis
        from better_profanity import profanity as _p
        _p.load_censor_words()   # ~1300 English words; good enough for MVP
        self._profanity = _p
        # Audit Pass 2 P1.B7 — observabilité fail-open ban check.
        if metrics is None:
            from ..observability.metrics import get_null_recorder
            metrics = get_null_recorder()
        self._metrics = metrics

    async def check_ingress(self, text: str, identity: Identity) -> ModerationVerdict:
        if not text or not text.strip():
            return ModerationVerdict(allowed=False, reason="empty", detector="length")
        if len(text) > _MAX_TEXT_LEN:
            return ModerationVerdict(allowed=False, reason="too long", detector="length")

        # Visitor-only gates
        if isinstance(identity, VisitorIdentity):
            # Persisted ban (Postgres) + ephemeral ban (Redis)
            ban = await self._check_ban(identity.ip_hash)
            if not ban.allowed:
                return ban

            verdict = await self._check_rate(identity.ip_hash)
            if not verdict.allowed:
                return verdict

        if self._profanity.contains_profanity(text):
            return ModerationVerdict(allowed=False, reason="langage inapproprié", detector="profanity")

        # Injection signals — log, maybe auto-ban, never deny (visitor is isolated)
        if isinstance(identity, VisitorIdentity):
            signals = scan(text)
            if signals:
                score = aggregate_weight(signals)
                log.warning(
                    "moderation.injection_signals",
                    ip_hash=identity.ip_hash,
                    score=score,
                    patterns=[s.pattern_id for s in signals],
                )
                if score >= _INJECTION_HARD_BAN_SCORE:
                    await self._auto_ban(identity.ip_hash, reason=f"injection score={score}", hours=1)
                    return ModerationVerdict(allowed=False, reason="comportement suspect", detector="injection")

        return ModerationVerdict(allowed=True)

    async def check_egress(self, text: str, identity: Identity) -> ModerationVerdict:
        # Minimal outbound check — the personality + filter prompts already constrain output.
        if len(text) > 2000:
            return ModerationVerdict(allowed=True, rewrite_to=text[:2000], detector="egress_length")
        return ModerationVerdict(allowed=True)

    async def _check_ban(self, ip_hash: str) -> ModerationVerdict:
        """Vérifie si `ip_hash` est banni (Redis fast path → Postgres persisted).

        Audit Pass 2 P1.B7 — politique fail-open documentée :
        Si Postgres est down, on log.ERROR (pas warning, c'est un incident
        infra) + on incrémente `moderation_ban_check_failed_total`. Le
        visiteur est ALLOWED dans ce cas — politique service > sécu pour
        ne pas bloquer tous les visiteurs lors d'un outage DB.

        Trade-off : pendant que la métrique alerte, des bans existants ne
        sont pas enforced. C'est acceptable car (a) les bans Redis du
        fast-path sont toujours actifs, (b) un Postgres down est un
        incident traité en quelques minutes, pas heures.
        """
        # Redis short-lived ban (fast path)
        if await self._redis.exists(f"shugu:ban:{ip_hash}"):
            return ModerationVerdict(allowed=False, reason="accès temporairement suspendu", detector="ban")
        # Postgres persisted ban — best-effort, cached in Redis for 60s after hit
        try:
            from sqlalchemy import select

            from ..db.models import Visitor
            from ..db.session import session_scope
            async with session_scope() as session:
                row = (await session.execute(
                    select(Visitor.ban_until).where(Visitor.ip_hash == ip_hash)
                )).scalar_one_or_none()
            if row is not None:
                from datetime import datetime, timezone
                if row > datetime.now(tz=timezone.utc):
                    ttl = max(int((row - datetime.now(tz=timezone.utc)).total_seconds()), 30)
                    await self._redis.set(f"shugu:ban:{ip_hash}", "1", ex=ttl)
                    return ModerationVerdict(allowed=False, reason="accès suspendu", detector="ban")
        except Exception as exc:
            # log.error (pas warning) — fail-open silencieux = incident sécu.
            # Sans la métrique, l'admin ne saurait pas que les bans Postgres
            # ne sont plus enforced.
            log.error(
                "moderation.ban_check_failed_fail_open",
                error=str(exc),
                error_kind=type(exc).__name__,
            )
            self._metrics.record_moderation_ban_check_failed(
                error_kind=type(exc).__name__,
            )
        return ModerationVerdict(allowed=True)

    async def _auto_ban(self, ip_hash: str, *, reason: str, hours: int) -> None:
        """Ephemeral ban in Redis + persist to Postgres."""
        ttl = hours * 3600
        try:
            await self._redis.set(f"shugu:ban:{ip_hash}", "1", ex=ttl)
            from datetime import datetime, timedelta, timezone

            from sqlalchemy.dialects.postgresql import insert as pg_insert

            from ..db.models import Visitor
            from ..db.session import session_scope
            ban_until = datetime.now(tz=timezone.utc) + timedelta(seconds=ttl)
            async with session_scope() as session:
                stmt = pg_insert(Visitor).values(
                    ip_hash=ip_hash, ban_until=ban_until, ban_reason=reason[:500],
                ).on_conflict_do_update(
                    index_elements=["ip_hash"],
                    set_={"ban_until": ban_until, "ban_reason": reason[:500],
                          "last_seen": datetime.now(tz=timezone.utc)},
                )
                await session.execute(stmt)
            log.warning("moderation.auto_ban", ip_hash=ip_hash, reason=reason, hours=hours)
        except Exception as exc:
            log.warning("moderation.auto_ban_failed", error=str(exc))

    async def _check_rate(self, ip_hash: str) -> ModerationVerdict:
        key = f"shugu:ratelimit:{ip_hash}"
        window = self._settings.visitor_rate_limit_window_s
        maxn = self._settings.visitor_rate_limit_max
        now = int(time.time())
        # Simple rolling-count via Redis list of timestamps, pruned per call.
        pipe = self._redis.pipeline()
        pipe.lpush(key, now)
        pipe.ltrim(key, 0, maxn * 2)   # keep a small buffer
        pipe.lrange(key, 0, maxn * 2 - 1)
        pipe.expire(key, window * 2)
        _, _, timestamps, _ = await pipe.execute()
        recent = [int(t) for t in timestamps if now - int(t) < window]
        if len(recent) > maxn:
            retry = window - (now - recent[-1])
            return ModerationVerdict(
                allowed=False,
                reason=f"rate limit, réessaie dans {max(retry, 1)}s",
                detector="rate_limit",
            )
        return ModerationVerdict(allowed=True)
