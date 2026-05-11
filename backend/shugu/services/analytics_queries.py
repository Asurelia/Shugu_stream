"""Service couche : queries SQL agrégées pour le dashboard admin analytics.

Read-only sur les tables Performance / Visitor / UserAccount. Aucune écriture.
Aucun decorator runtime. Le service est appelé uniquement par les routes
admin_analytics.py gated require_operator.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta, timezone
from typing import AsyncIterator, Literal, Optional

import structlog
from sqlalchemy import and_, cast, desc, func, or_, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import Performance, UserAccount, Visitor

_log = structlog.get_logger(__name__)

WindowLiteral = Literal["1h", "24h", "7d", "30d"]

_WINDOW_DELTA: dict[str, timedelta] = {
    "1h": timedelta(hours=1),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}

# PostgreSQL date_trunc bucket granularity per window
_WINDOW_BUCKET: dict[str, str] = {
    "1h": "minute",
    "24h": "hour",
    "7d": "day",
    "30d": "day",
}

# Hard export limit — 10 000 rows maximum
EXPORT_ROW_LIMIT = 10_000


def _pct_delta(curr: float, prev: float) -> float:
    """Calcule le pourcentage de variation entre deux valeurs."""
    if prev == 0:
        return 0.0 if curr == 0 else 100.0
    return ((curr - prev) / prev) * 100.0


async def _aggregates_window(
    session: AsyncSession,
    *,
    since: datetime,
    until: datetime,
    author_role: Optional[str] = None,
    route: Optional[str] = None,
) -> dict:
    """Calcule les agrégats de Performance sur une fenêtre temporelle."""
    conditions = [
        Performance.created_at >= since,
        Performance.created_at < until,
    ]
    if author_role:
        conditions.append(Performance.author_role == author_role)
    if route:
        conditions.append(Performance.route == route)

    base_where = and_(*conditions)

    total = (
        await session.execute(select(func.count()).select_from(Performance).where(base_where))
    ).scalar_one()

    visitors_unique = (
        await session.execute(
            select(func.count(func.distinct(Performance.author_ip_hash))).where(
                and_(base_where, Performance.author_ip_hash.is_not(None))
            )
        )
    ).scalar_one()

    avg_dur = (
        await session.execute(
            select(func.avg(Performance.duration_ms)).where(
                and_(base_where, Performance.duration_ms.is_not(None))
            )
        )
    ).scalar_one() or 0.0

    # JSONB null vs SQL NULL: asyncpg stores Python None as JSON null ('null'::jsonb)
    # which passes IS NOT NULL. We explicitly exclude JSON null via != 'null'::jsonb.
    refused = (
        await session.execute(
            select(func.count())
            .select_from(Performance)
            .where(
                and_(
                    base_where,
                    or_(
                        and_(
                            Performance.moderation_ingress.is_not(None),
                            Performance.moderation_ingress != cast(text("'null'"), JSONB),
                        ),
                        and_(
                            Performance.moderation_egress.is_not(None),
                            Performance.moderation_egress != cast(text("'null'"), JSONB),
                        ),
                    ),
                )
            )
        )
    ).scalar_one()

    refused_rate = (refused / total * 100) if total else 0.0

    return {
        "performances_total": int(total),
        "visitors_unique": int(visitors_unique),
        "avg_duration_ms": float(avg_dur),
        "moderation_refused_rate": float(refused_rate),
    }


async def count_active_bans(session: AsyncSession, redis) -> int:
    """Compte les bans actifs en DB + Redis, dédupliqués sur ip_hash.

    Graceful degrade : si Redis est indisponible, retourne le count DB seul
    et log un warning. Analytics ne doit jamais bloquer pour un blip Redis.
    """
    db_hashes: set[str] = {
        row
        for (row,) in (
            await session.execute(
                select(Visitor.ip_hash).where(Visitor.ban_until > datetime.now(timezone.utc))
            )
        )
    }

    redis_hashes: set[str] = set()
    try:
        async for key in redis.scan_iter(match="ban:*"):
            key_str = key.decode("utf-8") if isinstance(key, bytes) else key
            redis_hashes.add(key_str.removeprefix("ban:"))
    except Exception:
        _log.warning("analytics.bans_redis_unavailable")

    return len(db_hashes | redis_hashes)


async def kpis(
    session: AsyncSession,
    redis,
    *,
    window: WindowLiteral = "24h",
) -> dict:
    """Calcule les KPIs du dashboard analytics avec deltas vs période précédente."""
    now = datetime.now(timezone.utc)
    delta = _WINDOW_DELTA[window]
    since = now - delta
    prev_since = now - 2 * delta
    prev_until = since

    current = await _aggregates_window(session, since=since, until=now)
    previous = await _aggregates_window(session, since=prev_since, until=prev_until)
    bans = await count_active_bans(session, redis)

    _log.info(
        "admin_analytics.kpis_computed",
        window=window,
        performances_total=current["performances_total"],
    )

    return {
        "window": window,
        "visitors_unique": current["visitors_unique"],
        "visitors_unique_delta_pct": _pct_delta(
            current["visitors_unique"],
            previous["visitors_unique"],
        ),
        "performances_total": current["performances_total"],
        "performances_total_delta_pct": _pct_delta(
            current["performances_total"],
            previous["performances_total"],
        ),
        "avg_duration_ms": current["avg_duration_ms"],
        "avg_duration_ms_delta_pct": _pct_delta(
            current["avg_duration_ms"],
            previous["avg_duration_ms"],
        ),
        "moderation_refused_rate": current["moderation_refused_rate"],
        "moderation_refused_rate_delta_pct": _pct_delta(
            current["moderation_refused_rate"],
            previous["moderation_refused_rate"],
        ),
        "bans_active_count": bans,
    }


async def timeline(
    session: AsyncSession,
    *,
    window: WindowLiteral = "24h",
) -> dict:
    """Retourne les buckets de performances + visiteurs uniques par intervalle temporel."""
    now = datetime.now(timezone.utc)
    since = now - _WINDOW_DELTA[window]
    bucket_unit = _WINDOW_BUCKET[window]

    rows = (
        await session.execute(
            select(
                func.date_trunc(bucket_unit, Performance.created_at).label("bucket"),
                func.count().label("performances"),
                func.count(func.distinct(Performance.author_ip_hash)).label("visitors_unique"),
            )
            .where(Performance.created_at >= since)
            .group_by(text("bucket"))
            .order_by(text("bucket"))
        )
    ).all()

    return {
        "window": window,
        "buckets": [
            {
                "bucket": r.bucket,
                "performances": int(r.performances),
                "visitors_unique": int(r.visitors_unique),
            }
            for r in rows
        ],
    }


async def top_routes(
    session: AsyncSession,
    *,
    window: WindowLiteral = "24h",
    limit: int = 5,
) -> dict:
    """Retourne les top-N routes par nombre de performances sur la fenêtre."""
    now = datetime.now(timezone.utc)
    since = now - _WINDOW_DELTA[window]

    total_result = (
        await session.execute(
            select(func.count()).select_from(Performance).where(Performance.created_at >= since)
        )
    ).scalar_one()
    total = int(total_result)

    rows = (
        await session.execute(
            select(
                Performance.route,
                func.count().label("cnt"),
            )
            .where(Performance.created_at >= since)
            .group_by(Performance.route)
            .order_by(desc("cnt"))
            .limit(limit)
        )
    ).all()

    items = [
        {
            "route": r.route,
            "count": int(r.cnt),
            "pct": (r.cnt / total * 100) if total else 0.0,
        }
        for r in rows
    ]

    return {"window": window, "total": total, "items": items}


async def top_visitors(
    session: AsyncSession,
    *,
    window: WindowLiteral = "24h",
    limit: int = 5,
) -> dict:
    """Retourne les top-N visiteurs par nombre de messages dans la fenêtre."""
    now = datetime.now(timezone.utc)
    since = now - _WINDOW_DELTA[window]

    rows = (
        await session.execute(
            select(
                Performance.author_ip_hash,
                func.count().label("msg_count_window"),
            )
            .where(
                and_(
                    Performance.created_at >= since,
                    Performance.author_ip_hash.is_not(None),
                )
            )
            .group_by(Performance.author_ip_hash)
            .order_by(desc("msg_count_window"))
            .limit(limit)
        )
    ).all()

    now_utc = datetime.now(timezone.utc)
    items = []
    for r in rows:
        ip_hash = r.author_ip_hash
        # Check ban status from Visitor table
        visitor = (
            await session.execute(select(Visitor).where(Visitor.ip_hash == ip_hash))
        ).scalar_one_or_none()

        first_seen = visitor.first_seen if visitor else None
        last_seen = visitor.last_seen if visitor else None
        is_banned = bool(visitor and visitor.ban_until and visitor.ban_until > now_utc)

        items.append(
            {
                "ip_hash_truncated": ip_hash[:12],
                "msg_count_window": int(r.msg_count_window),
                "first_seen": first_seen,
                "last_seen": last_seen,
                "is_banned": is_banned,
            }
        )

    return {"items": items}


async def heatmap(
    session: AsyncSession,
    *,
    window: WindowLiteral = "24h",
) -> dict:
    """Retourne la distribution des performances par heure de la journée (UTC).

    Toujours 24 buckets (0..23), même si certaines heures ont count=0.
    """
    now = datetime.now(timezone.utc)
    since = now - _WINDOW_DELTA[window]

    rows = (
        await session.execute(
            select(
                func.extract("hour", Performance.created_at).label("hour"),
                func.count().label("cnt"),
            )
            .where(Performance.created_at >= since)
            .group_by(text("hour"))
            .order_by(text("hour"))
        )
    ).all()

    counts: dict[int, int] = {int(r.hour): int(r.cnt) for r in rows}
    # Pad to always 24 buckets
    buckets = [{"hour": h, "count": counts.get(h, 0)} for h in range(24)]
    max_count = max((b["count"] for b in buckets), default=0)

    return {"window": window, "buckets": buckets, "max_count": max_count}


async def funnel(session: AsyncSession) -> dict:
    """Calcule le funnel de conversion visiteur → member → VIP.

    - visitors_unique_total : COUNT(DISTINCT ip_hash) ALL TIME dans Visitor
    - members_total : UserAccount avec email_verified_at IS NOT NULL
    - vips_total : UserAccount avec vip_since IS NOT NULL et vip_until NULL ou > now
    """
    now = datetime.now(timezone.utc)

    visitors_total = (await session.execute(select(func.count()).select_from(Visitor))).scalar_one()

    members_total = (
        await session.execute(
            select(func.count())
            .select_from(UserAccount)
            .where(UserAccount.email_verified_at.is_not(None))
        )
    ).scalar_one()

    vips_total = (
        await session.execute(
            select(func.count())
            .select_from(UserAccount)
            .where(
                and_(
                    UserAccount.vip_since.is_not(None),
                    or_(
                        UserAccount.vip_until.is_(None),
                        UserAccount.vip_until > now,
                    ),
                )
            )
        )
    ).scalar_one()

    v = int(visitors_total)
    m = int(members_total)
    vip = int(vips_total)

    return {
        "visitors_unique_total": v,
        "members_total": m,
        "vips_total": vip,
        "visitor_to_member_pct": _pct_delta(m, v) if v else 0.0,
        "member_to_vip_pct": _pct_delta(vip, m) if m else 0.0,
    }


async def performances_list(
    session: AsyncSession,
    *,
    author_role: Optional[str] = None,
    route: Optional[str] = None,
    since: Optional[datetime] = None,
    limit: int = 25,
    offset: int = 0,
) -> dict:
    """Retourne la liste paginée des performances avec filtres optionnels."""
    conditions = []
    if author_role:
        conditions.append(Performance.author_role == author_role)
    if route:
        conditions.append(Performance.route == route)
    if since:
        conditions.append(Performance.created_at >= since)

    where_clause = and_(*conditions) if conditions else None

    count_q = select(func.count()).select_from(Performance)
    list_q = select(Performance)

    if where_clause is not None:
        count_q = count_q.where(where_clause)
        list_q = list_q.where(where_clause)

    total = (await session.execute(count_q)).scalar_one()

    rows = (
        (
            await session.execute(
                list_q.order_by(desc(Performance.created_at)).offset(offset).limit(limit)
            )
        )
        .scalars()
        .all()
    )

    items = []
    for p in rows:
        items.append(
            {
                "performance_id": p.performance_id,
                "author_role": p.author_role,
                "author_ip_hash_truncated": (p.author_ip_hash[:12] if p.author_ip_hash else None),
                "route": p.route,
                "duration_ms": p.duration_ms,
                "has_moderation_refusal": bool(
                    p.moderation_ingress is not None or p.moderation_egress is not None
                ),
                "created_at": p.created_at,
                "played_at": p.played_at,
                "input_text_excerpt": (p.input_text or "")[:120],
                "output_text_excerpt": (p.output_text[:120] if p.output_text else None),
            }
        )

    return {"total": int(total), "items": items}


async def performance_detail(
    session: AsyncSession,
    performance_id: str,
) -> Optional[dict]:
    """Retourne le détail complet d'une performance. None si introuvable."""
    p = (
        await session.execute(
            select(Performance).where(Performance.performance_id == performance_id)
        )
    ).scalar_one_or_none()

    if p is None:
        return None

    return {
        "performance_id": p.performance_id,
        "author_role": p.author_role,
        "author_ip_hash_truncated": (p.author_ip_hash[:12] if p.author_ip_hash else None),
        "route": p.route,
        "duration_ms": p.duration_ms,
        "input_text": p.input_text,
        "output_text": p.output_text,
        "moderation_ingress": p.moderation_ingress,
        "moderation_egress": p.moderation_egress,
        "created_at": p.created_at,
        "played_at": p.played_at,
    }


