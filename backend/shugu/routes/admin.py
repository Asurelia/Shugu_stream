"""Operator-only admin endpoints."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import desc, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ..auth.dependencies import require_operator
from ..core.identity import OperatorIdentity
from ..db.models import Performance, Visitor
from ..db.session import session_scope

router = APIRouter(prefix="/api/admin", tags=["admin"])
log = structlog.get_logger(__name__)


class BanRequest(BaseModel):
    ip_hash: str
    hours: int = 24
    reason: str = ""


class PerformanceOut(BaseModel):
    performance_id: str
    author_role: str
    route: str
    input_text: str
    output_text: Optional[str]
    duration_ms: Optional[int]
    created_at: datetime


class BanOut(BaseModel):
    ip_hash: str
    ban_until: Optional[datetime]
    ban_reason: Optional[str]
    msg_count: int
    last_seen: datetime


@router.get("/performances", response_model=list[PerformanceOut])
async def list_performances(limit: int = 50, _: OperatorIdentity = Depends(require_operator)):
    limit = min(max(limit, 1), 500)
    async with session_scope() as session:
        rows = (await session.execute(
            select(Performance).order_by(desc(Performance.created_at)).limit(limit)
        )).scalars().all()
    return [
        PerformanceOut(
            performance_id=r.performance_id,
            author_role=r.author_role,
            route=r.route,
            input_text=r.input_text,
            output_text=r.output_text,
            duration_ms=r.duration_ms,
            created_at=r.created_at,
        )
        for r in rows
    ]


@router.get("/bans", response_model=list[BanOut])
async def list_bans(_: OperatorIdentity = Depends(require_operator)):
    now = datetime.now(tz=timezone.utc)
    async with session_scope() as session:
        rows = (await session.execute(
            select(Visitor).where(Visitor.ban_until > now).order_by(desc(Visitor.ban_until))
        )).scalars().all()
    return [
        BanOut(ip_hash=r.ip_hash, ban_until=r.ban_until, ban_reason=r.ban_reason,
               msg_count=r.msg_count, last_seen=r.last_seen)
        for r in rows
    ]


@router.post("/bans")
async def ban_ip(body: BanRequest, identity: OperatorIdentity = Depends(require_operator)):
    if len(body.ip_hash) != 64:
        raise HTTPException(status_code=400, detail="ip_hash must be a 64-char sha256")
    ban_until = datetime.now(tz=timezone.utc) + timedelta(hours=body.hours)
    async with session_scope() as session:
        stmt = pg_insert(Visitor).values(
            ip_hash=body.ip_hash, ban_until=ban_until, ban_reason=body.reason[:500],
        ).on_conflict_do_update(
            index_elements=["ip_hash"],
            set_={"ban_until": ban_until, "ban_reason": body.reason[:500]},
        )
        await session.execute(stmt)
    # Also set Redis key so the ban is effective immediately
    from ..app import get_redis
    await get_redis().set(f"shugu:ban:{body.ip_hash}", "1", ex=body.hours * 3600)
    log.warning("admin.ban", operator=identity.username, ip_hash=body.ip_hash,
                hours=body.hours, reason=body.reason)
    return {"ok": True, "ban_until": ban_until.isoformat()}


@router.delete("/bans/{ip_hash}")
async def unban_ip(ip_hash: str, identity: OperatorIdentity = Depends(require_operator)):
    if len(ip_hash) != 64:
        raise HTTPException(status_code=400, detail="ip_hash must be a 64-char sha256")
    async with session_scope() as session:
        result = await session.execute(
            select(Visitor).where(Visitor.ip_hash == ip_hash)
        )
        row = result.scalar_one_or_none()
        if row:
            row.ban_until = None
            row.ban_reason = None
    from ..app import get_redis
    await get_redis().delete(f"shugu:ban:{ip_hash}")
    log.info("admin.unban", operator=identity.username, ip_hash=ip_hash)
    return {"ok": True}


@router.get("/stats")
async def stats(_: OperatorIdentity = Depends(require_operator)):
    from ..app import get_quota, get_redis
    redis = get_redis()
    pending = await redis.llen("shugu:queue:pending")
    ready = await redis.zcard("shugu:queue:ready")
    async with session_scope() as session:
        total_perf = (await session.execute(select(func.count()).select_from(Performance))).scalar_one()
        last_24h = (await session.execute(
            select(func.count()).select_from(Performance).where(
                Performance.created_at > datetime.now(tz=timezone.utc) - timedelta(hours=24)
            )
        )).scalar_one()
        active_bans = (await session.execute(
            select(func.count()).select_from(Visitor).where(
                Visitor.ban_until > datetime.now(tz=timezone.utc)
            )
        )).scalar_one()
    quota_snapshot = await get_quota().snapshot()
    return {
        "queue_pending": pending,
        "queue_ready": ready,
        "performances_total": total_perf,
        "performances_last_24h": last_24h,
        "active_bans": active_bans,
        "quota": quota_snapshot,
    }


@router.get("/quota")
async def quota_snapshot(_: OperatorIdentity = Depends(require_operator)):
    """Daily TTS character budget + 5h LLM request budget, per current plan."""
    from ..app import get_quota
    return await get_quota().snapshot()


@router.get("/metrics")
async def metrics_snapshot(_: OperatorIdentity = Depends(require_operator)):
    """In-memory observability snapshot: rate-limit usage per tool +
    per-minute event rates + TTS TTFB percentiles + interrupt counters."""
    from ..app import get_metrics, get_rate_limiter, get_redis
    redis = get_redis()
    pending = await redis.llen("shugu:queue:pending")
    ready = await redis.zcard("shugu:queue:ready")
    return {
        "queue": {"pending": pending, "ready": ready},
        "rate_limits": get_rate_limiter().snapshot(),
        "metrics": get_metrics().snapshot(),
    }
