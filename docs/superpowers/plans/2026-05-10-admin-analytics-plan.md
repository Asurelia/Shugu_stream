# Admin Analytics — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement task-by-task. Checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remplacer la page mockée `/[username]/admin/analytics` par un dashboard prod-ready (KPIs avec delta, timeline, heatmap, top-N, funnel, liste paginée, export CSV) branché sur `Performance`/`Visitor`/`UserAccount` via 8 routes admin REST gated `require_operator`.

**Architecture:** Read-only sur l'existant. 1 service `analytics_queries.py` (queries SQL agrégées), 1 route `admin_analytics.py` (8 endpoints), refonte UI sur primitives `liquid-glass`. PAS de decorator, PAS de migration, PAS de feature flag.

**Tech Stack:** Python 3.11+ / FastAPI / SQLAlchemy async / Pydantic v2 / pytest+pytest-asyncio / structlog. Next.js App Router / TypeScript strict / liquid-glass primitives.

**Spec source de vérité :** [docs/superpowers/specs/2026-05-10-admin-analytics-design.md](../specs/2026-05-10-admin-analytics-design.md)

**Quality contract (non-négociable) :** prod-ready strict, zéro `@skip` / `@xfail` / placeholder / TODO / "Coming soon". Tous tests activés et passent. Coverage ≥ 90 %.

---

## File Structure

| Path | Action |
|---|---|
| `backend/shugu/services/analytics_queries.py` | **nouveau** |
| `backend/shugu/routes/admin_analytics.py` | **nouveau** |
| `backend/tests/integration/test_admin_analytics_routes.py` | **nouveau** |
| `backend/shugu/app.py` | **modifié** (1 ligne `include_router`) |
| `backend/tests/conftest.py` | **modifié** (3 fixtures supplémentaires) |
| `frontend/src/services/adminAnalyticsClient.ts` | **nouveau** |
| `frontend/src/app/[username]/admin/analytics/_client.tsx` | **refonte complète** |

---

## Task 0: Dépendance Moderation A

**Files:** (read only)

- [ ] **Step 0.1 : Vérifier que les fixtures partagées sont mergées**

```bash
grep -E "^async def (db_session|operator_cookie|api_client|member_cookie)" backend/tests/conftest.py
```

Expected: les 4 fixtures sont définies (créées par sub-project A via ruflo).

- [ ] **Step 0.2 : Si fixtures absentes → BLOCKER**

Si A n'est pas encore mergée et que ces fixtures n'existent pas : **STOP**. Soit attendre la merge de A, soit extraire les fixtures dans une PR conftest indépendante avant analytics. Ne PAS dupliquer les fixtures.

---

## Task 1: Fixtures de seed analytics

**Files:**
- Modify: `backend/tests/conftest.py`

- [ ] **Step 1.1 : Ajouter `seed_performances`, `seed_visitors`, `seed_user_accounts`**

Ajouter à la fin de `conftest.py` :

```python
@pytest_asyncio.fixture
async def seed_performances(db_session):
    """Insère 50 Performance variées sur 6 jours pour tests analytics."""
    from datetime import datetime, timedelta, timezone
    from ulid import ULID
    from sqlalchemy import insert
    from shugu.db.models import Performance

    now = datetime.now(timezone.utc)
    roles = ["visitor", "member", "vip", "operator"]
    routes = ["visitor_ws", "viewer", "operator_ws"]
    rows = []
    for i in range(50):
        rows.append({
            "performance_id": str(ULID()),
            "author_role": roles[i % 4],
            "author_ip_hash": ("a" * 32 + f"{i:032d}")[:64],
            "route": routes[i % 3],
            "input_text": f"input {i}",
            "input_sha256": "0" * 64,
            "output_text": f"output {i}" if i % 5 else None,
            "duration_ms": 100 + i * 10,
            "moderation_ingress": {"detector": "profanity"} if i % 7 == 0 else None,
            "moderation_egress": None,
            "created_at": now - timedelta(hours=i * 3),
        })
    await db_session.execute(insert(Performance), rows)
    await db_session.commit()
    return rows


@pytest_asyncio.fixture
async def seed_visitors(db_session):
    """Insère 30 Visitor avec ban_until variés."""
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import insert
    from shugu.db.models import Visitor

    now = datetime.now(timezone.utc)
    rows = []
    for i in range(30):
        rows.append({
            "ip_hash": ("v" * 32 + f"{i:032d}")[:64],
            "first_seen": now - timedelta(days=i),
            "last_seen": now - timedelta(hours=i),
            "msg_count": i * 3,
            "ban_until": (now + timedelta(hours=2)) if i % 7 == 0 else None,
        })
    await db_session.execute(insert(Visitor), rows)
    await db_session.commit()
    return rows


@pytest_asyncio.fixture
async def seed_user_accounts(db_session):
    """Insère 15 UserAccount : 5 pending, 7 members, 3 VIPs."""
    from datetime import datetime, timezone
    from ulid import ULID
    from sqlalchemy import insert
    from shugu.db.models import UserAccount

    now = datetime.now(timezone.utc)
    rows = []
    for i in range(5):
        rows.append({"id": str(ULID()), "username": f"pending{i}", "email": f"p{i}@ex.com",
                     "password_hash": "x" * 60, "email_verified_at": None,
                     "is_active": True, "created_at": now})
    for i in range(7):
        rows.append({"id": str(ULID()), "username": f"member{i}", "email": f"m{i}@ex.com",
                     "password_hash": "x" * 60, "email_verified_at": now,
                     "is_active": True, "created_at": now})
    for i in range(3):
        rows.append({"id": str(ULID()), "username": f"vip{i}", "email": f"v{i}@ex.com",
                     "password_hash": "x" * 60, "email_verified_at": now,
                     "vip_since": now, "is_active": True, "created_at": now})
    await db_session.execute(insert(UserAccount), rows)
    await db_session.commit()
    return rows
```

- [ ] **Step 1.2 : Vérifier collecte pytest**

```bash
cd backend && pytest tests/conftest.py --collect-only 2>&1 | tail -10
```

Expected: pas d'erreur d'import, fixtures visibles.

- [ ] **Step 1.3 : Commit**

```bash
git add backend/tests/conftest.py
git commit -m "🧪 test(fixtures): seed_performances/visitors/user_accounts for analytics tests"
```

---

## Task 2: TDD `analytics_queries.kpis` complete

**Files:**
- Create: `backend/tests/integration/test_admin_analytics_routes.py`
- Create: `backend/shugu/services/analytics_queries.py`

- [ ] **Step 2.1 : Créer les tests KPIs (route-level)**

Note : on teste directement les routes, pas le service en isolation. Plus simple et plus représentatif (les routes wrappent les queries trivialement).

```python
"""Tests intégration admin analytics — 8 routes + queries agrégées."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest


# ─── KPIs ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_kpis_returns_zero_when_no_data(api_client, operator_cookie):
    r = await api_client.get("/api/admin/analytics/kpis?window=24h", cookies=operator_cookie)
    assert r.status_code == 200
    body = r.json()
    assert body["window"] == "24h"
    assert body["visitors_unique"] == 0
    assert body["performances_total"] == 0


@pytest.mark.asyncio
async def test_kpis_computes_visitors_unique(api_client, operator_cookie, seed_performances):
    # seed_performances spans 6 jours, donc en window=24h on a ~8 perfs et ~8 ip_hash uniques
    r = await api_client.get("/api/admin/analytics/kpis?window=24h", cookies=operator_cookie)
    body = r.json()
    assert body["visitors_unique"] > 0
    assert body["performances_total"] > 0


@pytest.mark.asyncio
async def test_kpis_computes_avg_duration(api_client, operator_cookie, seed_performances):
    r = await api_client.get("/api/admin/analytics/kpis?window=7d", cookies=operator_cookie)
    body = r.json()
    assert body["avg_duration_ms"] > 0


@pytest.mark.asyncio
async def test_kpis_computes_moderation_refused_rate(api_client, operator_cookie, seed_performances):
    r = await api_client.get("/api/admin/analytics/kpis?window=7d", cookies=operator_cookie)
    body = r.json()
    # 50 perfs, 1 sur 7 a moderation_ingress non-null → ~7 refusées → rate ~14%
    assert 0 < body["moderation_refused_rate"] < 30


@pytest.mark.asyncio
async def test_kpis_delta_pct_handles_zero_previous(api_client, operator_cookie):
    # Pas de seed → période précédente vide aussi
    r = await api_client.get("/api/admin/analytics/kpis?window=1h", cookies=operator_cookie)
    body = r.json()
    assert body["visitors_unique_delta_pct"] == 0.0


@pytest.mark.asyncio
async def test_kpis_window_validation(api_client, operator_cookie):
    r = await api_client.get("/api/admin/analytics/kpis?window=invalid", cookies=operator_cookie)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_kpis_requires_operator(api_client):
    r = await api_client.get("/api/admin/analytics/kpis?window=24h")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_kpis_rejects_member_cookie(api_client, member_cookie):
    """Sécurité non-régression : un member ne doit pas accéder à analytics."""
    r = await api_client.get("/api/admin/analytics/kpis?window=24h", cookies=member_cookie)
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_kpis_bans_active_count_db_only(api_client, operator_cookie, seed_visitors):
    """seed_visitors : 30 visitors, 1 sur 7 a ban_until → 5 bans DB."""
    r = await api_client.get("/api/admin/analytics/kpis?window=24h", cookies=operator_cookie)
    body = r.json()
    assert body["bans_active_count"] >= 4  # 30/7 ≈ 5, marge ±1


@pytest.mark.asyncio
async def test_kpis_bans_active_count_redis_only(api_client, operator_cookie, redis_client):
    """3 bans Redis sans aucun en DB."""
    await redis_client.set(b"ban:r1", b"1", ex=3600)
    await redis_client.set(b"ban:r2", b"1", ex=3600)
    await redis_client.set(b"ban:r3", b"1", ex=3600)
    r = await api_client.get("/api/admin/analytics/kpis?window=24h", cookies=operator_cookie)
    assert r.json()["bans_active_count"] == 3


@pytest.mark.asyncio
async def test_kpis_bans_dedup_db_redis_overlap(api_client, operator_cookie, redis_client, db_session):
    """1 ip_hash banni à la fois en DB ET Redis → compté UNE fois."""
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import insert
    from shugu.db.models import Visitor
    overlap_hash = "o" * 64
    now = datetime.now(timezone.utc)
    await db_session.execute(insert(Visitor).values(
        ip_hash=overlap_hash, first_seen=now, last_seen=now, msg_count=0,
        ban_until=now + timedelta(hours=1),
    ))
    await db_session.commit()
    await redis_client.set(f"ban:{overlap_hash}".encode(), b"1", ex=3600)
    r = await api_client.get("/api/admin/analytics/kpis?window=24h", cookies=operator_cookie)
    assert r.json()["bans_active_count"] == 1
```

