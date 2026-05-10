# Admin Schedule — Calendar prod-ready

**Date :** 2026-05-10
**Auteur :** Claude (décisions tranchées en autonomie déléguée)
**Statut :** Spec à valider — implémentation déléguée à `ruflo-autopilot` après gate
**Sub-project :** 3/4 (suit Moderation A et Analytics B)

---

## 0. Quality Contract (non-négociable)

- Prod-ready strict : zéro placeholder/stub/TODO.
- Tests réels uniquement : zéro `@skip` / `@xfail` / bouchon.
- UI sans "Coming soon".
- TDD strict + coverage ≥ 90 %.

---

## 1. Contexte

`/[username]/admin/schedule` est aujourd'hui mockée (`_client.tsx`, 184 lignes statiques). Il faut un vrai planificateur de streams.

**Asymétrie avec A/B :** aucun model existant. Migration Alembic obligatoire. CRUD complet (create/read/update/delete) au lieu de read-only.

---

## 2. Scope

### Inclus

- **Nouveau model `ScheduledStream`** (migration Alembic)
- **5 routes admin** CRUD `/api/admin/schedule/*` gated `require_operator`
- **1 route publique** `/api/schedule/upcoming` non gated (calendrier public visible aux viewers)
- **UI calendar mensuel** (vue grid 7×N) + liste à venir + form de création/édition modal
- Polling 60s unifié
- Status manuel : `planned | live | past | cancelled`

### Exclus (out of MVP)

- Récurrence (RRULE iCalendar) — one-shot uniquement
- Notifications email/Discord automatiques quand `starts_at` approche
- Status auto-update background job (cron)
- Lien public `.ics` (calendar feed export)
- Multi-timezones côté admin (UTC backend, local côté UI)
- Drag-and-drop pour replanifier (utiliser form édition)

---

## 3. Architecture

### 3.1. Modules backend (4 nouveaux + 2 modifiés)

| Fichier | Action |
|---|---|
| `backend/alembic/versions/XXXX_scheduled_streams.py` | **nouveau** migration |
| `backend/shugu/db/models.py` | **modifié** ajouter classe `ScheduledStream` |
| `backend/shugu/services/scheduled_streams.py` | **nouveau** CRUD operations |
| `backend/shugu/routes/admin_schedule.py` | **nouveau** routes admin |
| `backend/shugu/routes/public_schedule.py` | **nouveau** route publique |
| `backend/shugu/app.py` | **modifié** 2 `include_router` |
| `backend/tests/unit/test_scheduled_streams_service.py` | **nouveau** |
| `backend/tests/integration/test_admin_schedule_routes.py` | **nouveau** |
| `backend/tests/integration/test_public_schedule_routes.py` | **nouveau** |

### 3.2. Modules frontend (1 nouveau + 1 refondu)

| Fichier | Action |
|---|---|
| `frontend/src/services/adminScheduleClient.ts` | **nouveau** |
| `frontend/src/app/[username]/admin/schedule/_client.tsx` | **refonte complète** |

---

## 4. Data model

### 4.1. Nouvelle table `scheduled_streams`

```python
class ScheduledStream(Base):
    __tablename__ = "scheduled_streams"

    id: Mapped[str] = mapped_column(String(26), primary_key=True)  # ULID
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="planned")
    created_by: Mapped[str] = mapped_column(String(26), nullable=False)  # OperatorIdentity username
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        server_onupdate=func.now(),
    )

    __table_args__ = (
        Index("idx_sched_starts_at", "starts_at"),
        Index("idx_sched_status_starts", "status", "starts_at"),
    )
```

**Pourquoi pas FK `Performance` ?** Le lien stream planifié → performance enregistrée n'a pas de besoin opérationnel MVP. Si nécessaire plus tard, ajouter `performance_id` nullable FK.

**Pourquoi `created_by: str(26)` et pas FK `UserAccount.id` ?** L'`OperatorIdentity` peut exister sans `UserAccount` (operator legacy Spoukie). On stocke un username string pour audit.

### 4.2. Migration Alembic

Nom : `XXXX_scheduled_streams.py` (next sequential number).