async def _count_performances_for_export(
    session: AsyncSession,
    *,
    since: datetime,
    until: datetime,
    author_role: Optional[str] = None,
    route: Optional[str] = None,
) -> int:
    """Compte les performances pour l'export CSV (utilisé pour la limite 10k)."""
    conditions = [
        Performance.created_at >= since,
        Performance.created_at <= until,
    ]
    if author_role:
        conditions.append(Performance.author_role == author_role)
    if route:
        conditions.append(Performance.route == route)

    return int(
        (
            await session.execute(
                select(func.count()).select_from(Performance).where(and_(*conditions))
            )
        ).scalar_one()
    )


async def export_performances_csv(
    session: AsyncSession,
    *,
    since: datetime,
    until: datetime,
    author_role: Optional[str] = None,
    route: Optional[str] = None,
    operator_id: str = "unknown",
) -> AsyncIterator[str]:
    """Génère un export CSV streaming des performances.

    Lève ValueError si le count dépasse EXPORT_ROW_LIMIT.
    Audit log structlog à chaque appel.
    """
    count = await _count_performances_for_export(
        session,
        since=since,
        until=until,
        author_role=author_role,
        route=route,
    )

    if count > EXPORT_ROW_LIMIT:
        raise ValueError(f"Export too large: {count} rows exceeds limit of {EXPORT_ROW_LIMIT}")

    _log.info(
        "audit.analytics_export",
        operator_id=operator_id,
        since=since.isoformat(),
        until=until.isoformat(),
        author_role=author_role,
        route=route,
        rows=count,
    )

    conditions = [
        Performance.created_at >= since,
        Performance.created_at <= until,
    ]
    if author_role:
        conditions.append(Performance.author_role == author_role)
    if route:
        conditions.append(Performance.route == route)

    rows = (
        (
            await session.execute(
                select(Performance)
                .where(and_(*conditions))
                .order_by(Performance.created_at)
                .limit(EXPORT_ROW_LIMIT)
            )
        )
        .scalars()
        .all()
    )

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "performance_id",
            "author_role",
            "author_ip_hash_truncated",
            "route",
            "duration_ms",
            "has_moderation_refusal",
            "created_at",
            "played_at",
            "input_text_excerpt",
            "output_text_excerpt",
        ]
    )
    header = buf.getvalue()
    buf.seek(0)
    buf.truncate(0)

    yield header

    for p in rows:
        writer.writerow(
            [
                p.performance_id,
                p.author_role,
                (p.author_ip_hash[:12] if p.author_ip_hash else ""),
                p.route,
                p.duration_ms if p.duration_ms is not None else "",
                "true"
                if (p.moderation_ingress is not None or p.moderation_egress is not None)
                else "false",
                p.created_at.isoformat(),
                p.played_at.isoformat() if p.played_at else "",
                (p.input_text or "")[:120],
                (p.output_text[:120] if p.output_text else ""),
            ]
        )
        line = buf.getvalue()
        buf.seek(0)
        buf.truncate(0)
        yield line
