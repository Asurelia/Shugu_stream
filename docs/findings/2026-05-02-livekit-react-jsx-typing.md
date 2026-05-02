---
date: 2026-05-02
status: mitigated
severity: high
discovered_during: PR #76 (Sprint A migration Next 13→16)
related_files:
  - frontend/src/pages/vip/room.tsx
  - frontend/node_modules/@livekit/components-react/dist/components/LiveKitRoom.d.ts
---

## Résumé

Les composants exportés par `@livekit/components-react@2.9.20` sont typés
`(props) => React.ReactNode` au lieu de `JSX.Element`. TypeScript en mode strict
refuse de les utiliser comme tags JSX :

```
error TS2786: 'LiveKitRoom' cannot be used as a JSX component.
  Its return type 'ReactNode' is not a valid JSX element.
    Type 'undefined' is not assignable to type 'Element | null'.
```

## Symptôme observé

`npx tsc --noEmit` lève l'erreur à la ligne 143 de `vip/room.tsx` :
```tsx
<LiveKitRoom token={token} serverUrl={serverUrl} ...>
```

Le build `next build` retournait l'erreur uniquement quand on l'a tenté pour la première fois (pas de CI = pas de découverte).

## Cause racine probable

`@livekit/components-react` shippe ses composants typés avec `React.ReactNode`
dans leur signature de retour, qui est plus permissif que `JSX.Element`
(`ReactNode` inclut `undefined`, `bigint`, `Promise<ReactNode>` depuis React 19,
etc.). C'est probablement intentionnel côté lib pour permettre des composants
async, mais ça rend leur usage en JSX strict impossible sans cast.

## Impact

- **Toute page utilisant `LiveKitRoom` (ou autre composant livekit-react)** échoue à `tsc` strict.
- Une seule occurrence actuellement (`vip/room.tsx`), mais dès qu'on ajoute un autre composant LiveKit (ChatBox, ParticipantTile, etc.), même problème.
- Pas de runtime impact — c'est purement statique TS.

## Mitigation appliquée (PR #76)

Cast local dans `vip/room.tsx` :
```tsx
import { LiveKitRoom as LiveKitRoomImpl, ... } from "@livekit/components-react";
const LiveKitRoom = LiveKitRoomImpl as unknown as React.ComponentType<
  Record<string, unknown>
>;
```

Le cast en `Record<string, unknown>` permet n'importe quelle prop, ce qui n'est
pas idéal pour le typecheck de l'utilisation mais permet de débloquer le build.

## Action recommandée

1. **Court terme (Sprint B/C/D)** : refaire le wrapper avec un `React.FC`
   typé strict sur les vraies props :
   ```tsx
   const LiveKitRoom = LiveKitRoomImpl as unknown as React.FC<
     Omit<React.HTMLAttributes<HTMLDivElement>, 'onError'> & {
       token: string;
       serverUrl: string;
       connect?: boolean;
       audio?: boolean;
       video?: boolean;
       onDisconnected?: () => void;
     }
   >;
   ```

2. **Moyen terme (Phase 2 / Sprint E1 — App Router migration)** : créer
   un composant wrapper côté `frontend/src/components/livekit/` qui :
   - cast le typage une fois
   - exporte avec une API stricte
   - encapsule les imports `@livekit/components-react`

3. **Upstream (idéal)** : ouvrir une issue sur
   https://github.com/livekit/components-js demandant que les composants
   soient typés `JSX.Element` au lieu de `ReactNode`. Plusieurs autres
   projets ont rencontré le même problème (cherche "LiveKitRoom JSX
   component" sur Google).

## Références

- TypeScript 5.1+ a relâché la contrainte JSX.Element vs ReactNode mais
  partiellement seulement. À re-tester après bump TS au Sprint D.
- Notre `tsconfig.json` n'a PAS `"jsx": "react-jsx"` mais `"jsx": "preserve"`,
  donc Next gère la transformation. Probablement pas un changement à faire.