```python
def upgrade():
    op.create_table(
        "scheduled_streams",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="planned"),
        sa.Column("created_by", sa.String(26), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint("duration_minutes > 0 AND duration_minutes <= 1440",
                           name="ck_sched_duration_positive"),
        sa.CheckConstraint("status IN ('planned','live','past','cancelled')",
                           name="ck_sched_status_enum"),
    )
    op.create_index("idx_sched_starts_at", "scheduled_streams", ["starts_at"])
    op.create_index("idx_sched_status_starts", "scheduled_streams", ["status", "starts_at"])


def downgrade():
    op.drop_index("idx_sched_status_starts", table_name="scheduled_streams")
    op.drop_index("idx_sched_starts_at", table_name="scheduled_streams")
    op.drop_table("scheduled_streams")
```

CHECK constraints DB :
- `duration_minutes ∈ ]0, 1440]` (max 24 h, garde-fou)
- `status ∈ {'planned', 'live', 'past', 'cancelled'}`

---

## 5. API REST

### Routes admin (gated `require_operator`)

#### `GET /api/admin/schedule`

Query : `status?` (filtrer), `since?`, `until?`, `limit` (1-200, default 50), `offset`.

```python
class ScheduleListItem(BaseModel):
    id: str
    title: str
    description: Optional[str]
    starts_at: datetime
    duration_minutes: int
    status: Literal["planned", "live", "past", "cancelled"]
    created_by: str
    created_at: datetime
    updated_at: datetime

class ScheduleListResponse(BaseModel):
    total: int
    items: list[ScheduleListItem]
```

#### `POST /api/admin/schedule`

```python
class ScheduleCreateBody(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=5000)
    starts_at: datetime
    duration_minutes: int = Field(ge=1, le=1440)

    @field_validator("starts_at")
    @classmethod
    def must_be_future(cls, v):
        if v <= datetime.now(timezone.utc) - timedelta(minutes=5):
            raise ValueError("starts_at must be in the future (5min tolerance)")
        return v
```

Retourne `ScheduleListItem` créé (status auto = `planned`, created_by depuis OperatorIdentity).

#### `GET /api/admin/schedule/{id}`

Retourne `ScheduleListItem` ou 404.

#### `PATCH /api/admin/schedule/{id}`

```python
class ScheduleUpdateBody(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=5000)
    starts_at: Optional[datetime] = None
    duration_minutes: Optional[int] = Field(default=None, ge=1, le=1440)
    status: Optional[Literal["planned", "live", "past", "cancelled"]] = None
```

Partial update (PATCH). `updated_at` auto par DB. Renvoie 404 si id inconnu. Renvoie 409 si transition status invalide (cf. § 6.2).

#### `DELETE /api/admin/schedule/{id}`

Hard delete. 204 No Content. Idempotent (204 même si déjà absent).

### Route publique (non gated)

#### `GET /api/schedule/upcoming`

Query : `limit` (1-50, default 10). Retourne uniquement les streams `status IN ('planned', 'live')` avec `starts_at >= NOW() - 24h` (live + planifiés à venir + en cours il y a moins de 24h pour ne pas masquer un live en retard).

```python
class PublicScheduleItem(BaseModel):
    id: str
    title: str
    description: Optional[str]
    starts_at: datetime
    duration_minutes: int
    status: Literal["planned", "live"]   # past/cancelled exclus côté query

class PublicScheduleResponse(BaseModel):
    items: list[PublicScheduleItem]
```

**Sécurité publique :** pas de `created_by` exposé, pas de `created_at`/`updated_at`. Champ `description` peut être affiché publiquement → docstring rappelle "ne pas mettre d'info privée".

---

## 6. Logique métier critique

### 6.1. Création stream (transaction simple)

```python
async def create_scheduled_stream(
    session: AsyncSession,
    *,
    title: str, description: Optional[str],
    starts_at: datetime, duration_minutes: int,
    created_by: str,
) -> dict:
    new_id = str(ULID())
    await session.execute(
        insert(ScheduledStream).values(
            id=new_id, title=title, description=description,
            starts_at=starts_at, duration_minutes=duration_minutes,
            status="planned", created_by=created_by,
        )
    )
    row = (await session.execute(
        select(ScheduledStream).where(ScheduledStream.id == new_id)
    )).scalar_one()
    return _row_to_dict(row)
```

### 6.2. Transitions de status (state machine)

Transitions autorisées :
```
planned  → live
planned  → cancelled
planned  → past         (si starts_at < NOW() - 24h, "rétroactif clean")
live     → past
live     → cancelled
past     → planned      (NON : irréversible)
cancelled → planned     (NON : irréversible — créer un nouveau stream à la place)
```