- [ ] **Step 2.2 : Run → tous FAIL**

```bash
cd backend && pytest tests/integration/test_admin_analytics_routes.py -v -k kpis 2>&1 | head -20
```

Expected: 404 ou ModuleNotFoundError.

- [ ] **Step 2.3 : Créer le service `analytics_queries.py`**

```python
"""Service couche : queries SQL agrégées pour le dashboard admin analytics."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from sqlalchemy import and_, case, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import Performance, UserAccount, Visitor

WindowLiteral = Literal["1h", "24h", "7d", "30d"]

_WINDOW_DELTA = {
    "1h": timedelta(hours=1),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}


def _pct_delta(curr: float, prev: float) -> float:
    if prev == 0:
        return 0.0 if curr == 0 else 100.0
    return ((curr - prev) / prev) * 100.0


async def _aggregates_window(session: AsyncSession, *, since: datetime, until: datetime) -> dict:
    base_where = and_(Performance.created_at >= since, Performance.created_at < until)

    total = (await session.execute(
        select(func.count()).select_from(Performance).where(base_where)
    )).scalar_one()
    visitors_unique = (await session.execute(
        select(func.count(func.distinct(Performance.author_ip_hash))).where(base_where)
    )).scalar_one()
    avg_dur = (await session.execute(
        select(func.avg(Performance.duration_ms)).where(base_where)
    )).scalar_one() or 0.0
    refused = (await session.execute(
        select(func.count()).select_from(Performance).where(and_(
            base_where,
            or_(Performance.moderation_ingress.is_not(None),
                Performance.moderation_egress.is_not(None)),
        ))
    )).scalar_one()
    refused_rate = (refused / total * 100) if total else 0.0
    return {
        "performances_total": int(total),
        "visitors_unique": int(visitors_unique),
        "avg_duration_ms": float(avg_dur),
        "moderation_refused_rate": float(refused_rate),
    }


async def count_active_bans(session: AsyncSession, redis) -> int:
    db_hashes = {row for (row,) in (await session.execute(
        select(Visitor.ip_hash).where(Visitor.ban_until > datetime.now(timezone.utc))
    ))}
    redis_hashes: set[str] = set()
    try:
        async for key in redis.scan_iter(match="ban:*"):
            key_str = key.decode("utf-8") if isinstance(key, bytes) else key
            redis_hashes.add(key_str.removeprefix("ban:"))
    except Exception:
        import structlog
        structlog.get_logger(__name__).warning("analytics.bans_redis_unavailable")
    return len(db_hashes | redis_hashes)


async def kpis(session: AsyncSession, redis, *, window: WindowLiteral = "24h") -> dict:
    if window not in _WINDOW_DELTA:
        raise ValueError(f"invalid window: {window}")
    now = datetime.now(timezone.utc)
    delta = _WINDOW_DELTA[window]
    current = await _aggregates_window(session, since=now - delta, until=now)
    previous = await _aggregates_window(session, since=now - 2 * delta, until=now - delta)
    bans = await count_active_bans(session, redis)
    return {
        "window": window,
        "visitors_unique": current["visitors_unique"],
        "visitors_unique_delta_pct": _pct_delta(current["visitors_unique"], previous["visitors_unique"]),
        "performances_total": current["performances_total"],
        "performances_total_delta_pct": _pct_delta(current["performances_total"], previous["performances_total"]),
        "avg_duration_ms": current["avg_duration_ms"],
        "avg_duration_ms_delta_pct": _pct_delta(current["avg_duration_ms"], previous["avg_duration_ms"]),
        "moderation_refused_rate": current["moderation_refused_rate"],
        "moderation_refused_rate_delta_pct": _pct_delta(current["moderation_refused_rate"], previous["moderation_refused_rate"]),
        "bans_active_count": bans,
    }
```

- [ ] **Step 2.4 : Créer la route**

```python
"""Routes admin analytics — /api/admin/analytics/* gated require_operator."""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from ..auth.dependencies import require_operator
from ..core.identity import OperatorIdentity
from ..db.session import session_scope
from ..services import analytics_queries as svc

router = APIRouter(prefix="/api/admin/analytics", tags=["admin-analytics"])


WindowLiteral = Literal["1h", "24h", "7d", "30d"]


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


def _get_redis(request: Request):
    """Récupère le client redis depuis l'app state.

    Pattern projet : Redis exposé via app.state.redis au startup event de app.py.
    Voir comment c'est fait dans backend/shugu/app.py et adapter si différent.
    """
    return request.app.state.redis


@router.get("/kpis", response_model=KPIsResponse)
async def kpis(
    window: WindowLiteral = "24h",
    redis=Depends(_get_redis),
    _op: OperatorIdentity = Depends(require_operator),
):
    async with session_scope() as s:
        return await svc.kpis(s, redis, window=window)
```

- [ ] **Step 2.5 : Wire le router dans `app.py`**

Ajouter avec les autres `include_router` :

```python
from .routes.admin_analytics import router as admin_analytics_router
# …
app.include_router(admin_analytics_router)
```

- [ ] **Step 2.6 : Run KPIs tests → PASS**

```bash
cd backend && pytest tests/integration/test_admin_analytics_routes.py -v -k kpis
```

Expected: 11 PASS.

- [ ] **Step 2.7 : Commit**

```bash
git add backend/tests/integration/test_admin_analytics_routes.py backend/shugu/services/analytics_queries.py backend/shugu/routes/admin_analytics.py backend/shugu/app.py
git commit -m "✨ feat(analytics): /kpis route + service kpis() with deltas + ban dedup + 11 tests"
```

---

## Task 3: TDD `/timeline` route

**Files:**
- Modify: `backend/tests/integration/test_admin_analytics_routes.py`
- Modify: `backend/shugu/services/analytics_queries.py`
- Modify: `backend/shugu/routes/admin_analytics.py`

- [ ] **Step 3.1 : Tests timeline**

```python
@pytest.mark.asyncio
async def test_timeline_24h_returns_24_buckets(api_client, operator_cookie, seed_performances):
    r = await api_client.get("/api/admin/analytics/timeline?window=24h", cookies=operator_cookie)
    assert r.status_code == 200
    body = r.json()
    assert body["window"] == "24h"
    # 24h / bucket de 1h = max 24 buckets (peut être moins si données creuses)
    assert len(body["buckets"]) <= 24


@pytest.mark.asyncio
async def test_timeline_7d_bucket_size_1d(api_client, operator_cookie, seed_performances):
    r = await api_client.get("/api/admin/analytics/timeline?window=7d", cookies=operator_cookie)
    body = r.json()
    assert len(body["buckets"]) <= 7


@pytest.mark.asyncio
async def test_timeline_includes_visitors_unique_per_bucket(api_client, operator_cookie, seed_performances):
    r = await api_client.get("/api/admin/analytics/timeline?window=7d", cookies=operator_cookie)
    body = r.json()
    if body["buckets"]:
        b = body["buckets"][0]
        assert "performances" in b
        assert "visitors_unique" in b
        assert "bucket" in b


@pytest.mark.asyncio
async def test_timeline_requires_operator(api_client):
    r = await api_client.get("/api/admin/analytics/timeline?window=24h")
    assert r.status_code == 401
```

- [ ] **Step 3.2 : Run → FAIL**

- [ ] **Step 3.3 : Ajouter `timeline()` au service**

```python
_WINDOW_BUCKET = {
    "1h": "minute",   # PostgreSQL date_trunc unit ; bucket 1 min sur 1h
    "24h": "hour",
    "7d": "day",
    "30d": "day",
}


async def timeline(session: AsyncSession, *, window: WindowLiteral = "24h") -> dict:
    if window not in _WINDOW_DELTA:
        raise ValueError(f"invalid window: {window}")
    now = datetime.now(timezone.utc)
    since = now - _WINDOW_DELTA[window]
    bucket = _WINDOW_BUCKET[window]
    rows = (await session.execute(
        select(
            func.date_trunc(bucket, Performance.created_at).label("bucket"),
            func.count().label("performances"),
            func.count(func.distinct(Performance.author_ip_hash)).label("visitors_unique"),
        )
        .where(Performance.created_at >= since)
        .group_by("bucket")
        .order_by("bucket")
    )).all()
    return {
        "window": window,
        "buckets": [
            {"bucket": r.bucket, "performances": int(r.performances),
             "visitors_unique": int(r.visitors_unique)}
            for r in rows
        ],
    }
```

