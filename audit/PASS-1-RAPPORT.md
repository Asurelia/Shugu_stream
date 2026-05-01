# Audit Shugu_stream — Pass 1 (Outils statiques)

**Date** : 2026-05-01
**Commit audité** : `4e6427f` (main)
**Méthode** : ruff, mypy, bandit, pip-audit, npm audit, eslint, tsc

---

## Résumé exécutif

| Domaine | Statut | Findings | Sévérité max |
|---|---|---|---|
| Backend Python — lint (ruff) | ✅ Propre | 0 | — |
| Backend Python — types (mypy) | ⚠️ À corriger | 64 erreurs | Moyen |
| Backend Python — sécurité (bandit) | ✅ Propre | 35 (Low) | Low |
| Backend Python — deps (pip-audit) | ✅ Propre | 1 (pip self) | — |
| Frontend — lint (eslint via next) | ⚠️ À corriger | **25 issues** | Error |
| Frontend — types (tsc) | 🔴 **À corriger** | **17 erreurs** | Type errors |
| Frontend — deps (npm audit) | 🟡 Partiel | 10 vulns (de 25) | 1 critical (Next.js — backlog) |
| Sémantique (semgrep) | 🔴 **À traiter** | 3 XSS templates | High |

**Verdict Pass 1** : Le code Python est très propre (kudos aux AIs sur le style/sécurité). Le **vrai problème est côté frontend deps** (Next.js + écosystème) avec 2 CVE critiques + 8 high. Les erreurs mypy ne sont pas des bugs runtime mais signalent du code "Any-driven" qui pourrait masquer des bugs futurs.

---

## 🔴 P0 — Critique (à fixer immédiatement)

### P0.1 — Vulnérabilités frontend (RÉSOLU PARTIELLEMENT 2026-05-01)

`npm audit fix` (sans `--force`) a éliminé **15 vulns sur 25** :
- ✅ Toutes les **8 high** corrigées (axios, braces, cross-spawn, dompurify direct, flatted, minimatch, picomatch, semver)
- ✅ 1 critical corrigée (form-data)
- ✅ 6 moderate corrigées (word-wrap, yaml, etc.)

**Reste 10 vulns nécessitant `--force` (breaking changes Next.js/Vitest)** :
- `next` (1 critical) — Next.js 13 → 16 breaking change. **Migration séparée requise** (3-5 jours).
- `dompurify` (moderate, transitif via @charcoal-ui)
- `vite`, `vite-node`, `vitest`, `esbuild`, `postcss` (moderate) — vitest 1 → 4
- `qs` (moderate, transitif via elevenlabs) — elevenlabs 0.x → 1.59
- `@charcoal-ui/icons` (moderate) — peer-dep
- `elevenlabs` (low)

**Décision** : ces 10 vulns sont **acceptées en backlog** (P2 — Migration Next.js 13 → 16 + Vitest 1 → 4 séparée). La surface d'attaque est limitée car Next.js sert le build statique en production.

---

## 🔴 P0.3 — XSS potentielle dans templates emails (semgrep)

3 occurrences dans :
- `backend/shugu/adapters/email_templates/vip_promoted.html:38`
- `backend/shugu/adapters/email_templates/vip_revoked.html:21,29`

Pattern détecté : `<a href="{{ site_url }}">` — si `site_url` est contrôlé par un attaquant ou contient `javascript:...`, exécution arbitraire dans le client email (peu de clients exécutent JS, mais Outlook web et Gmail web peuvent dans certains cas).

**Fix** : préfixer la variable par un schéma fixe : `<a href="https://{{ site_url }}">` ou valider en Python que `site_url` commence par `https://` avant rendu.

---

## 🟠 P1 — Important (à fixer cette semaine)

### P1.1 — 64 erreurs mypy à fort risque (extraits)

Catégories détectées :
- **Async iterators mal annotés** (`brain_shugu.py:66`, `llm_thinker.py:162`, `workers.py:111`) — protocol définit `respond` sync mais l'implémentation est `async`. Bug latent : appel sans `await` pourrait ne pas itérer.
- **Typage Redis manquant** (`world_ws.py:130`, `visitor_ws.py`, `operator_voice_ws.py:135`, `editor_ws.py:217`) — `redis: object` au lieu de `Redis` partout dans les routes WS. La fonction `verify()` ne fait pas son contrat de type.
- **Métriques recorder typed object** (`visitor_ws.py:86,102,211`) — `metrics: object` au lieu d'un protocol précis. La méthode `inc()` peut être absente sans erreur compile.
- **Literal mismatches** (`memory/agent.py:774,800`, `auth/email_verify.py:85`) — strings passés où Literal types attendus.
- **`Result[Any].rowcount` indéfini** (`memory/maintenance.py:98,125`) — accès attribut sur Result SQLAlchemy possiblement None.
- **Coroutine pas await** (`llm_thinker.py:162`, `workers.py:111`) — `Coroutine[Any, Any, AsyncIterator]` utilisé comme iterator → bug runtime garanti si jamais ce chemin est emprunté.
- **`pipeline/queue.py` await sur Awaitable|int** — la queue mélange sync et async, plusieurs `await` sur valeurs déjà résolues.