Implémentation :
```python
_VALID_TRANSITIONS = {
    "planned": {"live", "cancelled", "past"},
    "live": {"past", "cancelled"},
    "past": set(),
    "cancelled": set(),
}


def _validate_status_transition(current: str, new: str) -> None:
    if new == current:
        return  # no-op accepté
    allowed = _VALID_TRANSITIONS.get(current, set())
    if new not in allowed:
        raise HTTPException(
            status_code=409,
            detail=f"Status transition invalide : {current} → {new}. "
                    f"Transitions valides depuis {current} : {sorted(allowed) or 'aucune'}.",
        )
```

### 6.3. Public upcoming query

```python
async def list_upcoming(session: AsyncSession, *, limit: int = 10) -> list[dict]:
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
    return [_to_public_dict(r) for r in rows]
```

---

## 7. UI / Frontend

### 7.1. Layout

```
AdminShell active="schedule" title="Planning streams" subtitle="..."
├── Header right : pill "{count_planned + count_live} streams à venir"
├── Top bar : [Mois précédent] [Mois courant] [Mois suivant] + bouton "+ Nouveau stream"
├── Grid 2 colonnes (lg:[1fr_320px])
│   ├── Colonne principale
│   │   ├── GlassSection "Calendrier mensuel"
│   │   │   Grid 7×N (jours du mois) :
│   │   │   - Header semaine : Lun Mar Mer Jeu Ven Sam Dim
│   │   │   - Cellules jour avec :
│   │   │     * Date en haut
│   │   │     * Pills colorées par stream du jour (max 3 visibles + "+N" si plus)
│   │   │     * Click cellule jour = créer stream pré-rempli date
│   │   │     * Click pill stream = ouvrir modal détail/édition
│   └── Rail droit
│       ├── GlassSection "À venir (7 prochains jours)"
│       │   - Liste streams ordrés par starts_at
│       │   - Click row = modal détail
│       └── GlassSection "Statut récents"
│           - count past 7d, count cancelled 7d
```

### 7.2. Modal Nouveau / Édition stream

```
GlassModal
├── h3 "Nouveau stream" ou "Éditer : {title}"
├── GlassInput title (required)
├── Textarea description (optional, max 5000)
├── Date/time picker starts_at (native input type=datetime-local)
├── Number input duration_minutes (1-1440)
├── (Edit only) Select status — affichage des transitions valides selon état courant
├── Footer :
│   - [Annuler] (ghost)
│   - [Supprimer] (danger, edit only, confirm second-stage)
│   - [Créer] / [Enregistrer] (primary)
```

Validation côté frontend :
- `title` non vide, ≤ 200 chars
- `starts_at` >= NOW() - 5 min (cohérent backend validator)
- `duration_minutes` ∈ [1, 1440]

Erreurs backend (422) affichées en toast + soulignement champ erronné.

### 7.3. Polling 60s

```typescript
useEffect(() => {
  const tick = () => Promise.all([
    listStreams({ since: monthStart, until: monthEnd }),
    listStreams({ status: "planned", limit: 7, since: now }),  // pour rail droit upcoming
  ]);
  tick();
  const id = setInterval(tick, 60_000);
  return () => clearInterval(id);
}, [currentMonth]);
```

### 7.4. Timezone

- **Backend stocke UTC** (`timestamptz`)
- **Frontend affiche timezone locale** browser (`new Date(iso).toLocaleString(...)`)
- **Form `datetime-local`** retourne string sans timezone → parser comme local timezone → convertir UTC avant POST/PATCH
- Pas de paramètre user timezone MVP

---

## 8. Tests (TDD strict)

### 8.1. Fixtures partagées

Réutilise `db_session`, `operator_cookie`, `member_cookie`, `api_client` de A.

Ajouter spécifique :

```python
@pytest_asyncio.fixture
async def seed_scheduled_streams(db_session):
    """Insère 5 streams variés : 2 planned futurs, 1 live, 1 past, 1 cancelled."""
    from datetime import datetime, timedelta, timezone
    from ulid import ULID
    from sqlalchemy import insert
    from shugu.db.models import ScheduledStream

    now = datetime.now(timezone.utc)
    rows = [
        {"id": str(ULID()), "title": "Demain 21h", "description": None,
         "starts_at": now + timedelta(days=1, hours=4), "duration_minutes": 120,
         "status": "planned", "created_by": "operator"},
        {"id": str(ULID()), "title": "Dans 3 jours", "description": "Spécial",
         "starts_at": now + timedelta(days=3), "duration_minutes": 90,
         "status": "planned", "created_by": "operator"},
        {"id": str(ULID()), "title": "Live actuel", "description": None,
         "starts_at": now - timedelta(minutes=30), "duration_minutes": 60,
         "status": "live", "created_by": "operator"},
        {"id": str(ULID()), "title": "Hier", "description": None,
         "starts_at": now - timedelta(days=1), "duration_minutes": 60,
         "status": "past", "created_by": "operator"},
        {"id": str(ULID()), "title": "Annulé", "description": None,
         "starts_at": now + timedelta(days=2), "duration_minutes": 60,
         "status": "cancelled", "created_by": "operator"},
    ]
    await db_session.execute(insert(ScheduledStream), rows)
    await db_session.commit()
    return rows
```