- [ ] **Step 3.4 : Ajouter route + schemas Pydantic**

```python
class TimelineBucket(BaseModel):
    bucket: datetime
    performances: int
    visitors_unique: int


class TimelineResponse(BaseModel):
    window: WindowLiteral
    buckets: list[TimelineBucket]


@router.get("/timeline", response_model=TimelineResponse)
async def timeline(
    window: WindowLiteral = "24h",
    _op: OperatorIdentity = Depends(require_operator),
):
    async with session_scope() as s:
        return await svc.timeline(s, window=window)
```

- [ ] **Step 3.5 : Run → 4 PASS**

```bash
cd backend && pytest tests/integration/test_admin_analytics_routes.py -v -k timeline
```

- [ ] **Step 3.6 : Commit**

```bash
git add backend/tests/integration/test_admin_analytics_routes.py backend/shugu/services/analytics_queries.py backend/shugu/routes/admin_analytics.py
git commit -m "✨ feat(analytics): /timeline route — date_trunc buckets + visitors_unique per bucket"
```

---

## Task 4: TDD `/top-routes` route

- [ ] **Step 4.1 : Tests**

```python
@pytest.mark.asyncio
async def test_top_routes_groups_by_route_desc(api_client, operator_cookie, seed_performances):
    r = await api_client.get("/api/admin/analytics/top-routes?window=7d", cookies=operator_cookie)
    body = r.json()
    assert body["total"] > 0
    counts = [item["count"] for item in body["items"]]
    assert counts == sorted(counts, reverse=True)


@pytest.mark.asyncio
async def test_top_routes_respects_limit(api_client, operator_cookie, seed_performances):
    r = await api_client.get("/api/admin/analytics/top-routes?window=7d&limit=2", cookies=operator_cookie)
    assert len(r.json()["items"]) <= 2


@pytest.mark.asyncio
async def test_top_routes_pct_of_total(api_client, operator_cookie, seed_performances):
    r = await api_client.get("/api/admin/analytics/top-routes?window=7d", cookies=operator_cookie)
    body = r.json()
    total = body["total"]
    for item in body["items"]:
        expected_pct = (item["count"] / total * 100) if total else 0
        assert abs(item["pct"] - expected_pct) < 0.01
```

- [ ] **Step 4.2 : Run → FAIL**

- [ ] **Step 4.3 : Service + route**

Ajouter au service :
```python
async def top_routes(session: AsyncSession, *, window: WindowLiteral, limit: int = 5) -> dict:
    if window not in _WINDOW_DELTA:
        raise ValueError(f"invalid window: {window}")
    if not 1 <= limit <= 20:
        raise ValueError("limit must be 1..20")
    since = datetime.now(timezone.utc) - _WINDOW_DELTA[window]
    total = (await session.execute(
        select(func.count()).select_from(Performance).where(Performance.created_at >= since)
    )).scalar_one()
    rows = (await session.execute(
        select(Performance.route, func.count().label("c"))
        .where(Performance.created_at >= since)
        .group_by(Performance.route)
        .order_by(desc("c"))
        .limit(limit)
    )).all()
    items = [{"route": r.route, "count": int(r.c),
              "pct": (int(r.c) / total * 100) if total else 0.0}
             for r in rows]
    return {"window": window, "total": int(total), "items": items}
```

Route :
```python
class TopRoute(BaseModel):
    route: str
    count: int
    pct: float

class TopRoutesResponse(BaseModel):
    window: WindowLiteral
    total: int
    items: list[TopRoute]


@router.get("/top-routes", response_model=TopRoutesResponse)
async def top_routes(
    window: WindowLiteral = "24h",
    limit: int = Query(5, ge=1, le=20),
    _op: OperatorIdentity = Depends(require_operator),
):
    async with session_scope() as s:
        return await svc.top_routes(s, window=window, limit=limit)
```

- [ ] **Step 4.4 : Run → 3 PASS**

- [ ] **Step 4.5 : Commit**

```bash
git commit -m "✨ feat(analytics): /top-routes route + GROUP BY route with pct of total"
```

---

## Task 5: TDD `/top-visitors` route

- [ ] **Step 5.1 : Tests**

```python
@pytest.mark.asyncio
async def test_top_visitors_returns_truncated_hash(api_client, operator_cookie, seed_performances):
    r = await api_client.get("/api/admin/analytics/top-visitors?window=7d", cookies=operator_cookie)
    body = r.json()
    for item in body["items"]:
        assert len(item["ip_hash_truncated"]) == 12
        assert "ip_hash" not in item


@pytest.mark.asyncio
async def test_top_visitors_orders_by_msg_count_desc(api_client, operator_cookie, seed_performances):
    r = await api_client.get("/api/admin/analytics/top-visitors?window=7d", cookies=operator_cookie)
    counts = [item["msg_count_window"] for item in r.json()["items"]]
    assert counts == sorted(counts, reverse=True)


@pytest.mark.asyncio
async def test_top_visitors_is_banned_flag(api_client, operator_cookie, db_session):
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import insert
    from shugu.db.models import Performance, Visitor
    from ulid import ULID

    now = datetime.now(timezone.utc)
    banned_hash = "b" * 64
    await db_session.execute(insert(Visitor).values(
        ip_hash=banned_hash, first_seen=now, last_seen=now, msg_count=10,
        ban_until=now + timedelta(hours=1),
    ))
    for _ in range(3):
        await db_session.execute(insert(Performance).values(
            performance_id=str(ULID()), author_role="visitor", author_ip_hash=banned_hash,
            route="visitor_ws", input_text="x", input_sha256="0"*64,
            created_at=now - timedelta(hours=1),
        ))
    await db_session.commit()

    r = await api_client.get("/api/admin/analytics/top-visitors?window=24h", cookies=operator_cookie)
    body = r.json()
    banned_item = next((it for it in body["items"] if it["ip_hash_truncated"] == banned_hash[:12]), None)
    assert banned_item is not None
    assert banned_item["is_banned"] is True
```

- [ ] **Step 5.2 : Run → FAIL**

- [ ] **Step 5.3 : Service + route**

```python
async def top_visitors(session: AsyncSession, *, window: WindowLiteral, limit: int = 5) -> dict:
    if window not in _WINDOW_DELTA:
        raise ValueError(f"invalid window: {window}")
    if not 1 <= limit <= 50:
        raise ValueError("limit must be 1..50")
    now = datetime.now(timezone.utc)
    since = now - _WINDOW_DELTA[window]
    rows = (await session.execute(
        select(
            Performance.author_ip_hash,
            func.count().label("msg_count_window"),
            func.min(Performance.created_at).label("first_in_window"),
            func.max(Performance.created_at).label("last_in_window"),
        )
        .where(and_(Performance.created_at >= since,
                    Performance.author_ip_hash.is_not(None)))
        .group_by(Performance.author_ip_hash)
        .order_by(desc("msg_count_window"))
        .limit(limit)
    )).all()

    hashes = [r.author_ip_hash for r in rows]
    if not hashes:
        return {"items": []}

    banned_q = (await session.execute(
        select(Visitor.ip_hash).where(and_(Visitor.ip_hash.in_(hashes),
                                            Visitor.ban_until > now))
    ))
    banned_set = {h for (h,) in banned_q}

    items = [{
        "ip_hash_truncated": (r.author_ip_hash or "")[:12],
        "msg_count_window": int(r.msg_count_window),
        "first_seen": r.first_in_window,
        "last_seen": r.last_in_window,
        "is_banned": r.author_ip_hash in banned_set,
    } for r in rows]
    return {"items": items}
```

Route :
```python
class TopVisitor(BaseModel):
    ip_hash_truncated: str
    msg_count_window: int
    first_seen: datetime
    last_seen: datetime
    is_banned: bool

class TopVisitorsResponse(BaseModel):
    items: list[TopVisitor]


@router.get("/top-visitors", response_model=TopVisitorsResponse)
async def top_visitors(
    window: WindowLiteral = "24h",
    limit: int = Query(5, ge=1, le=50),
    _op: OperatorIdentity = Depends(require_operator),
):
    async with session_scope() as s:
        return await svc.top_visitors(s, window=window, limit=limit)
```

- [ ] **Step 5.4 : Run → 3 PASS**

- [ ] **Step 5.5 : Commit**

```bash
git commit -m "✨ feat(analytics): /top-visitors with truncated hash + is_banned flag"
```

---

## Task 6: TDD `/heatmap` route

- [ ] **Step 6.1 : Tests**

```python
@pytest.mark.asyncio
async def test_heatmap_always_24_buckets(api_client, operator_cookie):
    r = await api_client.get("/api/admin/analytics/heatmap?window=24h", cookies=operator_cookie)
    body = r.json()
    assert len(body["buckets"]) == 24
    assert [b["hour"] for b in body["buckets"]] == list(range(24))


@pytest.mark.asyncio
async def test_heatmap_groups_by_hour(api_client, operator_cookie, seed_performances):
    r = await api_client.get("/api/admin/analytics/heatmap?window=7d", cookies=operator_cookie)
    body = r.json()
    assert body["max_count"] >= 0
    total = sum(b["count"] for b in body["buckets"])
    assert total > 0


@pytest.mark.asyncio
async def test_heatmap_max_count_correct(api_client, operator_cookie, seed_performances):
    r = await api_client.get("/api/admin/analytics/heatmap?window=7d", cookies=operator_cookie)
    body = r.json()
    assert body["max_count"] == max(b["count"] for b in body["buckets"])
```

