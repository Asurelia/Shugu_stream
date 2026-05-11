# Admin Community — Décision : retirer du backlog actuel

**Date :** 2026-05-10
**Auteur :** Claude (décision tranchée en autonomie, mode "trancher avec rationale")
**Statut :** **Sub-project D REPORTÉ** — pas un MVP de cette session
**Sub-project :** 4/4 (suit A, B, C)

---

## Décision

**Retirer la page `/[username]/admin/community` du backlog `admin-pages` actuel.**

La page mockée reste en l'état (statique) jusqu'à ce que :
1. Une session dédiée cadre le scope avec Sylvain (réponse à la question préalable critique)
2. OU le besoin métier émerge concrètement avec des features spécifiques demandées par des utilisateurs réels

---

## Pourquoi retirer (pas juste reporter)

J'ai du mal à trancher D en autonomie **proprement** parce que la question préalable critique du template B/C/D (cf. § Sub-project D) reste ouverte :

> "Community" pour ce projet, c'est quoi exactement ?
>  - (1) Listing UserAccount actifs récemment
>  - (2) Raids/shoutouts Twitch-like
>  - (3) Système supporters avec tiers/badges
>  - (4) Dashboard d'engagement social
>  - (5) Autre chose pas dans la roadmap

Sans cette réponse, **tout choix d'archi serait du devinage** — exactement ce que je dois éviter selon mémoire `feedback_workflow_discipline` ("STOP si ambiguïté non couverte").

Le mode "trancher en autonomie" délégué par Sylvain reste valable, mais il a une limite : on tranche les **choix techniques sur un périmètre métier clair**, pas le **périmètre métier lui-même**. La sémantique d'une page admin est un choix produit, pas un choix dev.

---

## Hypothèses analysées (toutes rejetées en autonomie)

### Hypothèse 1 — Listing UserAccount actifs récemment

**Test de pertinence :** Doublonne `/admin/users` qui existe déjà et permet déjà de filtrer par `last_seen_at` (cf. `backend/shugu/routes/admin_users.py`).

**Verdict :** YAGNI. Ajouter un filtre `?last_seen_after=...` à `/admin/users` si besoin. Pas une page séparée.

### Hypothèse 2 — Raids / shoutouts Twitch-like

**Test de pertinence :** Le projet est "Streamer IA autonome" (mémoire `reference_phase_plan`). Twitch raids/shoutouts = pattern multi-créateurs humains. Le streamer IA Shugu n'a probablement pas d'autres streamers IA à raider, et inversement.

**Verdict :** Hors scope MVP du produit. À reconsidérer si Shugu intègre une plateforme externe (Twitch/YouTube live chat) où les raids physiques arrivent.

### Hypothèse 3 — Système supporters tiers/badges

**Test de pertinence :** Nouvelle économie produit (monétisation, paiement, gestion tiers). Le model `UserAccount.vip_since/vip_until` existe déjà = 2 tiers minimum (member/VIP). Ajouter "Supporter Bronze/Silver/Gold" sans signal de business besoin = over-engineering.

**Verdict :** Attendre que Sylvain ait une stratégie monétisation explicite. Pas un sub-project, c'est une roadmap.

### Hypothèse 4 — Dashboard engagement social

**Test de pertinence :** "Engagement" = quoi ? Nb follows ? Messages ? Reactions ? Aucune de ces données n'existe en backend Shugu. Ingérer depuis quelle plateforme ? Avec quelle authentification OAuth ?

**Verdict :** Trop d'inconnues. Multi-mois de travail produit avant d'avoir un MVP testable.

### Hypothèse 5 — Autre chose

**Test de pertinence :** Sans signal métier, je devinerais. Mémoire `feedback_workflow_discipline` interdit explicitement.

**Verdict :** STOP.

---

## Plan d'action concret

### Étape 1 — Conserver la page mockée

Pas de modification de `frontend/src/app/[username]/admin/community/_client.tsx`. La page existe en mock, c'est fine pour MVP : un dashboard admin avec 3 pages prod (Moderation, Analytics, Schedule) + 1 placeholder honnête vaut mieux qu'une 4ème page bricolée.

Optionnel : remplacer le mock par un placeholder transparent **"Communauté — à venir"** (1 GlassSection, 5 lignes), pour ne pas laisser le faux contenu mock induire en erreur. **Recommandation : ne pas faire ça non plus** — c'est un "Coming soon" qui viole le quality contract. Soit on fait, soit la page reste mockée comme aujourd'hui.

### Étape 2 — Ouvrir une issue de cadrage

À la fin de la session, créer une issue GitHub :

```
Title: [admin] Community page — needs product scope before implementation

Body:
The admin/community page is currently a static mock. We deliberately deferred
implementation in the 2026-05-10 session because the product scope is not yet
defined.

Before implementation, decide WHICH of the following Community means for Shugu:
- (1) Active users listing — likely redundant with /admin/users
- (2) Raids/shoutouts — requires external platform integration
- (3) Supporters tiers — requires monetization strategy
- (4) Engagement dashboard — requires social data ingestion
- (5) Other product scope

Decision blocked on: product strategy clarity.
Estimated effort once cadrage done: similar to Analytics B (sub-project ~3 days).
```

Plus utile qu'une page bidon prod.

### Étape 3 — Lever le report quand le scope est clair

Quand Sylvain a tranché entre (1)-(5) ou une variante :
1. Lancer un brainstorming dédié `superpowers:brainstorming`
2. Écrire le spec `docs/superpowers/specs/YYYY-MM-DD-admin-community-design.md`
3. Suivre le pattern golden path (A → B → C)
4. Déléguer à ruflo

---

## Conclusion

3 sub-projects prod-ready (A Moderation, B Analytics, C Schedule) > 4 sub-projects dont 1 bancal.

La discipline "STOP si ambiguïté" appliquée ici **est un succès du workflow**, pas un échec : on évite 1-2 jours de boulot qui aurait dû être jeté quand Sylvain aurait dit "non, je voulais autre chose".

Cette décision est cohérente avec :
- Mémoire `feedback_workflow_discipline` (STOP avant code sur ambiguïté)
- Mémoire `feedback_modular_architecture` (extensible — la page peut être ajoutée plus tard sans refacto)
- Standards globaux CLAUDE.md ("NEVER add placeholder code... If you don't know something, say it")

---

## Référence

Template B/C/D : [Admin Pages Template](2026-05-10-admin-pages-template-bcd.md) (section "Sub-project D — Community")
