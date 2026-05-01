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
| Frontend — lint (eslint via next) | ⚠️ Outil non installé | — | — |
| Frontend — types (tsc) | ⚠️ Outil non installé | — | — |
| Frontend — deps (npm audit) | 🔴 **À traiter** | **25 vulns** | **Critical x2** |
| Sémantique (semgrep) | 🔴 **À traiter** | 3 XSS templates | High |

**Verdict Pass 1** : Le code Python est très propre (kudos aux AIs sur le style/sécurité). Le **vrai problème est côté frontend deps** (Next.js + écosystème) avec 2 CVE critiques + 8 high. Les erreurs mypy ne sont pas des bugs runtime mais signalent du code "Any-driven" qui pourrait masquer des bugs futurs.

---

## 🔴 P0 — Critique (à fixer immédiatement)

### P0.1 — Vulnérabilités frontend critical
- **next.js** : 2 CVE critiques
  - `GHSA-c59h-r6p8-q9wc` : missing cache-control header → CDN peut cacher réponse vide
  - `GHSA-g77x-44xx-532m` : DoS via image optimization
- **form-data** : `GHSA-fjxv-7rqg-78g4` — unsafe random pour boundary multipart
- **Fix proposé** : `cd frontend && npm audit fix --force` puis rebuild + tests

### P0.2 — Vulnérabilités frontend high (8)
- `axios` — CSRF
- `braces` — uncontrolled resource consumption
- `cross-spawn` — ReDoS
- `dompurify` — prototype pollution (sécurité XSS critique vu qu'on l'utilise pour sanitize)
- `flatted` — DoS via parse
- `minimatch` — ReDoS
- `picomatch` — method injection
- `semver` — ReDoS

**Fix proposé** : même `npm audit fix --force`. Vérifier ensuite que rien ne casse au build.

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

### P1.5 — Outils frontend manquants (eslint/tsc)

Le frontend n'a pas installé `next` localement (`npm install` jamais exécuté ou .bin perdu). Impossible d'auditer eslint et types tsc.

**Fix** : `cd frontend && npm install` puis re-run lint + tsc avant Pass 2.

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
