# Moderation Hub — Pivot vers dashboard pipeline IA agent

**Date :** 2026-05-10
**Auteur :** Claude (brainstorming session avec Sylvain)
**Statut :** Spec validée — implémentation déléguée à `ruflo-autopilot:autopilot-coordinator`
**Sub-project :** 1/4 (Moderation A → Analytics B → Schedule C → Community D)

---

## 1. Contexte et problème

La page `/[username]/admin/moderation` est aujourd'hui un placeholder 100 % mocké (cf. `frontend/src/app/[username]/admin/moderation/_client.tsx` — 197 lignes, constantes `EVENTS` / `LOG` inline, toggles AutoMod sans effet, `useState` non branchés).

Deux découvertes ont structuré le scope :

1. **Le model `ModerationEvent`** (`backend/shugu/db/models.py:165`) ne correspond PAS au mock UI. Le model logue le **pipeline IA agent** (`phase: 'ingress'|'egress'`, `detector`, `verdict`), le mock affiche un **dashboard chat moderation Twitch-like** (queue messages, automod caps/links/wordlist, équipe mods).
2. **Le model `ModerationEvent` n'a aucun writer** dans le backend (grep `ModerationEvent` → 1 seul fichier : la définition). Le pipeline `BasicModeration` (`backend/shugu/adapters/moderation_basic.py`) produit des `ModerationVerdict` mais ne les persiste jamais.

**Décision produit (option 2 du brainstorming) :** pivoter la page UI pour refléter le **pipeline IA réel**. Le dashboard "chat moderation Twitch" est hors scope (probablement hors MVP "Streamer IA autonome" — cf. `reference_phase_plan`).

---

## 2. Scope

### Inclus

- **Hook persistance** : brancher l'écriture de `ModerationEvent` quand `BasicModeration` retourne un verdict `allowed=False`.
- **Routes admin REST** : `/api/admin/moderation/{events,stats,bans}` + `DELETE /bans/{ip_hash}`.
- **Refonte UI** : 4 sections (KPIs, Filtres, Events list, Bans+Stats) — réutilisation de `liquid-glass` primitives existantes, AUCUN nouveau composant.
- **Polling 30s** : refresh auto unifié (events + stats + bans en parallèle).
- **Tests TDD** : unit (`LoggingModeration`) + intégration (routes admin) — coverage ≥ 90 % sur les nouveaux modules.

### Exclus (out of scope)

