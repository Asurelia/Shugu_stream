# Findings — index

Liste des problèmes/dettes/anomalies repérés mais **non fixés immédiatement**. Triés par sévérité décroissante puis date.

## Open

| Date | Sévérité | Fichier | Sujet | Sprint cible |
|------|----------|---------|-------|--------------|
| 2026-05-02 | high | [`2026-05-02-livekit-react-jsx-typing.md`](2026-05-02-livekit-react-jsx-typing.md) | LiveKitRoom retourne `ReactNode` au lieu de `JSX.Element` (cast workaround) | Phase 2 / E1 |
| 2026-05-02 | high | [`2026-05-02-typescript-eslint-plugin-missing.md`](2026-05-02-typescript-eslint-plugin-missing.md) | Plugin `@typescript-eslint/eslint-plugin` jamais installé malgré 7 `eslint-disable-next-line` qui le réfèrent | Sprint B (13→14) |
| 2026-05-02 | medium | [`2026-05-02-frontend-no-ci-broken-build.md`](2026-05-02-frontend-no-ci-broken-build.md) | `next build` n'a jamais réussi sur main (pas de CI frontend, type errors masqués par `next dev`) | Sprint A (PR #76) — fixed in this PR |
| 2026-05-02 | medium | [`2026-05-02-meta-component-incomplete.md`](2026-05-02-meta-component-incomplete.md) | Composant `Meta` ne supportait pas `title` malgré 10 pages qui passaient cette prop | Sprint A — fixed in PR #76 |
| 2026-05-02 | medium | [`2026-05-02-img-instead-of-next-image.md`](2026-05-02-img-instead-of-next-image.md) | 2 fichiers utilisent `<img>` au lieu de `<Image>` (warnings perf @next/next/no-img-element) | Phase 2 ou Three.js sprint |
| 2026-05-02 | medium | [`2026-05-02-react-hooks-exhaustive-deps.md`](2026-05-02-react-hooks-exhaustive-deps.md) | 3 warnings `react-hooks/exhaustive-deps` ignorés (potentielles stale closures) | Phase 2 |
| 2026-05-02 | low | [`2026-05-02-jsx-a11y-aria-button-role.md`](2026-05-02-jsx-a11y-aria-button-role.md) | `aria-selected` sur role `button` (devrait être role `tab`) — accessibility | Phase 2 |
| 2026-05-02 | low | [`2026-05-02-eslint-disabled-rules.md`](2026-05-02-eslint-disabled-rules.md) | 2 règles ESLint désactivées globalement (`react/no-unescaped-entities`, `@typescript-eslint/no-explicit-any`) | Phase 2 ou backlog dédié |
| 2026-05-02 | low | [`2026-05-02-three-stale-version.md`](2026-05-02-three-stale-version.md) | Three.js 0.149 (mai 2023) — pas de patches sécu depuis 2 ans, 44 fichiers concernés | Phase 3 (post-Phase 2) |

## Mitigated (workaround posé en attendant le vrai fix)

| Date | Fichier | Workaround | Suivi |
|------|---------|-----------|-------|
| 2026-05-02 | livekit-react-jsx-typing | Cast `as React.ComponentType<Record<string, unknown>>` dans vip/room.tsx | Issue upstream livekit-js |

## Fixed (gardés pour l'historique)

| Date | Fichier | PR de fix |
|------|---------|-----------|
| 2026-05-02 | frontend-no-ci-broken-build | PR #76 |
| 2026-05-02 | meta-component-incomplete | PR #76 |

## Wontfix

(vide pour l'instant)