- [ ] **Step 6.2 : Run → FAIL**

- [ ] **Step 6.3 : Service + route**

```python
async def heatmap_hour_of_day(session: AsyncSession, *, window: WindowLiteral) -> dict:
    if window not in _WINDOW_DELTA:
        raise ValueError(f"invalid window: {window}")
    since = datetime.now(timezone.utc) - _WINDOW_DELTA[window]
    rows = (await session.execute(
        select(
            func.extract("hour", Performance.created_at).label("hour"),
            func.count().label("c"),
        )
        .where(Performance.created_at >= since)
        .group_by("hour")
    )).all()
    by_hour = {int(r.hour): int(r.c) for r in rows}
    buckets = [{"hour": h, "count": by_hour.get(h, 0)} for h in range(24)]
    return {"window": window, "buckets": buckets,
            "max_count": max((b["count"] for b in buckets), default=0)}
```

Route :
```python
class HeatmapBucket(BaseModel):
    hour: int
    count: int

class HeatmapResponse(BaseModel):
    window: WindowLiteral
    buckets: list[HeatmapBucket]
    max_count: int


@router.get("/heatmap", response_model=HeatmapResponse)
async def heatmap(
    window: WindowLiteral = "24h",
    _op: OperatorIdentity = Depends(require_operator),
):
    async with session_scope() as s:
        return await svc.heatmap_hour_of_day(s, window=window)
```

- [ ] **Step 6.4 : Run → 3 PASS**
- [ ] **Step 6.5 : Commit**

```bash
git commit -m "✨ feat(analytics): /heatmap route — hour-of-day UTC with always-24-buckets"
```

---

## Task 7: TDD `/funnel` route

- [ ] **Step 7.1 : Tests**

```python
@pytest.mark.asyncio
async def test_funnel_3_levels(api_client, operator_cookie, seed_visitors, seed_user_accounts):
    r = await api_client.get("/api/admin/analytics/funnel", cookies=operator_cookie)
    body = r.json()
    assert body["visitors_unique_total"] == 30
    assert body["members_total"] == 10   # 7 members + 3 vips (tous email_verified)
    assert body["vips_total"] == 3


@pytest.mark.asyncio
async def test_funnel_ratios_handle_zero_visitors(api_client, operator_cookie):
    r = await api_client.get("/api/admin/analytics/funnel", cookies=operator_cookie)
    body = r.json()
    assert body["visitor_to_member_pct"] == 0.0
    assert body["member_to_vip_pct"] == 0.0


@pytest.mark.asyncio
async def test_funnel_excludes_unverified(api_client, operator_cookie, seed_user_accounts):
    r = await api_client.get("/api/admin/analytics/funnel", cookies=operator_cookie)
    body = r.json()
    # 5 pending exclus, 7 members + 3 vips = 10 total
    assert body["members_total"] == 10


@pytest.mark.asyncio
async def test_funnel_excludes_expired_vips(api_client, operator_cookie, db_session):
    from datetime import datetime, timedelta, timezone
    from ulid import ULID
    from sqlalchemy import insert
    from shugu.db.models import UserAccount
    now = datetime.now(timezone.utc)
    await db_session.execute(insert(UserAccount).values(
        id=str(ULID()), username="expired_vip", email="ev@ex.com",
        password_hash="x" * 60, email_verified_at=now,
        vip_since=now - timedelta(days=30), vip_until=now - timedelta(days=1),
        is_active=True, created_at=now,
    ))
    await db_session.commit()
    r = await api_client.get("/api/admin/analytics/funnel", cookies=operator_cookie)
    assert r.json()["vips_total"] == 0  # le vip expired n'est pas compté
```

- [ ] **Step 7.2 : Run → FAIL**

- [ ] **Step 7.3 : Service + route**

```python
async def funnel(session: AsyncSession) -> dict:
    now = datetime.now(timezone.utc)
    visitors_unique_total = (await session.execute(
        select(func.count()).select_from(Visitor)
    )).scalar_one()
    members_total = (await session.execute(
        select(func.count()).select_from(UserAccount).where(UserAccount.email_verified_at.is_not(None))
    )).scalar_one()
    vips_total = (await session.execute(
        select(func.count()).select_from(UserAccount).where(and_(
            UserAccount.vip_since.is_not(None),
            or_(UserAccount.vip_until.is_(None), UserAccount.vip_until > now),
        ))
    )).scalar_one()
    return {
        "visitors_unique_total": int(visitors_unique_total),
        "members_total": int(members_total),
        "vips_total": int(vips_total),
        "visitor_to_member_pct": (int(members_total) / int(visitors_unique_total) * 100) if visitors_unique_total else 0.0,
        "member_to_vip_pct": (int(vips_total) / int(members_total) * 100) if members_total else 0.0,
    }
```

Route :
```python
class FunnelResponse(BaseModel):
    visitors_unique_total: int
    members_total: int
    vips_total: int
    visitor_to_member_pct: float
    member_to_vip_pct: float


@router.get("/funnel", response_model=FunnelResponse)
async def funnel(_op: OperatorIdentity = Depends(require_operator)):
    async with session_scope() as s:
        return await svc.funnel(s)
```

- [ ] **Step 7.4 : Run → 4 PASS**
- [ ] **Step 7.5 : Commit**

```bash
git commit -m "✨ feat(analytics): /funnel route — visitor → member → VIP with ratios"
```

---

## Task 8: TDD `/performances` list + detail

- [ ] **Step 8.1 : Tests list**

```python
@pytest.mark.asyncio
async def test_performances_list_returns_paginated(api_client, operator_cookie, seed_performances):
    r = await api_client.get("/api/admin/analytics/performances?limit=10", cookies=operator_cookie)
    body = r.json()
    assert body["total"] == 50
    assert len(body["items"]) == 10


@pytest.mark.asyncio
async def test_performances_list_filters_by_author_role(api_client, operator_cookie, seed_performances):
    r = await api_client.get("/api/admin/analytics/performances?author_role=vip&limit=50", cookies=operator_cookie)
    body = r.json()
    for item in body["items"]:
        assert item["author_role"] == "vip"


@pytest.mark.asyncio
async def test_performances_list_filters_by_route(api_client, operator_cookie, seed_performances):
    r = await api_client.get("/api/admin/analytics/performances?route=viewer&limit=50", cookies=operator_cookie)
    for item in r.json()["items"]:
        assert item["route"] == "viewer"


@pytest.mark.asyncio
async def test_performances_list_excerpt_truncated(api_client, operator_cookie, db_session):
    from datetime import datetime, timezone
    from sqlalchemy import insert
    from shugu.db.models import Performance
    from ulid import ULID
    long_text = "x" * 300
    await db_session.execute(insert(Performance).values(
        performance_id=str(ULID()), author_role="visitor", author_ip_hash="a" * 64,
        route="visitor_ws", input_text=long_text, input_sha256="0" * 64,
        output_text=long_text, created_at=datetime.now(timezone.utc),
    ))
    await db_session.commit()
    r = await api_client.get("/api/admin/analytics/performances?limit=5", cookies=operator_cookie)
    item = r.json()["items"][0]
    assert len(item["input_text_excerpt"]) <= 120
    assert len(item["output_text_excerpt"]) <= 120


@pytest.mark.asyncio
async def test_performances_list_truncates_ip_hash(api_client, operator_cookie, seed_performances):
    r = await api_client.get("/api/admin/analytics/performances?limit=1", cookies=operator_cookie)
    item = r.json()["items"][0]
    assert item["author_ip_hash_truncated"] is None or len(item["author_ip_hash_truncated"]) == 12
    assert "author_ip_hash" not in item


@pytest.mark.asyncio
async def test_performance_detail_returns_full_text(api_client, operator_cookie, seed_performances):
    list_r = await api_client.get("/api/admin/analytics/performances?limit=1", cookies=operator_cookie)
    pid = list_r.json()["items"][0]["performance_id"]
    r = await api_client.get(f"/api/admin/analytics/performances/{pid}", cookies=operator_cookie)
    assert r.status_code == 200
    body = r.json()
    assert "input_text" in body  # complet, pas excerpt
    assert "output_text" in body


@pytest.mark.asyncio
async def test_performance_detail_404_unknown(api_client, operator_cookie):
    r = await api_client.get("/api/admin/analytics/performances/00000000000000000000000000", cookies=operator_cookie)
    assert r.status_code == 404
```

- [ ] **Step 8.2 : Run → FAIL**

- [ ] **Step 8.3 : Service + routes**