### 8.2. Tests admin routes

`backend/tests/integration/test_admin_schedule_routes.py` :

- **LIST :**
  - `test_list_returns_empty` (no seed)
  - `test_list_returns_all_seeded`
  - `test_list_filters_by_status`
  - `test_list_filters_by_since_until_range`
  - `test_list_pagination`
  - `test_list_requires_operator` (401)
  - `test_list_rejects_member_cookie` (403)

- **CREATE :**
  - `test_create_returns_201_with_planned_status` (status auto = planned)
  - `test_create_rejects_past_starts_at` (422)
  - `test_create_rejects_duration_zero` (422)
  - `test_create_rejects_duration_over_1440` (422)
  - `test_create_rejects_title_empty` (422)
  - `test_create_persists_created_by_from_operator`
  - `test_create_rejects_member_cookie`

- **GET single :**
  - `test_get_returns_full_item`
  - `test_get_404_unknown_id`

- **PATCH :**
  - `test_patch_partial_update_title`
  - `test_patch_partial_update_status_planned_to_live`
  - `test_patch_partial_update_status_planned_to_cancelled`
  - `test_patch_rejects_invalid_transition_past_to_planned` (409)
  - `test_patch_rejects_invalid_transition_cancelled_to_planned` (409)
  - `test_patch_accepts_status_no_op` (live → live)
  - `test_patch_updates_updated_at_timestamp`
  - `test_patch_404_unknown_id`
  - `test_patch_rejects_member_cookie`

- **DELETE :**
  - `test_delete_204_when_exists`
  - `test_delete_idempotent_204_when_absent`
  - `test_delete_actually_removes_row`
  - `test_delete_rejects_member_cookie`

`backend/tests/integration/test_public_schedule_routes.py` :

- **PUBLIC :**
  - `test_public_upcoming_returns_only_planned_and_live`
  - `test_public_upcoming_excludes_past_status` (même future starts_at)
  - `test_public_upcoming_excludes_cancelled`
  - `test_public_upcoming_excludes_starts_before_24h_ago`
  - `test_public_upcoming_orders_by_starts_at_asc`
  - `test_public_upcoming_respects_limit`
  - `test_public_upcoming_does_not_expose_created_by`
  - `test_public_upcoming_does_not_require_auth` (200 sans cookie)

`backend/tests/unit/test_scheduled_streams_service.py` (state machine validation isolée) :

- `test_valid_transition_planned_to_live`
- `test_valid_transition_planned_to_cancelled`
- `test_valid_transition_planned_to_past`
- `test_valid_transition_live_to_past`
- `test_valid_transition_live_to_cancelled`
- `test_invalid_transition_past_to_planned`
- `test_invalid_transition_past_to_live`
- `test_invalid_transition_cancelled_to_anything`
- `test_no_op_transition_accepted`

**Total : ~42 tests.** Tous activés, tous prod-ready.

### 8.3. Coverage cible : ≥ 90 %

Sur les 3 nouveaux modules backend (`services/scheduled_streams.py`, `routes/admin_schedule.py`, `routes/public_schedule.py`).

---

## 9. Error handling

| Couche | Erreur | Comportement |
|---|---|---|
| Migration alembic | Échec apply | Migration rollback automatique alembic ; investigation manuelle |
| `services.create` | Unique violation (ID collision ULID) | Re-générer ID 1 fois, sinon HTTPException 500 |
| `services.patch` | Transition invalide | HTTPException 409 avec liste transitions valides |
| `services.patch` | ID inconnu | HTTPException 404 |
| `routes.create` | starts_at dans le passé | HTTPException 422 (Pydantic validator) |
| `routes.create` | duration hors [1, 1440] | HTTPException 422 |
| `routes.public_upcoming` | DB down | HTTPException 503 (data publique, dégrader proprement) |
| Frontend `_client.tsx` | `AdminError` | toast.error |
| Frontend form | validation locale failed | inline error + soulignement champ |

