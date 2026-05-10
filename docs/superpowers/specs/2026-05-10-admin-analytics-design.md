# Admin Analytics — Dashboard prod-ready

**Date :** 2026-05-10
**Auteur :** Claude (en autonomie déléguée, décisions tranchées avec rationale visible)
**Statut :** Spec à valider par Sylvain — implémentation déléguée à `ruflo-autopilot` après gate
**Sub-project :** 2/4 (suit Moderation A — en cours par ruflo)

---

## 0. Quality Contract (non-négociable, hérité directive utilisateur)

- **Prod-ready uniquement** : aucun placeholder, aucun stub, aucun `TODO` dans le code livré.
- **Tests réels** : zéro `@pytest.mark.skip`, zéro `@xfail`, zéro test bouchon. Tous les tests valident le code réel et passent.
- **UI sans `Coming soon`** : si une section est dans ce spec, elle est implémentée fonctionnellement.
- **TDD strict** : rouge → vert → commit, jamais modifier un test pour passer (mémoire `feedback_workflow_discipline`).
- **Coverage ≥ 90 %** sur les 2 nouveaux modules backend (`services/analytics_queries.py`, `routes/admin_analytics.py`).

---

## 1. Contexte et problème

`/[username]/admin/analytics` est aujourd'hui une page mockée (`frontend/src/app/[username]/admin/analytics/_client.tsx`, 174 lignes statiques). Elle doit afficher de vraies metriques business issues du pipeline IA agent.

**Asset existant :** les models `Visitor`, `Performance`, `UserAccount`, `UserSession` sont **déjà persistés** par le pipeline runtime (visitor_ws, viewer routes, auth flow). Aucune nouvelle ingestion à coder. Le sub-project consiste à :

1. Écrire des **queries SQL agrégées** sur ces tables.
2. Exposer des **routes admin REST** gated `require_operator`.
3. **Refondre l'UI** mockée vers un dashboard branché.

Asymétrie avec Moderation A : **pas de decorator runtime** à wirer (les données arrivent déjà en DB). C'est un projet read-only pure.

---

## 2. Scope (γ Vue complète tranchée)

### Inclus

- **KPI band** : 4 MetricTile avec delta vs période précédente (`↑ 12 % vs J-1`)
- **Filtre fenêtre temporelle** : `1h / 24h / 7d / 30d`
- **Filtre dimensions** : `author_role`, `route`
- **Liste paginée des `Performance`** (25/page) avec détail click → input/output text
- **Stats panneau droit** : top 5 routes, top 5 visiteurs par `msg_count`, distribution `author_role`
- **Heatmap horaire** : 24 colonnes (hour-of-day), bar chart, sur la fenêtre active
- **Funnel conversion** : visitor → member → VIP avec 2 ratios
- **Bans actifs** : KPI count (DB `Visitor.ban_until` + Redis `ban:*`)
- **Export CSV** : route `GET /export?type=performances&since=...`, limit 10k rows, `StreamingResponse`
- **Polling auto 60s** (vs 30s Moderation A — analytics moins time-critical)

### Exclus

- Cohort analysis / retention curves (YAGNI, à itérer si besoin)
- Real-time websocket push (polling 60s suffit pour MVP)
- Custom date range picker (les 4 tabs `1h/24h/7d/30d` couvrent les besoins ops)
- Charts complexes (line graph multi-séries) — bar charts + MetricTile suffisent
- Tableaux pivot / aggrégations custom utilisateur (out of MVP)

---

## 3. Architecture

### 3.1. Pattern read-only, sans decorator

```
Pipeline runtime (visitor_ws, viewer, auth)
        │
        ▼
  Visitor / Performance / UserAccount / UserSession   ← persistés
        │
        ▼
  services/analytics_queries.py    ← nouveau, queries SQL agrégées
        │
        ▼
  routes/admin_analytics.py         ← nouveau, routes /api/admin/analytics/*
        │
        ▼
  Frontend service + UI refondue
```

**Pas de decorator, pas de wiring app.py logique métier**. Seule modification `app.py` : `include_router(admin_analytics_router)`.

### 3.2. Modules backend (2 nouveaux + 1 modifié)