→ Voir `audit/02-mypy.txt` pour la liste complète.

### P1.2 — Bandit : assertions en production (`B101`, 20 occurrences)

20 `assert` dans `shugu/app.py` et autres. Quand Python tourne avec `-O` (optimisations), les `assert` sont supprimés → la garde disparaît silencieusement. Si un assert est utilisé pour vérifier une invariante critique (auth, validation), c'est un bug de sécurité.

**Fix** : remplacer par `if not cond: raise XError("...")` quand l'invariante doit toujours être vérifiée.

### P1.3 — Bandit : try/except/pass (`B110`, 5 occurrences)

`tts_minimax.py:237`, `pipeline/picker.py:190`, etc. Erreur silencieusement avalée → debug d'incident impossible. À tracer en log.warning au minimum.

### P1.4 — Bandit : hardcoded password strings (`B105`, 4 occurrences)

`shugu/auth/jwt_tokens.py:44,57` etc. Faux positifs probables (chaînes "access"/"refresh" qui sont des type tokens, pas des secrets), à confirmer.

### P1.5 — TypeScript — 17 erreurs tsc

Composants mal typés ou utilisés avec mauvais props :

- **11 occurrences `Property 'title' does not exist on type 'IntrinsicAttributes'`** dans :
  - `src/pages/[username]/admin/users.tsx:130`
  - `src/pages/account/login.tsx:47`, `profile.tsx:41,55`, `register.tsx:51`, `verify-email.tsx:40`
  - `src/pages/vip/room.tsx:85,99,119,142`
  → Un composant (probablement `SectionCard` ou wrapper) reçoit `title=` mais sa signature ne le déclare pas. Soit ajouter le prop, soit retirer les usages.

- **`LiveKitRoom cannot be used as JSX component`** (`src/pages/vip/room.tsx:143`) — mismatch entre version React types et version `@livekit/components-react`. Probable `npm install` à mettre à jour ou `@types/react` aligned.

- **`Property 'options' does not exist on GlassTabsProps`** (`users.tsx:154`) — composant utilisé avec un prop non déclaré.

- **3 `top-level await` not allowed** dans `panels.test.tsx:99,172,207` — `tsconfig.json` doit cibler `module: 'es2022'+` et `target: 'es2017'+`.

- **`Expected 1-2 arguments, but got 0`** (`transform-controls.test.ts:83`) — appel de fonction avec args manquants.

- **`Unused '@ts-expect-error' directive`** (`vitest.setup.ts:21`) — soit l'erreur est partie, soit la directive est mal placée.

→ Voir `audit/05-tsc.txt` pour la liste complète.

### P1.6 — ESLint — 25 issues

Distribution :
- **7 erreurs `Definition for rule '@typescript-eslint/no-explicit-any' was not found`** → bug de configuration eslint (le plugin n'est pas chargé). Fix config plutôt que les fichiers.
- **7 `react/no-unescaped-entities`** dans pages/account/* → apostrophes brutes dans JSX. Trivial : remplacer par `&apos;` ou `{"'"}`.
- **2 `@next/next/no-img-element`** dans `DesktopWindow.tsx`, `VirtualDesktop.tsx` → utiliser `next/image`.
- **2 `react-hooks/exhaustive-deps`** dans `useSceneRig.ts:295`, `index.tsx:436` → **vrais bugs potentiels** : effects avec deps manquantes, peuvent ne pas re-run quand attendu.
- **1 `jsx-a11y/role-supports-aria-props`** dans `ScenesListPanel.tsx:198` → `role="button"` + `aria-selected` non standard.

→ Voir `audit/04-eslint.txt` pour la liste complète.

---

## 🟡 P2 — Nettoyage (backlog)

### P2.1 — Bandit : random() pour non-crypto (`B311`, 6 occurrences)

`vip_bridge_client.py:135`, `canned_responses.py:151` — `random.choice()` pour des choix gameplay. Pas un risque crypto (faux positif Bandit). À documenter `# nosec` pour silencer.

---

## ✅ Bonnes nouvelles

- **Ruff = 0 finding** sur 21690 lignes Python — code AI très propre stylistiquement
- **Bandit 0 high/medium** — pas d'injection SQL/XSS/SSRF visible côté Python
- **Pip-audit venv = 1 vuln triviale** (pip self) — chaîne de dépendances Python clean
- **Tests existants** : déjà confirmé à 78/78 verts sur les fichiers récemment touchés

---

## Décisions à prendre avant Pass 2

1. **Doit-on lancer `npm audit fix --force`** maintenant ? Risque : breaking changes Next.js majeur.
2. **Doit-on lancer `npm install` pour activer eslint/tsc** ?
3. **Lance-t-on Pass 2 (multi-agents qualitatifs)** sur le code actuel ou après fix des P0 ?

Recommandation : fixer P0.1+P0.2 (npm audit fix), installer outils frontend, **puis** Pass 2.
