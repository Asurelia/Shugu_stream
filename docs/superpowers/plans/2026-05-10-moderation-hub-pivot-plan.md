# Moderation Hub Pivot — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remplacer la page mockée `/[username]/admin/moderation` par un vrai dashboard branché sur le pipeline IA agent existant (`BasicModeration` → table `moderation_events`).

**Architecture:** Decorator pattern (`LoggingModeration` wraps `BasicModeration`) pour persister chaque verdict refusé dans la table existante. 4 routes admin REST (`require_operator`). Frontend service `fetch`-based + UI refondue sur primitives `liquid-glass` existantes.

**Tech Stack:** Python 3.11+ / FastAPI / SQLAlchemy async / Pydantic v2 / Redis (fakeredis pour tests) / pytest + pytest-asyncio / structlog. Next.js App Router / TypeScript strict / liquid-glass primitives internes.

**Spec source de vérité :** [docs/superpowers/specs/2026-05-10-moderation-hub-pivot-design.md](../specs/2026-05-10-moderation-hub-pivot-design.md)

---

## File Structure

### Fichiers à créer

| Path | Responsabilité |
|---|---|
| `backend/shugu/adapters/moderation_logging.py` | Décorateur `LoggingModeration` qui persiste les refus |
| `backend/shugu/services/moderation_events.py` | Queries SQL (list, aggregate stats) |
| `backend/shugu/routes/admin_moderation.py` | Routes `/api/admin/moderation/*` |
| `backend/tests/unit/test_moderation_logging.py` | Tests unit du décorateur |
| `backend/tests/integration/test_admin_moderation_routes.py` | Tests intégration routes admin |
| `frontend/src/services/adminModerationClient.ts` | Wrapper fetch typé |

### Fichiers à modifier

| Path | Modification |
|---|---|
| `backend/shugu/app.py` | Ligne 275 : wrapper `LoggingModeration(BasicModeration(...))` + include router |
| `backend/shugu/services/__init__.py` | Exporter le nouveau module (si pattern existant) |
| `backend/tests/conftest.py` | Ajouter fixtures `db_session`, `operator_cookie`, `seed_events`, `seed_redis_bans`, `api_client` |
| `frontend/src/app/[username]/admin/moderation/_client.tsx` | Refonte complète (mock → branché) |

### Fichiers NON touchés (préservation explicite)

- `backend/shugu/adapters/moderation_basic.py` — code audité
- `backend/shugu/core/protocols.py` — Protocol `ModerationLayer` stable
- `backend/shugu/db/models.py` — `ModerationEvent` schema stable
- `backend/shugu/routes/visitor_ws.py`, `backend/shugu/pipeline/workers.py` — consommateurs

---

## Task 0: Vérification préalable de la table `moderation_events`

**Files:**
- Read only: DB schema check

- [ ] **Step 0.1 : Vérifier que la table existe**

Run:
```bash
psql "$SHUGU_POSTGRES_DSN" -c "\d moderation_events"
```

Expected output (extrait minimal) :
```
                            Table "public.moderation_events"
      Column      |           Type           | …
------------------+--------------------------+--
 id               | bigint                   | NOT NULL
 performance_id   | character varying(26)    |
 phase            | character varying(16)    | NOT NULL
 detector         | character varying(32)    | NOT NULL
 verdict          | character varying(16)    | NOT NULL
 details          | jsonb                    |
 created_at       | timestamp with time zone |
```

- [ ] **Step 0.2 : Si la table existe → SKIP Task 0.3, passer à Task 1**

- [ ] **Step 0.3 : Si la table N'EXISTE PAS → créer une migration Alembic**

Vérifier d'abord :
```bash
ls backend/alembic/versions/ | head -5
alembic -c backend/alembic.ini current
```

Créer la migration :
```bash
alembic -c backend/alembic.ini revision -m "add_moderation_events_table" --autogenerate
```

Vérifier le contenu généré, puis appliquer :
```bash
alembic -c backend/alembic.ini upgrade head
```

- [ ] **Step 0.4 : Commit (uniquement si migration créée)**

```bash
git add backend/alembic/versions/*moderation_events*.py
git commit -m "🗄️ chore(db): alembic migration for moderation_events table"
```

---

## Task 1: Fixtures de test backend (préalable TDD)

**Files:**
- Modify: `backend/tests/conftest.py`

- [ ] **Step 1.1 : Ajouter import et fixture `db_session`**

Ajouter en tête de `conftest.py` (après les imports existants) :

```python
from typing import AsyncIterator
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession
```

Ajouter la fixture après `redis_client` :

```python
@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """Session async PostgreSQL avec rollback par test."""
    from shugu.db.session import SessionLocal
    async with SessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()
            await session.close()
```

- [ ] **Step 1.2 : Ajouter fixture `seed_redis_bans`**

```python
@pytest_asyncio.fixture
async def seed_redis_bans(redis_client):
    """Insère 2 bans Redis : 1 avec TTL 3600s, 1 perma (-1)."""
    a = "a" * 64  # SHA-256 hex factice
    b = "b" * 64
    await redis_client.set(f"ban:{a}", "1", ex=3600)
    await redis_client.set(f"ban:{b}", "1")  # no TTL
    return {"ttl_60min": a, "perma": b}
```

- [ ] **Step 1.3 : Ajouter fixture `seed_events`**

```python
@pytest_asyncio.fixture
async def seed_events(db_session):
    """Insère 20 ModerationEvent variés (3 detectors, 2 phases, sur 24h)."""
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import insert
    from shugu.db.models import ModerationEvent

    now = datetime.now(timezone.utc)
    rows = []
    detectors = ["profanity", "injection", "rate_limit"]
    phases = ["ingress", "egress"]
    for i in range(20):
        rows.append({
            "phase": phases[i % 2],
            "detector": detectors[i % 3],
            "verdict": "refused",
            "details": {
                "reason": f"reason-{i}",
                "identity_kind": "visitor",
                "ip_hash": "c" * 64,
                "text_excerpt": f"msg {i}",
                "text_len": 10 + i,
            },
            "created_at": now - timedelta(hours=i),
        })
    await db_session.execute(insert(ModerationEvent), rows)
    await db_session.commit()
    return rows
```

- [ ] **Step 1.4 : Ajouter fixture `operator_cookie` + `api_client`**

```python
@pytest_asyncio.fixture
async def api_client():
    """TestClient FastAPI async."""
    from httpx import AsyncClient, ASGITransport
    from shugu.app import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture
async def operator_cookie(api_client):
    """Cookie shugu_access valide pour un OperatorIdentity de test.

    Utilise le flow d'auth existant pour générer un JWT operator. Si le projet
    a un endpoint de login operator, l'appeler. Sinon, forger un cookie via
    shugu.auth.user_tokens.create_access_token avec role=operator.
    """
    from shugu.auth import user_tokens
    token = user_tokens.create_access_token(
        subject="test-operator",
        extra={"role": "operator", "username": "test-op"},
    )
    return {"shugu_access": token}
```

> ⚠️ Si `user_tokens.create_access_token` n'a pas cette signature exacte, adapter en lisant `backend/shugu/auth/user_tokens.py` AVANT de coder cette fixture. La forge JWT operator EXISTE forcément dans le projet — chercher `OperatorIdentity` ou un fichier `test_*` qui auth déjà en operator.

- [ ] **Step 1.5 : Vérifier que les fixtures importent**

Run:
```bash
cd backend && pytest tests/conftest.py --collect-only 2>&1 | head -20
```

Expected: pas d'erreur d'import. Si erreur, fixer les imports.

- [ ] **Step 1.6 : Commit**