| Fichier | Rôle |
|---|---|
| `backend/shugu/services/analytics_queries.py` *(nouveau)* | Queries SQL agrégées (KPIs, timeline, top-N, heatmap, funnel, ban count) |
| `backend/shugu/routes/admin_analytics.py` *(nouveau)* | Routes `/api/admin/analytics/*` |
| `backend/shugu/app.py` *(modifié, 1 ligne)* | `app.include_router(admin_analytics_router)` |
| `backend/tests/integration/test_admin_analytics_routes.py` *(nouveau)* | Tests intégration routes + queries |

### 3.3. Modules frontend (1 nouveau + 1 refondu)

| Fichier | Rôle |
|---|---|
| `frontend/src/services/adminAnalyticsClient.ts` *(nouveau)* | Wrapper `fetch` typé sur `/api/admin/analytics/*` |
| `frontend/src/app/[username]/admin/analytics/_client.tsx` *(refondu)* | Mock → UI branchée |

### 3.4. Modules NON touchés (préservation)

- `backend/shugu/db/models.py` — schemas existants suffisent, aucune migration.
- `backend/shugu/routes/visitor_ws.py`, `viewer.py`, etc. — producteurs de données, hors scope.
- `backend/shugu/adapters/moderation_*` — distinct du sub-project A.

---

## 4. Data model (lecture seule sur l'existant)

### 4.1. Tables utilisées

```python
# Source primaire — performances
class Performance:
    performance_id: str(26) PK         # ULID
    author_role: str(16)               # 'visitor' | 'member' | 'vip' | 'operator'
    author_ip_hash: str(64) nullable
    route: str(32)                     # 'visitor_ws' | 'viewer' | ...
    input_text: text
    output_text: text nullable
    duration_ms: int nullable
    moderation_ingress: JSONB nullable # verdict ingress de la perf
    moderation_egress: JSONB nullable  # verdict egress de la perf
    created_at: timestamptz INDEX
    played_at: timestamptz nullable
    # Index : idx_perf_created (created_at), idx_perf_author (author_ip_hash, created_at)

# Source secondaire — visiteurs uniques
class Visitor:
    ip_hash: str(64) PK
    first_seen: timestamptz
    last_seen: timestamptz
    msg_count: int                     # nb messages cumulés
    ban_until: timestamptz nullable    # ban DB long terme (≠ Redis TTL)
    ban_reason: text nullable

# Source comptes
class UserAccount:
    id: str(26) PK
    username: str(32)
    email: str(254)
    email_verified_at: timestamptz nullable    # → distingue "pending" vs "member"
    vip_since: timestamptz nullable             # → distingue "member" vs "vip"
    vip_until: timestamptz nullable
    is_active: bool
    created_at: timestamptz
    last_seen_at: timestamptz nullable

```

> `UserSession` (table existante) n'est PAS utilisée dans ce sub-project — toutes les metriques peuvent être calculées depuis `Performance`/`Visitor`/`UserAccount` uniquement. Si un besoin "membres actuellement connectés" émerge, ajouter une route `/sessions/active` plus tard.

### 4.2. Aucune nouvelle table, aucune migration Alembic

Le sub-project est **100 % read-only** sur l'existant.

---

## 5. API REST

Toutes routes gated `Depends(require_operator)`. Pydantic schemas explicites. Erreurs typées `AdminError` côté frontend.

### `GET /api/admin/analytics/kpis`

Query : `window` ∈ `1h|24h|7d|30d`, default `24h`.

```python
class KPIsResponse(BaseModel):
    window: Literal["1h", "24h", "7d", "30d"]
    visitors_unique: int                 # COUNT(DISTINCT ip_hash) sur Performance.author_ip_hash dans window
    visitors_unique_delta_pct: float     # vs période précédente de même taille
    performances_total: int              # COUNT(Performance) dans window
    performances_total_delta_pct: float
    avg_duration_ms: float
    avg_duration_ms_delta_pct: float
    moderation_refused_rate: float       # COUNT(WHERE moderation_ingress IS NOT NULL OR moderation_egress IS NOT NULL) / total
    moderation_refused_rate_delta_pct: float
    bans_active_count: int               # DB (Visitor.ban_until > NOW()) + Redis (SCAN ban:*) sommés, dédupliqués sur ip_hash
```

### `GET /api/admin/analytics/timeline`

Query : `window`. Buckets : 5 min (1h), 1 h (24h), 1 jour (7d), 1 jour (30d).

