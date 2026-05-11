# Admin Pages — Template de pré-cadrage sub-projects B, C, D

**Date :** 2026-05-10
**Auteur :** Claude (rédigé pendant l'exécution ruflo du sub-project A Moderation)
**Statut :** Pré-cadrage — chaque sub-project doit faire son propre brainstorming complet avant impl

---

## Contexte

Page mocks identifiées en début de session : `analytics`, `moderation`, `schedule`, `community` (4 pages 100 % statiques sur 12 routes admin). Décision d'ordre validée par Sylvain :

```
A) moderation  → traité dans 2026-05-10-moderation-hub-pivot-design.md (PR en cours)
B) analytics   → ce template (pré-cadrage)
C) schedule    → ce template (pré-cadrage)
D) community   → ce template (pré-cadrage)
```

Le sub-project A sert de **golden path** : architecture validée, pattern reproductible.

---

## Pattern reproductible (golden path issu de A)

Chaque sub-project doit reproduire exactement la structure suivante :

### Backend

```
backend/shugu/
├── adapters/<feature>_xxx.py          # décorateur OU adapter (selon B/C/D)
├── services/<feature>_xxx.py          # queries SQL agrégées
├── routes/admin_<feature>.py          # routes /api/admin/<feature>/* gated require_operator
└── (app.py : wiring + include_router)

backend/tests/
├── unit/test_<feature>_xxx.py
├── integration/test_admin_<feature>_routes.py
└── conftest.py (fixtures partagées : db_session, operator_cookie, api_client)
```

### Frontend

```
frontend/src/services/admin<Feature>Client.ts    # wrapper fetch typé (mirror)
frontend/src/app/[username]/admin/<feature>/_client.tsx   # refonte (mock → branché)
frontend/src/app/[username]/admin/<feature>/page.tsx      # NON touché (wrapper SSR)
```

### Tests TDD strict

- Rouge → vert → commit, jamais modifier les tests pour passer.
- Coverage ≥ 90 % sur les 3 nouveaux modules backend.
- 1 test de sécurité non-régression : `test_*_rejects_member_cookie` (PII protection).
- 1 test idempotence pour chaque DELETE/POST sensible.

### Composants UI réutilisés (déjà dispo, ne PAS recréer)

- `AdminShell active="<feature>" title=... subtitle=...`
- `MetricTile` × 4 pour la KPI band
- `GlassSection`, `GlassRow`, `GlassPill`, `GlassButton`, `GlassTabs`, `GlassInput`, `GlassModal`
- `useToast` pour erreurs/success
- Pattern polling 30s : `useEffect` + `setInterval(load, 30_000)` + `clearInterval` au unmount

---

## Sub-project B — Analytics

### Pré-cadrage

**Status backend :** models `Visitor` et `Performance` existent dans `backend/shugu/db/models.py` (lignes 38, 49). **Probablement** déjà peuplés en production (le streamer IA tracke ses sessions/visiteurs). À confirmer en début de brainstorming.

**Données potentielles à afficher :**
- Total visites / jour / semaine / mois
- Durée moyenne de session visitor
- Top performances (vues, durée, engagement)
- Distribution des `identity_kind` (visitor anonyme vs member vs VIP)
- Heatmap horaire (à quelle heure les visiteurs viennent)
- Conversion visitor → member (email_verified ratio)

**Décisions à trancher en brainstorming (avant impl) :**

1. **Source de vérité metrics** : `Visitor`+`Performance` SQL directs, ou agrégations Prometheus déjà collectées (`MetricsRecorder`) ?
2. **Granularité temporelle** : 1h / 24h / 7j (cohérent avec Moderation A) ou plus fin (5min/1min) ?
3. **Définition "session"** : timeout d'inactivité côté `UserSession`, ou simple bornes start/end ?
4. **PII** : afficher `username` member en clair ? `ip_hash` ? Probablement OK pour operator vu que c'est moins sensible que moderation (pas de PII textuelle).
5. **Comparaison périodes** : KPIs "vs jour précédent" / "vs semaine dernière" ? Si oui, doubler les queries.

**Architecture suggérée :** PAS de decorator (les `Visitor`/`Performance` sont déjà persistés par le pipeline). Juste 1 service `analytics_queries.py` + 1 route `admin_analytics.py`. Plus simple que A.

**Estimation taille :** ~50-70 % du coût de A (pas de decorator à wirer dans `app.py`).

### Brainstorming requis avant impl

Lancer `superpowers:brainstorming` avec les 5 décisions à trancher ci-dessus comme questions.

---

## Sub-project C — Schedule

### Pré-cadrage

**Status backend :** AUCUN model existant. Migration Alembic obligatoire.

**Modèle proposé (à valider en brainstorming) :**

```python
class ScheduledStream(Base):
    __tablename__ = "scheduled_streams"
    id: str(26) primary key  # ULID
    title: str(200)
    description: text nullable
    starts_at: timestamptz NOT NULL
    duration_minutes: int NOT NULL
    status: str(16)   # 'planned' | 'live' | 'past' | 'cancelled'
    created_by: FK UserAccount(id) NOT NULL  # operator qui a planifié
    created_at: timestamptz default now()
    updated_at: timestamptz
```

**Décisions à trancher en brainstorming :**

1. **Timezone** : stocker UTC, afficher local ? Quelle TZ par défaut côté UI ?
2. **Récurrence** : streams récurrents (chaque mardi 21h) ou one-shot uniquement MVP ?
3. **Status auto-update** : un job qui passe `planned → live → past` ? Ou MVP en édition manuelle ?
4. **Notifications** : email/Discord/RSS quand `starts_at` approche ? Ou hors scope MVP ?
5. **Public read** : la liste doit-elle être visible côté viewer/visitor (calendar public) ? Ou strictement admin-only ?
6. **Liaison `Performance`** : un `ScheduledStream` est-il lié au `Performance` créé quand le stream démarre vraiment ? (`performance_id` nullable FK ?)

**Architecture suggérée :**
- Migration Alembic
- CRUD complet (5 routes : list, get, create, update, delete)
- Pas de decorator (pas de pipeline runtime)
- UI : calendar mensuel + form de création/édition

**Estimation taille :** ~140-160 % du coût de A (migration + CRUD complet vs juste read+1 delete sur A).

### Brainstorming requis avant impl

Plus structurant que B. Faire un brainstorming complet avec les 6 décisions ci-dessus.

---

## Sub-project D — Community

### Pré-cadrage

**Status backend :** AUCUN model. Scope FLOU — le mock UI actuel suggère "followers récents" + "raids" + "sub goals" + "top supporters" mais aucun de ces concepts n'existe en backend Shugu_stream.

**Question préalable critique (à poser avant tout brainstorming) :**

> "Community" pour ce projet, c'est quoi exactement ?
>
> - (1) Une liste des `UserAccount` actifs récemment (members + VIPs) — simple, recyclage de données existantes
> - (2) Un système de raids/shoutouts Twitch-like — nécessite intégration plateforme externe
> - (3) Un système de "supporters" avec tiers/badges — nouvelle économie produit, gros scope
> - (4) Un dashboard d'engagement social (follows/messages) — nécessite social data ingest
> - (5) Autre chose qui n'est pas encore dans la roadmap

**Si la réponse n'est pas claire pour Sylvain** : retirer D du backlog et le remettre dans `reference_phase_plan` comme "à cadrer plus tard". Mieux vaut 3 sub-projects bien faits qu'un 4ème inutile.

**Si la réponse est (1)** : c'est trivial — réutiliser le pattern `admin/users` existant avec filtre `last_seen_at > NOW() - INTERVAL '7 days'`. Pas un sub-project à part entière, fusion possible avec `users`.

**Si la réponse est (2/3/4)** : c'est un sub-project complet qui mérite son propre spec, plus large que A/B/C.

### Brainstorming requis avant impl

OBLIGATOIRE — pas de raccourci. Commencer par la "Question préalable critique" ci-dessus.

---

## Ordre d'exécution recommandé

Une fois A (Moderation) mergée :

1. **B Analytics** ensuite — coût bas, models déjà en place, fort retour produit (KPIs créateur).
2. **C Schedule** après — coût moyen, périmètre clair une fois la migration faite.
3. **D Community** en dernier OU à retirer du backlog si scope reste flou après questionnement Sylvain.

Chaque sub-project = 1 brainstorming complet → 1 spec → 1 plan → 1 délégation ruflo → 1 PR. Pas de mega-PR.

---

## Checklist par sub-project (à dérouler à chaque brainstorming)

- [ ] Lire le golden path : `docs/superpowers/specs/2026-05-10-moderation-hub-pivot-design.md`
- [ ] Vérifier en backend les models existants (`grep -n "class.*Base" backend/shugu/db/models.py`)
- [ ] Vérifier en backend si la table cible existe (`alembic` + `\d <table>`)
- [ ] Identifier les hooks "⚠️ adapter au projet" (auth, redis DI, etc.)
- [ ] Cadrer 4-6 questions structurantes (scope, decisions produit, sécurité)
- [ ] Proposer 2-3 approches d'archi avec recommandation
- [ ] Présenter design en sections (data model / API / UI / tests / error handling)
- [ ] Self-review du spec (placeholders, cohérence, scope)
- [ ] Faire valider le spec par Sylvain
- [ ] Écrire le plan d'implémentation (tasks bite-sized, TDD)
- [ ] Préalable manuel (ex. vérif migration) pour éliminer les ambiguïtés
- [ ] Déléguer à ruflo-autopilot avec briefing complet (contraintes mémoires)
- [ ] Monitor + relancer si stuck
- [ ] Review PR finale avec Sylvain

---

## Références

- Golden path : [Moderation Hub Pivot design](2026-05-10-moderation-hub-pivot-design.md) + [plan](../plans/2026-05-10-moderation-hub-pivot-plan.md)
- Mémoires : `feedback_modular_architecture`, `feedback_workflow_discipline`, `feedback_ruflo_workflow`, `feedback_chef_orchestre`
- Pattern référent backend : `backend/shugu/routes/admin_users.py`
- Pattern référent frontend : `frontend/src/app/[username]/admin/users/_client.tsx`
