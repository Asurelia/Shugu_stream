# AGENTS.md — Shugu_stream

> Briefing complet pour tout agent IA (Claude Code, Cursor, Copilot, etc.)
> qui travaille sur ce repo. Lis-moi en premier avant toute modification.

**Stack** : FastAPI + asyncio + Redis + Postgres (pgvector) + **Next.js 16 (App Router)** + React 18 + Three.js
**Mission** : VTuber AI live multi-visiteurs, opérateur Hermes (MiniMax M2.7) pilote avatar VRM via tool_calls, streaming TTS MiniMax/ElevenLabs/Edge, STT faster-whisper, scène 3D temps réel.
**Branche principale** : `main`
**Date d'écriture** : 2026-05-01 (post-audit Pass 2 Sprint 5) — màj migration Next.js 13→16 + App Router (2026-05-02)

---

## TL;DR — Ce qu'un agent doit savoir en 2 minutes

1. **Audit Pass 2 effectué** — lis `audit/PASS-2-CONSOLIDATION.md`. Tous les P0 sont éliminés. 16/36 P1 traités. 24 P2 et migration Next.js restent en backlog.
2. **Architecture en couches L0→L4** — `docs/layers/L0-FOUNDATION.md` est strict (allowlist d'imports). Ne PAS importer un layer haut depuis un layer bas.
3. **Tests réels uniquement** — TDD, pas de mock-driven. Si tu modifies un test pour le faire passer, tu casses la garantie.
4. **Branche systématique** — JAMAIS commit sur main directement. Format : `type/description-YYYYMMDD-HHMMSS-NNN`.
5. **Backend Python 3.13 + FastAPI moderne**, **frontend Next.js 16.2 (App Router)** — migration 13→16 + Pages Router → App Router complétée 2026-05-02 (PRs #76-#85).
6. **5 métriques Prometheus observables** sur `/metrics` — utilise-les, ne les casse pas.

---

## Architecture en bref

### Backend (`backend/shugu/`)

```
core/             # L0 — types, errors, identity, event_bus, protocols (Protocol structurels)
senses/           # L1 — bus, types, adapters chat/voice/event/vision
agent/            # L2 — runner, loop, llm_thinker, action_parser, handlers, tools
world/            # L3 — types, reducers, state_store, publisher
adapters/         # External services : MiniMax, ElevenLabs, Edge-TTS, Whisper, Hermes, etc.
auth/             # JWT operator + user (member/vip), dependencies FastAPI, rate_limit
routes/           # FastAPI endpoints (auth, account, admin_users, livekit, WS visitor/operator/world/voice/editor)
middleware/       # SecurityHeadersMiddleware (Helmet-style)
observability/   # MetricsRecorder Protocol + Null/Prometheus impls + structlog config
db/              # SQLAlchemy 2.0 async + Alembic migrations
director/        # Phase E4 — orchestrator + scene workers (LLM-driven scene composition)
memory/          # Phase 1.3 — MemoryAgent + MemoryService (pgvector recall, fact extraction)
persona/        # Phase 5.2 — Persona state + brain wiring
pipeline/       # workers (prep, picker, ingestion, extraction), voice_duplex, body_router
scene_composer/ # Phase E5 — authored scenes + player
```

### Frontend (`frontend/src/`)

```
features/        # Domain-driven : viewer-3d, scene-composer, scene-editor, desktop, etc.
app/             # Next.js 16 App Router (account/, admin/, vip/, [username]/, smoke/)
lib/             # Utilities, hooks, stores (Zustand)
components/      # Composants atomic + composés
```

---

## Audit Pass 2 — État après 5 sprints

| Catégorie | Initial | Restant |
|---|---|---|
| **P0** | 20 | **0** ✅ |
| **P1** | 36 | 20 (16 traités) |
| **P2** | 24 | 24 (cosmétiques) |
| Frontend deps | 25 vulns | 10 (need Next.js 13→16) |

### Ce qui a été fait (5 PR mergés)

- **#68 Sprint 1** : 8 P0 fixes structurels (DB pool, Mood/Emotion homonymes rename, JSON fanout pré-sérialisé, rate-limit /auth/login, révocation VIP JWT, Identity guards, silent failures workers, apply(action) typage)
- **#69 Sprint 2** : 6 P0 tests (jwt_tokens 18, user_tokens 17, dependencies 20, /auth/* E2E 17, injection_detector 58, moderation_basic 20)
- **#70 Sprint 3** : 5 P1 sécurité (JWT secrets fail-fast, rate-limit /api/account/login, deactivate revoke JWT, security headers middleware, leaks process bornés)
- **#71 Sprint 4** : 7 P1 STT chain + observability (STTError, 4 métriques Prometheus, narrow except hermes_state/logout/picker)
- **#72 Sprint 5** : 5 P1 sécurité avancé (BrainError re-raise, narrow tool parse, moderation fail-open observability, wiring persona/memory metrics)

### 5 métriques Prometheus exposées en `/metrics`

| Counter | Wirée dans | Quoi mesurer |
|---|---|---|
| `tts_fallback_total{from_provider, to_provider}` | `FallbackTTS` | Bascule TTS primary → secondary |
| `event_bus_drop_total{topic}` | `InProcessEventBus` | Drop-oldest sur slow consumer |
| `persona_fallback_total{from_persona, to_persona}` | `HermesEmbodiedBrain` | Persona fallback `hermes_public` → `shugu` |
| `memory_recall_failed_total{error_kind}` | `Orchestrator` | Crash recall pgvector/embedder |
| `moderation_ban_check_failed_total{error_kind}` | `BasicModeration` | Ban check Postgres fail-open |

Plus les 6 compteurs Phase 8.2 (agent_runner_*, world_delta_*, sense_events_*).

### Backlog identifié à traiter ensuite

#### ~~P1 type-design (~4h)~~ ✅ Fait Sprint 6 PR #75
- `core/types.py` : `Subject`, `UserId`, `SessionId`, `OperatorUsername` (NewType de str, zéro overhead runtime).
- Helpers `make_visitor_subject` / `make_member_subject` / `make_vip_subject` / `make_operator_subject` — lowercase + valident non-vide.
- Wired dans 5 call-sites prod : `operator_ws.py`, `operator_voice_ws.py`, `visitor_ws.py`, `internal_vip.py` (×2), `director/orchestrator.py`. Élimine la duplication des conventions `f"<role>:{x.lower()}"`.
- `derive_viewer_subject` retourne `Optional[Subject]` mais préserve la casse (le persona store `relationships` est keyed en raw — lowercaser casserait les states legacy). Documenté.
- Mypy non gaté en CI : ces NewType sont une documentation type pour qui lance mypy localement et un point central pour les futurs callsites.

#### ~~Tests `/api/account/*` E2E (~3-4h)~~ ✅ Fait Sprint 6 PR #74
Routes user (register, verify-email, login user, refresh user, logout user, me user) couvertes par 38 tests E2E avec `_FakeDB` stateful in-memory. Voir `backend/tests/integration/test_account_routes.py`.

#### 11 silent failures Cat C (légitimes mais à observer)
Fallbacks documentés mais qui auraient besoin de métriques additionnelles ou de narrow except. Voir `audit/pass2-silent-failures.md` section Cat C.

#### 24 P2 (cosmétiques)
Timing oracles d'énumération, micro-optims perf (asyncio.Lock contention, snapshot world cache), 5 type-design suggestions, 2 tests fragiles. Voir `audit/PASS-2-CONSOLIDATION.md`.

#### ~~Migration Next.js 13 → 16~~ ✅ COMPLÉTÉE (2026-05-02)

**Phase 1 (bumps Next)** : PRs #76 (CI frontend) → #77 (Next 14) → #78 (Next 15) → #79 (Next 16 + remove `publicRuntimeConfig`). 0 critical CVEs (les 2 Next CRITICAL éliminés ✅). Reste 5 moderate (dompurify dans @charcoal-ui/icons, postcss devDep).

**Phase 2 (App Router)** : PRs #80 (bootstrap layout) → #81 (auth pages) → #82 (public pages) → #83 (scene-composer redirect) → #84 (10 admin pages) → #85 (root + cleanup). 100% des pages migrées de Pages Router vers App Router. Pattern Server shell + Client island appliqué partout. `pages/` directory supprimé.

**Phase 3 (Three.js)** : 0.149 → 0.160+ (44 fichiers, sprint séparé). Pas commencé. Voir `docs/findings/2026-05-02-three-stale-version.md`.

Plan complet : `C:\Users\rafai\.claude\plans\velvety-skipping-penguin.md`.
Findings collectés en chemin : `docs/findings/INDEX.md`.

---

## Règles de modification — NON NÉGOCIABLES

### 1. Branche systématique
```bash
git checkout -b type/description-$(date +%Y%m%d-%H%M%S)-001
```
Types : `feat`, `fix`, `chore`, `docs`, `test`, `refactor`. **Jamais** commit direct sur `main`.

### 2. Verification before completion
- Run les tests **après** chaque modification (`pytest backend/tests/unit/test_<module>.py`)
- Run `ruff check shugu tests alembic` depuis `backend/` avant de commit
- Si tu ne peux pas tester quelque chose (UI, externe), **dis-le explicitement** dans le commit message

### 3. TDD réel
- Écrire le test **avant** la fix quand un bug est identifié
- **Ne jamais** modifier un test pour qu'il passe — c'est une régression silencieuse
- Si un test pré-existant casse à cause de ta modif, comprends pourquoi avant de l'ajuster

### 4. Code complet
- **Pas de stubs**, pas de TODO planted, pas de "rest remains the same"
- Si tu touches un fichier, lis-le **entièrement** d'abord
- Pas de `pass` silencieux dans un except — toujours log au moins en debug

### 5. Architecture en couches
- `core/` (L0) ne peut PAS importer depuis `agent/`, `pipeline/`, `routes/`, etc.
- Les Protocols vivent dans `core/protocols.py`. Les implémentations satisfont par structural typing.
- L'allowlist d'imports cross-layer est testée dans `tests/unit/test_arch_layers_l0.py`

### 6. Sécurité par design
- Tout secret en `Settings` avec validator fail-fast en prod
- Toute route admin avec `Depends(require_operator)`
- Tout fanout JSON sur WS via `_ws_serializer.serialize_cached`
- Toute construction `Identity` (`OperatorIdentity`, `MemberIdentity`, `VIPIdentity`) **sauf** via les dépendances FastAPI auth.* — sinon les `__post_init__` lèvent

---

## Patterns à respecter

### Logger
```python
import structlog
log = structlog.get_logger(__name__)
log.warning("event_name", key1=value1, key2=value2)  # event_name en snake_case
```

### Métriques (injection Recorder)
```python
class MyService:
    def __init__(self, ..., metrics: "MetricsRecorder | None" = None):
        if metrics is None:
            from ..observability.metrics import get_null_recorder
            metrics = get_null_recorder()
        self._metrics = metrics

    async def do_thing(self) -> None:
        try:
            ...
        except Exception as exc:
            self._metrics.record_failure(error_kind=type(exc).__name__)
            raise  # ou pas selon politique
```

### Async lifecycle worker
```python
async def stop(self) -> None:
    self._running = False
    if self._task is not None and not self._task.done():
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass  # attendu
        except Exception as exc:
            log.exception("worker.stop_failed: %s", exc)
    self._task = None
```

### Erreurs typées
```python
# core/errors.py
class ShuguError(Exception): pass
class BrainError(ShuguError): pass
class TTSError(ShuguError): pass
class STTError(ShuguError): pass
class AuthError(ShuguError): pass
class ModerationReject(ShuguError): pass
```
**Re-raise typé** > return string vide. Le caller a la responsabilité de feedback user.

### Rate-limit (helper réutilisable)
```python
from ..auth.rate_limit import enforce_rate_limit
await enforce_rate_limit(redis, key=f"shugu:ratelimit:foo:{ip_h}", limit=10, window_s=900, log_on_burst=5)
```

---

## Pièges à éviter (leçons apprises)

### 1. Identity validators (P0.T4 Sprint 1)
`VIPIdentity.__post_init__` exige `user_id`, `username`, `jti`. Mais **PAS** `vip_since` (n'est pas dans le JWT par design — voir docstring `user_tokens.py:78`). Régression introduite et attrapée par tests Sprint 2 P0.A4.

### 2. Mood / Emotion homonymes (P0.T1/T2 Sprint 1)
Avant Sprint 1 : 3 vocabulaires `Mood` disjoints sous le même nom (`world.types.Mood`, `core.body_control.Mood`, `core.mood.MoodState`). Un import dans le mauvais fichier passait mypy mais crashait au runtime. Désormais : `WorldMood` / `BodyMood` distincts + alias rétro-compat.

### 3. JSON fanout (P0.P2 Sprint 1)
`json.dumps(event)` dans une boucle subscriber WS = O(N viewers × payload). Toujours utiliser `serialize_cached(event, cache)` du module `routes/_ws_serializer.py` pour fanout sur les topics chauds (stage, world.delta).

### 4. Exception in fire-and-forget tasks (Sprint 5 review)
`asyncio.create_task(coro)` sans handler `add_done_callback` → exception silently lost. Toujours wrap dans une coro locale qui catch + envoie un event d'erreur au client (cf. `routes/operator_ws.py:_run_with_failure_event`).

### 5. Cookies Secure=True en TestClient
`TestClient(app)` ne renvoie pas les cookies Secure sur HTTP. Utiliser `TestClient(app, base_url="https://testserver")` pour les tests E2E auth.

### 6. CI vs venv local
`cachetools` était dispo localement via une autre install transitive mais pas déclaré dans `pyproject.toml`. CI fail. **Toujours** déclarer les deps explicitement, pas hériter implicite.

### 7. CI livekit.agents optionnel
`livekit.agents` n'est pas dans la CI minimale (pas dans `dependencies`, juste via worker VIP optionnel). Tests qui importent `shugu.adapters.stt_livekit_adapter` doivent `pytest.importorskip("livekit.agents")`.

### 8. Pydantic field_validator order
`field_validator` ne voit que les fields **déjà validés**. Si tu valides un field qui dépend d'un autre défini plus loin dans le model, utilise `model_validator(mode="after")`. Cf. `Settings._validate_jwt_secrets`.

### 9. Mocking session_scope
Les tests qui touchent un endpoint avec DB doivent monkeypatch `session_scope` au niveau du module `shugu.db.session`, pas du module qui importe (les imports sont bind-time). Pattern :
```python
@asynccontextmanager
async def fake_session_scope():
    sess = MagicMock()
    sess.execute = AsyncMock(return_value=...)
    yield sess
monkeypatch.setattr("shugu.db.session.session_scope", fake_session_scope)
```

---

## Workflows de dev

### Lancer le backend en local
```bash
cd backend
.venv/Scripts/activate.bat   # Windows
python -m uvicorn shugu.app:app --reload --port 8701
```

### Lancer les tests backend
```bash
cd backend
python -m pytest tests/unit/ -q                                     # tests unit
python -m pytest tests/integration/ -q                              # tests intégration (besoin Postgres + Redis)
python -m pytest tests/unit/test_<module>.py -v --tb=short          # debug ciblé
```

### Lint
```bash
cd backend
ruff check shugu tests alembic                                      # OBLIGATOIRE avant commit
ruff check shugu tests alembic --fix                                # auto-fix imports/style
```

### Lancer le frontend
```bash
cd frontend
npm install                                                          # 1 fois
npm run dev                                                          # http://localhost:3005
npm run build                                                        # smoke test prod
npm run lint                                                         # next lint
npx tsc --noEmit                                                     # type-check
```

### Workflow Git typique
```bash
git checkout main && git pull
git checkout -b feat/my-feature-$(date +%Y%m%d-%H%M%S)-001
# ... edit code, run tests, lint
git add -A
git commit -m "✨ feat(scope): description courte

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
git push origin feat/my-feature-...
gh pr create --title "..." --body "..."
```

---

## Index documentaire

- `ARCHITECTURE.md` — vue système end-to-end (300+ lignes)
- `DEPLOY.md` — déploiement VPS + Docker
- `LAUNCHER.md` — script de boot dev (Redis, Postgres, services)
- `CHANGELOG.md` — historique versions
- `docs/layers/L0-FOUNDATION.md` — règles d'allowlist d'imports
- `docs/PHASE1-FOUNDATION.md` — décisions Phase 1
- `docs/MEMORY_ARCHITECTURE.md` — système mémoire pgvector
- `audit/PASS-1-RAPPORT.md` — outils statiques
- `audit/PASS-2-CONSOLIDATION.md` — synthèse 80 findings + plan Sprint 1-5
- `audit/pass2-{security,silent-failures,performance,type-design,test-coverage}.md` — rapports individuels

---

## Réfs externes / Conventions

- **TypeScript strict** des deux côtés
- **Pydantic v2** + `model_config = SettingsConfigDict(...)`
- **SQLAlchemy 2.0 async** (jamais 1.x sync style)
- **structlog** > logging stdlib (event_name structuré)
- **bcrypt rounds=12** (production) / **rounds=4** (tests rapides)
- **JWT HS256** + JTI Redis revocation set, rotation atomique sur refresh
- **Cookies HttpOnly + Secure + SameSite=strict**
- **CSP + HSTS prod + X-Frame-Options DENY** via `SecurityHeadersMiddleware`
- **better-profanity** pour filtrage langue (~1300 mots EN)
- **fastembed** pour embeddings (intfloat/multilingual-e5-large, 1024 dim)

---

## Si tu hésites

1. Lis le rapport d'audit pertinent dans `audit/`
2. Lis l'ARCHITECTURE.md pour le contexte système
3. Cherche un pattern existant (rate_limit, security_headers) — on a déjà fait ce genre de truc
4. **Demande à l'utilisateur** plutôt que d'inventer un comportement
5. **Toujours** un test, toujours un commit propre, toujours une branche

---

**Dernière mise à jour** : 2026-05-01 post-Sprint 5 PR #72.
**Prochaine grosse étape** : Three.js 0.149 → 0.160+ (Phase 3) OU s'attaquer aux 11 silent failures Cat C / 24 P2 OU les 48 violations React Hooks strict (cf `docs/findings/2026-05-02-react-hooks-strict-rules-next16.md`).
