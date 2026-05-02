---
date: 2026-05-02
status: fixed
severity: medium
discovered_during: PR #76 (Sprint A migration Next 13→16)
related_files:
  - .github/workflows/ci.yml
  - frontend/
fixed_by: PR #76
---

## Résumé

Le frontend Next.js n'avait **AUCUN job CI** (lint/test/build) dans
`.github/workflows/ci.yml` jusqu'à PR #76. Conséquence : `next build` n'a
**jamais réussi sur main** depuis l'écriture des pages account/admin —
7 erreurs TypeScript et un import non résolu (`@livekit/components-styles`)
sont restés masqués.

## Symptôme observé

Première exécution de `BASE_PATH="" npm run build` localement (le 2026-05-02) :
```
Failed to compile.
./src/pages/[username]/admin/users.tsx:130:13
Type error: Type '{ title: string; }' is not assignable to type 'IntrinsicAttributes'.
  Property 'title' does not exist on type 'IntrinsicAttributes'.
```
Puis 6 autres erreurs en cascade (cf finding `meta-component-incomplete`,
`livekit-react-jsx-typing`, etc.).

## Cause racine probable

- Le workflow CI a été écrit avec backend en focus exclusif (cf agent
  Pass 2 audit qui flaggait déjà l'absence de CI frontend).
- `next dev` est tolérant aux types (compile-on-demand, JIT lenient) :
  l'app marchait en dev malgré les errors. Personne n'avait la friction
  de lancer `next build` en local.
- Pas de checks pre-commit qui auraient fait `tsc --noEmit`.

## Impact

- **Tout PR mergée sur main pouvait casser le build prod sans détection.**
- Quand viendra le moment de déployer en prod (CI/CD vers shugu.spoukie.uk),
  le build aurait planté → potentielle indisponibilité du site.
- Le frontend a accumulé une dette technique invisible : 10 pages utilisaient
  `<Meta title>` pendant des semaines sans que ça soit détecté.

## Mitigation appliquée (PR #76)

Job `frontend-ci` ajouté à `.github/workflows/ci.yml` :
- Node 20, cache npm
- `npm ci` + `npm run lint` + `npm test -- --run` + `npm run build`
- 7 erreurs TS pré-existantes fixées en parallèle pour que le build passe.

## Action recommandée (suite)

1. **Pre-commit hook** côté repo (husky ou lefthook) qui lance `tsc --noEmit`
   sur les fichiers TypeScript modifiés. Évite de découvrir des erreurs en CI.
   Cible : Sprint B ou backlog à part.

2. **Job `frontend-typecheck` séparé** : actuellement le `npm run build`
   inclut le typecheck. Si on veut une remontée plus rapide d'erreurs TS
   (sans waitter le build complet), ajouter un step `npx tsc --noEmit`
   avant `npm run build`.

3. **Ajouter Playwright e2e en CI nightly** : actuellement runnable en
   local seulement (Three.js + VRM 28 MB → flaky). Un run nightly (cron
   GitHub Actions) capterait les régressions e2e sans bloquer les PRs.

4. **Couverture frontend** : Vitest tourne mais ne génère pas de coverage
   report. Ajouter `--coverage` + un seuil minimum éviterait les
   régressions silencieuses sur les stores Zustand qui sont core.

## Leçon

L'audit Pass 2 (2026-04-26) avait flaggé l'absence de CI frontend, et c'est
resté en backlog jusqu'à ce que la migration Next force la main. Pattern
récurrent : les findings d'audit non actionnés deviennent des blockers
imprévus 6 mois plus tard.