```bash
git add backend/tests/conftest.py
git commit -m "🧪 test(fixtures): db_session, operator_cookie, seed_events, seed_redis_bans"
```

---

## Task 2: TDD `LoggingModeration` — test allowed does NOT persist

**Files:**
- Create: `backend/tests/unit/test_moderation_logging.py`
- (preparation only, no impl yet)

- [ ] **Step 2.1 : Créer le fichier de test avec le premier test rouge**

```python
"""Tests unit pour LoggingModeration (décorateur ModerationLayer)."""
from __future__ import annotations

from dataclasses import dataclass

import pytest
from sqlalchemy import select

from shugu.adapters.moderation_logging import LoggingModeration
from shugu.core.identity import VisitorIdentity
from shugu.core.protocols import ModerationLayer, ModerationVerdict
from shugu.db.models import ModerationEvent


class FakeInner(ModerationLayer):
    """Stub ModerationLayer retournant un verdict fixe."""
    def __init__(self, verdict: ModerationVerdict):
        self._verdict = verdict
        self.ingress_calls = 0
        self.egress_calls = 0

    async def check_ingress(self, text, identity):
        self.ingress_calls += 1
        return self._verdict

    async def check_egress(self, text, identity):
        self.egress_calls += 1
        return self._verdict


def _visitor() -> VisitorIdentity:
    return VisitorIdentity(ip_hash="a" * 64, session_id="sess-1")


@pytest.mark.asyncio
async def test_check_ingress_allowed_does_not_persist(db_session):
    inner = FakeInner(ModerationVerdict(allowed=True))
    layer = LoggingModeration(inner)

    verdict = await layer.check_ingress("hello", _visitor())

    assert verdict.allowed is True
    assert inner.ingress_calls == 1
    rows = (await db_session.execute(select(ModerationEvent))).scalars().all()
    assert rows == []
```

- [ ] **Step 2.2 : Run le test → doit échouer (rouge)**

```bash
cd backend && pytest tests/unit/test_moderation_logging.py::test_check_ingress_allowed_does_not_persist -v
```

Expected: FAIL avec `ModuleNotFoundError: No module named 'shugu.adapters.moderation_logging'`

---

## Task 3: Impl minimale `LoggingModeration` skeleton

**Files:**
- Create: `backend/shugu/adapters/moderation_logging.py`

- [ ] **Step 3.1 : Créer le fichier squelette**

```python
"""LoggingModeration — décorateur ModerationLayer persistant les refus en DB.

Volume cible : ~5 % du trafic (uniquement allowed=False). Synchrone par design
(hot path) : INSERT PostgreSQL ~1-5 ms, amorti à <0.5 ms moyen sur le trafic
total. Fail-open : une erreur d'INSERT N'INTERROMPT JAMAIS le pipeline
moderation — on log l'erreur via structlog et on laisse le verdict remonter au
caller.
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

    async def _persist(self, phase, verdict, identity, text):
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
```

- [ ] **Step 3.2 : Run le test → doit passer (vert)**

```bash
cd backend && pytest tests/unit/test_moderation_logging.py::test_check_ingress_allowed_does_not_persist -v
```

Expected: PASS

- [ ] **Step 3.3 : Commit**

```bash
git add backend/tests/unit/test_moderation_logging.py backend/shugu/adapters/moderation_logging.py
git commit -m "✨ feat(moderation): LoggingModeration decorator skeleton + first unit test"
```

---

## Task 4: TDD `LoggingModeration` — test refused persists event

**Files:**
- Modify: `backend/tests/unit/test_moderation_logging.py`

- [ ] **Step 4.1 : Ajouter le test**

Ajouter à la suite du test précédent :

```python
@pytest.mark.asyncio
async def test_check_ingress_refused_persists_event(db_session):
    verdict = ModerationVerdict(allowed=False, reason="langage inapproprié", detector="profanity")
    layer = LoggingModeration(FakeInner(verdict))

    result = await layer.check_ingress("texte interdit", _visitor())

    assert result.allowed is False
    rows = (await db_session.execute(select(ModerationEvent))).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.phase == "ingress"
    assert row.detector == "profanity"
    assert row.verdict == "refused"
    assert row.details["reason"] == "langage inapproprié"
    assert row.details["identity_kind"] == "visitor"
    assert row.details["ip_hash"] == "a" * 64
    assert row.details["text_excerpt"] == "texte interdit"
    assert row.details["text_len"] == 14
```

- [ ] **Step 4.2 : Run → doit passer (LoggingModeration._persist déjà implémenté Task 3)**

```bash
cd backend && pytest tests/unit/test_moderation_logging.py::test_check_ingress_refused_persists_event -v
```

Expected: PASS

- [ ] **Step 4.3 : Commit**

```bash
git add backend/tests/unit/test_moderation_logging.py
git commit -m "🧪 test(moderation): assert refused verdict persists event row"
```

---

## Task 5: TDD `LoggingModeration` — autres invariants

**Files:**
- Modify: `backend/tests/unit/test_moderation_logging.py`

- [ ] **Step 5.1 : Ajouter les 5 tests restants**

```python
@pytest.mark.asyncio
async def test_check_egress_refused_persists_with_egress_phase(db_session):
    verdict = ModerationVerdict(allowed=False, reason="too long", detector="egress_length")
    layer = LoggingModeration(FakeInner(verdict))

    await layer.check_egress("réponse IA trop longue", _visitor())

    rows = (await db_session.execute(select(ModerationEvent))).scalars().all()
    assert len(rows) == 1
    assert rows[0].phase == "egress"


@pytest.mark.asyncio
async def test_details_truncates_text_excerpt_at_80_chars(db_session):
    long_text = "x" * 200
    verdict = ModerationVerdict(allowed=False, detector="length", reason="too long")
    layer = LoggingModeration(FakeInner(verdict))

    await layer.check_ingress(long_text, _visitor())

    row = (await db_session.execute(select(ModerationEvent))).scalars().one()
    assert row.details["text_excerpt"] == "x" * 80
    assert row.details["text_len"] == 200


@pytest.mark.asyncio
async def test_detector_fallback_unknown(db_session):
    verdict = ModerationVerdict(allowed=False, reason="???", detector=None)
    layer = LoggingModeration(FakeInner(verdict))

    await layer.check_ingress("foo", _visitor())

    row = (await db_session.execute(select(ModerationEvent))).scalars().one()
    assert row.detector == "unknown"


@pytest.mark.asyncio
async def test_text_excerpt_handles_none_text(db_session):
    verdict = ModerationVerdict(allowed=False, reason="empty", detector="length")
    layer = LoggingModeration(FakeInner(verdict))

    await layer.check_ingress(None, _visitor())  # type: ignore[arg-type]

    row = (await db_session.execute(select(ModerationEvent))).scalars().one()
    assert row.details["text_excerpt"] == ""
    assert row.details["text_len"] == 0


@pytest.mark.asyncio
async def test_persist_failure_does_not_break_pipeline(monkeypatch, caplog):
    """DB down → verdict est quand même retourné + warning structlog émis."""
    from shugu.adapters import moderation_logging as mod

    class BoomSession:
        async def __aenter__(self): raise RuntimeError("db down")
        async def __aexit__(self, *a): return False

    monkeypatch.setattr(mod, "session_scope", lambda: BoomSession())

    verdict = ModerationVerdict(allowed=False, reason="x", detector="profanity")
    layer = LoggingModeration(FakeInner(verdict))

    result = await layer.check_ingress("foo", _visitor())

    assert result.allowed is False  # pipeline non interrompu
```

- [ ] **Step 5.2 : Run tous les tests du module**