- Chat moderation Twitch-like (automod caps/links/wordlist, équipe mods, bans externes).
- Runtime config des detectors (toggle on/off live d'injection/profanity).
- `performance_id` dans les events (NULL pour MVP — sub-project futur).
- Retention policy automatique (table croît, à gérer dans 6 mois ≈ 180 k rows/an).
- Tests frontend exhaustifs (juste `tsc --noEmit` + ESLint ; Playwright optionnel).

---

## 3. Architecture

### 3.1. Pattern Decorator pour la persistance

```
visitor_ws / pipeline_workers
        │
        ▼
LoggingModeration  ← nouveau, implémente ModerationLayer Protocol
        │
        ├─→ inner.check_ingress/egress  (BasicModeration inchangée)
        │
        └─→ if not verdict.allowed:
              INSERT INTO moderation_events (...)
              (sync, fail-open)
```

**Pourquoi décorateur (option C choisie sur 3 approches) :**
- `BasicModeration` reste 100 % isolée de la DB (préserve l'audit Pass 2 P1.B7).
- Suit le pattern Adapter/Protocol déjà utilisé dans le projet.
- Activable/désactivable en 1 ligne (wrapping dans `app.py`).
- Testable isolément avec un fake `inner`.

### 3.2. Modules backend (4 nouveaux + 1 modifié)

| Fichier | Rôle |
|---|---|
| `backend/shugu/adapters/moderation_logging.py` *(nouveau)* | Décorateur `LoggingModeration` |
| `backend/shugu/services/moderation_events.py` *(nouveau)* | Queries d'agrégation (list + stats) |
| `backend/shugu/routes/admin_moderation.py` *(nouveau)* | Routes `/api/admin/moderation/*` |
| `backend/shugu/app.py` *(modifié)* | Wiring : `LoggingModeration(BasicModeration(...))` + `include_router` |
| `backend/tests/unit/test_moderation_logging.py` *(nouveau)* | Tests unit décorateur |
| `backend/tests/integration/test_admin_moderation_routes.py` *(nouveau)* | Tests intégration routes |

### 3.3. Modules frontend (1 nouveau + 1 refondu)

| Fichier | Rôle |
|---|---|
| `frontend/src/services/adminModerationClient.ts` *(nouveau)* | Wrapper fetch typé sur `/api/admin/moderation/*` |
| `frontend/src/app/[username]/admin/moderation/_client.tsx` *(refondu)* | Mock → UI branchée sur le service |

### 3.4. Modules non touchés (préservation)

- `backend/shugu/adapters/moderation_basic.py` — code audité, **0 changement**.
- `backend/shugu/core/protocols.py` — `ModerationLayer` Protocol stable.
- `backend/shugu/db/models.py` — `ModerationEvent` schema stable, **aucune colonne ajoutée**.
- `backend/shugu/routes/visitor_ws.py`, `pipeline/workers.py` — appellent `moderation.check_*`, ne savent rien du décorateur.
- `frontend/src/app/[username]/admin/moderation/page.tsx` — wrapper Server Component thin, **0 changement**.

---

## 4. Data model

### 4.1. Table `moderation_events` (existante, inchangée)

```python
class ModerationEvent(Base):
    __tablename__ = "moderation_events"
    id: BigInteger autoincrement primary key
    performance_id: FK → performances(performance_id) ON DELETE CASCADE  # NULL pour MVP
    phase: str(16)            # 'ingress' | 'egress'
    detector: str(32)         # 'length' | 'profanity' | 'injection' | 'ban' | 'rate_limit' | 'egress_length' | 'unknown'
    verdict: str(16)          # 'refused' (toujours — on ne loue que !allowed)
    details: JSONB nullable
    created_at: timestamptz default now()
```

### 4.2. Schema `details` JSONB (validé)

```jsonc
{
  "reason": "langage inapproprié",       // ModerationVerdict.reason
  "identity_kind": "visitor",             // identity.role : 'visitor'|'member'|'vip'|'operator'
  "ip_hash": "sha256-hex-64-chars",       // identity.ip_hash, NULL si absent
  "text_excerpt": "salut tu peux dire...", // text[:80] — limite PII fuite
  "text_len": 142
}
```

### 4.3. Migration Alembic

**Tâche 0 du plan d'implémentation (vérification préalable obligatoire) :**

```bash
alembic current
psql "$SHUGU_POSTGRES_DSN" -c "\d moderation_events"
```

- Si la table existe : aucune migration nécessaire, on procède.
- Si la table n'existe pas : créer la migration Alembic correspondant au model existant, l'appliquer en dev, l'inclure dans le PR.

---

## 5. API REST

Toutes routes gated par `Depends(require_operator)`. Pattern Pydantic identique à `admin_users.py`. Erreurs typées `AdminError` côté frontend.

### `GET /api/admin/moderation/events`

Query params : `phase`, `detector`, `since` (ISO datetime), `limit` (1-200, default 25), `offset` (≥0).

```python
class EventListItem(BaseModel):
    id: int
    phase: Literal["ingress", "egress"]
    detector: str
    verdict: str
    reason: Optional[str]
    identity_kind: Optional[str]
    ip_hash: Optional[str]
    text_excerpt: Optional[str]
    text_len: Optional[int]
    created_at: datetime

class EventListResponse(BaseModel):
    total: int
    items: list[EventListItem]
```

Pagination : `OFFSET/LIMIT` (acceptable jusqu'à ~10k rows ; au-delà migrer vers seek-based).

### `GET /api/admin/moderation/stats`

Query param : `window` ∈ {`1h`, `24h`, `7d`}, default `24h`.

```python
class StatsResponse(BaseModel):
    window: Literal["1h", "24h", "7d"]
    total_refused: int
    by_detector: dict[str, int]          # GROUP BY detector
    by_phase: dict[str, int]             # GROUP BY phase
    timeline: list[BucketCount]          # buckets de 5 min (1h) / 1h (24h) / 1d (7d)

class BucketCount(BaseModel):
    bucket: datetime
    count: int
```

### `GET /api/admin/moderation/bans`

Lit Redis (`SCAN match=ban:*`). Retourne :

```python
class BanItem(BaseModel):
    ip_hash: str
    ttl_seconds: int        # -1 = no TTL = perma

class BanListResponse(BaseModel):
    total: int
    items: list[BanItem]
```

### `DELETE /api/admin/moderation/bans/{ip_hash}`

- Validation : `ip_hash` doit matcher `^[a-f0-9]{64}$` (SHA-256 hex — bloque wildcard injection type `*`).
- `redis.delete(f"ban:{ip_hash}")` — idempotent (204 si key absent).
- Réponse : 204 No Content.

---

## 6. Logique métier critique

### 6.1. `LoggingModeration._persist()` (corps validé)

```python
async def _persist(
    self, phase: str, verdict: ModerationVerdict, identity: Identity, text: str
) -> None:
    try:
        details = {
            "reason": verdict.reason,
            "identity_kind": identity.role,
            "ip_hash": getattr(identity, "ip_hash", None) or None,
            "text_excerpt": (text or "")[:80],
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
            phase=phase, detector=verdict.detector, error=str(exc),
        )
```

**Invariants :**
- INSERT synchrone (await, pas `create_task`) — volume bas, latence ~1-5 ms acceptable.
- `try/except` swallow-and-log : **DB down n'interrompt JAMAIS le pipeline moderation** (fail-open).
- `getattr` defensive pour `ip_hash` (compatible futures `Identity` sans ce champ).
- `(text or "")[:80]` protège contre `text=None` ET limite PII fuite.
- `verdict.detector or "unknown"` fallback car `detector: Optional[str]` côté Protocol mais colonne NOT NULL.

### 6.2. Service `moderation_events.py` (queries SQL)

```python
async def list_events(*, phase=None, detector=None, since=None, limit=25, offset=0): ...
async def aggregate_stats(window: Literal["1h","24h","7d"]) -> StatsResponse: ...
```

Bucket sizes pour `timeline` :
- `1h` → buckets de 5 min (12 points)
- `24h` → buckets de 1 h (24 points)
- `7d` → buckets de 1 jour (7 points)

Generated via `date_trunc()` PostgreSQL.

### 6.3. Wiring `app.py`

Remplacer la ligne (qui doit ressembler à) :
```python
moderation = BasicModeration(settings, redis, metrics=...)
```
par :
```python
moderation = LoggingModeration(BasicModeration(settings, redis, metrics=...))
```

Et ajouter le router :
```python
from .routes.admin_moderation import router as admin_moderation_router
app.include_router(admin_moderation_router)
```

---

## 7. UI / Frontend

### 7.1. Layout (réutilise `liquid-glass` + `AdminShell`)

```
AdminShell active="moderation" title="Pipeline Moderation"
├── Header right : pill "{total_refused} refus 24h"
├── KPI band (4 MetricTile)
│   [Refus 24h] [Top detector] [Ingress/Egress] [Bans actifs]
├── Grid 2 colonnes (lg:[1fr_320px])
│   ├── Colonne principale
│   │   ├── GlassSection "Filtres"
│   │   │   GlassTabs phase [all|ingress|egress]
│   │   │   Detector pills (filtre)
│   │   │   Window pills [1h|24h|7d]
│   │   │   GlassButton "Rafraîchir"
│   │   └── GlassSection "Events" (paginée 25/page)
│   │       GlassRow par event :
│   │         label : <phase pill> <detector pill> <reason>
│   │         sub   : "il y a Xs · text_excerpt"
│   │         trailing : timestamp précis
│   │       pagination ← →
│   └── Rail droit
│       ├── GlassSection "Stats / detector"
│       │   bars horizontales depuis stats.by_detector
│       └── GlassSection "Bans actifs"
│           GlassRow par BanItem :
│             label : ip_hash truncate(12)
│             sub   : "TTL Xh" ou "permanent"
│             trailing : GlassButton danger "Lever"
│           → confirm modal → DELETE → toast success
```

### 7.2. Service `adminModerationClient.ts` (signatures)

Mirror exact de `adminUsersClient.ts` (cf. fichier existant) :

```ts
export type ModerationPhase = "ingress" | "egress";
export type ModerationEvent = { id, phase, detector, verdict, reason, identity_kind, ip_hash, text_excerpt, text_len, created_at };
export type EventListResponse = { total, items };
export type ModerationStats = { window, total_refused, by_detector, by_phase, timeline };
export type BanItem = { ip_hash, ttl_seconds };
export type BanListResponse = { total, items };
export class AdminError extends Error { /* identique */ }

export async function listEvents(params): Promise<EventListResponse>;
export async function getStats(window): Promise<ModerationStats>;
export async function listBans(): Promise<BanListResponse>;
export async function clearBan(ip_hash): Promise<void>;
```

### 7.3. Polling 30s

```ts
useEffect(() => {
  const tick = () => Promise.all([loadEvents(), loadStats(), loadBans()]);
  tick();
  const id = setInterval(tick, 30_000);
  return () => clearInterval(id);
}, [filters]);
```

Pas de spam toast en cas d'erreur réseau pendant le polling — silent retry au tick suivant.

---

## 8. Tests (TDD strict)

### 8.1. Discipline imposée

**Cycle rouge → vert → refactor.** Tests écrits AVANT le code. Si un test échoue, le test n'est JAMAIS modifié pour passer — c'est le code qui doit être corrigé. (Cf. mémoire `feedback_workflow_discipline` : 10 h perdues sur ce point.)

### 8.2. Unit `tests/unit/test_moderation_logging.py`

Tests du décorateur avec un fake `inner`.

- `test_check_ingress_allowed_does_not_persist`
- `test_check_ingress_refused_persists_event` (phase=ingress, schema details correct)
- `test_check_egress_refused_persists_with_egress_phase`
- `test_details_contains_ip_hash_for_visitor`
- `test_details_truncates_text_excerpt_at_80_chars`
- `test_persist_failure_does_not_break_pipeline` (DB raise → verdict quand même retourné, structlog warning émis)
- `test_detector_fallback_unknown` (verdict.detector=None → colonne `unknown`)

### 8.3. Intégration `tests/integration/test_admin_moderation_routes.py`

- `test_list_events_returns_empty`
- `test_list_events_filters_by_phase`
- `test_list_events_filters_by_detector`
- `test_list_events_pagination`
- `test_list_events_requires_operator` (401 sans cookie)
- `test_list_events_rejects_user_cookie` (403 si VIP/member — **test de non-régression sécurité**)
- `test_stats_24h_groups_by_detector`
- `test_stats_window_validation` (window invalide → 422)
- `test_list_bans_returns_redis_keys`
- `test_clear_ban_deletes_redis_key`
- `test_clear_ban_idempotent` (delete twice → 204+204)
- `test_clear_ban_rejects_invalid_ip_hash` (non-SHA-256 hex → 422)

### 8.4. Fixtures (`backend/tests/conftest.py` à compléter)

- `operator_cookie` — cookie d'auth pour OperatorIdentity de test
- `seed_events` — 20 events variés (3 detectors, 2 phases, timeline 24h)
- `seed_redis_bans` — 2 keys `ban:*` avec TTL différents (3600s + perma)

### 8.5. Coverage cible

**≥ 90 %** sur les 3 nouveaux modules backend (`adapters/moderation_logging.py`, `services/moderation_events.py`, `routes/admin_moderation.py`). Les fixtures de test n'entrent pas dans le calcul de coverage.

### 8.6. Tests frontend

- `tsc --noEmit` doit passer.
- `eslint` doit passer.
- **Pas de tests unitaires `_client.tsx`** (pattern projet — `adminUsersClient` n'en a pas).
- Playwright optionnel/skip pour MVP.

---

## 9. Error handling

| Couche | Erreur | Comportement |
|---|---|---|
| `LoggingModeration._persist` | DB down | `log.warning` + swallow → verdict normal |
| `LoggingModeration._persist` | JSONB encoding error | idem |
| `admin_moderation.list_events` | DB query fail | HTTPException 500 |
| `admin_moderation.list_bans` | Redis down | HTTPException 503 `"redis unavailable"` |
| `admin_moderation.clear_ban` | Redis down | HTTPException 503 |
| `admin_moderation.clear_ban` | `ip_hash` invalide | HTTPException 422 (regex validation) |
| Frontend | `AdminError` | `toast.error(detail)` (pattern `users`) |
| Frontend polling tick | network fail | Silent retry au prochain tick (pas de spam toast) |

---

## 10. Sécurité

- `ip_hash` : SHA-256 (déjà calculé par `core/identity.hash_ip`) — **pas de PII brute**.
- `text_excerpt[:80]` : limite la fuite si DB compromise.
- Routes admin : `require_operator` strict → un VIP/member auth ne lit PAS ces events (test non-régression).
- Validation `ip_hash` : regex `^[a-f0-9]{64}$` bloque wildcard injection Redis (`ban:*` qui supprimerait tous les bans).
- Cookies : `credentials: "include"` (pattern existant).
- Pas de CSRF token spécifique — le `require_operator` cookie est sameSite (cf. flow auth existant).

---

## 11. Observability

- `structlog` warning sur `_persist` failed (clé `moderation_event.persist_failed` agrégeable).
- `MetricsRecorder.record_moderation_decision` reste source de vérité pour les **totaux** (déjà appelé par `BasicModeration`).
- Pas de nouvelle metric Prometheus pour MVP.
- Logs structurés existants visibles dans le pipeline observability standard du projet.

---

## 12. Rollout

- **Pas de feature flag.** Le décorateur est strictement additif. Revert = 1 ligne dans `app.py`.
- **Pas de data migration.** Table vide au démarrage.
- **Smoke test obligatoire avant merge :**
  1. Lancer un message visitor refusé via le path moderation → vérifier 1 row dans `moderation_events`.
  2. Charger `/[username]/admin/moderation` → l'event apparaît.
  3. Lever un ban Redis depuis l'UI → key supprimée + toast success.
- **PR review obligatoire** par l'utilisateur (mémoire `feedback_workflow_discipline`).

---

## 13. Trade-offs documentés (décisions différées)

- **Pas de `performance_id`** dans les events MVP → on perd la possibilité de filtrer "events de cette performance". Sub-project futur si besoin (récupérer `performance_id` actif depuis le contexte WebSocket).
- **Synchrone hot path** → si volume × 100 (un jour ?), envisager queue Redis + worker async. Pas un piège pour aujourd'hui (volume cible ~5 % du trafic).
- **Pas de retention policy** automatique → table croît sans borne. À 5 %×10k req/jour ≈ 500 rows/jour ≈ 180 k/an. Pas critique court-terme. Cron `DELETE WHERE created_at < NOW() - INTERVAL '90 days'` à ajouter dans 6 mois.
- **Pagination OFFSET/LIMIT** → acceptable jusqu'à ~10 k events. Au-delà, seek-based pagination (`WHERE id < cursor`).

---

## 14. Plan d'implémentation (haut niveau — détaillé dans le plan ruflo)

Ordre TDD strict :

0. **Préalable** : vérifier que la table `moderation_events` existe en DB. Sinon, créer la migration Alembic.
1. **TDD backend unit** : tests `LoggingModeration` rouges → implémentation `moderation_logging.py` vert.
2. **TDD backend intégration** : tests routes rouges → implémentation `admin_moderation.py` + `services/moderation_events.py` vert.
3. **Wiring** : modifier `app.py` (decorator + router include) → smoke test backend complet.
4. **Frontend service** : `adminModerationClient.ts` (mirror types).
5. **Frontend UI** : refondre `_client.tsx` (mock → branché) avec polling 30s.
6. **Validation manuelle** : 3 smoke tests (cf. § 12 Rollout).
7. **PR + review** : commit, push, créer PR, review utilisateur, merge.

---

## 15. Template de réutilisation pour sub-projects suivants

Ce spec sert de **template** pour Analytics (B), Schedule (C), Community (D). Pattern à reproduire :

- Décorateur côté backend si la logique d'écriture peut être branchée sur un service existant.
- Routes admin REST sous `/api/admin/{feature}/*` gated `require_operator`.
- Service TS client typé mirror.
- Refonte `_client.tsx` réutilisant les primitives `liquid-glass`.
- TDD strict, ≥ 90 % coverage sur nouveaux modules.
- 1 PR par sub-project, review obligatoire.

Différences attendues :
- **Analytics (B)** : models `Visitor`/`Performance` déjà présents, donc même structure mais agrégations différentes (sessions, viewers/h, durée moyenne).
- **Schedule (C)** : aucun model existant → migration Alembic obligatoire (nouvelle table `scheduled_streams` ou similaire).
- **Community (D)** : aucun model + scope flou (cadrer dans un brainstorming séparé avant de lancer ruflo).

---

## 16. Références

- Mémoire `feedback_modular_architecture` — modularité non négociable.
- Mémoire `feedback_workflow_discipline` — TDD strict, jamais modifier les tests.
- Mémoire `feedback_ruflo_workflow` — déléguer à `ruflo-autopilot:autopilot-coordinator`.
- Mémoire `feedback_chef_orchestre` — rôle Claude = monitor + vérifier + relancer ruflo.
- Pattern référent backend : `backend/shugu/routes/admin_users.py` (381 lignes).
- Pattern référent frontend : `frontend/src/app/[username]/admin/users/_client.tsx` (323 lignes) + `frontend/src/services/adminUsersClient.ts` (86 lignes).
- Best practices async logging : [DEV — Python Background Tasks Traps](https://dev.to/kaushikcoderpy/python-background-tasks-asyncio-traps-fastapi-celery-2026-381i), [FastAPI Best Practices — zhanymkanov](https://github.com/zhanymkanov/fastapi-best-practices).
