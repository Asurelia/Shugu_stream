"""Routes admin analytics — /api/admin/analytics/* gated require_operator.

8 routes :
- GET /kpis              : KPIs avec deltas vs période précédente
- GET /timeline          : buckets performances + visiteurs uniques par intervalle
- GET /top-routes        : top-N routes par volume
- GET /top-visitors      : top-N visiteurs par msg_count dans la fenêtre
- GET /heatmap           : distribution 24h par heure UTC (toujours 24 buckets)
- GET /funnel            : funnel visiteur → member → VIP
- GET /performances      : liste paginée avec filtres
- GET /performances/{id} : détail complet d'une performance
- GET /export            : export CSV streaming (hard limit 10k rows)
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..auth.dependencies import require_operator
from ..core.identity import OperatorIdentity
from ..db.session import session_scope
from ..services import analytics_queries as svc

router = APIRouter(prefix="/api/admin/analytics", tags=["admin-analytics"])

WindowLiteral = Literal["1h", "24h", "7d", "30d"]


# ─── Schemas Pydantic ─────────────────────────────────────────────────────────


class KPIsResponse(BaseModel):
    window: WindowLiteral
    visitors_unique: int
    visitors_unique_delta_pct: float
    performances_total: int
    performances_total_delta_pct: float
    avg_duration_ms: float
    avg_duration_ms_delta_pct: float
    moderation_refused_rate: float
    moderation_refused_rate_delta_pct: float
    bans_active_count: int


class TimelineBucket(BaseModel):
    bucket: datetime
    performances: int
    visitors_unique: int


class TimelineResponse(BaseModel):
    window: WindowLiteral
    buckets: list[TimelineBucket]


class TopRoute(BaseModel):
    route: str
    count: int
    pct: float


class TopRoutesResponse(BaseModel):
    window: str
    total: int
    items: list[TopRoute]


class TopVisitor(BaseModel):
    ip_hash_truncated: str
    msg_count_window: int
    first_seen: Optional[datetime] = None
    last_seen: Optional[datetime] = None
    is_banned: bool


class TopVisitorsResponse(BaseModel):
    items: list[TopVisitor]


class HeatmapBucket(BaseModel):
    hour: int
    count: int


class HeatmapResponse(BaseModel):
    window: str
    buckets: list[HeatmapBucket]
    max_count: int


class FunnelResponse(BaseModel):
    visitors_unique_total: int
    members_total: int
    vips_total: int
    visitor_to_member_pct: float
    member_to_vip_pct: float


class PerformanceListItem(BaseModel):
    performance_id: str
    author_role: str
    author_ip_hash_truncated: Optional[str] = None
    route: str
    duration_ms: Optional[int] = None
    has_moderation_refusal: bool
    created_at: datetime
    played_at: Optional[datetime] = None
    input_text_excerpt: str
    output_text_excerpt: Optional[str] = None

    model_config = {"from_attributes": True}


class PerformanceListResponse(BaseModel):
    total: int
    items: list[PerformanceListItem]


class PerformanceDetail(BaseModel):
    performance_id: str
    author_role: str
    author_ip_hash_truncated: Optional[str] = None
    route: str
    duration_ms: Optional[int] = None
    input_text: str
    output_text: Optional[str] = None
    moderation_ingress: Optional[dict] = None
    moderation_egress: Optional[dict] = None
    created_at: datetime
    played_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ─── Redis dependency ─────────────────────────────────────────────────────────


async def _get_redis():
    """Retourne le client Redis global depuis shugu.app.

    Import différé pour permettre le monkeypatching dans les tests
    (pattern identique à require_operator dans auth/dependencies.py).
    """
    from ..app import get_redis

    return get_redis()


# ─── Routes ───────────────────────────────────────────────────────────────────


@router.get("/kpis", response_model=KPIsResponse)
async def get_kpis(
    window: WindowLiteral = "24h",
    redis=Depends(_get_redis),
    _op: OperatorIdentity = Depends(require_operator),
):
    """KPIs du dashboard avec deltas vs la période précédente de même taille."""
    async with session_scope() as s:
        return await svc.kpis(s, redis, window=window)


@router.get("/timeline", response_model=TimelineResponse)
async def get_timeline(
    window: WindowLiteral = "24h",
    _op: OperatorIdentity = Depends(require_operator),
):
    """Timeline des performances + visiteurs uniques par bucket temporel."""
    async with session_scope() as s:
        return await svc.timeline(s, window=window)


@router.get("/top-routes", response_model=TopRoutesResponse)
async def get_top_routes(
    window: WindowLiteral = "24h",
    limit: int = Query(default=5, ge=1, le=20),
    _op: OperatorIdentity = Depends(require_operator),
):
    """Top-N routes par volume de performances sur la fenêtre."""
    async with session_scope() as s:
        return await svc.top_routes(s, window=window, limit=limit)


@router.get("/top-visitors", response_model=TopVisitorsResponse)
async def get_top_visitors(
    window: WindowLiteral = "24h",
    limit: int = Query(default=5, ge=1, le=20),
    _op: OperatorIdentity = Depends(require_operator),
):
    """Top-N visiteurs par msg_count dans la fenêtre."""
    async with session_scope() as s:
        return await svc.top_visitors(s, window=window, limit=limit)


@router.get("/heatmap", response_model=HeatmapResponse)
async def get_heatmap(
    window: WindowLiteral = "24h",
    _op: OperatorIdentity = Depends(require_operator),
):
    """Distribution horaire (UTC) des performances — toujours 24 buckets."""
    async with session_scope() as s:
        return await svc.heatmap(s, window=window)


@router.get("/funnel", response_model=FunnelResponse)
async def get_funnel(
    _op: OperatorIdentity = Depends(require_operator),
):
    """Funnel de conversion : visiteur → member → VIP."""
    async with session_scope() as s:
        return await svc.funnel(s)


@router.get("/performances", response_model=PerformanceListResponse)
async def list_performances(
    author_role: Optional[str] = None,
    route: Optional[str] = None,
    since: Optional[datetime] = None,
    limit: int = Query(default=25, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _op: OperatorIdentity = Depends(require_operator),
):
    """Liste paginée des performances avec filtres optionnels."""
    async with session_scope() as s:
        return await svc.performances_list(
            s,
            author_role=author_role,
            route=route,
            since=since,
            limit=limit,
            offset=offset,
        )


@router.get("/performances/{performance_id}", response_model=PerformanceDetail)
async def get_performance(
    performance_id: str,
    _op: OperatorIdentity = Depends(require_operator),
):
    """Détail complet d'une performance (input/output complets + moderation JSON)."""
    async with session_scope() as s:
        result = await svc.performance_detail(s, performance_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Performance not found")
    return result


@router.get("/export")
async def export_csv(
    since: datetime,
    until: datetime,
    export_type: str = Query(default="performances", alias="type"),
    author_role: Optional[str] = None,
    route: Optional[str] = None,
    _op: OperatorIdentity = Depends(require_operator),
):
    """Export CSV streaming des performances. Hard limit : 10 000 rows.

    Retourne HTTP 413 si le count dépasse la limite.
    Retourne HTTP 400 si since > until ou type non supporté.
    """
    if export_type != "performances":
        raise HTTPException(
            status_code=400,
            detail="Only type=performances is supported in this version",
        )
    if since > until:
        raise HTTPException(
            status_code=400,
            detail="since must be before until",
        )

    async def _stream():
        async with session_scope() as s:
            try:
                async for chunk in svc.export_performances_csv(
                    s,
                    since=since,
                    until=until,
                    author_role=author_role,
                    route=route,
                ):
                    yield chunk
            except ValueError as exc:
                # Can't send a 413 mid-stream; raise before streaming starts
                # This is caught by the outer try below
                raise exc

    # Pre-flight count check to return proper 413 before opening stream
    async with session_scope() as s:
        count = await svc._count_performances_for_export(
            s,
            since=since,
            until=until,
            author_role=author_role,
            route=route,
        )

    if count > svc.EXPORT_ROW_LIMIT:
        raise HTTPException(
            status_code=413,
            detail=(
                f"Export too large: {count} rows exceeds limit of "
                f"{svc.EXPORT_ROW_LIMIT}. Reduce the time window."
            ),
        )

    return StreamingResponse(
        _stream(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=performances.csv"},
    )