```python
async def list_performances(
    session: AsyncSession,
    *,
    author_role: Optional[str] = None,
    route: Optional[str] = None,
    since: Optional[datetime] = None,
    limit: int = 25,
    offset: int = 0,
) -> dict:
    stmt = select(Performance)
    count_stmt = select(func.count()).select_from(Performance)
    if author_role:
        stmt = stmt.where(Performance.author_role == author_role)
        count_stmt = count_stmt.where(Performance.author_role == author_role)
    if route:
        stmt = stmt.where(Performance.route == route)
        count_stmt = count_stmt.where(Performance.route == route)
    if since:
        stmt = stmt.where(Performance.created_at >= since)
        count_stmt = count_stmt.where(Performance.created_at >= since)
    total = (await session.execute(count_stmt)).scalar_one()
    rows = (await session.execute(
        stmt.order_by(desc(Performance.created_at)).limit(limit).offset(offset)
    )).scalars().all()
    items = [{
        "performance_id": r.performance_id,
        "author_role": r.author_role,
        "author_ip_hash_truncated": (r.author_ip_hash or "")[:12] if r.author_ip_hash else None,
        "route": r.route,
        "duration_ms": r.duration_ms,
        "has_moderation_refusal": (r.moderation_ingress is not None) or (r.moderation_egress is not None),
        "created_at": r.created_at,
        "played_at": r.played_at,
        "input_text_excerpt": (r.input_text or "")[:120],
        "output_text_excerpt": (r.output_text or "")[:120] if r.output_text else None,
    } for r in rows]
    return {"total": int(total), "items": items}


async def get_performance_detail(session: AsyncSession, performance_id: str) -> Optional[dict]:
    row = (await session.execute(
        select(Performance).where(Performance.performance_id == performance_id)
    )).scalar_one_or_none()
    if row is None:
        return None
    return {
        "performance_id": row.performance_id,
        "author_role": row.author_role,
        "author_ip_hash_truncated": (row.author_ip_hash or "")[:12] if row.author_ip_hash else None,
        "route": row.route,
        "duration_ms": row.duration_ms,
        "input_text": row.input_text,
        "output_text": row.output_text,
        "moderation_ingress": row.moderation_ingress,
        "moderation_egress": row.moderation_egress,
        "created_at": row.created_at,
        "played_at": row.played_at,
    }
```

Routes :
```python
class PerformanceListItem(BaseModel):
    performance_id: str
    author_role: str
    author_ip_hash_truncated: Optional[str]
    route: str
    duration_ms: Optional[int]
    has_moderation_refusal: bool
    created_at: datetime
    played_at: Optional[datetime]
    input_text_excerpt: str
    output_text_excerpt: Optional[str]

class PerformanceListResponse(BaseModel):
    total: int
    items: list[PerformanceListItem]

class PerformanceDetail(BaseModel):
    performance_id: str
    author_role: str
    author_ip_hash_truncated: Optional[str]
    route: str
    duration_ms: Optional[int]
    input_text: str
    output_text: Optional[str]
    moderation_ingress: Optional[dict]
    moderation_egress: Optional[dict]
    created_at: datetime
    played_at: Optional[datetime]


@router.get("/performances", response_model=PerformanceListResponse)
async def list_performances(
    author_role: Optional[str] = None,
    route_filter: Optional[str] = Query(default=None, alias="route"),
    since: Optional[datetime] = None,
    limit: int = Query(25, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _op: OperatorIdentity = Depends(require_operator),
):
    async with session_scope() as s:
        return await svc.list_performances(
            s, author_role=author_role, route=route_filter,
            since=since, limit=limit, offset=offset,
        )


@router.get("/performances/{performance_id}", response_model=PerformanceDetail)
async def performance_detail(
    performance_id: str,
    _op: OperatorIdentity = Depends(require_operator),
):
    async with session_scope() as s:
        detail = await svc.get_performance_detail(s, performance_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="performance not found")
        return detail
```

- [ ] **Step 8.4 : Run → 7 PASS**
- [ ] **Step 8.5 : Commit**

```bash
git commit -m "✨ feat(analytics): /performances list+detail routes with filters + 120ch excerpt + ip_hash truncate"
```

---

## Task 9: TDD `/export` CSV streaming

- [ ] **Step 9.1 : Tests**

```python
@pytest.mark.asyncio
async def test_export_csv_returns_csv(api_client, operator_cookie, seed_performances):
    r = await api_client.get("/api/admin/analytics/export?type=performances", cookies=operator_cookie)
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    csv_text = r.text
    assert csv_text.startswith("performance_id,author_role")
    assert csv_text.count("\n") >= 50  # header + 50 rows


@pytest.mark.asyncio
async def test_export_csv_413_when_over_10k(api_client, operator_cookie, monkeypatch):
    from shugu.services import analytics_queries
    async def fake_count(*args, **kwargs):
        return 10001
    monkeypatch.setattr(analytics_queries, "_count_performances_for_export", fake_count)
    r = await api_client.get("/api/admin/analytics/export?type=performances", cookies=operator_cookie)
    assert r.status_code == 413


@pytest.mark.asyncio
async def test_export_csv_filters_applied(api_client, operator_cookie, seed_performances):
    r = await api_client.get("/api/admin/analytics/export?type=performances&author_role=vip", cookies=operator_cookie)
    csv_text = r.text
    lines = csv_text.strip().split("\n")[1:]  # skip header
    for line in lines:
        assert ",vip," in line  # author_role field


@pytest.mark.asyncio
async def test_export_csv_requires_operator(api_client):
    r = await api_client.get("/api/admin/analytics/export?type=performances")
    assert r.status_code == 401
```

- [ ] **Step 9.2 : Run → FAIL**

- [ ] **Step 9.3 : Service + route**

```python
_EXPORT_HARD_LIMIT = 10_000


async def _count_performances_for_export(
    session: AsyncSession,
    *,
    author_role: Optional[str], route: Optional[str],
    since: Optional[datetime], until: Optional[datetime],
) -> int:
    stmt = select(func.count()).select_from(Performance)
    if author_role:
        stmt = stmt.where(Performance.author_role == author_role)
    if route:
        stmt = stmt.where(Performance.route == route)
    if since:
        stmt = stmt.where(Performance.created_at >= since)
    if until:
        stmt = stmt.where(Performance.created_at <= until)
    return int((await session.execute(stmt)).scalar_one())


def _row_to_csv(row: Performance) -> str:
    def _esc(v):
        if v is None: return ""
        s = str(v).replace('"', '""')
        return f'"{s}"' if "," in s or '"' in s or "\n" in s else s

    ip_trunc = (row.author_ip_hash or "")[:12] if row.author_ip_hash else ""
    has_refusal = "true" if (row.moderation_ingress or row.moderation_egress) else "false"
    return ",".join([
        _esc(row.performance_id),
        _esc(row.author_role),
        _esc(ip_trunc),
        _esc(row.route),
        _esc(row.duration_ms or ""),
        _esc(has_refusal),
        _esc(row.created_at.isoformat() if row.created_at else ""),
        _esc(row.played_at.isoformat() if row.played_at else ""),
        _esc((row.input_text or "")[:120]),
        _esc((row.output_text or "")[:120] if row.output_text else ""),
    ]) + "\n"
```

Route :
```python
from fastapi.responses import StreamingResponse
import structlog as _structlog

_audit_log = _structlog.get_logger(__name__)


@router.get("/export")
async def export(
    type: Literal["performances"] = "performances",
    author_role: Optional[str] = None,
    route_filter: Optional[str] = Query(default=None, alias="route"),
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    op: OperatorIdentity = Depends(require_operator),
):
    if type != "performances":
        raise HTTPException(status_code=400, detail="unsupported export type")
    async with session_scope() as s:
        count = await svc._count_performances_for_export(
            s, author_role=author_role, route=route_filter, since=since, until=until,
        )
        if count > svc._EXPORT_HARD_LIMIT:
            raise HTTPException(
                status_code=413,
                detail=f"Export trop grand ({count} rows). Limite : {svc._EXPORT_HARD_LIMIT}. "
                        "Réduire la fenêtre via since/until.",
            )

        _audit_log.info("audit.analytics_export", operator=op.username if hasattr(op, "username") else None,
                         author_role=author_role, route=route_filter,
                         since=since.isoformat() if since else None,
                         until=until.isoformat() if until else None, rows=count)

    async def gen():
        yield "performance_id,author_role,author_ip_hash_truncated,route,duration_ms,has_moderation_refusal,created_at,played_at,input_text_excerpt,output_text_excerpt\n"
        async with session_scope() as s2:
            stmt = select(Performance)
            if author_role: stmt = stmt.where(Performance.author_role == author_role)
            if route_filter: stmt = stmt.where(Performance.route == route_filter)
            if since: stmt = stmt.where(Performance.created_at >= since)
            if until: stmt = stmt.where(Performance.created_at <= until)
            stmt = stmt.order_by(desc(Performance.created_at))
            result = await s2.stream_scalars(stmt)
            async for row in result:
                yield svc._row_to_csv(row)

    return StreamingResponse(
        gen(), media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="performances.csv"'},
    )
```

- [ ] **Step 9.4 : Run → 4 PASS**
- [ ] **Step 9.5 : Commit**

```bash
git commit -m "✨ feat(analytics): /export CSV streaming + 10k limit + audit log + filter support"
```

---

## Task 10: Coverage verification + security non-regression

- [ ] **Step 10.1 : Vérifier le coverage**

```bash
cd backend && pytest tests/integration/test_admin_analytics_routes.py \
    --cov=shugu.services.analytics_queries \
    --cov=shugu.routes.admin_analytics \
    --cov-report=term-missing
```

Expected: ≥ 90 % sur chaque module. Si non, ajouter tests pour les branches manquantes.

- [ ] **Step 10.2 : Vérifier que toutes les routes rejettent member_cookie**

Ajouter au fichier de test :

```python
@pytest.mark.parametrize("endpoint", [
    "/api/admin/analytics/kpis?window=24h",
    "/api/admin/analytics/timeline?window=24h",
    "/api/admin/analytics/top-routes?window=24h",
    "/api/admin/analytics/top-visitors?window=24h",
    "/api/admin/analytics/heatmap?window=24h",
    "/api/admin/analytics/funnel",
    "/api/admin/analytics/performances?limit=5",
    "/api/admin/analytics/export?type=performances",
])
@pytest.mark.asyncio
async def test_all_routes_reject_member_cookie(api_client, member_cookie, endpoint):
    r = await api_client.get(endpoint, cookies=member_cookie)
    assert r.status_code in (401, 403)
```