```python
class TimelineBucket(BaseModel):
    bucket: datetime
    performances: int
    visitors_unique: int

class TimelineResponse(BaseModel):
    window: Literal["1h", "24h", "7d", "30d"]
    buckets: list[TimelineBucket]
```

### `GET /api/admin/analytics/top-routes`

Query : `window`, `limit` ∈ [1, 20], default 5.

```python
class TopRoute(BaseModel):
    route: str
    count: int
    pct: float                           # part du total

class TopRoutesResponse(BaseModel):
    window: str
    total: int
    items: list[TopRoute]
```

### `GET /api/admin/analytics/top-visitors`

Query : `window`, `limit` (default 5).

```python
class TopVisitor(BaseModel):
    ip_hash_truncated: str               # 12 premiers chars, jamais le full hash dans response
    msg_count_window: int                # nb dans la fenêtre, pas total Visitor.msg_count
    first_seen: datetime
    last_seen: datetime
    is_banned: bool

class TopVisitorsResponse(BaseModel):
    items: list[TopVisitor]
```

### `GET /api/admin/analytics/heatmap`

Query : `window`. Toujours retourne 24 buckets (hour 0..23), même si window=1h (les heures hors window auront `count=0`).

```python
class HeatmapBucket(BaseModel):
    hour: int                            # 0..23 (UTC)
    count: int

class HeatmapResponse(BaseModel):
    window: str
    buckets: list[HeatmapBucket]         # toujours 24 entries
    max_count: int                       # pour normaliser l'affichage côté UI
```

### `GET /api/admin/analytics/funnel`

```python
class FunnelResponse(BaseModel):
    visitors_unique_total: int           # COUNT(DISTINCT ip_hash) ALL TIME sur Visitor
    members_total: int                   # COUNT(UserAccount WHERE email_verified_at IS NOT NULL)
    vips_total: int                      # COUNT(UserAccount WHERE vip_since IS NOT NULL AND (vip_until IS NULL OR vip_until > NOW()))
    visitor_to_member_pct: float         # members / visitors_unique
    member_to_vip_pct: float             # vips / members
```

### `GET /api/admin/analytics/performances`

Liste paginée filtrée des performances.

Query : `author_role?`, `route?`, `since?`, `limit` (≤ 200, default 25), `offset`.

```python
class PerformanceListItem(BaseModel):
    performance_id: str
    author_role: str
    author_ip_hash_truncated: Optional[str]
    route: str
    duration_ms: Optional[int]
    has_moderation_refusal: bool         # moderation_ingress != NULL OR moderation_egress != NULL
    created_at: datetime
    played_at: Optional[datetime]
    input_text_excerpt: str              # input_text[:120]
    output_text_excerpt: Optional[str]   # output_text[:120] if not null

class PerformanceListResponse(BaseModel):
    total: int
    items: list[PerformanceListItem]
```

### `GET /api/admin/analytics/performances/{performance_id}`

Détail d'une perf (modale au click sur la liste).

```python
class PerformanceDetail(BaseModel):
    performance_id: str
    author_role: str
    author_ip_hash_truncated: Optional[str]
    route: str
    duration_ms: Optional[int]
    input_text: str                      # complet
    output_text: Optional[str]           # complet
    moderation_ingress: Optional[dict]
    moderation_egress: Optional[dict]
    created_at: datetime
    played_at: Optional[datetime]
```

### `GET /api/admin/analytics/export`

Query : `type=performances` (seul type supporté MVP), `since` ISO datetime, `until` ISO datetime, `author_role?`, `route?`.

Retourne `StreamingResponse` `text/csv`. **Hard limit : 10 000 rows**. Si la query dépasse → `HTTPException 413 Payload Too Large` avec suggestion de réduire la fenêtre.

CSV columns : `performance_id,author_role,author_ip_hash_truncated,route,duration_ms,has_moderation_refusal,created_at,played_at,input_text_excerpt,output_text_excerpt`.

---

## 6. Logique métier critique

### 6.1. Calcul des deltas de période

Pour `window=24h`, le delta compare `[now-24h, now]` vs `[now-48h, now-24h]`. Implémentation :

