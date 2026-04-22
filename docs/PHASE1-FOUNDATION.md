# Phase 1 — Fondation Streamer IA autonome

> **Branche** : `feat/autonomous-phase1-foundation-20260422-212210-001`
> **Plan source** : `C:\Users\rafai\.claude\plans\ultrathink-il-va-faloir-misty-dahl.md`
> **Inspiration** : `F:\Dev\Project\Project_cc` (agent CLI TypeScript — *patterns portés, pas code*)

---

## Pourquoi cette phase ?

Shugu_stream v4 Phase 3a livrait un VTuber IA single-path :
`visitor|operator → BrainAdapter → TTS → Picker → clients WS`.

La vision "streamer IA autonome" introduit plusieurs **boucles spécialisées**
(mémoire long-terme, régie, senses multiples) qui doivent coexister sans
multiplier les agents LLM. La Phase 1 pose les **fondations techniques** qui
permettront à ces boucles d'arriver dans les Phases 2-8 sans refactor majeur.

**Règle cardinale** (rappelée partout dans le code) :

> Les *senses*, *régie*, *memory* sont des **services** Python (pas des agents
> LLM). Il n'y a qu'**UNE SEULE** chaîne de cognition LLM, invoquée via le
> `BrainAdapter` Protocol existant. Le **Picker reste serial et unique** —
> la sortie scénique unique est déjà garantie.

---

## 4 briques livrées dans cette phase

### Brique 1.1 — Event bus distribué (Redis pub/sub hybride)

**Fichiers** : `backend/shugu/core/event_bus_redis.py`, `event_bus_factory.py`
+ hooks dans `config.py`, `app.py`.

**Quoi** : un `RedisEventBus` drop-in pour `InProcessEventBus` qui garde la
latence locale (`asyncio.Queue` direct) mais ajoute un fanout Redis pub/sub
pour les topics qui doivent traverser les process (ex : `vip.events` entre
le Worker LiveKit et le backend).

**Pourquoi hybride plutôt que tout-Redis** :
- Le topic `"stage"` transporte des chunks audio MP3 en bytes → pas JSON,
  doit rester intra-process. Le constructeur refuse `"stage"` dans
  `broadcast_topics`.
- Les hot paths (Picker → clients WS) gagnent en latence avec le fast path
  local (~µs vs ~ms avec Redis).

**Invariants** :
- Un event `publish()` est délivré à tous les subs locaux **UNE FOIS**
  (jamais deux, même si le fanout Redis le renvoie → filtré par uuid).
- Les payloads non-JSON (bytes) sont droppés du fanout avec warning mais la
  livraison locale passe.

**Activation** : `EVENT_BUS_MODE=redis` dans `.env`. Par défaut `inproc`
(compatible pré-Phase 1).

### Brique 1.2 — VIP bridge (vip_agent ↔ backend)

**Fichiers** : `backend/shugu/core/vip_bridge.py`,
`backend/shugu/routes/internal_vip.py`,
`backend/shugu/adapters/vip_bridge_client.py`.

**Problème** : le Worker `vip_agent.py` tourne dans son propre process Python
(design imposé par LiveKit Agents SDK). Il n'a **pas** accès à `_redis`, au
bus, aux sessions DB du backend. Sans bridge, il est aveugle.

**Solution** : HTTP localhost signé (shared secret `X-Internal-Secret` comparé
via `hmac.compare_digest`). Deux endpoints :

- `POST /internal/vip/event` — events one-way (`participant_joined`,
  `session_started`, etc.) republiés sur le topic bus `vip.events`.
- `POST /internal/vip/tool` — tool calls avec réponse.
  Phase 1 implémente **`chat.post`** seulement — enqueue le message dans la
  priority queue (tier=1), respectant l'invariant "toute production scénique
  passe par le Picker". `body.gesture` et `mood.set` retournent **501** —
  signal clair que la capability est réservée pour Phase 2.

**Client** : `VipBridgeClient` dans le process vip_agent, avec retry
exponentiel (3 tentatives, ~0.2-0.8s) et gestion propre des 4xx (erreur
caller, pas de retry) vs 5xx/timeouts (retry).