- [ ] **Step 10.3 : Run → 8 PASS**

- [ ] **Step 10.4 : Commit**

```bash
git commit -m "🛡️ test(analytics): security non-regression — member cookie rejected on all 8 routes"
```

---

## Task 11: Frontend service `adminAnalyticsClient.ts`

**Files:** Create `frontend/src/services/adminAnalyticsClient.ts`

- [ ] **Step 11.1 : Créer le service (mirror Pydantic)**

```typescript
/**
 * adminAnalyticsClient — wrappers fetch pour /api/admin/analytics/*.
 *
 * Gated opérateur côté backend (require_operator). Les cookies operator
 * (shugu_access) transitent automatiquement via credentials: "include".
 */

export type Window = "1h" | "24h" | "7d" | "30d";

export type KPIs = {
  window: Window;
  visitors_unique: number;
  visitors_unique_delta_pct: number;
  performances_total: number;
  performances_total_delta_pct: number;
  avg_duration_ms: number;
  avg_duration_ms_delta_pct: number;
  moderation_refused_rate: number;
  moderation_refused_rate_delta_pct: number;
  bans_active_count: number;
};

export type TimelineBucket = {
  bucket: string; performances: number; visitors_unique: number;
};

export type Timeline = { window: Window; buckets: TimelineBucket[] };

export type TopRoute = { route: string; count: number; pct: number };
export type TopRoutes = { window: Window; total: number; items: TopRoute[] };

export type TopVisitor = {
  ip_hash_truncated: string;
  msg_count_window: number;
  first_seen: string;
  last_seen: string;
  is_banned: boolean;
};
export type TopVisitors = { items: TopVisitor[] };

export type HeatmapBucket = { hour: number; count: number };
export type Heatmap = { window: Window; buckets: HeatmapBucket[]; max_count: number };

export type Funnel = {
  visitors_unique_total: number;
  members_total: number;
  vips_total: number;
  visitor_to_member_pct: number;
  member_to_vip_pct: number;
};

export type PerformanceListItem = {
  performance_id: string;
  author_role: string;
  author_ip_hash_truncated: string | null;
  route: string;
  duration_ms: number | null;
  has_moderation_refusal: boolean;
  created_at: string;
  played_at: string | null;
  input_text_excerpt: string;
  output_text_excerpt: string | null;
};
export type PerformanceList = { total: number; items: PerformanceListItem[] };

export type PerformanceDetail = {
  performance_id: string;
  author_role: string;
  author_ip_hash_truncated: string | null;
  route: string;
  duration_ms: number | null;
  input_text: string;
  output_text: string | null;
  moderation_ingress: Record<string, unknown> | null;
  moderation_egress: Record<string, unknown> | null;
  created_at: string;
  played_at: string | null;
};

export class AdminError extends Error {
  constructor(public status: number, public detail: string) {
    super(`[${status}] ${detail}`);
    this.name = "AdminError";
  }
}

async function req<T>(path: string, init: RequestInit = {}): Promise<T> {
  const r = await fetch(path, {
    credentials: "include",
    headers: { "Content-Type": "application/json", ...(init.headers || {}) },
    ...init,
  });
  const text = await r.text();
  const payload = text ? (() => { try { return JSON.parse(text); } catch { return { detail: text }; } })() : {};
  if (!r.ok) throw new AdminError(r.status, String(payload.detail ?? `HTTP ${r.status}`));
  return payload as T;
}

export async function getKpis(window: Window = "24h") {
  return req<KPIs>(`/api/admin/analytics/kpis?window=${window}`);
}
export async function getTimeline(window: Window = "24h") {
  return req<Timeline>(`/api/admin/analytics/timeline?window=${window}`);
}
export async function getTopRoutes(window: Window = "24h", limit = 5) {
  return req<TopRoutes>(`/api/admin/analytics/top-routes?window=${window}&limit=${limit}`);
}
export async function getTopVisitors(window: Window = "24h", limit = 5) {
  return req<TopVisitors>(`/api/admin/analytics/top-visitors?window=${window}&limit=${limit}`);
}
export async function getHeatmap(window: Window = "24h") {
  return req<Heatmap>(`/api/admin/analytics/heatmap?window=${window}`);
}
export async function getFunnel() {
  return req<Funnel>(`/api/admin/analytics/funnel`);
}
export async function listPerformances(params: {
  author_role?: string; route?: string; since?: string;
  limit?: number; offset?: number;
} = {}) {
  const qs = new URLSearchParams();
  if (params.author_role) qs.set("author_role", params.author_role);
  if (params.route) qs.set("route", params.route);
  if (params.since) qs.set("since", params.since);
  if (params.limit !== undefined) qs.set("limit", String(params.limit));
  if (params.offset !== undefined) qs.set("offset", String(params.offset));
  const q = qs.toString();
  return req<PerformanceList>(`/api/admin/analytics/performances${q ? `?${q}` : ""}`);
}
export async function getPerformanceDetail(id: string) {
  return req<PerformanceDetail>(`/api/admin/analytics/performances/${encodeURIComponent(id)}`);
}
export function exportCsvUrl(params: {
  author_role?: string; route?: string; since?: string; until?: string;
} = {}): string {
  const qs = new URLSearchParams({ type: "performances" });
  if (params.author_role) qs.set("author_role", params.author_role);
  if (params.route) qs.set("route", params.route);
  if (params.since) qs.set("since", params.since);
  if (params.until) qs.set("until", params.until);
  return `/api/admin/analytics/export?${qs.toString()}`;
}
```

- [ ] **Step 11.2 : Vérifier TS compile**

```bash
cd frontend && npx tsc --noEmit 2>&1 | grep -iE "analytics|error" | head -10
```

Expected: 0 erreur.

- [ ] **Step 11.3 : Commit**

```bash
git add frontend/src/services/adminAnalyticsClient.ts
git commit -m "✨ feat(services): adminAnalyticsClient — typed wrapper for 8 routes + CSV URL builder"
```

---

## Task 12: Frontend refonte `_client.tsx` Analytics

**Files:** Modify `frontend/src/app/[username]/admin/analytics/_client.tsx`

- [ ] **Step 12.1 : Réécrire le fichier en entier**

Le code complet du `_client.tsx` reproduit le layout spec § 7.1. Structure :