```bash
cd backend && pytest tests/unit/test_moderation_logging.py -v
```

Expected: 6 PASS, 0 FAIL.

Si un test échoue, lire la trace, identifier la cause, **corriger le code** (jamais le test).

- [ ] **Step 5.3 : Vérifier le coverage**

```bash
cd backend && pytest tests/unit/test_moderation_logging.py --cov=shugu.adapters.moderation_logging --cov-report=term-missing
```

Expected: ≥ 90 %. Si < 90 %, ajouter le test manquant pour la branche non couverte.

- [ ] **Step 5.4 : Commit**

```bash
git add backend/tests/unit/test_moderation_logging.py
git commit -m "🧪 test(moderation): egress phase, text excerpt, detector fallback, fail-open"
```

---

## Task 6: TDD `services/moderation_events.list_events`

**Files:**
- Create: `backend/tests/integration/test_admin_moderation_routes.py` (juste les tests services pour l'instant)
- Create: `backend/shugu/services/moderation_events.py`

- [ ] **Step 6.1 : Créer le fichier de test intégration**

```python
"""Tests intégration des routes admin moderation + service queries."""
from __future__ import annotations

import pytest

from shugu.services import moderation_events as svc


@pytest.mark.asyncio
async def test_list_events_returns_empty_when_no_data(db_session):
    result = await svc.list_events(db_session)
    assert result["total"] == 0
    assert result["items"] == []


@pytest.mark.asyncio
async def test_list_events_returns_seeded(db_session, seed_events):
    result = await svc.list_events(db_session, limit=50)
    assert result["total"] == 20
    assert len(result["items"]) == 20
    # Le plus récent en premier
    assert result["items"][0]["created_at"] >= result["items"][-1]["created_at"]


@pytest.mark.asyncio
async def test_list_events_filters_by_phase(db_session, seed_events):
    result = await svc.list_events(db_session, phase="ingress", limit=50)
    assert all(it["phase"] == "ingress" for it in result["items"])


@pytest.mark.asyncio
async def test_list_events_filters_by_detector(db_session, seed_events):
    result = await svc.list_events(db_session, detector="profanity", limit=50)
    assert all(it["detector"] == "profanity" for it in result["items"])


@pytest.mark.asyncio
async def test_list_events_pagination(db_session, seed_events):
    page1 = await svc.list_events(db_session, limit=10, offset=0)
    page2 = await svc.list_events(db_session, limit=10, offset=10)
    assert len(page1["items"]) == 10
    assert len(page2["items"]) == 10
    ids_p1 = {it["id"] for it in page1["items"]}
    ids_p2 = {it["id"] for it in page2["items"]}
    assert ids_p1.isdisjoint(ids_p2)
```

- [ ] **Step 6.2 : Run → tous échouent (rouge)**

```bash
cd backend && pytest tests/integration/test_admin_moderation_routes.py -v 2>&1 | head -30
```

Expected: 5 FAIL avec `ModuleNotFoundError: No module named 'shugu.services.moderation_events'`

- [ ] **Step 6.3 : Créer le service**

```python
"""Service couche : queries SQL sur ModerationEvent."""
from __future__ import annotations

from datetime import datetime
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
    """Retourne {total, items} paginés et filtrés."""
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
```

- [ ] **Step 6.4 : Run → 5 passent (vert)**

```bash
cd backend && pytest tests/integration/test_admin_moderation_routes.py -v
```

Expected: 5 PASS.

- [ ] **Step 6.5 : Commit**

```bash
git add backend/tests/integration/test_admin_moderation_routes.py backend/shugu/services/moderation_events.py
git commit -m "✨ feat(moderation): service.list_events with filters + pagination + tests"
```

---

## Task 7: TDD `services/moderation_events.aggregate_stats`

**Files:**
- Modify: `backend/tests/integration/test_admin_moderation_routes.py`
- Modify: `backend/shugu/services/moderation_events.py`

- [ ] **Step 7.1 : Ajouter les tests**

```python
@pytest.mark.asyncio
async def test_stats_24h_total_refused(db_session, seed_events):
    stats = await svc.aggregate_stats(db_session, window="24h")
    assert stats["total_refused"] == 20
    assert stats["window"] == "24h"


@pytest.mark.asyncio
async def test_stats_groups_by_detector(db_session, seed_events):
    stats = await svc.aggregate_stats(db_session, window="24h")
    # 20 events / 3 detectors → 7 ou 6 par detector
    assert set(stats["by_detector"].keys()) == {"profanity", "injection", "rate_limit"}
    assert sum(stats["by_detector"].values()) == 20


@pytest.mark.asyncio
async def test_stats_groups_by_phase(db_session, seed_events):
    stats = await svc.aggregate_stats(db_session, window="24h")
    assert sum(stats["by_phase"].values()) == 20
    assert set(stats["by_phase"].keys()) == {"ingress", "egress"}


@pytest.mark.asyncio
async def test_stats_timeline_buckets(db_session, seed_events):
    stats = await svc.aggregate_stats(db_session, window="24h")
    # window 24h → buckets de 1h → 24 buckets max
    assert len(stats["timeline"]) <= 24
    assert all("bucket" in b and "count" in b for b in stats["timeline"])
    total_in_timeline = sum(b["count"] for b in stats["timeline"])
    assert total_in_timeline == 20
```

- [ ] **Step 7.2 : Run → 4 FAIL**

```bash
cd backend && pytest tests/integration/test_admin_moderation_routes.py::test_stats_24h_total_refused -v
```

Expected: FAIL `AttributeError: module 'shugu.services.moderation_events' has no attribute 'aggregate_stats'`

- [ ] **Step 7.3 : Implémenter `aggregate_stats`**

Ajouter à `backend/shugu/services/moderation_events.py` :

```python
from datetime import timedelta, timezone


_WINDOW_TO_DELTA = {
    "1h": timedelta(hours=1),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
}
_WINDOW_TO_BUCKET = {
    "1h": "5 minutes",
    "24h": "1 hour",
    "7d": "1 day",
}


async def aggregate_stats(session: AsyncSession, *, window: str = "24h") -> dict:
    if window not in _WINDOW_TO_DELTA:
        raise ValueError(f"invalid window: {window}")
    now = datetime.now(timezone.utc)
    since = now - _WINDOW_TO_DELTA[window]

    base = select(ModerationEvent).where(ModerationEvent.created_at >= since)

    # total
    total = (await session.execute(
        select(func.count()).select_from(base.subquery())
    )).scalar_one()

    # by_detector
    rows = (await session.execute(
        select(ModerationEvent.detector, func.count())
        .where(ModerationEvent.created_at >= since)
        .group_by(ModerationEvent.detector)
    )).all()
    by_detector = {d: int(c) for d, c in rows}

    # by_phase
    rows = (await session.execute(
        select(ModerationEvent.phase, func.count())
        .where(ModerationEvent.created_at >= since)
        .group_by(ModerationEvent.phase)
    )).all()
    by_phase = {p: int(c) for p, c in rows}

    # timeline — date_trunc bucket
    bucket = _WINDOW_TO_BUCKET[window]
    timeline_rows = (await session.execute(
        select(
            func.date_trunc(bucket.split()[1] if " " in bucket else bucket,
                            ModerationEvent.created_at).label("bucket"),
            func.count().label("count"),
        )
        .where(ModerationEvent.created_at >= since)
        .group_by("bucket")
        .order_by("bucket")
    )).all()
    timeline = [{"bucket": r.bucket, "count": int(r.count)} for r in timeline_rows]

    return {
        "window": window,
        "total_refused": int(total),
        "by_detector": by_detector,
        "by_phase": by_phase,
        "timeline": timeline,
    }
```

> ⚠️ `date_trunc` PostgreSQL ne supporte que `'minute'|'hour'|'day'`, pas `'5 minutes'`. Pour les buckets 5min, utiliser `EXTRACT(EPOCH FROM created_at)/300` ou simplifier en 1min. Adapter la logique en lisant les docs PG si le test échoue.

- [ ] **Step 7.4 : Run → 4 PASS**

```bash
cd backend && pytest tests/integration/test_admin_moderation_routes.py -v -k stats
```

Expected: PASS. Si la query `date_trunc` échoue, simplifier à 'hour'/'day' (pas de 5min pour 1h window).

- [ ] **Step 7.5 : Commit**

```bash
git add backend/tests/integration/test_admin_moderation_routes.py backend/shugu/services/moderation_events.py
git commit -m "✨ feat(moderation): service.aggregate_stats with by_detector/by_phase/timeline"
```

---

## Task 8: TDD route `GET /api/admin/moderation/events`

**Files:**
- Modify: `backend/tests/integration/test_admin_moderation_routes.py`
- Create: `backend/shugu/routes/admin_moderation.py`

- [ ] **Step 8.1 : Ajouter les tests route**

```python
@pytest.mark.asyncio
async def test_route_list_events_empty(api_client, operator_cookie):
    r = await api_client.get("/api/admin/moderation/events", cookies=operator_cookie)
    assert r.status_code == 200
    body = r.json()
    assert body == {"total": 0, "items": []}


@pytest.mark.asyncio
async def test_route_list_events_requires_operator(api_client):
    r = await api_client.get("/api/admin/moderation/events")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_route_list_events_with_data(api_client, operator_cookie, seed_events):
    r = await api_client.get(
        "/api/admin/moderation/events?limit=5",
        cookies=operator_cookie,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 20
    assert len(body["items"]) == 5
```

- [ ] **Step 8.2 : Run → 3 FAIL**

Expected: 404 (route inexistante) ou import error.

- [ ] **Step 8.3 : Créer la route**

```python
"""Routes admin moderation — sous /api/admin/moderation/* gated require_operator."""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from ..auth.dependencies import require_operator
from ..core.identity import OperatorIdentity
from ..db.session import session_scope
from ..services import moderation_events as svc

router = APIRouter(prefix="/api/admin/moderation", tags=["admin-moderation"])


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


class EventListResponse(BaseModel):
    total: int
    items: list[EventListItem]


@router.get("/events", response_model=EventListResponse)
async def list_events(
    phase: Optional[Literal["ingress", "egress"]] = None,
    detector: Optional[str] = None,
    since: Optional[datetime] = None,
    limit: int = Query(25, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _op: OperatorIdentity = Depends(require_operator),
):
    async with session_scope() as s:
        return await svc.list_events(
            s, phase=phase, detector=detector, since=since, limit=limit, offset=offset,
        )
```

- [ ] **Step 8.4 : Wire le router dans `app.py` (préalable pour les tests)**

Lire `backend/shugu/app.py`, identifier la zone `app.include_router(...)` (chercher les autres routes admin), et ajouter :

```python
from .routes.admin_moderation import router as admin_moderation_router
# ...
app.include_router(admin_moderation_router)
```

- [ ] **Step 8.5 : Run les tests → 3 PASS**

```bash
cd backend && pytest tests/integration/test_admin_moderation_routes.py -v -k route_list_events
```

Expected: PASS.

- [ ] **Step 8.6 : Commit**

```bash
git add backend/tests/integration/test_admin_moderation_routes.py backend/shugu/routes/admin_moderation.py backend/shugu/app.py
git commit -m "✨ feat(moderation): GET /api/admin/moderation/events route + tests"
```

---

## Task 9: TDD route `GET /api/admin/moderation/stats`

**Files:**
- Modify: `backend/tests/integration/test_admin_moderation_routes.py`
- Modify: `backend/shugu/routes/admin_moderation.py`

- [ ] **Step 9.1 : Ajouter tests**

```python
@pytest.mark.asyncio
async def test_route_stats_24h(api_client, operator_cookie, seed_events):
    r = await api_client.get("/api/admin/moderation/stats?window=24h", cookies=operator_cookie)
    assert r.status_code == 200
    body = r.json()
    assert body["total_refused"] == 20
    assert body["window"] == "24h"


@pytest.mark.asyncio
async def test_route_stats_window_validation(api_client, operator_cookie):
    r = await api_client.get("/api/admin/moderation/stats?window=invalid", cookies=operator_cookie)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_route_stats_requires_operator(api_client):
    r = await api_client.get("/api/admin/moderation/stats")
    assert r.status_code == 401
```

- [ ] **Step 9.2 : Run → 3 FAIL**

- [ ] **Step 9.3 : Ajouter la route**

Ajouter dans `routes/admin_moderation.py` :

```python
class BucketCount(BaseModel):
    bucket: datetime
    count: int


class StatsResponse(BaseModel):
    window: Literal["1h", "24h", "7d"]
    total_refused: int
    by_detector: dict[str, int]
    by_phase: dict[str, int]
    timeline: list[BucketCount]


@router.get("/stats", response_model=StatsResponse)
async def stats(
    window: Literal["1h", "24h", "7d"] = "24h",
    _op: OperatorIdentity = Depends(require_operator),
):
    async with session_scope() as s:
        return await svc.aggregate_stats(s, window=window)
```

- [ ] **Step 9.4 : Run → 3 PASS**

- [ ] **Step 9.5 : Commit**

```bash
git add backend/tests/integration/test_admin_moderation_routes.py backend/shugu/routes/admin_moderation.py
git commit -m "✨ feat(moderation): GET /api/admin/moderation/stats route + tests"
```

---

## Task 10: TDD routes `GET/DELETE /api/admin/moderation/bans`

**Files:**
- Modify: `backend/tests/integration/test_admin_moderation_routes.py`
- Modify: `backend/shugu/routes/admin_moderation.py`

- [ ] **Step 10.1 : Ajouter les tests**

```python
@pytest.mark.asyncio
async def test_route_list_bans_returns_redis_keys(api_client, operator_cookie, seed_redis_bans):
    r = await api_client.get("/api/admin/moderation/bans", cookies=operator_cookie)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    ip_hashes = {item["ip_hash"] for item in body["items"]}
    assert ip_hashes == {seed_redis_bans["ttl_60min"], seed_redis_bans["perma"]}


@pytest.mark.asyncio
async def test_route_clear_ban_deletes_redis_key(api_client, operator_cookie, redis_client, seed_redis_bans):
    target = seed_redis_bans["ttl_60min"]
    r = await api_client.delete(f"/api/admin/moderation/bans/{target}", cookies=operator_cookie)
    assert r.status_code == 204
    assert await redis_client.get(f"ban:{target}") is None


@pytest.mark.asyncio
async def test_route_clear_ban_idempotent(api_client, operator_cookie):
    fake = "f" * 64
    r1 = await api_client.delete(f"/api/admin/moderation/bans/{fake}", cookies=operator_cookie)
    r2 = await api_client.delete(f"/api/admin/moderation/bans/{fake}", cookies=operator_cookie)
    assert r1.status_code == 204
    assert r2.status_code == 204


@pytest.mark.asyncio
async def test_route_clear_ban_rejects_invalid_hash(api_client, operator_cookie):
    r = await api_client.delete("/api/admin/moderation/bans/not_a_sha256", cookies=operator_cookie)
    assert r.status_code == 422
```

- [ ] **Step 10.2 : Run → 4 FAIL**

- [ ] **Step 10.3 : Implémenter les routes bans**

Ajouter dans `routes/admin_moderation.py` :

```python
import re

from ..app import _redis_dep  # OU récupérer redis via DI/lifespan — voir comment app.py expose le client

_IP_HASH_RE = re.compile(r"^[a-f0-9]{64}$")


class BanItem(BaseModel):
    ip_hash: str
    ttl_seconds: int


class BanListResponse(BaseModel):
    total: int
    items: list[BanItem]


async def _get_redis():
    """Récupère le client redis depuis l'app state.

    Lire backend/shugu/app.py pour comprendre comment redis est exposé. S'il est
    stocké dans app.state.redis, créer un Depends() qui le récupère via Request.
    """
    # ⚠️ adapter au pattern réel du projet — voir startup event app.py
    ...


@router.get("/bans", response_model=BanListResponse)
async def list_bans(
    redis=Depends(_get_redis),
    _op: OperatorIdentity = Depends(require_operator),
):
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
    if not _IP_HASH_RE.match(ip_hash):
        raise HTTPException(status_code=422, detail="ip_hash must be 64-char lowercase hex")
    await redis.delete(f"ban:{ip_hash}")
    # Pas de retour body — 204 No Content
```

> ⚠️ Le `_get_redis` Depends doit récupérer le **vrai** client redis. Lire `app.py` pour trouver le pattern (probablement `app.state.redis` set au startup). En test, le `api_client` fixture doit override ce Depends pour pointer vers le `redis_client` fakeredis. Si nécessaire, utiliser `app.dependency_overrides[_get_redis] = lambda: redis_client` dans la fixture `api_client`.

- [ ] **Step 10.4 : Run → 4 PASS**

```bash
cd backend && pytest tests/integration/test_admin_moderation_routes.py -v -k ban
```

Expected: PASS.

- [ ] **Step 10.5 : Commit**

```bash
git add backend/tests/integration/test_admin_moderation_routes.py backend/shugu/routes/admin_moderation.py
git commit -m "✨ feat(moderation): GET/DELETE /bans routes + regex validation + idempotency"
```

---

## Task 11: Test sécurité non-régression (reject member/vip cookies)

**Files:**
- Modify: `backend/tests/integration/test_admin_moderation_routes.py`
- Modify: `backend/tests/conftest.py`

- [ ] **Step 11.1 : Ajouter une fixture `member_cookie`**

Dans `conftest.py` :

```python
@pytest_asyncio.fixture
async def member_cookie():
    """Cookie pour un MemberIdentity de test — ne doit PAS accéder aux routes admin."""
    from shugu.auth import user_tokens
    token = user_tokens.create_access_token(
        subject="test-member",
        extra={"role": "member", "username": "test-member"},
    )
    return {"shugu_access": token}
```

- [ ] **Step 11.2 : Ajouter le test de non-régression sécurité**

```python
@pytest.mark.asyncio
async def test_route_list_events_rejects_member_cookie(api_client, member_cookie):
    """Sécurité : un member authentifié NE DOIT PAS accéder aux events admin (PII)."""
    r = await api_client.get("/api/admin/moderation/events", cookies=member_cookie)
    assert r.status_code in (401, 403)  # require_operator doit rejeter
```

- [ ] **Step 11.3 : Run → doit déjà passer car `require_operator` filtre**

```bash
cd backend && pytest tests/integration/test_admin_moderation_routes.py::test_route_list_events_rejects_member_cookie -v
```

Expected: PASS.

- [ ] **Step 11.4 : Vérifier le coverage global**

```bash
cd backend && pytest tests/unit/test_moderation_logging.py tests/integration/test_admin_moderation_routes.py \
    --cov=shugu.adapters.moderation_logging \
    --cov=shugu.services.moderation_events \
    --cov=shugu.routes.admin_moderation \
    --cov-report=term-missing
```

Expected: ≥ 90 % sur chaque module. Si non, ajouter le test de la branche manquante.

- [ ] **Step 11.5 : Commit**

```bash
git add backend/tests/conftest.py backend/tests/integration/test_admin_moderation_routes.py
git commit -m "🛡️ test(moderation): non-regression — member cookie cannot access admin routes"
```

---

## Task 12: Wiring `app.py` — wrapper LoggingModeration

**Files:**
- Modify: `backend/shugu/app.py:275`

- [ ] **Step 12.1 : Modifier la ligne 275**

Lire `backend/shugu/app.py` ligne 270-280 pour contexte. Ligne actuelle :

```python
moderation = BasicModeration(settings, _redis, metrics=_prom_recorder)
```

Remplacer par :

```python
from .adapters.moderation_logging import LoggingModeration
# ... (ligne 275)
moderation = LoggingModeration(BasicModeration(settings, _redis, metrics=_prom_recorder))
```

L'import doit être ajouté en haut du fichier avec les autres imports `from .adapters.*`.

- [ ] **Step 12.2 : Lancer la suite complète**

```bash
cd backend && pytest tests/ -x --tb=short 2>&1 | tail -30
```

Expected: ZÉRO test cassé. Si un test du pipeline pré-existant échoue à cause du wrapper, le LoggingModeration doit être 100 % transparent pour `allowed=True`. Lire l'erreur, fixer.

- [ ] **Step 12.3 : Commit**

```bash
git add backend/shugu/app.py
git commit -m "🔧 chore(app): wire LoggingModeration decorator around BasicModeration"
```

---

## Task 13: Smoke test backend manuel

**Files:** (aucun, validation runtime)

- [ ] **Step 13.1 : Lancer le backend en dev**

```bash
cd backend && uvicorn shugu.app:app --reload --port 8000
```

- [ ] **Step 13.2 : Forcer un refus moderation via WS visitor**

Dans un autre terminal, envoyer un message refusé (ex. texte vide ou trop long via `wscat` ou un test ad-hoc) au `/visitor/ws`.

Alternative : un `pytest` rapide ad-hoc qui appelle `LoggingModeration.check_ingress` avec un texte refusé via la stack live.

- [ ] **Step 13.3 : Vérifier l'INSERT en DB**

```bash
psql "$SHUGU_POSTGRES_DSN" -c "SELECT id, phase, detector, verdict, details, created_at FROM moderation_events ORDER BY created_at DESC LIMIT 5;"
```

Expected: 1+ row(s) récente(s) avec les détails attendus.

- [ ] **Step 13.4 : Tester la route admin via curl**

```bash
# Récupérer un cookie operator valide (selon flow auth projet)
curl -s "http://localhost:8000/api/admin/moderation/events?limit=5" \
  -H "Cookie: shugu_access=<TOKEN>" | jq .
```

Expected: JSON `{"total": N, "items": [...]}` avec au moins 1 item.

- [ ] **Step 13.5 : Si tout OK, pas de commit (juste validation)**

---

## Task 14: Frontend service `adminModerationClient.ts`

**Files:**
- Create: `frontend/src/services/adminModerationClient.ts`

- [ ] **Step 14.1 : Créer le service (mirror de `adminUsersClient.ts`)**

```typescript
/**
 * adminModerationClient — wrappers fetch pour /api/admin/moderation/*.
 *
 * Gated opérateur côté backend (require_operator). Les cookies operator
 * (shugu_access) transitent automatiquement via credentials: "include".
 */

export type ModerationPhase = "ingress" | "egress";

export type ModerationEvent = {
  id: number;
  phase: ModerationPhase;
  detector: string;
  verdict: string;
  reason: string | null;
  identity_kind: string | null;
  ip_hash: string | null;
  text_excerpt: string | null;
  text_len: number | null;
  created_at: string;
};

export type EventListResponse = { total: number; items: ModerationEvent[] };

export type BucketCount = { bucket: string; count: number };

export type ModerationStats = {
  window: "1h" | "24h" | "7d";
  total_refused: number;
  by_detector: Record<string, number>;
  by_phase: Record<ModerationPhase, number>;
  timeline: BucketCount[];
};

export type BanItem = { ip_hash: string; ttl_seconds: number };
export type BanListResponse = { total: number; items: BanItem[] };

export type ListEventsParams = {
  phase?: ModerationPhase;
  detector?: string;
  since?: string;
  limit?: number;
  offset?: number;
};

export class AdminError extends Error {
  constructor(public status: number, public detail: string) {
    super(`[${status}] ${detail}`);
    this.name = "AdminError";
  }
}

async function request<T>(path: string, opts: RequestInit = {}): Promise<T> {
  const resp = await fetch(path, {
    credentials: "include",
    headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
    ...opts,
  });
  const text = await resp.text();
  const payload = text ? (() => {
    try { return JSON.parse(text); } catch { return { detail: text }; }
  })() : {};
  if (!resp.ok) {
    const detail = (payload && payload.detail) || `HTTP ${resp.status}`;
    throw new AdminError(resp.status, String(detail));
  }
  return payload as T;
}

export async function listEvents(params: ListEventsParams = {}): Promise<EventListResponse> {
  const qs = new URLSearchParams();
  if (params.phase) qs.set("phase", params.phase);
  if (params.detector) qs.set("detector", params.detector);
  if (params.since) qs.set("since", params.since);
  if (params.limit !== undefined) qs.set("limit", String(params.limit));
  if (params.offset !== undefined) qs.set("offset", String(params.offset));
  const q = qs.toString();
  return request<EventListResponse>(`/api/admin/moderation/events${q ? `?${q}` : ""}`);
}

export async function getStats(window: "1h" | "24h" | "7d" = "24h"): Promise<ModerationStats> {
  return request<ModerationStats>(`/api/admin/moderation/stats?window=${window}`);
}

export async function listBans(): Promise<BanListResponse> {
  return request<BanListResponse>(`/api/admin/moderation/bans`);
}

export async function clearBan(ip_hash: string): Promise<void> {
  await request<void>(`/api/admin/moderation/bans/${encodeURIComponent(ip_hash)}`, {
    method: "DELETE",
  });
}
```

- [ ] **Step 14.2 : Vérifier que TypeScript compile**

```bash
cd frontend && npx tsc --noEmit 2>&1 | grep -i "moderation\|error" | head -10
```

Expected: 0 erreur sur les nouveaux fichiers.

- [ ] **Step 14.3 : Commit**

```bash
git add frontend/src/services/adminModerationClient.ts
git commit -m "✨ feat(services): adminModerationClient — typed fetch wrapper"
```

---

## Task 15: Refonte `_client.tsx` — KPI + Events + Filtres

**Files:**
- Modify: `frontend/src/app/[username]/admin/moderation/_client.tsx`

- [ ] **Step 15.1 : Réécrire le fichier en entier (le mock est jetable)**

```typescript
"use client";

/**
 * Moderation Hub — dashboard pipeline IA agent.
 *
 * Source de données : table `moderation_events` (refus persistés par
 * LoggingModeration) + bans Redis. Refresh auto toutes les 30 s.
 *
 * Endpoint backend gated `require_operator`.
 */
import { useCallback, useEffect, useMemo, useState } from "react";

import { AdminShell } from "@/components/admin/AdminShell";
import {
  GlassSection,
  GlassRow,
  GlassPill,
  GlassButton,
  GlassTabs,
  GlassModal,
  useToast,
} from "@/features/liquid-glass/primitives";
import { MetricTile } from "@/features/liquid-glass/dataviz";
import {
  listEvents,
  getStats,
  listBans,
  clearBan,
  AdminError,
  type ModerationEvent,
  type ModerationStats,
  type BanItem,
  type ModerationPhase,
} from "@/services/adminModerationClient";

const PAGE_SIZE = 25;
const POLL_MS = 30_000;

type PhaseFilter = "all" | ModerationPhase;
type WindowFilter = "1h" | "24h" | "7d";

function relTime(iso: string): string {
  const d = (Date.now() - new Date(iso).getTime()) / 1000;
  if (d < 60) return `il y a ${Math.floor(d)}s`;
  if (d < 3600) return `il y a ${Math.floor(d / 60)}m`;
  if (d < 86400) return `il y a ${Math.floor(d / 3600)}h`;
  return `il y a ${Math.floor(d / 86400)}j`;
}

function formatTTL(s: number): string {
  if (s < 0) return "permanent";
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  return `${Math.floor(s / 3600)}h`;
}

function detectorTone(d: string): "primary" | "warn" | "danger" | "default" {
  if (d === "profanity" || d === "injection") return "danger";
  if (d === "rate_limit" || d === "ban") return "warn";
  if (d === "length" || d === "egress_length") return "default";
  return "primary";
}

export function ModerationClient() {
  const toast = useToast();
  const [events, setEvents] = useState<ModerationEvent[]>([]);
  const [eventsTotal, setEventsTotal] = useState(0);
  const [stats, setStats] = useState<ModerationStats | null>(null);
  const [bans, setBans] = useState<BanItem[]>([]);
  const [loading, setLoading] = useState(true);

  const [phaseFilter, setPhaseFilter] = useState<PhaseFilter>("all");
  const [detectorFilter, setDetectorFilter] = useState<string | undefined>(undefined);
  const [windowFilter, setWindowFilter] = useState<WindowFilter>("24h");
  const [page, setPage] = useState(0);

  const [pendingClearBan, setPendingClearBan] = useState<BanItem | null>(null);
  const [mutating, setMutating] = useState(false);

  const offset = page * PAGE_SIZE;

  const load = useCallback(async () => {
    try {
      const [evs, sts, bns] = await Promise.all([
        listEvents({
          phase: phaseFilter === "all" ? undefined : phaseFilter,
          detector: detectorFilter,
          limit: PAGE_SIZE,
          offset,
        }),
        getStats(windowFilter),
        listBans(),
      ]);
      setEvents(evs.items);
      setEventsTotal(evs.total);
      setStats(sts);
      setBans(bns.items);
    } catch (err) {
      if (err instanceof AdminError) {
        toast.error("Chargement échoué", { description: err.detail });
      }
    } finally {
      setLoading(false);
    }
  }, [phaseFilter, detectorFilter, windowFilter, offset, toast]);

  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    load();
    const id = setInterval(load, POLL_MS);
    return () => clearInterval(id);
  }, [load]);
  /* eslint-enable react-hooks/set-state-in-effect */

  const topDetector = useMemo(() => {
    if (!stats) return "—";
    const entries = Object.entries(stats.by_detector);
    if (entries.length === 0) return "—";
    return entries.sort((a, b) => b[1] - a[1])[0][0];
  }, [stats]);

  const phaseRatio = useMemo(() => {
    if (!stats) return "—";
    const ig = stats.by_phase.ingress ?? 0;
    const eg = stats.by_phase.egress ?? 0;
    return `${ig} / ${eg}`;
  }, [stats]);

  const detectors = useMemo(() => Object.keys(stats?.by_detector ?? {}), [stats]);

  const onClearBanConfirm = async () => {
    if (!pendingClearBan) return;
    setMutating(true);
    try {
      await clearBan(pendingClearBan.ip_hash);
      toast.success("Ban levé", { description: pendingClearBan.ip_hash.slice(0, 12) });
      setPendingClearBan(null);
      await load();
    } catch (err) {
      const msg = err instanceof AdminError ? err.detail : "erreur réseau";
      toast.error("Échec lever ban", { description: msg });
    } finally {
      setMutating(false);
    }
  };

  return (
    <AdminShell
      active="moderation"
      title="Pipeline Moderation"
      subtitle="Dashboard des refus pipeline IA (ingress/egress) + bans actifs."
      headerRight={
        <GlassPill tone="primary" dot>
          {stats?.total_refused ?? 0} refus {windowFilter}
        </GlassPill>
      }
    >
      <section className="flex flex-col gap-5">
        {/* KPIs */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <MetricTile label={`Refus ${windowFilter}`} value={String(stats?.total_refused ?? 0)} color="#e08efe" />
          <MetricTile label="Top detector" value={topDetector} color="#fd6c9c" />
          <MetricTile label="Ingress / Egress" value={phaseRatio} color="#ffcf6b" />
          <MetricTile label="Bans actifs" value={String(bans.length)} color="#81ecff" />
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-[1fr_320px] gap-5">
          {/* Colonne principale */}
          <section className="flex flex-col gap-5">
            {/* Filtres */}
            <GlassSection title="Filtres" subtitle="Affine la liste des refus affichés.">
              <div className="flex flex-wrap items-center gap-3">
                <GlassTabs
                  value={phaseFilter}
                  onChange={(v) => { setPhaseFilter(v as PhaseFilter); setPage(0); }}
                  tabs={[
                    { value: "all", label: "Tous" },
                    { value: "ingress", label: "Ingress" },
                    { value: "egress", label: "Egress" },
                  ]}
                />
                <GlassTabs
                  value={windowFilter}
                  onChange={(v) => setWindowFilter(v as WindowFilter)}
                  tabs={[
                    { value: "1h", label: "1h" },
                    { value: "24h", label: "24h" },
                    { value: "7d", label: "7j" },
                  ]}
                />
                <div className="flex items-center gap-2">
                  <GlassButton
                    variant={detectorFilter === undefined ? "secondary" : "ghost"}
                    size="sm"
                    onClick={() => { setDetectorFilter(undefined); setPage(0); }}
                  >Tous detectors</GlassButton>
                  {detectors.map((d) => (
                    <GlassButton
                      key={d}
                      variant={detectorFilter === d ? "secondary" : "ghost"}
                      size="sm"
                      onClick={() => { setDetectorFilter(d); setPage(0); }}
                    >{d}</GlassButton>
                  ))}
                </div>
                <div className="ml-auto">
                  <GlassButton variant="ghost" size="sm" onClick={load}>
                    {loading ? "…" : "Rafraîchir"}
                  </GlassButton>
                </div>
              </div>
            </GlassSection>

            {/* Events */}
            <GlassSection
              title="Events refusés"
              subtitle={`${eventsTotal} total · page ${page + 1}/${Math.max(1, Math.ceil(eventsTotal / PAGE_SIZE))}`}
            >
              {loading && events.length === 0 ? (
                <div className="p-4 text-sm opacity-60">chargement…</div>
              ) : events.length === 0 ? (
                <div className="p-4 text-sm opacity-60">aucun refus sur la période</div>
              ) : (
                events.map((e) => (
                  <GlassRow
                    key={e.id}
                    label={
                      <span className="flex items-center gap-2">
                        <GlassPill tone={e.phase === "ingress" ? "secondary" : "tertiary"}>{e.phase}</GlassPill>
                        <GlassPill tone={detectorTone(e.detector)}>{e.detector}</GlassPill>
                        <span className="text-shugu-cream">{e.reason ?? "—"}</span>
                      </span>
                    }
                    sub={
                      <span className="block text-[12px] opacity-65">
                        {relTime(e.created_at)} · &quot;{e.text_excerpt ?? "—"}&quot; ({e.text_len ?? 0} chars)
                      </span>
                    }
                    trailing={
                      <span className="text-[11px] opacity-50">
                        {new Date(e.created_at).toLocaleTimeString("fr-FR")}
                      </span>
                    }
                  />
                ))
              )}

              {eventsTotal > PAGE_SIZE && (
                <div className="flex items-center justify-between gap-3 pt-4">
                  <GlassButton variant="ghost" size="sm"
                    disabled={page === 0}
                    onClick={() => setPage((p) => Math.max(0, p - 1))}>← Précédent</GlassButton>
                  <span className="text-[12px] opacity-60">
                    {offset + 1}–{Math.min(offset + events.length, eventsTotal)} sur {eventsTotal}
                  </span>
                  <GlassButton variant="ghost" size="sm"
                    disabled={offset + events.length >= eventsTotal}
                    onClick={() => setPage((p) => p + 1)}>Suivant →</GlassButton>
                </div>
              )}
            </GlassSection>
          </section>

          {/* Rail droit */}
          <aside className="flex flex-col gap-4">
            <GlassSection title="Stats / detector" subtitle={`Fenêtre ${windowFilter}`}>
              {stats && Object.entries(stats.by_detector).length > 0 ? (
                Object.entries(stats.by_detector)
                  .sort((a, b) => b[1] - a[1])
                  .map(([d, c]) => (
                    <GlassRow
                      key={d}
                      label={<span className="text-shugu-cream">{d}</span>}
                      trailing={<GlassPill tone={detectorTone(d)}>{c}</GlassPill>}
                    />
                  ))
              ) : (
                <div className="p-3 text-sm opacity-60">aucune donnée</div>
              )}
            </GlassSection>

            <GlassSection title="Bans actifs" subtitle={`${bans.length} keys Redis`}>
              {bans.length === 0 ? (
                <div className="p-3 text-sm opacity-60">aucun ban actif</div>
              ) : (
                bans.map((b) => (
                  <GlassRow
                    key={b.ip_hash}
                    label={<span className="font-mono text-shugu-cream">{b.ip_hash.slice(0, 12)}…</span>}
                    sub={`TTL ${formatTTL(b.ttl_seconds)}`}
                    trailing={
                      <GlassButton variant="danger" size="sm" onClick={() => setPendingClearBan(b)}>
                        Lever
                      </GlassButton>
                    }
                  />
                ))
              )}
            </GlassSection>
          </aside>
        </div>
      </section>

      {/* Modal confirmation lever ban */}
      {pendingClearBan && (
        <GlassModal open onClose={() => !mutating && setPendingClearBan(null)}>
          <div className="p-5 space-y-4">
            <h3 className="text-lg font-light text-shugu-cream">
              Lever le ban <code>{pendingClearBan.ip_hash.slice(0, 12)}…</code> ?
            </h3>
            <p className="text-sm opacity-70">
              Le visiteur correspondant pourra à nouveau interagir avec l&apos;agent IA. TTL actuel : {formatTTL(pendingClearBan.ttl_seconds)}.
            </p>
            <div className="flex items-center justify-end gap-2 pt-2">
              <GlassButton variant="ghost" size="sm" onClick={() => setPendingClearBan(null)} disabled={mutating}>
                Annuler
              </GlassButton>
              <GlassButton variant="danger" size="sm" onClick={onClearBanConfirm} disabled={mutating}>
                {mutating ? "…" : "Lever le ban"}
              </GlassButton>
            </div>
          </div>
        </GlassModal>
      )}
    </AdminShell>
  );
}
```

- [ ] **Step 15.2 : Vérifier TypeScript + ESLint**

```bash
cd frontend && npx tsc --noEmit 2>&1 | grep -i moderation | head -10
cd frontend && npx eslint src/app/\[username\]/admin/moderation/_client.tsx
```

Expected: 0 erreur.

- [ ] **Step 15.3 : Commit**

```bash
git add frontend/src/app/\[username\]/admin/moderation/_client.tsx
git commit -m "✨ feat(admin/moderation): refonte UI — branchée pipeline IA + polling 30s + clear ban modal"
```

---

## Task 16: Smoke test E2E

**Files:** (validation runtime uniquement)

- [ ] **Step 16.1 : Lancer backend + frontend**

```bash
# Terminal 1
cd backend && uvicorn shugu.app:app --reload --port 8000

# Terminal 2
cd frontend && pnpm dev
```

- [ ] **Step 16.2 : Forcer 5-10 refus moderation**

Via le path visitor WS, envoyer des messages refusés (texte vide, texte trop long, profanity, injection patterns). Vérifier en parallèle :

```bash
psql "$SHUGU_POSTGRES_DSN" -c "SELECT COUNT(*) FROM moderation_events WHERE created_at > NOW() - INTERVAL '5 minutes';"
```

Expected: ≥ 5 rows.

- [ ] **Step 16.3 : Charger `/[username]/admin/moderation`**

Ouvrir `http://localhost:3000/<test-user>/admin/moderation` connecté en operator. Vérifier visuellement :
- KPI band affiche `total_refused`, `top detector`, `ingress/egress`, `bans actifs`
- Section "Events refusés" liste les 5-10 events récents
- Section "Stats / detector" affiche les compteurs par detector
- Section "Bans actifs" liste les bans Redis présents

- [ ] **Step 16.4 : Tester le polling 30s**

Forcer 1 refus supplémentaire pendant que la page est ouverte. Au prochain tick 30s, le compteur Refus doit augmenter sans refresh manuel.

- [ ] **Step 16.5 : Tester le clear ban**

Si au moins 1 ban est présent dans la section "Bans actifs", cliquer "Lever" → modal s'ouvre → "Lever le ban" → toast success + key Redis disparaît.

```bash
redis-cli KEYS 'ban:*' | wc -l   # avant
# … clic Lever …
redis-cli KEYS 'ban:*' | wc -l   # après → -1
```

- [ ] **Step 16.6 : Vérifier la console browser (pas d'erreur)**

DevTools → Console → 0 erreur réseau ou JS pendant 1 minute de polling.

---

## Task 17: PR finale

**Files:** (workflow git)

- [ ] **Step 17.1 : Vérifier l'état git**

```bash
git status
git log --oneline origin/main..HEAD
```

Expected: ~15-17 commits, working tree clean.

- [ ] **Step 17.2 : Rebase sur main si nécessaire**

```bash
git fetch origin
git rebase origin/main
```

Résoudre les conflits si nécessaire (peu probable vu que tous les nouveaux fichiers).

- [ ] **Step 17.3 : Lancer la suite complète une dernière fois**

```bash
cd backend && pytest tests/ --tb=short
cd frontend && npx tsc --noEmit && npx eslint src/
```

Expected: 100 % pass.

- [ ] **Step 17.4 : Push + créer PR**

```bash
git push -u origin claude/crazy-sutherland-96ea1c
gh pr create --title "✨ feat(admin/moderation): pivot Moderation Hub → dashboard pipeline IA" --body "$(cat <<'EOF'
## Summary

Remplace la page mockée `/[username]/admin/moderation` par un dashboard branché sur le pipeline IA agent existant (`BasicModeration` → `ModerationEvent`).

**Architecture** : Decorator pattern (`LoggingModeration`) wrappe `BasicModeration` et persiste les verdicts refusés en DB. 4 routes admin REST gated `require_operator`. Frontend service `fetch`-based + UI refondue sur primitives `liquid-glass`.

**Décisions clés** :
- Log refusés uniquement (volume ~5% trafic, totaux via `MetricsRecorder` existant)
- Synchrone hot path + fail-open (DB down n'interrompt jamais le pipeline)
- Sécurité : `require_operator` + regex `^[a-f0-9]{64}$` sur `ip_hash` (anti-injection wildcard)
- TDD strict, coverage ≥ 90 % sur 3 nouveaux modules backend

Spec complet : `docs/superpowers/specs/2026-05-10-moderation-hub-pivot-design.md`
Plan complet : `docs/superpowers/plans/2026-05-10-moderation-hub-pivot-plan.md`

## Test plan

- [x] `pytest backend/tests/unit/test_moderation_logging.py` (6 tests)
- [x] `pytest backend/tests/integration/test_admin_moderation_routes.py` (12 tests)
- [x] Coverage ≥ 90% sur `adapters/moderation_logging.py`, `services/moderation_events.py`, `routes/admin_moderation.py`
- [x] Smoke test backend : forcer refus → INSERT DB vérifié
- [x] Smoke test E2E : page UI charge, polling 30s, clear ban fonctionnel
- [x] `tsc --noEmit` + `eslint` propres

## Sub-projects suivants

1/4 done. Suivants : Analytics (B), Schedule (C), Community (D) — voir spec § 15 pour template.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 17.5 : Retourner l'URL de la PR**

L'URL est affichée par `gh pr create`. La copier dans le résumé final pour l'utilisateur.

---

## Self-Review (effectuée avant handoff)

### 1. Spec coverage

| Spec section | Tâche(s) qui implémente |
|---|---|
| § 3.1 Decorator pattern | Task 3, Task 12 |
| § 3.2 Modules backend | Tasks 3, 6, 8-10 |
| § 3.3 Modules frontend | Tasks 14, 15 |
| § 4 Data model + JSONB schema | Tasks 3, 5 (test `details` content) |
| § 4.3 Migration Alembic | Task 0 |
| § 5 API REST 4 routes | Tasks 8, 9, 10 |
| § 6.1 `_persist()` body | Task 3 |
| § 6.2 Service queries | Tasks 6, 7 |
| § 6.3 Wiring app.py | Task 12 |
| § 7 UI sections + polling | Task 15 |
| § 8 Tests TDD + coverage | Tasks 2-7, 11 |
| § 9 Error handling | Task 5 (fail-open), Tasks 8-10 (HTTP 4xx/5xx) |
| § 10 Sécurité (operator + regex) | Tasks 10 (regex), 11 (non-régression) |
| § 12 Rollout smoke tests | Tasks 13, 16 |
| § 14 Plan high-level | matche les 17 tâches |

### 2. Placeholders

- ✅ Pas de "TBD"/"TODO" dans les steps
- ✅ Code complet dans chaque step (`Step N.M`)
- ⚠️ Task 1.4 (`operator_cookie`) et Task 10.3 (`_get_redis`) ont des notes "⚠️ adapter selon le projet" — ce sont des hooks où la doc projet doit être consultée. Les hooks sont explicites avec où chercher (`backend/shugu/auth/user_tokens.py`, `backend/shugu/app.py` startup event). Acceptable car ruflo doit lire avant d'écrire.

### 3. Type consistency

- ✅ `ModerationEvent` (model) ↔ `EventListItem` (Pydantic) ↔ `ModerationEvent` (TS) : champs alignés
- ✅ `ModerationVerdict` champs `allowed/reason/detector` identiques partout
- ✅ Names des routes : `/api/admin/moderation/events|stats|bans` cohérents entre tests, route, service TS
- ✅ `BanItem.ttl_seconds` int partout
- ✅ `BucketCount.bucket` datetime côté Python → string ISO côté TS

---

## Execution handoff

Plan complet et committé. Ce plan est **input direct pour `ruflo-autopilot:autopilot-coordinator`** — l'utilisateur a explicitement demandé cette voie de délégation (cf. mémoire `feedback_ruflo_workflow`).

Le prompt ruflo correspondant sera préparé par Claude après validation de ce plan par l'utilisateur.
