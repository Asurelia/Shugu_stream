---
date: 2026-05-02
status: fixed
severity: medium
discovered_during: PR #79 (Sprint D — Next 15 → 16 bump)
fixed_by: PR #88 (Sprint 7a, 11 violations) + PR #89 (Sprint 7b, 11 violations) + PR #90 (Sprint 7c, 26 violations) — règles ré-activées en `error` dans `eslint.config.mjs`
related_files:
  - frontend/eslint.config.mjs
  - frontend/src/app/_client.tsx
  - frontend/src/features/scene-composer/
  - frontend/src/features/scene-editor-v2/
  - frontend/src/components/
---

## Résumé

Le bump ESLint 9 + `eslint-config-next@16` introduit 3 nouvelles règles strict React Hooks (compiler-friendly, alignées sur React 19 / React Compiler) qui flaggent **48 patterns hérités à travers le code** :

- `react-hooks/set-state-in-effect` (25 occurrences)
- `react-hooks/refs` (20 occurrences)
- `react-hooks/purity` (3 occurrences)

## Symptôme observé

Au premier `npm run lint` post-bump Next 16 :
```
✖ 64 problems (48 errors, 16 warnings)
```

Top 3 règles flaggées :
- `react-hooks/set-state-in-effect` — `setState()` appelé synchrone dans un `useEffect`, déclenche un re-render cascadant.
- `react-hooks/refs` — `ref.current` lu pendant le render au lieu d'être lu dans un effect/event handler. Race condition possible avec React concurrent.
- `react-hooks/purity` — fonction render qui appelle des side effects (mutation, log, etc.).

## Cause racine probable

Ces patterns sont des **vrais risques** mais ils étaient acceptés par ESLint 8 + eslint-config-next@13 qui avaient des règles plus laxistes. Avec React 19 et le React Compiler à l'horizon, Vercel a tightené les règles dans `next/core-web-vitals` v16.

L'app a été écrite avant que ces règles existent → patterns accumulés sur 2+ ans.

## Impact

- **Re-renders cascadants** dus aux `setState` dans effects → potentiel jank UI sur Scene Editor avec 30+ meshes.
- **Stale closures** sur les `ref.current` lus en render → bugs subtils de synchronisation Three.js / WebSocket.
- **Render impuretés** (logs, mutations) → incompatible avec React Compiler activé. Si on veut bénéficier de l'optimisation auto-memo en Phase 2 (App Router + React 19), il FAUDRA fixer.

## Mitigation appliquée (PR #79)

`eslint.config.mjs` : règles dégradées de `error` → `warn` avec commentaire FIXME pointant vers ce finding :

```js
"react-hooks/set-state-in-effect": "warn",
"react-hooks/refs": "warn",
"react-hooks/purity": "warn",
```

Permet à la CI de passer (lint sort en 0 errors, 64 warnings) sans masquer
silencieusement les violations — chaque `npm run lint` les liste, le dev les voit.

## Action recommandée

**Phase 2 / Sprint E1-E6 (App Router migration)** — la migration force de
re-lire chaque hook ligne par ligne, c'est l'occasion idéale :

1. Pour chaque page migrée vers App Router (`pages/X.tsx` → `app/X/page.tsx`),
   fixer les violations React Hooks pendant la migration.
2. Patterns de fix typiques :
   - `setState dans effect` → `useReducer` ou `useSyncExternalStore` selon le cas.
   - `ref lu en render` → déplacer la lecture dans un `useEffect` ou un event handler.
   - `render impur` → extraire les side effects dans un `useEffect`.
3. À chaque PR Sprint E, ré-activer progressivement les règles en `error`
   pour les pages déjà migrées.
4. **Sprint E6 (cleanup)** : ré-activer toutes les 3 règles en `error` une
   fois les 64 warnings résolus.

## Pourquoi pas en Sprint D

- 64 warnings sur 100+ fichiers React = audit React Hooks complet,
  ~1-2 jours de travail focus.
- Mélanger ce refactor avec le bump Next 16 → diff énorme, bisect difficile
  si régression.
- Le scope Sprint D est *bumper Next 16*, pas *moderniser React Hooks*.

## Liste des fichiers concernés (pour Sprint E)

À ré-générer au moment du fix avec :
```bash
npm run lint 2>&1 | grep -E "react-hooks/(set-state-in-effect|refs|purity)"
```

Top fichiers (sample) :
- `src/pages/index.tsx` (multiple violations)
- `src/features/scene-composer/viewer/` (refs lus en render dans Three.js)
- `src/features/scene-editor-v2/` (setState dans effect)
- `src/components/` (multiple)
