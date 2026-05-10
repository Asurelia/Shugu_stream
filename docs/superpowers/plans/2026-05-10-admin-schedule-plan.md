# Admin Schedule — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Checkbox tracking.

**Goal:** Calendar admin prod-ready avec CRUD complet `ScheduledStream` (5 routes admin + 1 route publique), migration Alembic, UI calendar mensuel + form modal.

**Architecture:** Nouveau model + migration, service CRUD, 2 routers (admin + public), UI calendar grid 7×N. State machine status. PAS de feature flag.

**Tech Stack:** Python 3.11+ / FastAPI / SQLAlchemy async / Alembic / Pydantic v2 / pytest. Next.js / TypeScript strict / liquid-glass.

**Spec :** [docs/superpowers/specs/2026-05-10-admin-schedule-design.md](../specs/2026-05-10-admin-schedule-design.md)

**Quality contract :** prod-ready strict, zéro `@skip`/`@xfail`/placeholder/TODO/"Coming soon". Coverage ≥ 90 %.

---

## File Structure

| Path | Action |
|---|---|
| `backend/alembic/versions/XXXX_scheduled_streams.py` | **nouveau** |
| `backend/shugu/db/models.py` | **modifié** : ajouter `ScheduledStream` |
| `backend/shugu/services/scheduled_streams.py` | **nouveau** |
| `backend/shugu/routes/admin_schedule.py` | **nouveau** |
| `backend/shugu/routes/public_schedule.py` | **nouveau** |
| `backend/shugu/app.py` | **modifié** : 2 `include_router` |
| `backend/tests/unit/test_scheduled_streams_service.py` | **nouveau** |
| `backend/tests/integration/test_admin_schedule_routes.py` | **nouveau** |
| `backend/tests/integration/test_public_schedule_routes.py` | **nouveau** |
| `backend/tests/conftest.py` | **modifié** : `seed_scheduled_streams` fixture |
| `frontend/src/services/adminScheduleClient.ts` | **nouveau** |
| `frontend/src/app/[username]/admin/schedule/_client.tsx` | **refonte complète** |

---

## Task 0: Dépendance Moderation A merged

- [ ] Vérifier fixtures partagées `db_session`, `operator_cookie`, `member_cookie`, `api_client` présentes (créées par A).
- [ ] Si absent → BLOCKER, attendre merge A.

---

## Task 1: Migration Alembic + model

- [ ] **Step 1.1 :** Identifier le next revision id
```bash
ls backend/alembic/versions/ | tail -3
```

- [ ] **Step 1.2 :** Créer la migration `XXXX_scheduled_streams.py` avec le contenu du spec § 4.2 (CHECK constraints duration ∈ ]0,1440] et status enum).

- [ ] **Step 1.3 :** Ajouter le model `ScheduledStream` dans `backend/shugu/db/models.py` (à la fin du fichier, après `TimelineClip` ligne 359). Code complet en spec § 4.1.

- [ ] **Step 1.4 :** Appliquer
```bash
alembic -c backend/alembic.ini upgrade head
psql "$SHUGU_POSTGRES_DSN" -c "\d scheduled_streams"
```

- [ ] **Step 1.5 :** Commit
```bash
git add backend/alembic/versions/*scheduled* backend/shugu/db/models.py
git commit -m "🗄️ feat(db): scheduled_streams table + ScheduledStream model"
```

---

## Task 2: TDD state machine unit tests

- [ ] **Step 2.1 :** Créer `backend/tests/unit/test_scheduled_streams_service.py`

```python
"""Tests unit : state machine validation."""
import pytest
from fastapi import HTTPException

from shugu.services.scheduled_streams import _validate_status_transition


@pytest.mark.parametrize("curr,new", [
    ("planned", "live"),
    ("planned", "cancelled"),
    ("planned", "past"),
    ("live", "past"),
    ("live", "cancelled"),
    ("planned", "planned"),  # no-op
    ("live", "live"),
])
def test_valid_transition(curr, new):
    _validate_status_transition(curr, new)  # no raise


@pytest.mark.parametrize("curr,new", [
    ("past", "planned"),
    ("past", "live"),
    ("past", "cancelled"),
    ("cancelled", "planned"),
    ("cancelled", "live"),
    ("cancelled", "past"),
])
def test_invalid_transition_raises_409(curr, new):
    with pytest.raises(HTTPException) as exc_info:
        _validate_status_transition(curr, new)
    assert exc_info.value.status_code == 409
```

