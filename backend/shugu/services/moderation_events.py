"""Service couche : queries SQL sur ModerationEvent.

Ce module fournit list_events et aggregate_stats — des queries pures
SQLAlchemy async. Pas de logique métier ici : la transformation des
verdicts en rows est faite par LoggingModeration (adapters/).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import ModerationEvent


def _row_to_dict(row: ModerationEvent) -> dict:
    d = row.details or {}
    return {
        "id": row.id,
        "phase": row.phase,
        "detector": row.detector,
        "verdict": row.verdict,
        "reason": d.get("reason"),
        "identity_kind": d.get("identity_kind"),
        "ip_hash": d.get("ip_hash"),
        "text_excerpt": d.get("text_excerpt"),
        "text_len": d.get("text_len"),
        "created_at": row.created_at,
    }


async def list_events(
    session: AsyncSession,
    *,
    phase: Optional[str] = None,
    detector: Optional[str] = None,
    since: Optional[datetime] = None,
    limit: int = 25,
    offset: int = 0,
) -> dict:
    """Retourne {total, items} paginés et filtrés par phase/detector/since."""
    stmt = select(ModerationEvent)
    count_stmt = select(func.count()).select_from(ModerationEvent)
    if phase is not None:
        stmt = stmt.where(ModerationEvent.phase == phase)
        count_stmt = count_stmt.where(ModerationEvent.phase == phase)
    if detector is not None:
        stmt = stmt.where(ModerationEvent.detector == detector)
        count_stmt = count_stmt.where(ModerationEvent.detector == detector)
    if since is not None:
        stmt = stmt.where(ModerationEvent.created_at >= since)
        count_stmt = count_stmt.where(ModerationEvent.created_at >= since)

    total = (await session.execute(count_stmt)).scalar_one()
    rows = (
        await session.execute(
            stmt.order_by(desc(ModerationEvent.created_at)).limit(limit).offset(offset)
        )
    ).scalars().all()
    return {"total": int(total), "items": [_row_to_dict(r) for r in rows]}


_WINDOW_TO_DELTA: dict[str, timedelta] = {
    "1h": timedelta(hours=1),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
}
# date_trunc granularity — PG only supports 'minute', 'hour', 'day', etc.
# '1h' window uses 'minute' buckets (too many for 60, simplify to 'hour' here).
_WINDOW_TO_TRUNC: dict[str, str] = {
    "1h": "hour",
    "24h": "hour",
    "7d": "day",
}


async def aggregate_stats(session: AsyncSession, *, window: str = "24h") -> dict:
    """Agrège les stats sur la fenêtre temporelle demandée.

    Retourne {window, total_refused, by_detector, by_phase, timeline}.
    timeline : liste de {bucket: datetime, count: int} triée par bucket.

    Raise ValueError si window n'est pas dans {'1h', '24h', '7d'}.
    """
    if window not in _WINDOW_TO_DELTA:
        raise ValueError(f"invalid window: {window!r} — must be one of {list(_WINDOW_TO_DELTA)}")
    now = datetime.now(timezone.utc)
    since = now - _WINDOW_TO_DELTA[window]

    # total refused dans la fenêtre
    total = (await session.execute(
        select(func.count()).select_from(ModerationEvent)
        .where(ModerationEvent.created_at >= since)
    )).scalar_one()

    # by_detector
    det_rows = (await session.execute(
        select(ModerationEvent.detector, func.count().label("cnt"))
        .where(ModerationEvent.created_at >= since)
        .group_by(ModerationEvent.detector)
    )).all()
    by_detector = {d: int(c) for d, c in det_rows}

    # by_phase
    phase_rows = (await session.execute(
        select(ModerationEvent.phase, func.count().label("cnt"))
        .where(ModerationEvent.created_at >= since)
        .group_by(ModerationEvent.phase)
    )).all()
    by_phase = {p: int(c) for p, c in phase_rows}

    # timeline — date_trunc par heure ou jour selon la fenêtre
    trunc = _WINDOW_TO_TRUNC[window]
    tl_rows = (await session.execute(
        select(
            func.date_trunc(trunc, ModerationEvent.created_at).label("bucket"),
            func.count().label("count"),
        )
        .where(ModerationEvent.created_at >= since)
        .group_by("bucket")
        .order_by("bucket")
    )).all()
    timeline = [{"bucket": r.bucket, "count": int(r.count)} for r in tl_rows]

    return {
        "window": window,
        "total_refused": int(total),
        "by_detector": by_detector,
        "by_phase": by_phase,
        "timeline": timeline,
    }
