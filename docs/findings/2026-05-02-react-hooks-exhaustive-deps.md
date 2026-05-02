---
date: 2026-05-02
status: open
severity: medium
discovered_during: PR #76 (Sprint A migration Next 13→16)
related_files:
  - frontend/src/features/scene-composer/viewer/three-stage/useSceneRig.ts
  - frontend/src/pages/index.tsx
---

## Résumé

3 warnings `react-hooks/exhaustive-deps` ignorés silencieusement — potentielles **stale closures** dans des hooks `useEffect` :

```
./src/features/scene-composer/viewer/three-stage/useSceneRig.ts
295:25  Warning: The ref value 'meshRegistryRef.current' will likely have changed by
        the time this effect cleanup function runs. If this ref points to a node
        rendered by React, copy 'meshRegistryRef.current' to a variable inside
        the effect, and use that variable in the cleanup function.

./src/pages/index.tsx
436:6  Warning: React Hook useEffect has missing dependencies: 'appendLog' and
       'desktopDispatch'. Either include them or remove the dependency array.
```

## Symptôme observé

Warnings ESLint à chaque `npm run lint`. Non bloquant, mais signal d'alerte.

## Impact

### `useSceneRig.ts:295`
La cleanup function d'un `useEffect` capture `meshRegistryRef.current` au moment
de l'effect setup. Si la ref change entre setup et cleanup (très probable dans
un éditeur 3D où les meshes sont ajoutés/retirés dynamiquement), la cleanup
itère sur l'**ancienne** liste de meshes — peut leak des Three.js objects ou
bien tenter de dispose des objets déjà disposed.

**Risque concret** : memory leak Three.js dans Scene Composer après plusieurs
recharges de scène ou switches de mode.

### `pages/index.tsx:436`
`useEffect` avec `[]` array de deps mais utilise `appendLog` et `desktopDispatch`
en closure. Si ces fonctions changent (typique avec `useCallback` non-stable),
le effect tourne avec les **anciennes versions** → comportement incohérent
au runtime.

**Risque concret** : logs perdus ou dispatched vers le mauvais reducer si
le user interagit avant que React stabilise les callbacks.

## Cause racine probable

- Pour `useSceneRig.ts` : pattern courant en Three.js de tenir une ref
  globale du scene tree, et oublier que React peut re-render entre
  setup et unmount.
- Pour `index.tsx` : copy-paste d'un effect simple, puis ajout de logs
  ultérieurement sans mettre à jour les deps.

## Action recommandée

**Phase 2 (App Router migration)** — la migration force de re-lire ces hooks
ligne par ligne, c'est l'occasion de fixer :

### Pour `useSceneRig.ts:295`
```ts
useEffect(() => {
  const registry = meshRegistryRef.current; // snapshot at setup
  return () => {
    // utiliser `registry` au lieu de `meshRegistryRef.current`
    registry.forEach(disposeMesh);
  };
}, []);
```

### Pour `pages/index.tsx:436`
- Soit ajouter `appendLog` et `desktopDispatch` aux deps (et s'assurer
  qu'ils sont stables via `useCallback` côté provider).
- Soit utiliser `useEffectEvent` (React 19 hook, dispo en App Router) pour
  capturer ces fonctions sans les rendre dépendances.

**Test** : ajouter un test unit qui mock le scenario "effect re-run avec
nouvelles deps" et vérifie que le bon comportement est observé.

## Pourquoi pas en Sprint A

Ces warnings sont là depuis des semaines/mois. Les fixer demande de comprendre
la sémantique du code (Three.js, React lifecycle), ce qui dépasse le scope
"locker la CI". Le Sprint A se contente de les laisser en warning et de
documenter ici.