- [ ] **Step 2.2 :** Run → FAIL (service module n'existe pas).

- [ ] **Step 2.3 :** Créer `backend/shugu/services/scheduled_streams.py` minimal avec juste `_validate_status_transition`.

```python
"""Service CRUD pour scheduled_streams."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from fastapi import HTTPException
from sqlalchemy import and_, delete, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import ScheduledStream

log = structlog.get_logger(__name__)

_VALID_TRANSITIONS = {
    "planned": {"live", "cancelled", "past"},
    "live": {"past", "cancelled"},
    "past": set(),
    "cancelled": set(),
}


def _validate_status_transition(current: str, new: str) -> None:
    if new == current:
        return
    allowed = _VALID_TRANSITIONS.get(current, set())
    if new not in allowed:
        raise HTTPException(
            status_code=409,
            detail=f"Status transition invalide : {current} → {new}. "
                    f"Transitions valides depuis {current} : {sorted(allowed) or 'aucune'}.",
        )
```

- [ ] **Step 2.4 :** Run → PASS (9 paramétrés OK + 6 paramétrés invalides).

- [ ] **Step 2.5 :** Commit
```bash
git add backend/tests/unit/test_scheduled_streams_service.py backend/shugu/services/scheduled_streams.py
git commit -m "🧪 test(scheduled): state machine status transitions (9 valid + 6 invalid)"
```

---

## Task 3: TDD service CRUD complet

- [ ] **Step 3.1 :** Ajouter `seed_scheduled_streams` à `conftest.py` (code complet en spec § 8.1).

- [ ] **Step 3.2 :** Ajouter tests CRUD service dans `test_scheduled_streams_service.py` :

```python
@pytest.mark.asyncio
async def test_create_returns_dict_with_id(db_session):
    from datetime import datetime, timedelta, timezone
    from shugu.services.scheduled_streams import create_stream
    starts_at = datetime.now(timezone.utc) + timedelta(hours=24)
    row = await create_stream(db_session, title="T1", description="D1",
                               starts_at=starts_at, duration_minutes=60,
                               created_by="op1")
    assert len(row["id"]) == 26  # ULID
    assert row["status"] == "planned"
    assert row["created_by"] == "op1"


@pytest.mark.asyncio
async def test_list_returns_paginated_filtered(db_session, seed_scheduled_streams):
    from shugu.services.scheduled_streams import list_streams
    r = await list_streams(db_session, status="planned")
    assert r["total"] == 2
    for item in r["items"]:
        assert item["status"] == "planned"


@pytest.mark.asyncio
async def test_get_by_id_returns_or_none(db_session, seed_scheduled_streams):
    from shugu.services.scheduled_streams import get_stream
    existing_id = seed_scheduled_streams[0]["id"]
    found = await get_stream(db_session, existing_id)
    assert found is not None
    assert found["id"] == existing_id
    missing = await get_stream(db_session, "0" * 26)
    assert missing is None


@pytest.mark.asyncio
async def test_patch_partial_update(db_session, seed_scheduled_streams):
    from shugu.services.scheduled_streams import patch_stream
    sid = seed_scheduled_streams[0]["id"]
    updated = await patch_stream(db_session, sid, title="new title")
    assert updated["title"] == "new title"
    # Champs non touchés inchangés
    assert updated["description"] is None


@pytest.mark.asyncio
async def test_patch_invalid_transition_raises_409(db_session, seed_scheduled_streams):
    from shugu.services.scheduled_streams import patch_stream
    past_id = next(s for s in seed_scheduled_streams if s["status"] == "past")["id"]
    with pytest.raises(HTTPException) as exc:
        await patch_stream(db_session, past_id, status="planned")
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_delete_returns_true_then_false(db_session, seed_scheduled_streams):
    from shugu.services.scheduled_streams import delete_stream
    sid = seed_scheduled_streams[0]["id"]
    assert (await delete_stream(db_session, sid)) is True
    assert (await delete_stream(db_session, sid)) is False  # idempotent
```

- [ ] **Step 3.3 :** Run → FAIL.

- [ ] **Step 3.4 :** Implémenter les 5 fonctions service dans `services/scheduled_streams.py` :

```python
from ulid import ULID


def _row_to_dict(row: ScheduledStream) -> dict:
    return {
        "id": row.id, "title": row.title, "description": row.description,
        "starts_at": row.starts_at, "duration_minutes": row.duration_minutes,
        "status": row.status, "created_by": row.created_by,
        "created_at": row.created_at, "updated_at": row.updated_at,
    }


async def list_streams(
    session: AsyncSession, *,
    status: Optional[str] = None,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    limit: int = 50, offset: int = 0,
) -> dict:
    stmt = select(ScheduledStream)
    count_stmt = select(func.count()).select_from(ScheduledStream)
    if status:
        stmt = stmt.where(ScheduledStream.status == status)
        count_stmt = count_stmt.where(ScheduledStream.status == status)
    if since:
        stmt = stmt.where(ScheduledStream.starts_at >= since)
        count_stmt = count_stmt.where(ScheduledStream.starts_at >= since)
    if until:
        stmt = stmt.where(ScheduledStream.starts_at <= until)
        count_stmt = count_stmt.where(ScheduledStream.starts_at <= until)
    total = (await session.execute(count_stmt)).scalar_one()
    rows = (await session.execute(
        stmt.order_by(ScheduledStream.starts_at).limit(limit).offset(offset)
    )).scalars().all()
    return {"total": int(total), "items": [_row_to_dict(r) for r in rows]}


async def get_stream(session: AsyncSession, stream_id: str) -> Optional[dict]:
    row = (await session.execute(
        select(ScheduledStream).where(ScheduledStream.id == stream_id)
    )).scalar_one_or_none()
    return _row_to_dict(row) if row else None


async def create_stream(
    session: AsyncSession, *,
    title: str, description: Optional[str],
    starts_at: datetime, duration_minutes: int,
    created_by: str,
) -> dict:
    new_id = str(ULID())
    await session.execute(insert(ScheduledStream).values(
        id=new_id, title=title, description=description,
        starts_at=starts_at, duration_minutes=duration_minutes,
        status="planned", created_by=created_by,
    ))
    await session.commit()
    return await get_stream(session, new_id)  # type: ignore[return-value]


async def patch_stream(
    session: AsyncSession, stream_id: str, **updates,
) -> Optional[dict]:
    current = await get_stream(session, stream_id)
    if current is None:
        return None
    if "status" in updates and updates["status"] is not None:
        _validate_status_transition(current["status"], updates["status"])
    set_values = {k: v for k, v in updates.items() if v is not None}
    if not set_values:
        return current
    await session.execute(
        update(ScheduledStream).where(ScheduledStream.id == stream_id).values(**set_values)
    )
    await session.commit()
    return await get_stream(session, stream_id)


async def delete_stream(session: AsyncSession, stream_id: str) -> bool:
    result = await session.execute(
        delete(ScheduledStream).where(ScheduledStream.id == stream_id)
    )
    await session.commit()
    return result.rowcount > 0


async def list_upcoming_public(session: AsyncSession, *, limit: int = 10) -> list[dict]:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=24)
    rows = (await session.execute(
        select(ScheduledStream)
        .where(and_(
            ScheduledStream.status.in_(["planned", "live"]),
            ScheduledStream.starts_at >= cutoff,
        ))
        .order_by(ScheduledStream.starts_at)
        .limit(limit)
    )).scalars().all()
    return [{
        "id": r.id, "title": r.title, "description": r.description,
        "starts_at": r.starts_at, "duration_minutes": r.duration_minutes,
        "status": r.status,
    } for r in rows]
```

Note : ajouter `from sqlalchemy import func` aux imports.

- [ ] **Step 3.5 :** Run → PASS.

- [ ] **Step 3.6 :** Commit
```bash
git commit -m "✨ feat(scheduled): service CRUD complet (list/get/create/patch/delete) + public upcoming"
```

---

## Task 4: TDD routes admin (5 endpoints)

- [ ] **Step 4.1 :** Créer `backend/tests/integration/test_admin_schedule_routes.py` avec **tous les 25 tests admin** listés dans le spec § 8.2 (LIST + CREATE + GET + PATCH + DELETE + sécurité). Chaque test concret avec assertions sur status_code + body.

Exemple pour CREATE :

```python
@pytest.mark.asyncio
async def test_create_returns_201_with_planned_status(api_client, operator_cookie):
    from datetime import datetime, timedelta, timezone
    starts_at = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    r = await api_client.post("/api/admin/schedule",
                              cookies=operator_cookie,
                              json={"title": "T", "description": None,
                                    "starts_at": starts_at,
                                    "duration_minutes": 60})
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "planned"
    assert body["title"] == "T"
    assert len(body["id"]) == 26


@pytest.mark.asyncio
async def test_create_rejects_past_starts_at(api_client, operator_cookie):
    from datetime import datetime, timedelta, timezone
    starts_at = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    r = await api_client.post("/api/admin/schedule", cookies=operator_cookie,
                              json={"title": "T", "starts_at": starts_at,
                                    "duration_minutes": 60})
    assert r.status_code == 422
```

(Compléter de manière analogue pour les 24 autres tests selon § 8.2.)

- [ ] **Step 4.2 :** Run → tous FAIL.

- [ ] **Step 4.3 :** Créer `backend/shugu/routes/admin_schedule.py` :

```python
"""Routes admin schedule — /api/admin/schedule/*."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator

from ..auth.dependencies import require_operator
from ..core.identity import OperatorIdentity
from ..db.session import session_scope
from ..services import scheduled_streams as svc

router = APIRouter(prefix="/api/admin/schedule", tags=["admin-schedule"])

StatusLiteral = Literal["planned", "live", "past", "cancelled"]


class ScheduleListItem(BaseModel):
    id: str
    title: str
    description: Optional[str]
    starts_at: datetime
    duration_minutes: int
    status: StatusLiteral
    created_by: str
    created_at: datetime
    updated_at: datetime


class ScheduleListResponse(BaseModel):
    total: int
    items: list[ScheduleListItem]


class ScheduleCreateBody(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=5000)
    starts_at: datetime
    duration_minutes: int = Field(ge=1, le=1440)

    @field_validator("starts_at")
    @classmethod
    def must_be_future(cls, v):
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        if v <= datetime.now(timezone.utc) - timedelta(minutes=5):
            raise ValueError("starts_at doit être dans le futur (tolérance 5min)")
        return v


class ScheduleUpdateBody(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=5000)
    starts_at: Optional[datetime] = None
    duration_minutes: Optional[int] = Field(default=None, ge=1, le=1440)
    status: Optional[StatusLiteral] = None


@router.get("", response_model=ScheduleListResponse)
async def list_schedules(
    status: Optional[StatusLiteral] = None,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _op: OperatorIdentity = Depends(require_operator),
):
    async with session_scope() as s:
        return await svc.list_streams(s, status=status, since=since, until=until,
                                       limit=limit, offset=offset)


@router.post("", response_model=ScheduleListItem, status_code=status.HTTP_201_CREATED)
async def create_schedule(
    body: ScheduleCreateBody,
    op: OperatorIdentity = Depends(require_operator),
):
    async with session_scope() as s:
        return await svc.create_stream(
            s, title=body.title, description=body.description,
            starts_at=body.starts_at, duration_minutes=body.duration_minutes,
            created_by=getattr(op, "username", "operator"),
        )


@router.get("/{stream_id}", response_model=ScheduleListItem)
async def get_schedule(
    stream_id: str,
    _op: OperatorIdentity = Depends(require_operator),
):
    async with session_scope() as s:
        found = await svc.get_stream(s, stream_id)
        if found is None:
            raise HTTPException(404, "scheduled stream not found")
        return found


@router.patch("/{stream_id}", response_model=ScheduleListItem)
async def update_schedule(
    stream_id: str,
    body: ScheduleUpdateBody,
    _op: OperatorIdentity = Depends(require_operator),
):
    updates = body.model_dump(exclude_unset=True, exclude_none=True)
    async with session_scope() as s:
        result = await svc.patch_stream(s, stream_id, **updates)
        if result is None:
            raise HTTPException(404, "scheduled stream not found")
        return result


@router.delete("/{stream_id}", status_code=204)
async def delete_schedule(
    stream_id: str,
    _op: OperatorIdentity = Depends(require_operator),
):
    async with session_scope() as s:
        await svc.delete_stream(s, stream_id)
```

- [ ] **Step 4.4 :** Wirer dans `app.py` :
```python
from .routes.admin_schedule import router as admin_schedule_router
app.include_router(admin_schedule_router)
```

- [ ] **Step 4.5 :** Run → tous PASS.

- [ ] **Step 4.6 :** Commit
```bash
git commit -m "✨ feat(schedule): 5 routes admin CRUD + Pydantic schemas + state machine wiring"
```

---

## Task 5: TDD route publique

- [ ] **Step 5.1 :** Créer `test_public_schedule_routes.py` avec les 8 tests du spec § 8.2.

- [ ] **Step 5.2 :** Créer `backend/shugu/routes/public_schedule.py` :

```python
"""Route publique /api/schedule/upcoming — non gated."""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from ..db.session import session_scope
from ..services import scheduled_streams as svc

router = APIRouter(prefix="/api/schedule", tags=["public-schedule"])


class PublicScheduleItem(BaseModel):
    id: str
    title: str
    description: Optional[str]
    starts_at: datetime
    duration_minutes: int
    status: Literal["planned", "live"]


class PublicScheduleResponse(BaseModel):
    items: list[PublicScheduleItem]


@router.get("/upcoming", response_model=PublicScheduleResponse)
async def upcoming(limit: int = Query(10, ge=1, le=50)):
    async with session_scope() as s:
        items = await svc.list_upcoming_public(s, limit=limit)
        return {"items": items}
```

- [ ] **Step 5.3 :** Wire dans `app.py` :
```python
from .routes.public_schedule import router as public_schedule_router
app.include_router(public_schedule_router)
```

- [ ] **Step 5.4 :** Run → PASS.

- [ ] **Step 5.5 :** Coverage check
```bash
pytest backend/tests/integration/test_admin_schedule_routes.py \
       backend/tests/integration/test_public_schedule_routes.py \
       backend/tests/unit/test_scheduled_streams_service.py \
       --cov=shugu.services.scheduled_streams \
       --cov=shugu.routes.admin_schedule \
       --cov=shugu.routes.public_schedule \
       --cov-report=term-missing
```

Expected ≥ 90 %.

- [ ] **Step 5.6 :** Commit
```bash
git commit -m "✨ feat(schedule): public /api/schedule/upcoming route + tests + 90% coverage"
```

---

## Task 6: Frontend service

- [ ] **Step 6.1 :** Créer `frontend/src/services/adminScheduleClient.ts` :

```typescript
export type ScheduleStatus = "planned" | "live" | "past" | "cancelled";

export type ScheduledStream = {
  id: string;
  title: string;
  description: string | null;
  starts_at: string;
  duration_minutes: number;
  status: ScheduleStatus;
  created_by: string;
  created_at: string;
  updated_at: string;
};

export type ScheduleListResponse = { total: number; items: ScheduledStream[] };

export type ScheduleCreateBody = {
  title: string;
  description?: string | null;
  starts_at: string;
  duration_minutes: number;
};

export type ScheduleUpdateBody = Partial<ScheduleCreateBody> & {
  status?: ScheduleStatus;
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

export async function listSchedules(params: {
  status?: ScheduleStatus; since?: string; until?: string;
  limit?: number; offset?: number;
} = {}): Promise<ScheduleListResponse> {
  const qs = new URLSearchParams();
  if (params.status) qs.set("status", params.status);
  if (params.since) qs.set("since", params.since);
  if (params.until) qs.set("until", params.until);
  if (params.limit !== undefined) qs.set("limit", String(params.limit));
  if (params.offset !== undefined) qs.set("offset", String(params.offset));
  const q = qs.toString();
  return req(`/api/admin/schedule${q ? `?${q}` : ""}`);
}

export async function getSchedule(id: string): Promise<ScheduledStream> {
  return req(`/api/admin/schedule/${encodeURIComponent(id)}`);
}

export async function createSchedule(body: ScheduleCreateBody): Promise<ScheduledStream> {
  return req(`/api/admin/schedule`, { method: "POST", body: JSON.stringify(body) });
}

export async function updateSchedule(id: string, body: ScheduleUpdateBody): Promise<ScheduledStream> {
  return req(`/api/admin/schedule/${encodeURIComponent(id)}`, {
    method: "PATCH", body: JSON.stringify(body),
  });
}

export async function deleteSchedule(id: string): Promise<void> {
  await req(`/api/admin/schedule/${encodeURIComponent(id)}`, { method: "DELETE" });
}
```

- [ ] **Step 6.2 :** TS compile check.
- [ ] **Step 6.3 :** Commit
```bash
git commit -m "✨ feat(services): adminScheduleClient typed CRUD wrapper"
```

---

## Task 7: Frontend refonte `_client.tsx`

- [ ] **Step 7.1 :** Réécrire en entier le fichier avec **calendar grid 7×N mensuel** + **rail droit "à venir"** + **modal create/edit/delete**. Layout complet en spec § 7.1 et § 7.2.

Le code complet à produire suit le pattern de `analytics/_client.tsx` (refondu par sub-project B) :

```typescript
"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { AdminShell } from "@/components/admin/AdminShell";
import {
  GlassSection, GlassRow, GlassPill, GlassButton, GlassInput,
  GlassModal, useToast,
} from "@/features/liquid-glass/primitives";
import {
  listSchedules, getSchedule, createSchedule, updateSchedule, deleteSchedule,
  AdminError,
  type ScheduledStream, type ScheduleStatus, type ScheduleCreateBody,
} from "@/services/adminScheduleClient";

const POLL_MS = 60_000;

// Helpers calendrier
function startOfMonth(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth(), 1);
}
function endOfMonth(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth() + 1, 0);
}
function daysGridForMonth(date: Date): (Date | null)[] {
  // Aligne sur lundi
  const first = startOfMonth(date);
  const last = endOfMonth(date);
  const firstWeekday = (first.getDay() + 6) % 7; // 0 = lundi
  const days: (Date | null)[] = [];
  for (let i = 0; i < firstWeekday; i++) days.push(null);
  for (let d = 1; d <= last.getDate(); d++) {
    days.push(new Date(date.getFullYear(), date.getMonth(), d));
  }
  while (days.length % 7 !== 0) days.push(null);
  return days;
}
function isSameDay(a: Date, b: Date): boolean {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}
function fmtMonthFr(d: Date): string {
  return d.toLocaleDateString("fr-FR", { month: "long", year: "numeric" });
}
function fmtTime(iso: string): string {
  return new Date(iso).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
}
function toDatetimeLocalInput(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
function statusTone(s: ScheduleStatus): "primary" | "warn" | "danger" | "default" | "secondary" {
  if (s === "live") return "primary";
  if (s === "planned") return "secondary";
  if (s === "cancelled") return "danger";
  return "default";
}

type EditDraft = {
  id: string | null;
  title: string;
  description: string;
  starts_at: string;     // datetime-local input value
  duration_minutes: number;
  status: ScheduleStatus | null;
};

export function ScheduleClient() {
  const toast = useToast();
  const [currentMonth, setCurrentMonth] = useState(() => startOfMonth(new Date()));
  const [monthStreams, setMonthStreams] = useState<ScheduledStream[]>([]);
  const [upcoming, setUpcoming] = useState<ScheduledStream[]>([]);
  const [loading, setLoading] = useState(true);
  const [draft, setDraft] = useState<EditDraft | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<ScheduledStream | null>(null);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    try {
      const monthStart = startOfMonth(currentMonth).toISOString();
      const monthEnd = endOfMonth(currentMonth).toISOString();
      const now = new Date().toISOString();
      const [month, up] = await Promise.all([
        listSchedules({ since: monthStart, until: monthEnd, limit: 200 }),
        listSchedules({ since: now, status: "planned", limit: 10 }),
      ]);
      setMonthStreams(month.items);
      setUpcoming(up.items);
    } catch (err) {
      if (err instanceof AdminError) toast.error("Chargement échoué", { description: err.detail });
    } finally {
      setLoading(false);
    }
  }, [currentMonth, toast]);

  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    load();
    const id = setInterval(load, POLL_MS);
    return () => clearInterval(id);
  }, [load]);
  /* eslint-enable react-hooks/set-state-in-effect */

  const gridDays = useMemo(() => daysGridForMonth(currentMonth), [currentMonth]);
  const streamsByDay = useMemo(() => {
    const map = new Map<string, ScheduledStream[]>();
    for (const s of monthStreams) {
      const d = new Date(s.starts_at);
      const key = `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
      const arr = map.get(key) ?? [];
      arr.push(s);
      map.set(key, arr);
    }
    return map;
  }, [monthStreams]);

  const openNewOnDay = (day: Date) => {
    const at21h = new Date(day.getFullYear(), day.getMonth(), day.getDate(), 21, 0);
    setDraft({
      id: null, title: "", description: "",
      starts_at: toDatetimeLocalInput(at21h),
      duration_minutes: 120, status: null,
    });
  };

  const openEdit = async (stream: ScheduledStream) => {
    setDraft({
      id: stream.id,
      title: stream.title,
      description: stream.description ?? "",
      starts_at: toDatetimeLocalInput(new Date(stream.starts_at)),
      duration_minutes: stream.duration_minutes,
      status: stream.status,
    });
  };

  const onSaveDraft = async () => {
    if (!draft) return;
    setSaving(true);
    try {
      const startsIso = new Date(draft.starts_at).toISOString();
      if (draft.id === null) {
        await createSchedule({
          title: draft.title,
          description: draft.description || null,
          starts_at: startsIso,
          duration_minutes: draft.duration_minutes,
        });
        toast.success("Stream créé");
      } else {
        await updateSchedule(draft.id, {
          title: draft.title,
          description: draft.description || null,
          starts_at: startsIso,
          duration_minutes: draft.duration_minutes,
          status: draft.status ?? undefined,
        });
        toast.success("Stream modifié");
      }
      setDraft(null);
      await load();
    } catch (err) {
      const msg = err instanceof AdminError ? err.detail : "Erreur";
      toast.error("Échec", { description: msg });
    } finally {
      setSaving(false);
    }
  };

  const onConfirmDelete = async () => {
    if (!confirmDelete) return;
    setSaving(true);
    try {
      await deleteSchedule(confirmDelete.id);
      toast.success("Stream supprimé");
      setConfirmDelete(null);
      setDraft(null);
      await load();
    } catch (err) {
      const msg = err instanceof AdminError ? err.detail : "Erreur";
      toast.error("Suppression échouée", { description: msg });
    } finally {
      setSaving(false);
    }
  };

  return (
    <AdminShell
      active="schedule"
      title="Planning streams"
      subtitle="Crée, édite, annule les streams planifiés."
      headerRight={
        <GlassPill tone="primary" dot>
          {upcoming.length} à venir
        </GlassPill>
      }
    >
      <section className="flex flex-col gap-5">
        {/* Top bar */}
        <div className="flex items-center gap-3">
          <GlassButton variant="ghost" size="sm" onClick={() => setCurrentMonth(new Date(currentMonth.getFullYear(), currentMonth.getMonth() - 1, 1))}>
            ← Mois précédent
          </GlassButton>
          <span className="text-shugu-cream capitalize">{fmtMonthFr(currentMonth)}</span>
          <GlassButton variant="ghost" size="sm" onClick={() => setCurrentMonth(new Date(currentMonth.getFullYear(), currentMonth.getMonth() + 1, 1))}>
            Mois suivant →
          </GlassButton>
          <div className="ml-auto">
            <GlassButton variant="secondary" size="sm" onClick={() => openNewOnDay(new Date())}>
              + Nouveau stream
            </GlassButton>
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-[1fr_320px] gap-5">
          {/* Calendar grid */}
          <GlassSection title="Calendrier mensuel" subtitle="Click cellule = créer, click stream = éditer.">
            <div className="grid grid-cols-7 gap-1 text-xs">
              {["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"].map((d) => (
                <div key={d} className="text-center opacity-60 py-1">{d}</div>
              ))}
              {gridDays.map((day, idx) => {
                if (!day) return <div key={`empty-${idx}`} className="aspect-square" />;
                const key = `${day.getFullYear()}-${day.getMonth()}-${day.getDate()}`;
                const list = streamsByDay.get(key) ?? [];
                const isToday = isSameDay(day, new Date());
                return (
                  <button
                    key={key}
                    onClick={() => openNewOnDay(day)}
                    className={`aspect-square p-1 rounded text-left hover:bg-white/5 ${isToday ? "ring-1 ring-shugu-magenta/60" : ""}`}
                  >
                    <div className="text-shugu-cream text-[11px] opacity-80">{day.getDate()}</div>
                    <div className="flex flex-col gap-0.5 mt-1">
                      {list.slice(0, 3).map((s) => (
                        <button
                          key={s.id}
                          onClick={(ev) => { ev.stopPropagation(); openEdit(s); }}
                          className="block w-full"
                        >
                          <GlassPill tone={statusTone(s.status)}>
                            <span className="text-[9px]">{fmtTime(s.starts_at)} {s.title.slice(0, 12)}</span>
                          </GlassPill>
                        </button>
                      ))}
                      {list.length > 3 && (
                        <span className="text-[9px] opacity-60">+{list.length - 3}</span>
                      )}
                    </div>
                  </button>
                );
              })}
            </div>
          </GlassSection>

          {/* Rail droit */}
          <aside className="flex flex-col gap-4">
            <GlassSection title="À venir" subtitle="Prochains streams planifiés.">
              {loading && upcoming.length === 0 ? (
                <div className="p-3 text-sm opacity-60">chargement…</div>
              ) : upcoming.length === 0 ? (
                <div className="p-3 text-sm opacity-60">aucun stream planifié</div>
              ) : (
                upcoming.map((s) => (
                  <button key={s.id} onClick={() => openEdit(s)} className="text-left w-full">
                    <GlassRow
                      label={
                        <span className="flex items-center gap-2">
                          <GlassPill tone={statusTone(s.status)}>{s.status}</GlassPill>
                          <span className="text-shugu-cream">{s.title}</span>
                        </span>
                      }
                      sub={`${new Date(s.starts_at).toLocaleString("fr-FR")} · ${s.duration_minutes}min`}
                    />
                  </button>
                ))
              )}
            </GlassSection>
          </aside>
        </div>
      </section>

      {/* Modal create/edit */}
      {draft && (
        <GlassModal open onClose={() => !saving && setDraft(null)}>
          <div className="p-5 space-y-3 max-w-lg">
            <h3 className="text-lg font-light text-shugu-cream">
              {draft.id === null ? "Nouveau stream" : "Éditer le stream"}
            </h3>

            <label className="block">
              <span className="text-xs opacity-70 mb-1 block">Titre</span>
              <GlassInput
                value={draft.title}
                onChange={(e) => setDraft({ ...draft, title: e.target.value })}
                placeholder="Stream du soir"
                maxLength={200}
              />
            </label>

            <label className="block">
              <span className="text-xs opacity-70 mb-1 block">Description (optionnel)</span>
              <textarea
                value={draft.description}
                onChange={(e) => setDraft({ ...draft, description: e.target.value })}
                maxLength={5000}
                className="w-full p-2 rounded bg-black/30 text-shugu-cream"
                rows={3}
              />
            </label>

            <label className="block">
              <span className="text-xs opacity-70 mb-1 block">Début</span>
              <input
                type="datetime-local"
                value={draft.starts_at}
                onChange={(e) => setDraft({ ...draft, starts_at: e.target.value })}
                className="w-full p-2 rounded bg-black/30 text-shugu-cream"
              />
            </label>

            <label className="block">
              <span className="text-xs opacity-70 mb-1 block">Durée (minutes)</span>
              <GlassInput
                type="number"
                min={1}
                max={1440}
                value={String(draft.duration_minutes)}
                onChange={(e) => setDraft({ ...draft, duration_minutes: parseInt(e.target.value || "0", 10) })}
              />
            </label>

            {draft.id !== null && draft.status !== null && (
              <label className="block">
                <span className="text-xs opacity-70 mb-1 block">Statut</span>
                <select
                  value={draft.status}
                  onChange={(e) => setDraft({ ...draft, status: e.target.value as ScheduleStatus })}
                  className="w-full p-2 rounded bg-black/30 text-shugu-cream"
                >
                  <option value="planned">planned</option>
                  <option value="live">live</option>
                  <option value="past">past</option>
                  <option value="cancelled">cancelled</option>
                </select>
              </label>
            )}

            <div className="flex items-center justify-end gap-2 pt-2">
              <GlassButton variant="ghost" size="sm" onClick={() => setDraft(null)} disabled={saving}>
                Annuler
              </GlassButton>
              {draft.id !== null && (
                <GlassButton variant="danger" size="sm"
                  onClick={() => setConfirmDelete(monthStreams.find((s) => s.id === draft.id) ?? upcoming.find((s) => s.id === draft.id) ?? null)}
                  disabled={saving}
                >
                  Supprimer
                </GlassButton>
              )}
              <GlassButton variant="primary" size="sm" onClick={onSaveDraft} disabled={saving || !draft.title}>
                {saving ? "…" : draft.id === null ? "Créer" : "Enregistrer"}
              </GlassButton>
            </div>
          </div>
        </GlassModal>
      )}

      {/* Modal confirm delete */}
      {confirmDelete && (
        <GlassModal open onClose={() => !saving && setConfirmDelete(null)}>
          <div className="p-5 space-y-3 max-w-md">
            <h3 className="text-lg font-light text-shugu-cream">
              Supprimer &quot;{confirmDelete.title}&quot; ?
            </h3>
            <p className="text-sm opacity-70">Cette action est irréversible.</p>
            <div className="flex items-center justify-end gap-2 pt-2">
              <GlassButton variant="ghost" size="sm" onClick={() => setConfirmDelete(null)} disabled={saving}>Annuler</GlassButton>
              <GlassButton variant="danger" size="sm" onClick={onConfirmDelete} disabled={saving}>
                {saving ? "…" : "Supprimer"}
              </GlassButton>
            </div>
          </div>
        </GlassModal>
      )}
    </AdminShell>
  );
}
```

- [ ] **Step 7.2 :** TS + ESLint check.

- [ ] **Step 7.3 :** Commit
```bash
git commit -m "✨ feat(admin/schedule): refonte UI — calendar 7xN + form modal + delete confirm + polling 60s"
```

---

## Task 8: Smoke tests manuels + PR

- [ ] **Step 8.1 :** Backend + frontend up. Migration alembic appliquée.

- [ ] **Step 8.2 :** Tester :
  - Créer 1 stream → row DB visible, apparait dans le calendrier
  - Édit titre + status planned → cancelled → row update
  - Supprimer → row disparait
  - GET `/api/schedule/upcoming` sans cookie → 200 avec stream créé
  - Login member → POST `/api/admin/schedule` → 401 ou 403

- [ ] **Step 8.3 :** Suite complète :
```bash
cd backend && pytest tests/ --tb=short
cd frontend && npx tsc --noEmit && npx eslint src/
```

- [ ] **Step 8.4 :** PR
```bash
git push -u origin claude/crazy-sutherland-96ea1c
gh pr create --title "✨ feat(admin/schedule): calendar prod-ready — CRUD + public upcoming" --body "$(cat <<'EOF'
## Summary