```python
async def compute_kpi_with_delta(session, *, window):
    now = datetime.now(timezone.utc)
    delta = _WINDOW_DELTA[window]
    current_start = now - delta
    previous_start = now - 2 * delta

    current = await _query_aggregates(session, since=current_start, until=now)
    previous = await _query_aggregates(session, since=previous_start, until=current_start)

    def pct_delta(curr, prev):
        if prev == 0:
            return 0.0 if curr == 0 else 100.0
        return ((curr - prev) / prev) * 100.0

    return {
        "visitors_unique": current["visitors"],
        "visitors_unique_delta_pct": pct_delta(current["visitors"], previous["visitors"]),
        # ... idem pour autres metrics
    }
```

### 6.2. Heatmap horaire UTC

```python
async def heatmap_hour_of_day(session, *, window):
    since = datetime.now(timezone.utc) - _WINDOW_DELTA[window]
    rows = await session.execute(
        select(
            func.extract("hour", Performance.created_at).label("hour"),
            func.count().label("count"),
        )
        .where(Performance.created_at >= since)
        .group_by("hour")
    )
    rows_by_hour = {int(r.hour): int(r.count) for r in rows}
    buckets = [{"hour": h, "count": rows_by_hour.get(h, 0)} for h in range(24)]
    max_count = max((b["count"] for b in buckets), default=0)
    return {"window": window, "buckets": buckets, "max_count": max_count}
```

> Note : `EXTRACT(hour FROM ts)` retourne en UTC (timezone-aware column). L'utilisateur final voit l'heure UTC. Pour afficher en heure locale, transformation côté frontend possible plus tard.

### 6.3. Funnel — calcul ratios

```python
async def funnel(session):
    visitors_unique = (await session.execute(select(func.count(Visitor.ip_hash)))).scalar_one()
    members = (await session.execute(
        select(func.count(UserAccount.id)).where(UserAccount.email_verified_at.is_not(None))
    )).scalar_one()
    now = datetime.now(timezone.utc)
    vips = (await session.execute(
        select(func.count(UserAccount.id)).where(
            UserAccount.vip_since.is_not(None),
            (UserAccount.vip_until.is_(None)) | (UserAccount.vip_until > now),
        )
    )).scalar_one()
    return {
        "visitors_unique_total": int(visitors_unique),
        "members_total": int(members),
        "vips_total": int(vips),
        "visitor_to_member_pct": (members / visitors_unique * 100) if visitors_unique else 0.0,
        "member_to_vip_pct": (vips / members * 100) if members else 0.0,
    }
```

### 6.4. Bans actifs (DB + Redis dédupliqué)

```python
async def count_active_bans(session, redis):
    db_count_q = select(func.count(Visitor.ip_hash)).where(Visitor.ban_until > func.now())
    db_set_q = select(Visitor.ip_hash).where(Visitor.ban_until > func.now())
    db_hashes = {row for (row,) in await session.execute(db_set_q)}

    redis_hashes = set()
    async for key in redis.scan_iter(match="ban:*"):
        ip_hash = key.decode("utf-8") if isinstance(key, bytes) else key
        redis_hashes.add(ip_hash.removeprefix("ban:"))

    return len(db_hashes | redis_hashes)
```

### 6.5. Export CSV avec hard limit

```python
async def stream_csv(session, *, filters):
    # Compter d'abord
    count = (await session.execute(_build_count_query(filters))).scalar_one()
    if count > 10_000:
        raise HTTPException(
            status_code=413,
            detail=f"Export trop grand ({count} rows). Réduire la fenêtre — limite 10 000.",
        )
    # Stream rows
    async def generator():
        yield "performance_id,author_role,...\n"
        async for row in await session.stream(_build_select_query(filters)):
            yield _row_to_csv(row)
    return StreamingResponse(generator(), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=performances.csv"})
```

---

## 7. UI / Frontend

### 7.1. Layout