**Fail-closed** : si `VIP_INTERNAL_SECRET` est vide dans `.env`, les routes
retournent systématiquement 401 (pas d'endpoint ouvert en prod par accident).

### Brique 1.3 — MemoryAgent skeleton + pgvector

**Fichiers** : `backend/shugu/memory/{__init__,types,models,agent}.py`
+ `backend/alembic/versions/0005_memory_agent.py`
+ hooks dans `config.py`, `app.py`, `alembic/env.py`.

**Quoi** : un `MemoryAgent` coordinateur unique pour le stockage long-terme :
- 3 tables (`memory_facts`, `memory_relations`, `persona_state`)
- pgvector extension + colonne `embedding vector(1024)` (nullable Phase 1)
- pg_trgm extension + index GIN pour le recall keyword Phase 1
- API `store() / recall() / maintenance() / persona_get() / persona_set()`

**Décisions figées** :
- Dim embedding = **1024** (bge-m3). Changer = migration explicite +
  plan de re-embed.
- **Pas d'index hnsw Phase 1** (zéro données — inutile). Sera créé Phase 2
  après le premier seed.
- Recall Phase 1 = `ILIKE` + `pg_trgm`. Phase 2 basculera sur cosine distance
  sur l'embedding.

**Principes respectés** :
- Le `MemoryAgent` n'appelle JAMAIS de LLM — c'est un coordinateur DB pur.
  L'extraction LLM-assistée (regex → LLM fallback) arrive Phase 2 via un
  `BrainAdapter` dédié.
- `session_factory` est injecté (pas importé) → mockable en tests sans DB.

**Activation** : `MEMORY_ENABLED=false` par défaut Phase 1. L'agent est
instantié dans le lifespan mais aucun brain ne l'appelle encore. Phase 2
flippera le flag + branchera `recall()` dans `brain_shugu.respond()`.

### Brique 1.4 (partielle) — Bootstrap tests + CI skeleton

**Fichiers** : `backend/pyproject.toml` (config tool),
`backend/tests/{__init__,conftest,unit,integration}/`,
`.github/workflows/ci.yml`.

**Quoi** : poser la rigueur tests/CI avant le reste — aucune brique Phase 1
ne pouvait atterrir sans harness pour vérifier qu'elle ne régresse pas
l'existant. Le CI actuel lint les nouveaux fichiers + lance les tests unit
sur push/PR. **La finalisation (services Postgres + Redis en CI pour les
tests d'intégration) est `Brique 1.4 finalisation` — tâche pending.**

**Gains annexes de la phase** : 3 dépendances sous-déclarées du projet
existant ont été trouvées et ajoutées à `pyproject.toml` (jinja2,
pydantic[email], livekit-api) — le test de smoke `test_sanity_boot_imports_app_ok`
les a capturées.

---

## Diagramme cible (projeté après Phases 2-8)

```
    ┌─────────────── SENSES (workers, pas LLM agents) ──────────────────┐
    │ chat visitor │ chat VIP │ voice opérateur │ voice VIP │ ambient   │
    └────────────────────────────┬───────────────────────────────────────┘
                                 │
                                 ▼ events (RedisEventBus topics)
                  ┌─────────────────────────────────┐
                  │  STAGE DIRECTOR (Phase 3)       │
                  │  arbitre → priority_tier        │
                  └────────┬────────────────────────┘
                           │
                           ▼ RedisQueue.enqueue_ready(msg, tier)
                  ┌─────────────────────────────────┐
                  │  PRIORITY QUEUE (existante)     │
                  └────────┬────────────────────────┘
                           │
                           ▼ Picker.pop_ready()  ← UNIQUE dequeuer serial
                  ┌─────────────────────────────────┐
                  │  PICKER (existant, préservé)    │
                  └────────┬────────────────────────┘
         ┌─────────────────┴──────────┐
         ▼ (cognition)                ▼ (TTS stream)
┌─────────────────────┐  ┌────────────────┐
│  BRAIN ADAPTER      │◄─┤  MEMORY AGENT  │ ← Phase 1 Brique 1.3 (tables prêtes)
│  (unique LLM path)  │  │  (Phase 2)     │
└─────────────────────┘  └────────────────┘
```

---

## Comment reviewer cette phase (guide débutant)

1. **Commencer par ce doc** (vous y êtes).
2. **Lire le plan d'architecture** : `C:\Users\rafai\.claude\plans\ultrathink-il-va-faloir-misty-dahl.md`.
3. **Parcourir les 4 briques** dans cet ordre :
   - `backend/shugu/core/event_bus_redis.py` (le + pédagogique — patterns async/await, drop-oldest)
   - `backend/shugu/memory/agent.py` (exemple de service coordinateur sans LLM)
   - `backend/shugu/core/vip_bridge.py` + `routes/internal_vip.py` (HTTP signé + fail-closed)
   - `backend/alembic/versions/0005_memory_agent.py` (migration pgvector)
4. **Lire les tests** pour comprendre les invariants garantis :
   - `backend/tests/unit/test_event_bus_*.py`
   - `backend/tests/unit/test_memory_agent.py`
   - `backend/tests/unit/test_vip_bridge_*.py`
5. **Lancer localement** :
   ```bash
   cd backend
   python -m venv .venv
   .venv/Scripts/pip install -e '.[dev]'
   .venv/Scripts/pytest tests/unit/ -v
   ```
6. **Voir le boot** : `backend/shugu/app.py` lifespan est l'ordre de wiring
   — les commentaires `# Phase 1 Brique X.Y` signalent les nouveaux blocs.

---

## Ce qui **reste** à faire en Phase 1 (backlog)

- **Brique 1.4 finalisation** : ajouter services Docker (redis + pgvector)
  au workflow Actions pour activer les tests integration.
- **Cleanup lint existant** (tâche dédiée, ~90 erreurs pré-existantes dans
  `backend/shugu/` — auto-fixable majoritairement).
- **Intégration concrète `vip_agent.py` → `VipBridgeClient`** : actuellement
  le bridge est prêt des deux côtés, mais le Worker n'appelle pas encore
  `emit_event(participant_joined)`. Petit brick de suivi à prévoir.

---

## Liens utiles

- `ARCHITECTURE.md` (racine) — vue d'ensemble pré-Phase 1
- `DEPLOY.md` (racine) — setup VPS + locaux
- `CHANGELOG.md` (racine) — historique des phases
- `backend/shugu/core/event_bus.py` — InProcessEventBus (pattern originel,
  non modifié Phase 1 — le RedisEventBus l'étend sans le remplacer)