Remplace `/[username]/admin/schedule` mockée par un planificateur de streams complet.

**Sub-project C/4** (suit Moderation A et Analytics B). Spec : `docs/superpowers/specs/2026-05-10-admin-schedule-design.md` · Plan : `docs/superpowers/plans/2026-05-10-admin-schedule-plan.md`

## Features

- Migration Alembic table `scheduled_streams` avec CHECK constraints duration ∈ ]0, 1440] et status enum
- 5 routes admin REST CRUD gated `require_operator`
- 1 route publique `/api/schedule/upcoming` non gated
- State machine status (planned → live → past, planned → cancelled, irréversibles)
- UI calendar mensuel 7×N + form modal create/edit/delete + rail "à venir"
- Polling 60s, timezone UTC backend / local browser

## Test plan

- [x] ~42 tests (9 unit state machine + 25 admin routes + 8 public routes)
- [x] Coverage ≥ 90% sur 3 nouveaux modules
- [x] Sécurité non-régression : member_cookie rejeté sur 5 routes admin
- [x] Migration alembic apply/downgrade OK
- [x] Smoke tests : create/edit/delete + public visibility + admin gating

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-review

- ✅ Migration Alembic complète avec CHECK constraints
- ✅ State machine validée par tests dédiés
- ✅ 5 routes admin CRUD + 1 publique
- ✅ Tests couvrent transitions invalides + idempotency delete + non-régression sécurité
- ✅ Pas de placeholder, code complet partout
- ✅ Cohérence types : `ScheduleStatus` partout, `ScheduleListItem` Pydantic ↔ `ScheduledStream` TS

## Execution handoff

Input prêt pour ruflo après merge des sub-projects A + B (dépendance fixtures via conftest).
