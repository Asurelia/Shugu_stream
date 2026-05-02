---
date: 2026-05-02
status: open
severity: medium
discovered_during: PR #76 (Sprint A migration Next 13→16)
related_files:
  - frontend/src/features/desktop/DesktopWindow.tsx
  - frontend/src/features/desktop/VirtualDesktop.tsx
---

## Résumé

2 composants utilisent `<img>` HTML natif au lieu de `<Image>` de `next/image`. Warnings ESLint `@next/next/no-img-element` :

```
./src/features/desktop/DesktopWindow.tsx
102:13  Warning: Using `<img>` could result in slower LCP and higher bandwidth.
        Consider using `<Image />` from `next/image` to automatically optimize images.

./src/features/desktop/VirtualDesktop.tsx
45:13  Warning: Using `<img>` could result in slower LCP and higher bandwidth.
```

## Symptôme observé

`npm run lint` flagge en warning (non bloquant). Pas d'impact build.

## Impact

- **Performance** : pas d'optimisation auto (resize, format AVIF/WebP, lazy
  loading). LCP (Largest Contentful Paint) potentiellement dégradé.
- **Bandwidth** : images servies en taille originale même sur mobile.
- L'utilisateur du desktop virtuel charge des assets non optimisés (logos
  fenêtres, icônes app).

## Cause racine probable

Probable copie de pattern HTML standard sans réflexion sur Next image
optimization. `next/image` impose des contraintes (width/height obligatoires,
config `images.remotePatterns` pour sources externes) qui peuvent avoir
été perçues comme friction → choix `<img>` raccourci.

## Action recommandée

**Phase 2 (App Router migration) ou backlog dédié** :

1. Identifier les sources des images (statiques bundled vs URLs externes
   vs blob URLs créés dynamiquement).
2. Pour les statiques (icônes app dans VirtualDesktop) : import direct
   et `<Image src={icon} width={32} height={32} alt="..." />`.
3. Pour les dynamiques (DesktopWindow probablement décor de fenêtre) :
   évaluer si `<Image>` apporte vraiment qqch ou si `<img>` est OK
   (avec eslint-disable explicit).

## Décision implicite (à confirmer)

Si après audit on décide que `<img>` est OK pour ces 2 cas (ex: blob URLs
ou pure UI cosmétique sans LCP impact), ajouter un `eslint-disable-next-line @next/next/no-img-element` avec commentaire explicatif. Pas juste désactiver
la règle globalement.
