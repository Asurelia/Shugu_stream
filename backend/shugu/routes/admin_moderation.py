"""Routes admin moderation — /api/admin/moderation/* gated require_operator.

4 routes :
- GET  /events         : liste paginée avec filtres phase/detector/since
- GET  /stats          : agrégats sur fenêtre temporelle (1h/24h/7d)
- GET  /bans           : liste des bans Redis (clé ban:*)
- DELETE /bans/{hash}  : supprime un ban (idempotent, 204)
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from ..auth.dependencies import require_operator
from ..core.identity import OperatorIdentity
from ..db.session import session_scope
from ..services import moderation_events as svc

router = APIRouter(prefix="/api/admin/moderation", tags=["admin-moderation"])

_IP_HASH_RE = re.compile(r"^[a-f0-9]{64}$")


# ─── Schémas Pydantic ────────────────────────────────────────────────────────


class EventListItem(BaseModel):
    id: int
    phase: Literal["ingress", "egress"]
    detector: str
    verdict: str
    reason: Optional[str] = None
    identity_kind: Optional[str] = None
    ip_hash: Optional[str] = None
    text_excerpt: Optional[str] = None
    text_len: Optional[int] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class EventListResponse(BaseModel):
    total: int
    items: list[EventListItem]


class BucketCount(BaseModel):
    bucket: datetime
    count: int


class StatsResponse(BaseModel):
    window: Literal["1h", "24h", "7d"]
    total_refused: int
    by_detector: dict[str, int]
    by_phase: dict[str, int]
    timeline: list[BucketCount]


class BanItem(BaseModel):
    ip_hash: str
    ttl_seconds: int


class BanListResponse(BaseModel):
    total: int
    items: list[BanItem]


# ─── Redis dependency ─────────────────────────────────────────────────────────


async def _get_redis():
    """Retourne le client Redis global depuis shugu.app.

    Import différé pour permettre le monkeypatching dans les tests
    (pattern identique à require_operator dans auth/dependencies.py).
    """
    from ..app import get_redis
    return get_redis()


# ─── Routes ──────────────────────────────────────────────────────────────────


@router.get("/events", response_model=EventListResponse)
async def list_events(
    phase: Optional[Literal["ingress", "egress"]] = None,
    detector: Optional[str] = None,
    since: Optional[datetime] = None,
    limit: int = Query(25, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _op: OperatorIdentity = Depends(require_operator),
):
    """Liste paginée des ModerationEvent refusés.

    Filtres optionnels : phase, detector, since (ISO 8601 datetime).
    """
    async with session_scope() as s:
        return await svc.list_events(
            s, phase=phase, detector=detector, since=since, limit=limit, offset=offset,
        )


@router.get("/stats", response_model=StatsResponse)
async def stats(
    window: Literal["1h", "24h", "7d"] = "24h",
    _op: OperatorIdentity = Depends(require_operator),
):
    """Agrégats moderation sur une fenêtre temporelle.

    window : '1h' | '24h' (défaut) | '7d'
    """
    async with session_scope() as s:
        return await svc.aggregate_stats(s, window=window)


@router.get("/bans", response_model=BanListResponse)
async def list_bans(
    redis=Depends(_get_redis),
    _op: OperatorIdentity = Depends(require_operator),
):
    """Liste tous les bans Redis actifs (clés ban:*)."""
    items: list[BanItem] = []
    async for key in redis.scan_iter(match="ban:*"):
        key_str = key.decode() if isinstance(key, bytes) else key
        ip_hash = key_str.removeprefix("ban:")
        ttl = await redis.ttl(key)
        items.append(BanItem(ip_hash=ip_hash, ttl_seconds=int(ttl)))
    return BanListResponse(total=len(items), items=items)


@router.delete("/bans/{ip_hash}", status_code=204)
async def clear_ban(
    ip_hash: str,
    redis=Depends(_get_redis),
    _op: OperatorIdentity = Depends(require_operator),
):
    """Supprime un ban Redis. Idempotent (204 même si la clé n'existe pas).

    ip_hash doit être 64 caractères hexadécimaux lowercase (SHA-256).
    """
    if not _IP_HASH_RE.match(ip_hash):
        raise HTTPException(
            status_code=422,
            detail="ip_hash must be 64-char lowercase hex (SHA-256)",
        )
    await redis.delete(f"ban:{ip_hash}")