```
AdminShell active="analytics" title="Analytics" subtitle="..."
├── Header right : pill "{visitors_unique} visiteurs {window}"
├── KPI band (4 MetricTile avec delta sub-text)
│   [Visiteurs uniques↑12%] [Performances↑3%] [Durée moy↓5%] [Bans actifs]
├── Window tabs (1h | 24h | 7d | 30d) + Refresh manuel button
├── Grid 2 colonnes (lg:[1fr_320px])
│   ├── Colonne principale
│   │   ├── GlassSection "Timeline" — bars verticales (Performances + Visiteurs unique)
│   │   ├── GlassSection "Heatmap horaire" — 24 colonnes hour-of-day
│   │   ├── GlassSection "Filtres" — author_role + route dropdowns
│   │   ├── GlassSection "Performances" (paginée 25/page)
│   │   │   GlassRow per perf : role pill + route pill + duration + excerpt
│   │   │   Click row → GlassModal détail (input/output text + moderation JSON)
│   │   └── Bouton "Exporter CSV" → trigger /api/admin/analytics/export
│   └── Rail droit
│       ├── GlassSection "Top routes" — top 5 bars
│       ├── GlassSection "Top visiteurs" — 5 cards (ip_hash truncate + msg_count + ban pill)
│       └── GlassSection "Funnel"
│           visitors_total → members (X %) → vips (Y %)
```

### 7.2. Composants réutilisés (déjà existants)

- `AdminShell`, `MetricTile`, `GlassSection`, `GlassRow`, `GlassPill`, `GlassButton`, `GlassTabs`, `GlassInput`, `GlassModal`, `useToast` — tous dispo.
- **Aucun nouveau composant à créer**.

### 7.3. Polling 60s unifié

```typescript
useEffect(() => {
  const tick = () => Promise.all([
    loadKpis(), loadTimeline(), loadTopRoutes(),
    loadTopVisitors(), loadHeatmap(), loadFunnel(),
    loadPerformances(),
  ]);
  tick();
  const id = setInterval(tick, 60_000);
  return () => clearInterval(id);
}, [window, filters, page]);
```

7 fetches en parallèle / 60s = pression négligeable sur le backend (la plupart des queries sont indexées sur `created_at`).

### 7.4. PII côté frontend

- `username` member affiché en clair (operator a déjà cette info via `/admin/users`).
- **`email` jamais affiché dans Analytics** — la route backend ne retourne pas d'email du tout. Opérateur passe par `/admin/users` pour identifier un member par email.
- `ip_hash` truncate 12 chars (cohérent avec Moderation A) — backend retourne déjà `ip_hash_truncated`, le frontend l'affiche tel quel sans démasquage.

> **Décision PII MVP** : aucun email dans Analytics, aucun ip_hash complet. Si le besoin "qui est ce visitor anonyme ?" émerge, ajouter une route admin de search dans `/admin/users` plus tard — pas dans Analytics.

---

## 8. Tests (TDD strict, prod-ready, pas de skip)

### 8.1. Fixtures partagées (réutilise celles de Moderation A)

`backend/tests/conftest.py` aura déjà `db_session`, `operator_cookie`, `api_client`, `redis_client` (créées par Moderation A en cours par ruflo). On **réutilise** ces fixtures.

Ajouter une fixture spécifique :

```python
@pytest_asyncio.fixture
async def seed_performances(db_session):
    """Insère 50 Performance variées sur 7 jours pour tests analytics."""
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
            "created_at": now - timedelta(hours=i * 3),  # spread over 6 jours
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
        rows.append({
            "id": str(ULID()), "username": f"pending{i}", "email": f"p{i}@ex.com",
            "password_hash": "x" * 60, "email_verified_at": None, "is_active": True,
            "created_at": now,
        })
    for i in range(7):
        rows.append({
            "id": str(ULID()), "username": f"member{i}", "email": f"m{i}@ex.com",
            "password_hash": "x" * 60, "email_verified_at": now, "is_active": True,
            "created_at": now,
        })
    for i in range(3):
        rows.append({
            "id": str(ULID()), "username": f"vip{i}", "email": f"v{i}@ex.com",
            "password_hash": "x" * 60, "email_verified_at": now, "vip_since": now,
            "is_active": True, "created_at": now,
        })
    await db_session.execute(insert(UserAccount), rows)
    await db_session.commit()
    return rows
```

### 8.2. Liste des tests (intégration uniquement — les queries sont l'unité naturelle)

`backend/tests/integration/test_admin_analytics_routes.py` :

- `test_kpis_returns_zero_when_no_data`
- `test_kpis_computes_visitors_unique` (compte les DISTINCT)
- `test_kpis_computes_performances_total`
- `test_kpis_computes_avg_duration`
- `test_kpis_computes_moderation_refused_rate`
- `test_kpis_computes_bans_active_count_db_only`
- `test_kpis_computes_bans_active_count_redis_only`
- `test_kpis_computes_bans_active_count_deduplicates_db_redis_overlap`
- `test_kpis_delta_pct_handles_zero_previous`
- `test_kpis_window_validation` (`invalid` → 422)
- `test_kpis_requires_operator` (401)
- `test_kpis_rejects_member_cookie` (sécurité)