```typescript
"use client";

/**
 * Admin Analytics — dashboard prod-ready.
 *
 * Source : Performance + Visitor + UserAccount tables (read-only).
 * 8 endpoints backend gated require_operator. Polling 60s unifié.
 * PII-conservative : email jamais retourné, ip_hash truncate 12.
 */
import { useCallback, useEffect, useMemo, useState } from "react";

import { AdminShell } from "@/components/admin/AdminShell";
import {
  GlassSection, GlassRow, GlassPill, GlassButton, GlassTabs,
  GlassModal, useToast,
} from "@/features/liquid-glass/primitives";
import { MetricTile } from "@/features/liquid-glass/dataviz";
import {
  getKpis, getTimeline, getTopRoutes, getTopVisitors, getHeatmap,
  getFunnel, listPerformances, getPerformanceDetail, exportCsvUrl,
  AdminError,
  type Window, type KPIs, type Timeline, type TopRoutes, type TopVisitors,
  type Heatmap, type Funnel, type PerformanceList, type PerformanceListItem,
  type PerformanceDetail,
} from "@/services/adminAnalyticsClient";

const PAGE_SIZE = 25;
const POLL_MS = 60_000;

function relTime(iso: string): string {
  const d = (Date.now() - new Date(iso).getTime()) / 1000;
  if (d < 60) return `il y a ${Math.floor(d)}s`;
  if (d < 3600) return `il y a ${Math.floor(d / 60)}m`;
  if (d < 86400) return `il y a ${Math.floor(d / 3600)}h`;
  return `il y a ${Math.floor(d / 86400)}j`;
}

function fmtDelta(pct: number): { label: string; tone: "primary" | "warn" | "danger" | "default" } {
  if (Math.abs(pct) < 1) return { label: "stable", tone: "default" };
  const arrow = pct > 0 ? "↑" : "↓";
  const tone = pct > 0 ? "primary" : "danger";
  return { label: `${arrow} ${Math.abs(pct).toFixed(1)}%`, tone };
}

function fmtDuration(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

export function AnalyticsClient() {
  const toast = useToast();
  const [window, setWindow] = useState<Window>("24h");

  const [kpis, setKpis] = useState<KPIs | null>(null);
  const [timeline, setTimeline] = useState<Timeline | null>(null);
  const [topRoutes, setTopRoutes] = useState<TopRoutes | null>(null);
  const [topVisitors, setTopVisitors] = useState<TopVisitors | null>(null);
  const [heatmap, setHeatmap] = useState<Heatmap | null>(null);
  const [funnel, setFunnel] = useState<Funnel | null>(null);
  const [perfs, setPerfs] = useState<PerformanceList | null>(null);
  const [loading, setLoading] = useState(true);

  const [authorRoleFilter, setAuthorRoleFilter] = useState<string | undefined>();
  const [routeFilter, setRouteFilter] = useState<string | undefined>();
  const [page, setPage] = useState(0);

  const [openDetail, setOpenDetail] = useState<PerformanceDetail | null>(null);

  const offset = page * PAGE_SIZE;

  const load = useCallback(async () => {
    try {
      const [k, tl, tr, tv, hm, fn, pl] = await Promise.all([
        getKpis(window),
        getTimeline(window),
        getTopRoutes(window, 5),
        getTopVisitors(window, 5),
        getHeatmap(window),
        getFunnel(),
        listPerformances({
          author_role: authorRoleFilter, route: routeFilter,
          limit: PAGE_SIZE, offset,
        }),
      ]);
      setKpis(k); setTimeline(tl); setTopRoutes(tr); setTopVisitors(tv);
      setHeatmap(hm); setFunnel(fn); setPerfs(pl);
    } catch (err) {
      if (err instanceof AdminError) toast.error("Chargement échoué", { description: err.detail });
    } finally {
      setLoading(false);
    }
  }, [window, authorRoleFilter, routeFilter, offset, toast]);

  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    load();
    const id = setInterval(load, POLL_MS);
    return () => clearInterval(id);
  }, [load]);
  /* eslint-enable react-hooks/set-state-in-effect */

  const openPerformance = async (item: PerformanceListItem) => {
    try {
      const d = await getPerformanceDetail(item.performance_id);
      setOpenDetail(d);
    } catch (err) {
      if (err instanceof AdminError) toast.error("Détail indisponible", { description: err.detail });
    }
  };

  const onExport = () => {
    const url = exportCsvUrl({ author_role: authorRoleFilter, route: routeFilter });
    window?.open?.(url, "_blank") ?? (globalThis.location.href = url);
  };

  const totalPages = useMemo(() => Math.max(1, Math.ceil((perfs?.total ?? 0) / PAGE_SIZE)), [perfs]);

  return (
    <AdminShell
      active="analytics"
      title="Analytics"
      subtitle="Pipeline IA · visiteurs · conversions · export CSV."
      headerRight={
        <GlassPill tone="primary" dot>
          {kpis?.visitors_unique ?? 0} visiteurs uniques {window}
        </GlassPill>
      }
    >
      <section className="flex flex-col gap-5">
        {/* KPIs */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <MetricTile
            label="Visiteurs uniques"
            value={String(kpis?.visitors_unique ?? 0)}
            color="#e08efe"
            sub={kpis ? fmtDelta(kpis.visitors_unique_delta_pct).label : ""}
          />
          <MetricTile
            label="Performances"
            value={String(kpis?.performances_total ?? 0)}
            color="#fd6c9c"
            sub={kpis ? fmtDelta(kpis.performances_total_delta_pct).label : ""}
          />
          <MetricTile
            label="Durée moy"
            value={kpis ? fmtDuration(kpis.avg_duration_ms) : "—"}
            color="#ffcf6b"
            sub={kpis ? fmtDelta(kpis.avg_duration_ms_delta_pct).label : ""}
          />
          <MetricTile
            label="Bans actifs"
            value={String(kpis?.bans_active_count ?? 0)}
            color="#81ecff"
          />
        </div>

        {/* Window + Refresh */}
        <div className="flex items-center gap-3">
          <GlassTabs
            value={window}
            onChange={(v) => setWindow(v as Window)}
            tabs={[
              { value: "1h", label: "1h" },
              { value: "24h", label: "24h" },
              { value: "7d", label: "7j" },
              { value: "30d", label: "30j" },
            ]}
          />
          <div className="ml-auto flex items-center gap-2">
            <GlassButton variant="ghost" size="sm" onClick={load}>
              {loading ? "…" : "Rafraîchir"}
            </GlassButton>
            <GlassButton variant="secondary" size="sm" onClick={onExport}>
              Exporter CSV
            </GlassButton>
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-[1fr_320px] gap-5">
          {/* Colonne principale */}
          <section className="flex flex-col gap-5">
            {/* Timeline (bars) */}
            <GlassSection title="Timeline" subtitle={`Performances + visiteurs uniques sur ${window}`}>
              {timeline && timeline.buckets.length > 0 ? (
                <div className="flex items-end gap-1 h-32 px-2 pt-2">
                  {timeline.buckets.map((b) => {
                    const max = Math.max(...timeline.buckets.map((x) => x.performances), 1);
                    const h = (b.performances / max) * 100;
                    return (
                      <div key={b.bucket} className="flex-1 flex flex-col justify-end items-center" title={`${b.performances} perfs · ${b.visitors_unique} visiteurs`}>
                        <div style={{ height: `${h}%`, minHeight: 2 }} className="w-full rounded-t bg-shugu-magenta/60" />
                      </div>
                    );
                  })}
                </div>
              ) : (
                <div className="p-4 text-sm opacity-60">aucune activité sur cette période</div>
              )}
            </GlassSection>

            {/* Heatmap horaire */}
            <GlassSection title="Heatmap horaire" subtitle="Performances par heure (UTC)">
              {heatmap ? (
                <div className="flex items-end gap-px h-24 px-2 pt-2">
                  {heatmap.buckets.map((b) => {
                    const intensity = heatmap.max_count > 0 ? b.count / heatmap.max_count : 0;
                    return (
                      <div key={b.hour} className="flex-1 flex flex-col justify-end items-center" title={`${b.hour}h · ${b.count} perfs`}>
                        <div
                          style={{ height: `${intensity * 100}%`, minHeight: 2, opacity: 0.3 + intensity * 0.7 }}
                          className="w-full rounded-t bg-shugu-cyan"
                        />
                        <span className="text-[9px] opacity-50 mt-1">{b.hour}</span>
                      </div>
                    );
                  })}
                </div>
              ) : (
                <div className="p-4 text-sm opacity-60">chargement…</div>
              )}
            </GlassSection>

            {/* Filtres performances */}
            <GlassSection title="Filtres performances" subtitle="Affine la liste.">
              <div className="flex flex-wrap items-center gap-3">
                <span className="text-xs opacity-70">Rôle :</span>
                {(["visitor", "member", "vip", "operator"] as const).map((r) => (
                  <GlassButton
                    key={r}
                    variant={authorRoleFilter === r ? "secondary" : "ghost"}
                    size="sm"
                    onClick={() => { setAuthorRoleFilter(authorRoleFilter === r ? undefined : r); setPage(0); }}
                  >{r}</GlassButton>
                ))}
                <span className="text-xs opacity-70 ml-3">Route :</span>
                {(topRoutes?.items ?? []).map((r) => (
                  <GlassButton
                    key={r.route}
                    variant={routeFilter === r.route ? "secondary" : "ghost"}
                    size="sm"
                    onClick={() => { setRouteFilter(routeFilter === r.route ? undefined : r.route); setPage(0); }}
                  >{r.route}</GlassButton>
                ))}
              </div>
            </GlassSection>

            {/* Performances */}
            <GlassSection
              title="Performances"
              subtitle={`${perfs?.total ?? 0} total · page ${page + 1}/${totalPages}`}
            >
              {loading && !perfs ? (
                <div className="p-4 text-sm opacity-60">chargement…</div>
              ) : !perfs?.items.length ? (
                <div className="p-4 text-sm opacity-60">aucune performance</div>
              ) : (
                perfs.items.map((p) => (
                  <button
                    key={p.performance_id}
                    onClick={() => openPerformance(p)}
                    className="text-left w-full"
                  >
                    <GlassRow
                      label={
                        <span className="flex items-center gap-2">
                          <GlassPill tone={p.author_role === "vip" ? "primary" : p.author_role === "operator" ? "danger" : "secondary"}>
                            {p.author_role}
                          </GlassPill>
                          <GlassPill tone="tertiary">{p.route}</GlassPill>
                          {p.has_moderation_refusal && <GlassPill tone="warn">refusé</GlassPill>}
                          {p.duration_ms !== null && <span className="text-[11px] opacity-60">{fmtDuration(p.duration_ms)}</span>}
                        </span>
                      }
                      sub={
                        <span className="block text-[12px] opacity-65">
                          {relTime(p.created_at)} · &quot;{p.input_text_excerpt}&quot;
                        </span>
                      }
                      trailing={p.author_ip_hash_truncated && (
                        <span className="font-mono text-[11px] opacity-50">{p.author_ip_hash_truncated}…</span>
                      )}
                    />
                  </button>
                ))
              )}

              {(perfs?.total ?? 0) > PAGE_SIZE && (
                <div className="flex items-center justify-between gap-3 pt-4">
                  <GlassButton variant="ghost" size="sm" disabled={page === 0} onClick={() => setPage((p) => Math.max(0, p - 1))}>← Précédent</GlassButton>
                  <span className="text-[12px] opacity-60">
                    {offset + 1}–{Math.min(offset + (perfs?.items.length ?? 0), perfs?.total ?? 0)} sur {perfs?.total ?? 0}
                  </span>
                  <GlassButton variant="ghost" size="sm" disabled={offset + (perfs?.items.length ?? 0) >= (perfs?.total ?? 0)} onClick={() => setPage((p) => p + 1)}>Suivant →</GlassButton>
                </div>
              )}
            </GlassSection>
          </section>

          {/* Rail droit */}
          <aside className="flex flex-col gap-4">
            {/* Funnel */}
            <GlassSection title="Funnel" subtitle="Conversion visiteur → VIP">
              <GlassRow label="Visiteurs uniques (tout temps)" trailing={<GlassPill tone="primary">{funnel?.visitors_unique_total ?? 0}</GlassPill>} />
              <GlassRow
                label={<span>Members <span className="opacity-50 text-[11px]">({funnel ? funnel.visitor_to_member_pct.toFixed(1) : 0}%)</span></span>}
                trailing={<GlassPill tone="secondary">{funnel?.members_total ?? 0}</GlassPill>}
              />
              <GlassRow
                label={<span>VIPs <span className="opacity-50 text-[11px]">({funnel ? funnel.member_to_vip_pct.toFixed(1) : 0}%)</span></span>}
                trailing={<GlassPill tone="primary" dot>{funnel?.vips_total ?? 0}</GlassPill>}
              />
            </GlassSection>

            {/* Top routes */}
            <GlassSection title="Top routes" subtitle={`${window}`}>
              {(topRoutes?.items ?? []).length === 0 ? (
                <div className="p-3 text-sm opacity-60">aucune donnée</div>
              ) : (
                topRoutes!.items.map((r) => (
                  <GlassRow
                    key={r.route}
                    label={<span className="text-shugu-cream">{r.route}</span>}
                    sub={`${r.pct.toFixed(1)}% du total`}
                    trailing={<GlassPill tone="tertiary">{r.count}</GlassPill>}
                  />
                ))
              )}
            </GlassSection>

            {/* Top visitors */}
            <GlassSection title="Top visiteurs" subtitle={`${window}`}>
              {(topVisitors?.items ?? []).length === 0 ? (
                <div className="p-3 text-sm opacity-60">aucune donnée</div>
              ) : (
                topVisitors!.items.map((v) => (
                  <GlassRow
                    key={v.ip_hash_truncated}
                    label={<span className="font-mono text-shugu-cream">{v.ip_hash_truncated}…</span>}
                    sub={`${v.msg_count_window} msgs · ${relTime(v.last_seen)}`}
                    trailing={v.is_banned && <GlassPill tone="danger">banni</GlassPill>}
                  />
                ))
              )}
            </GlassSection>
          </aside>
        </div>
      </section>

      {/* Modal détail performance */}
      {openDetail && (
        <GlassModal open onClose={() => setOpenDetail(null)}>
          <div className="p-5 space-y-3 max-w-2xl">
            <div className="flex items-center gap-2">
              <h3 className="text-lg font-light text-shugu-cream">Performance</h3>
              <GlassPill tone="secondary">{openDetail.author_role}</GlassPill>
              <GlassPill tone="tertiary">{openDetail.route}</GlassPill>
            </div>
            <div className="text-[11px] opacity-50 font-mono">
              {openDetail.performance_id} · {relTime(openDetail.created_at)}
              {openDetail.author_ip_hash_truncated && ` · ${openDetail.author_ip_hash_truncated}…`}
            </div>
            <div>
              <div className="text-xs opacity-70 mb-1">Input :</div>
              <pre className="text-sm bg-black/30 p-3 rounded whitespace-pre-wrap">{openDetail.input_text}</pre>
            </div>
            {openDetail.output_text && (
              <div>
                <div className="text-xs opacity-70 mb-1">Output :</div>
                <pre className="text-sm bg-black/30 p-3 rounded whitespace-pre-wrap">{openDetail.output_text}</pre>
              </div>
            )}
            {(openDetail.moderation_ingress || openDetail.moderation_egress) && (
              <div>
                <div className="text-xs opacity-70 mb-1">Moderation :</div>
                <pre className="text-xs bg-black/30 p-3 rounded">
                  {JSON.stringify({
                    ingress: openDetail.moderation_ingress,
                    egress: openDetail.moderation_egress,
                  }, null, 2)}
                </pre>
              </div>
            )}
            <div className="flex justify-end pt-2">
              <GlassButton variant="ghost" size="sm" onClick={() => setOpenDetail(null)}>Fermer</GlassButton>
            </div>
          </div>
        </GlassModal>
      )}
    </AdminShell>
  );
}
```

