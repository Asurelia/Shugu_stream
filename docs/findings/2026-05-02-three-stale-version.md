---
date: 2026-05-02
status: fixed
severity: low
discovered_during: Audit Phase 1 exploration migration Next 13→16 (PR #76)
fixed_by: PR #86 (Phase 3 Three.js 0.149 → 0.170 + @pixiv/three-vrm 1.0.9 → 3.5.2)
related_files:
  - frontend/package.json
  - frontend/src/features/scene-composer/
  - frontend/src/features/scene-editor-v2/
  - frontend/src/components/vrm-viewer.tsx (et autres adapters Three)
---

## Résumé

`three: ^0.149.0` (mai 2023) est utilisé dans **44 fichiers** (Scene Composer, Scene Editor v2, VRM Viewer, Emote Controller, animations procédurales). Cette version a 2+ ans de retard et n'a reçu aucun patch de sécurité depuis.

## Symptôme observé

Pas de bug observable — Three.js fonctionne. Mais :
- **Pas de patch security** depuis r149 (mai 2023).
- **Pas de bug fixes** des releases r150-r170 (2 ans de fixes communautaires).
- **Pas de nouvelles features** (per-instance batching, WebGPU progress, optimizations).

## Cause racine probable

Le projet a été initié sur r149 (probablement parce que `@pixiv/three-vrm@1.0.9`
était pinné sur r149). Personne n'a fait l'effort de bumper depuis.

## Impact

### Sécurité
Three.js peut être vecteur d'attaque (parsing GLTF malformés, DOS via
geometries spéciales, XSS via shaders custom). Les CVEs Three.js sont
rares mais existent. r149 n'a aucune protection contre les patchs r150+.

### Performance
- r150+ : optimisations significatives sur `BatchedMesh`, `BufferGeometry`,
  WebGPURenderer.
- Notre Scene Editor avec 30+ meshes par scène pourrait gagner 20-40%
  framerate sur GPU mobile.

### Compatibilité
- `@pixiv/three-vrm@1.0.9` est limité à r149-r155 environ. Pour bumper Three,
  il faut bumper VRM à `^2.0.0` (breaking changes API VRM 0.x → 1.0).
- `livekit-client` n'est pas couplé à Three, donc no impact.

### Long term
Plus on attend, plus l'écart grandit. r150 → r170 = ~20 majors avec
breaking changes cumulatifs : material refactor, geometry serialization,
shader chunks renamed.

## Mitigation actuelle

**Aucune.** Le projet vit avec r149. Pas de scan CVE Three.js dans `npm audit`
parce que Three.js publie ses CVEs hors NPM advisories généralement.

## Action recommandée

**Phase 3 (post Phase 2 App Router)** — sprint dédié, hors scope migration Next :

1. **Lire le CHANGELOG Three.js** r150 → r170 et noter les breaking changes
   qui touchent notre code (44 fichiers).

2. **Bump `@pixiv/three-vrm`** d'abord vers `^2.x` :
   - Voir migration guide pixiv/three-vrm
   - Probable refactor des API d'animation (VRMAnimation, EmotionDecay)

3. **Bump Three** vers `^0.170.0` (ou plus récent stable) une fois VRM compatible.

4. **Smoke test exhaustif** :
   - Scene Editor v2 : load + edit + save + reload
   - Scene Composer : VRM load + animations procédurales (breathing, swaying, blinking)
   - VRM Viewer : full character render + lipsync + expressions

5. **Effort estimé** : 3-4h selon plan migration `velvety-skipping-penguin.md`.

## Pourquoi pas plus tôt

- Pas un blocker fonctionnel actuellement.
- Migration Next est plus urgente (CVEs CRITICAL Next bloqués par 13.2).
- Faire les deux en parallèle multiplierait les régressions à debugger.