- `test_timeline_24h_bucket_size_1h` (24 buckets)
- `test_timeline_7d_bucket_size_1d` (7 buckets)
- `test_timeline_includes_visitors_unique_per_bucket`

- `test_top_routes_groups_by_route_and_orders_desc`
- `test_top_routes_respects_limit_param`
- `test_top_routes_computes_pct_of_total`

- `test_top_visitors_returns_truncated_ip_hash` (vérifier que le full hash N'EST PAS dans la response)
- `test_top_visitors_orders_by_msg_count_in_window`
- `test_top_visitors_marks_banned_with_flag`

- `test_heatmap_returns_always_24_buckets` (même quand vide)
- `test_heatmap_groups_by_hour_of_day`
- `test_heatmap_max_count_for_normalization`

- `test_funnel_computes_3_levels`
- `test_funnel_ratios_handle_zero_visitors`
- `test_funnel_excludes_unverified_from_members`
- `test_funnel_excludes_expired_vips`

- `test_performances_list_returns_paginated`
- `test_performances_list_filters_by_author_role`
- `test_performances_list_filters_by_route`
- `test_performances_list_excerpt_truncated_at_120_chars`
- `test_performance_detail_returns_full_text`
- `test_performance_detail_404_unknown_id`

- `test_export_csv_returns_streaming_response`
- `test_export_csv_413_when_over_10k_rows` (mock count returns > 10000)
- `test_export_csv_includes_only_filtered_rows`
- `test_export_csv_requires_operator`

**Total : 36 tests**, tous prod-ready, tous activés (pas de skip).

### 8.3. Coverage cible

`pytest --cov=shugu.services.analytics_queries --cov=shugu.routes.admin_analytics --cov-report=term-missing` ≥ **90 %**.

---

## 9. Error handling

| Couche | Erreur | Comportement |
|---|---|---|
| `analytics_queries.*` | DB query échoue (timeout, connexion) | Laisser remonter → route attrape → HTTPException 500 |
| `analytics_queries.count_active_bans` | Redis down | Logger warning + retourner uniquement le count DB (graceful degrade) |
| `routes/admin_analytics.export` | Count > 10 000 rows | HTTPException 413 avec suggestion |
| `routes/admin_analytics.*` | `window` invalide | HTTPException 422 (Pydantic auto) |
| `routes/admin_analytics.performance_detail` | `performance_id` unknown | HTTPException 404 |
| Frontend | `AdminError` 500 / 503 | `toast.error(detail)` |
| Frontend | polling tick échoue | Silent retry au prochain tick |
| Frontend | export 413 | `toast.warn("Export trop grand", { description: "Réduisez la fenêtre"})` |

Le **graceful degrade Redis** sur `count_active_bans` est volontaire : analytics ne doit jamais cacher de KPIs si Redis a un blip. On affiche "bans DB only" et on log. Le sub-project A reste source de vérité pour la gestion Redis ; analytics expose juste un compteur.

---

## 10. Sécurité

- **Routes `require_operator`** strict. Test de non-régression `test_kpis_rejects_member_cookie`.
- **PII** :
  - `ip_hash` truncate 12 chars dans toutes les responses (jamais le hash complet ne leak)
  - **`email` jamais retourné** par les routes analytics — aucun champ `email` dans les Pydantic schemas. Si operator veut connaître l'email d'un member, passer par `/admin/users`. Volontaire RGPD-conservative : analytics = metrics anonymisées par défaut.
  - `username` ok en clair quand applicable (déjà visible dans `/admin/users`)
- **Export CSV** : hard limit 10 000 rows ; structlog `audit.analytics_export` à chaque appel (qui, quand, quels filtres).
- **Validation Pydantic stricte** sur `since/until` (ISO datetime obligatoire, refus si `since > until`).
- **CSRF** : cookies sameSite (pattern existant `admin/users`).

---

## 11. Observability

- `structlog` info `admin_analytics.kpis_computed`, `admin_analytics.export_streamed` avec count + duration_ms.
- Pas de nouvelle metric Prometheus pour MVP (les data sources `Performance`/`Visitor` ont déjà leurs counters via `MetricsRecorder` au moment d'insertion).
- **Audit trail export CSV** : structlog `audit.analytics_export operator_id=... since=... rows=...`. Permet à un audit RGPD futur de tracer les downloads de données utilisateur.

---

## 12. Rollout

- **Pas de migration Alembic** (read-only sur l'existant)
- **Pas de feature flag** (pages admin sont déjà gated par `require_operator`)
- **Pas de wiring critique app.py** (juste `include_router`)
- **Smoke tests post-merge** :
  1. Charger `/[username]/admin/analytics` → KPIs s'affichent avec données réelles
  2. Changer window 24h → 7d → buckets timeline changent correctement
  3. Click sur 1 Performance → modal détail s'ouvre avec input/output complets
  4. Click "Exporter CSV" → fichier téléchargé, ouvrable Excel/LibreOffice, X rows attendues

---

## 13. Trade-offs documentés

- **Heatmap UTC seul** : pas de conversion timezone utilisateur. Acceptable car operator = 1 personne ; ajouter `local_tz` query param si Sylvain veut.
- **Pas de cohort analysis** : YAGNI. `Visitor.first_seen` permet un calcul de retention mais on attend que le besoin émerge.
- **Pas de comparaison fine "vs week-end"** : seul `delta vs période précédente de même taille` est implémenté. Suffisant pour MVP.
- **Email masqué partout** : decision RGPD-conservative. Trade-off perceptible si operator veut comprendre "qui est ce member" sans cliquer `/admin/users`.
- **Export CSV limit 10 000** : suffisant pour 30 jours de stream. Au-delà, pagination ou export async via job queue (out of scope MVP).
- **Heatmap par hour-of-day uniquement** : pas de "lundi vs mardi" (day-of-week). Décision YAGNI car streamer IA = pas pattern hebdomadaire évident.

---

## 14. Plan d'implémentation (haut niveau)

Le plan détaillé sera écrit dans `docs/superpowers/plans/2026-05-10-admin-analytics-plan.md` après validation de ce spec.

**Étapes high-level :**

0. **Préalable** : vérifier que les fixtures de Moderation A sont mergées (`db_session`, `operator_cookie`, `api_client`). Si A pas encore mergée : extraire ces fixtures dans une PR conftest indépendante avant analytics.
1. **Service `analytics_queries.py`** TDD : 1 test par query (`kpis`, `timeline`, `top_routes`, `top_visitors`, `heatmap`, `funnel`, `performances_list`, `performance_detail`, `bans_count`, `export_stream`).
2. **Route `admin_analytics.py`** TDD : 1 route par endpoint, schemas Pydantic, gating operator, validation params.
3. **Test sécurité non-régression** (reject member_cookie sur toutes les routes).
4. **Wiring `app.py`** (1 ligne `include_router`).
5. **Frontend service `adminAnalyticsClient.ts`** mirror types.
6. **Frontend refonte `_client.tsx`** avec layout § 7.1 + polling 60s.
7. **Smoke tests manuels** post-build.
8. **PR finale**.

---

## 15. Template Compatibility (héritage golden path)

Ce spec suit la structure du golden path Moderation A pour faciliter la délégation ruflo :

- Mêmes sections numérotées
- Mêmes patterns Pydantic / `request<T>` / `AdminError`
- Mêmes primitives `liquid-glass`
- Même contrat de qualité TDD strict, coverage 90%, pas de skip

Différences sub-project B vs A :
- **Pas de decorator** runtime — A wrap `BasicModeration`, B est read-only
- **Pas de migration** — A skip Task 0, B également
- **8 routes vs 4** — B est plus riche en endpoints
- **Polling 60s vs 30s** — B est moins time-critical

---

## 16. Références

- Golden path : [Moderation Hub Pivot design](2026-05-10-moderation-hub-pivot-design.md)
- Template B/C/D : [Admin Pages Template](2026-05-10-admin-pages-template-bcd.md) (suit cette structure)
- Pattern référent backend : `backend/shugu/routes/admin_users.py`
- Pattern référent frontend : `frontend/src/app/[username]/admin/users/_client.tsx`
- Mémoires : `feedback_modular_architecture`, `feedback_workflow_discipline`, `feedback_ruflo_workflow`, `feedback_chef_orchestre`