- [ ] **Step 12.2 : Vérifier TS + ESLint**

```bash
cd frontend && npx tsc --noEmit 2>&1 | grep -i analytics | head
cd frontend && npx eslint src/app/\[username\]/admin/analytics/_client.tsx
```

Expected: 0 erreur. Note : `window` est utilisé comme variable d'état ; vérifier qu'aucun conflit avec `globalThis.window` (le code utilise `globalThis.location` au lieu de `window.location` pour éviter).

- [ ] **Step 12.3 : Vérifier `page.tsx` est inchangé**

```bash
cat frontend/src/app/\[username\]/admin/analytics/page.tsx
```

Doit rester thin wrapper Server Component avec metadata. NE PAS toucher.

- [ ] **Step 12.4 : Commit**

```bash
git add frontend/src/app/\[username\]/admin/analytics/_client.tsx
git commit -m "✨ feat(admin/analytics): refonte UI — branchée 8 endpoints + polling 60s + CSV export + detail modal"
```

---

## Task 13: Smoke tests manuels post-build

- [ ] **Step 13.1 : Backend + frontend up**

```bash
cd backend && uvicorn shugu.app:app --reload --port 8000   # term 1
cd frontend && pnpm dev                                      # term 2
```

- [ ] **Step 13.2 : Ouvrir /[username]/admin/analytics**

Connecté en operator. Vérifier :
- KPI band affiche 4 tiles avec deltas
- Window tabs `1h/24h/7d/30d` changent les données
- Timeline bars visibles
- Heatmap 24 colonnes visibles
- Top routes / Top visiteurs / Funnel renseignés (si DB a des données)
- Liste Performances paginée, click ouvre modal détail

- [ ] **Step 13.3 : Test export CSV**

Cliquer "Exporter CSV". Fichier `performances.csv` télécharge. Ouvrir → headers + rows OK.

- [ ] **Step 13.4 : Test polling**

Forcer 1 nouvelle Performance via path visitor_ws/viewer pendant que la page est ouverte. Au tick suivant (≤ 60s), `performances_total` augmente.

- [ ] **Step 13.5 : Test DevTools console**

0 erreur JS/réseau pendant 90s de polling.

---

## Task 14: PR finale

- [ ] **Step 14.1 : Vérifier état git**

```bash
git status
git log --oneline origin/main..HEAD | head -20
```

Expected: ~15 commits, working tree clean.

- [ ] **Step 14.2 : Rebase main si besoin**

```bash
git fetch origin
git rebase origin/main
```

- [ ] **Step 14.3 : Suite complète**

```bash
cd backend && pytest tests/ --tb=short
cd frontend && npx tsc --noEmit && npx eslint src/
```

Expected: 100% pass.

- [ ] **Step 14.4 : Push + PR**

```bash
git push -u origin claude/crazy-sutherland-96ea1c
gh pr create --title "✨ feat(admin/analytics): dashboard prod-ready — 8 routes + UI refondue" --body "$(cat <<'EOF'
## Summary

Remplace la page mockée `/[username]/admin/analytics` par un dashboard prod-ready branché sur `Performance`/`Visitor`/`UserAccount` via 8 routes admin REST.

**Sub-project B/4** (suit Moderation A). Spec : `docs/superpowers/specs/2026-05-10-admin-analytics-design.md` · Plan : `docs/superpowers/plans/2026-05-10-admin-analytics-plan.md`

## Features

- KPI band (visiteurs uniques, perfs, durée moy, bans) avec **delta vs période précédente**
- Timeline 4 fenêtres (`1h/24h/7d/30d`) + **heatmap horaire UTC** 24 colonnes
- **Top routes** + **top visiteurs** + **funnel** visitor → member → VIP
- Liste paginée Performance avec filtres `author_role`/`route` + modal détail
- **Export CSV** streaming (hard limit 10k rows) + audit log structlog
- Polling 60s unifié
- **PII-conservative** : email jamais retourné, ip_hash truncate 12

## Architecture

Read-only. 2 nouveaux modules backend, 1 ligne `app.py`. AUCUNE migration. AUCUN decorator. AUCUN feature flag.

## Test plan

- [x] 36+ tests integration backend (KPIs, timeline, top-N, heatmap, funnel, list, detail, export)
- [x] Coverage ≥ 90% sur `services/analytics_queries.py` + `routes/admin_analytics.py`
- [x] Sécurité non-régression : 8 routes rejettent member_cookie (parametrize)
- [x] `tsc --noEmit` + `eslint` propres
- [x] Smoke test manuel : KPIs + delta + tabs window + heatmap + export CSV + polling + modal detail

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 14.5 : Retourner URL PR**

---

## Self-review

### 1. Spec coverage

| Spec section | Tâche |
|---|---|
| § 3.2 modules backend | Tasks 2, 3, 8, 11 |
| § 5 8 routes API | Tasks 2 (kpis), 3 (timeline), 4 (top-routes), 5 (top-visitors), 6 (heatmap), 7 (funnel), 8 (performances), 9 (export) |
| § 6.1 calcul delta | Task 2 (_pct_delta) |
| § 6.2 heatmap UTC | Task 6 |
| § 6.3 funnel ratios | Task 7 |
| § 6.4 bans dedup | Task 2 (count_active_bans) |
| § 6.5 export CSV streaming | Task 9 |
| § 7 UI sections | Task 12 |
| § 8 tests TDD | Tasks 2-10 |
| § 10 sécurité non-régression | Task 10 |
| § 12 rollout smoke | Task 13 |

### 2. Placeholders : aucun. Tout code complet.

### 3. Type consistency

- `WindowLiteral` cohérent backend + frontend (`Window`).
- `ip_hash_truncated` 12 chars partout, jamais `ip_hash` complet exposé.
- `_count_performances_for_export` est private (underscore) mais monkeypatchable depuis le test (cf. Task 9.1).

---

## Execution handoff

Plan complet et prod-ready. Input pour `ruflo-autopilot:autopilot-coordinator` après que sub-project A (Moderation) soit mergé.

Note : la dépendance sur les fixtures partagées (Task 0) impose A → B en série, **PAS en parallèle**.