---

## 10. Sécurité

- Routes admin `require_operator` strict. Test non-régression `*_rejects_member_cookie`.
- **Route publique `/api/schedule/upcoming` :**
  - Pas de PII exposée (pas de `created_by`)
  - Pas de info interne (created_at/updated_at masqués)
  - Rate limiting standard (utilise le rate limiter middleware existant si présent ; sinon, à ajouter — vérifier `backend/shugu/app.py`)
- Validation Pydantic stricte : `title` max 200, `description` max 5000.
- `id` path param validé regex ULID Crockford32 : `^[0-9A-HJKMNP-TV-Z]{26}$` (refuse SQL injection).

---

## 11. Observability

- `structlog` info `admin_schedule.{created,updated,deleted}` avec `id`, `operator`, ancien/nouveau status.
- Pas de metric Prometheus dédiée pour MVP.
- L'`updated_at` est l'audit trail interne ; pour audit RGPD complet, voir handover plus tard.

---

## 12. Rollout

- **Migration Alembic à appliquer** avant que les routes soient appelées. Inclure dans le PR.
- **Pas de feature flag** : routes additives.
- **Smoke tests post-merge :**
  1. Migration alembic apply OK
  2. Créer un stream depuis l'UI → row en DB
  3. Edit, transition planned → cancelled → row update
  4. Delete → row supprimée
  5. `/api/schedule/upcoming` accessible sans cookie, retourne le stream créé
  6. Member auth ne peut pas créer/edit/delete

---

## 13. Trade-offs documentés

- **One-shot only** : pas de récurrence MVP. iCalendar RRULE = scope add-on plus tard.
- **No auto status update** : un stream `planned` reste planned même si `starts_at` passé. Cron à ajouter dans 3-6 mois si volume augmente.
- **Timezone browser-side** : pas de paramètre user timezone. OK pour MVP solo-operator.
- **Pas de notifications** : info passive (calendrier consultable). Streamer notifié indépendamment hors application.
- **Hard delete** : pas de soft-delete (`is_active=false`). Si erreur, recréer. Acceptable pour streams pas critique business.

---

## 14. Plan d'implémentation (haut niveau)

Étapes :

0. **Préalable** : vérifier que les fixtures `db_session`, `operator_cookie`, `member_cookie`, `api_client` existent (créées par A).
1. **Migration alembic** : créer fichier `XXXX_scheduled_streams.py`, vérifier `alembic upgrade head` OK en dev.
2. **Model SQLAlchemy** : ajouter classe `ScheduledStream` dans `db/models.py`.
3. **TDD unit** state machine transitions.
4. **TDD service** `scheduled_streams.py` (list, get, create, patch, delete).
5. **TDD routes admin** : 5 endpoints (CRUD).
6. **TDD route publique** `/api/schedule/upcoming`.
7. **Sécurité** : 4 tests `_rejects_member_cookie` sur routes admin.
8. **Wiring `app.py`** : 2 `include_router`.
9. **Frontend service** `adminScheduleClient.ts`.
10. **Frontend refonte `_client.tsx`** : calendar grid + form modal.
11. **Smoke tests manuels**.
12. **PR finale**.

---

## 15. Compatibilité golden path

- Structure spec identique à Moderation A et Analytics B
- Patterns Pydantic / `request<T>` / `AdminError` cohérents
- Primitives `liquid-glass` réutilisées : `AdminShell`, `GlassSection`, `GlassRow`, `GlassPill`, `GlassButton`, `GlassModal`, `useToast`
- Polling 60s (comme B)
- TDD strict / coverage 90 % / non-régression sécurité

**Différences vs A/B :**
- **Migration Alembic obligatoire** (vs 0 pour A, 0 pour B)
- **CRUD complet** vs read-only A/B
- **1 route publique** vs 100 % admin pour A/B
- **State machine status** (validation transitions)
- **Calendar grid** UI vs simple liste

---

## 16. Références

- Golden path : [Moderation Hub Pivot](2026-05-10-moderation-hub-pivot-design.md), [Analytics](2026-05-10-admin-analytics-design.md)
- Template : [Admin Pages BCD](2026-05-10-admin-pages-template-bcd.md)
- Pattern backend référent : `backend/shugu/routes/admin_users.py`
- Pattern Alembic référent : `backend/alembic/versions/0004_user_accounts.py`
- Mémoires : `feedback_modular_architecture`, `feedback_workflow_discipline`, `feedback_ruflo_workflow`
