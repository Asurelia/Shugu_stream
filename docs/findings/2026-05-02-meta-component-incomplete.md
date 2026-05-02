---
date: 2026-05-02
status: fixed
severity: medium
discovered_during: PR #76 (Sprint A migration Next 13→16)
related_files:
  - frontend/src/components/meta.tsx
  - frontend/src/pages/account/login.tsx
  - frontend/src/pages/account/profile.tsx
  - frontend/src/pages/account/register.tsx
  - frontend/src/pages/account/verify-email.tsx
  - frontend/src/pages/vip/room.tsx
  - frontend/src/pages/[username]/admin/users.tsx
fixed_by: PR #76
---

## Résumé

Le composant `Meta` dans `frontend/src/components/meta.tsx` n'acceptait **aucune prop** (signature `() => JSX.Element`), mais **10 pages** l'invoquaient avec `<Meta title="..." />`. TypeScript strict aurait dû planter — masqué par l'absence de CI frontend (cf finding `frontend-no-ci-broken-build`).

## Symptôme observé

```
./src/pages/[username]/admin/users.tsx:130:13
Type error: Type '{ title: string; }' is not assignable to type 'IntrinsicAttributes'.
  Property 'title' does not exist on type 'IntrinsicAttributes'.
```

Le runtime tolérait silencieusement : la prop `title` était passée mais ignorée par `Meta` qui hardcodait `"Shugu ♡ AI VTuber live"`.

## Cause racine probable

L'écriture initiale de `Meta` (component.tsx:3-23) date d'avant l'ajout des pages auth/admin/vip. Quelqu'un a écrit `<Meta title="...">` en pensant que c'était paramétrable (par cohérence avec d'autres composants Glass qui le sont), sans vérifier la signature.

## Impact

- **10 pages** rendaient toutes le même titre `"Shugu ♡ AI VTuber live"` quel que soit le `title` passé. SEO et UX dégradé silencieusement.
- L'utilisateur voyait toujours le même titre dans son onglet de navigateur, peu importe la page.
- Pas d'indication serveur — uniquement statique côté DOM.

## Mitigation appliquée (PR #76)

Réécriture de `Meta` :
```tsx
type MetaProps = { title?: string };
export const Meta = ({ title }: MetaProps = {}) => {
  const defaultTitle = "Shugu ♡ AI VTuber live";
  const documentTitle = title ?? defaultTitle;
  // ... og:title et twitter:title gardent defaultTitle pour SEO/social cards consistants
};
```

Le document title (`<title>`) override mais les meta og/twitter restent sur le branding défaut — décision pragmatique pour ne pas "polluer" les social shares avec des titres techniques (ex: "Connexion — Shugu" peu engageant en tweet preview).

## Action recommandée

1. **Phase 2 (App Router migration)** : remplacer entièrement `<Meta>` par
   l'API `metadata` export native d'App Router. Le composant `Meta` deviendra
   obsolète. Cible : Sprint E1 ou E2.

2. **Avant Phase 2** : envisager de paramétrer aussi `description` côté
   `Meta` props pour permettre des descriptions par page (actuellement toutes
   les pages partagent la même description, qui est très "homepage").

3. **Test snapshot** : ajouter un `Meta.test.tsx` qui vérifie que le title
   passé est bien rendu dans `<title>`. Catch silent regressions futures.

## Leçon

Composant trop "fermé" par défaut : `() => JSX.Element` interdit toute
extension. Pattern préférable :
```tsx
type Props = React.PropsWithChildren<{ title?: string }>;
export const Meta = ({ title, children }: Props) => { ... };
```
Force le call site à être réfléchi sur ce qu'il passe.
