# Scene Editor v2 — Audit (2026-04-27)

Audit READ-ONLY préparatoire à la refonte du Scene Editor en 3 workspaces (`Scene 3D` / `Overlays 2D` / `Show / Preview`). Tous les chemins sont vérifiés byte-pour-byte dans le worktree `bold-hugle-647620` au commit `6452c40`.

> **Statut des sources** : 3 audits subagent + 3 vérifications manuelles (arbre Figma_mini, package.json frontend, listing scene-composer/editor/legacy). L'audit subagent figma_mini citait des fichiers inexistants (`canvas/Canvas.tsx`, `modes/*Mode.tsx`, `mouse.ts`) — corrigé dans cet audit.

---

## A — Code 3D existant côté Shugu

### A.1 Stack & dépendances (vérifiées)
Source : `frontend/package.json`.

| Lib | Version | Rôle |
|-----|---------|------|
| next | 13.2.4 (Pages Router) | Routing |
| react / react-dom | 18.2.0 | UI |
| three | 0.149.0 | Moteur 3D |
| @pixiv/three-vrm | 1.0.9 | VRM loader/runtime |
| @gltf-transform/core | 2.4.6 | GLTF tools |
| zustand | 4.5.7 | State store |
| zundo | 2.3.0 | Undo middleware Zustand |
| immer | 10.2.0 | State immutability |
| livekit-client / @livekit/components-react | 2.18 / 2.9 | Voix VIP |
| tailwindcss | 3.3.1 | Styling |
| vitest / @testing-library/react / playwright | 1.6 / 14.3 / 1.59 | Tests |

### A.2 scene-composer (Phase E5, base solide à conserver)
Source : `frontend/src/features/scene-composer/` — **28 fichiers**.

**Viewer 3D modulaire** (`viewer/three-stage/`) :
- `createCamera.ts` — caméra perspective
- `createScene.ts` — scène Three.js + lights
- `loadVrm.ts` — chargement VRM (lib/VRMAnimation utilisée)
- `transform-controls.ts` — gizmos transform (W/E/R)
- `raycaster-selection.ts` — sélection ray-cast
- `animations.ts` — VRMA animation mixer
- `prop-instances.ts` — instances de props
- `dispose.ts` — cleanup
- `helpers.ts` — utilitaires
- `useSceneRig.ts` — hook React qui assemble le tout

**Interactions** (`viewer/interactions/`) :
- `useGizmoBinding.ts` — binding store ↔ gizmos avec debounce RAF
- `useDragDropTarget.ts` — drag&drop assets dans viewport (Phase E5.3)

**AFK Loops** (`viewer/afk/`) :
- `useAfkLoops.ts` — loops AFK déterministes (Phase E5.4)

**Panels** :
- `panels/AssetCataloguePanel.tsx` — librairie d'assets groupée
- `panels/ScenesListPanel.tsx` — liste de scènes sauvées
- `panels/SceneInspectorPanel.tsx` — properties contextuelles
- `panels/PlayModeToolbar.tsx` — Play / Stop / AFK config
- `panels/inspector/{TransformSection,AxisSlider,inspector-styles}.tsx`
- `panels/catalogue/{AssetSection,catalogue-styles}.tsx`

**API & store** :
- `api/{catalogClient,scenesClient,httpClient}.ts` — client REST
- `store/useSceneComposerStore.ts` — Zustand store (playMode, afkLoops, currentVrmaUrl, selectedMeshId, transformMode)
- `SceneComposerApp.tsx` — composant racine

**Tests Vitest** : 12 fichiers (`__tests__/`) couvrant viewer, panels, store, clients, animations, transform-controls, raycaster, drag-drop, afk-loops, gizmo-binding.

### A.3 scene-editor (Phase B-G, partiellement réutilisable)
Source : `frontend/src/features/scene-editor/` — **11 fichiers**.

| Fichier | Verdict |
|---------|---------|
| `SceneEditorApp.tsx` | **Jeter** — redondant avec scene-composer |
| `PopoutApp.tsx` | **Conserver** — fenêtre popout pour opérateur |
| `panels-main.tsx` / `panels-aux.tsx` | **Jeter** — refondu en v2 |
| `primitives.tsx` | **Évaluer** — possibles helpers à garder |
| `viewer-adapter.tsx` | **Jeter** — remplacé par useSceneRig |
| `hotkeys.tsx` | **Conserver/inspirer** — système hotkeys existant |
| `dnd-context.ts` | **Évaluer** — refondu via useDragDropTarget |
| `mock-data.ts` | **Jeter** — fixtures de dev |
| `index.ts` | **Refaire** — barrel export v2 |
| `__tests__/viewer-adapter.test.tsx` | **Jeter avec viewer-adapter** |

### A.4 scene-editor-legacy (à dégager intégralement)
Source : `frontend/src/features/admin/scene-editor-legacy/` — **6 fichiers**.

`InspectorPanel.tsx`, `SceneEditorToolbar.tsx`, `SceneEditorViewer.tsx`, `SceneLibrary.tsx`, `types.ts`, `__tests__/SceneEditorViewer.test.tsx`. Architecture monolithique pré-Phase B. **Suppression complète en PR cleanup finale.**

### A.5 Composants 3D ailleurs
- `components/ViewerStage.tsx` — viewer principal du stream public
- `components/vrmViewer.tsx` — autre wrapper VRM
- `lib/VRMAnimation/{loadVRMAnimation,VRMAnimation,VRMAnimationLoaderPlugin,VRMAnimationLoaderPluginOptions,VRMCVRMAnimation}.ts` — infrastructure VRMA Mixamo
- `lib/VRMLookAtSmootherLoaderPlugin/{VRMLookAtSmoother,VRMLookAtSmootherLoaderPlugin}.ts` — smoothing du regard

### A.6 Routes admin actuelles
Source : `frontend/src/pages/[username]/admin/` — 9 routes : `analytics`, `assets`, `community`, `creator-home`, `index` (live control), `moderation`, `scene-composer`, `scene-editor`, `schedule`, `users`. Pages `/shugu/admin/{scene-composer,scene-editor-popout}.tsx` (sans `[username]`) pour vues opérateur.

### A.7 Backend (à approfondir au moment du branchement)
L'audit subagent identifie côté Python :
- `backend/shugu/scene_composer/` : ScenePlayer, schemas Pydantic v2 (TriggerSpec discriminé), modèles SQLAlchemy `authored_scene`, types `static`/`timeline`/`loop`, persistence JSONB.
- API REST `/api/scenes/*`, `/api/assets/*`.
- WebSocket : events scene update, director, etc.
- À VÉRIFIER en PR2 quand on branchera v2 sur le backend (évite hallucination).

---

## B — Overlays 2D existants (le chrome stream)

| Composant | Path | Rôle |
|-----------|------|------|
| `SubGoalBar.tsx` | `frontend/src/components/SubGoalBar.tsx` | Compteur sub goal |
| `BottomTitleBand.tsx` | `frontend/src/components/viewer/BottomTitleBand.tsx` | Lower third |

**Manque actuellement** : alerts (donations/follows/raids), templates configurables, event ticker, supporters list, overlay safe-area visualizer.

Ces overlays sont du DOM HTML/React superposé au viewer 3D, pas du canvas 2D. **Conséquence pour v2** : le workspace `Overlays 2D` n'est pas un éditeur vectoriel mais un **éditeur de templates DOM** avec :
- Positionnement absolu/relative (X/Y/anchor)
- Taille (W/H/min/max)
- Style (background, blur, gradient, border, shadow, font)
- Animation (entrée/sortie, transitions)
- Data binding (sub goal counter, last follower, etc.)

---

## C — Liquid-glass (visuel à conserver)

Source : `frontend/src/styles/liquid-glass.css` (1664 lignes vérifiées) + `frontend/src/features/liquid-glass/{primitives,dataviz,index}`.

### C.1 Tokens (fragment)
| Token | Valeur |
|-------|--------|
| `--lg-blur` | `6px` (faible 4px / fort 10px) |
| `--lg-saturation` | `180%` |
| `--lg-tint` | `rgba(18, 14, 30, 0.52)` |
| `--lg-tint-strong` | `rgba(22, 18, 38, 0.72)` |
| `--lg-edge-top` | `rgba(255,255,255,0.18)` |
| `--lg-specular` | `rgba(255,255,255,0.12)` |
| Radius | `lg=18px / lg-card=22px / lg-modal=28px / lg-pill=999px / lgi=14px` |

### C.2 Primitives (15 composants)
- `LiquidLayers` — specular + edge + shimmer
- `GlassSurface` — base verre (variant: card/pill/modal/plain × tone: default/strong/weak)
- `GlassCard` — `GlassSurface variant=card` + padding optionnel
- `GlassButton` — variants primary/secondary/ghost/subtle/danger × sizes sm/md/lg × tier vip/admin
- `GlassInput` — input + label uppercase mono + hint/error
- `GlassPill` — pastille colorée (default/primary/secondary/tertiary/warn/danger) + dot
- `GlassTabs` — tablist accessible avec gradient sur tab actif
- `GlassModal` — overlay scrim + animation entrée + close ESC
- `GlassSwitch` — toggle iOS-like avec glow rose
- `GlassSection` — section header + body + danger variant
- `GlassRow` — ligne style "iOS Settings" (label/sub/value/trailing)

**Dataviz** (4 composants, utiles surtout en stream metrics) :
- `Sparkline`, `BarList`, `Heatmap`, `MetricTile`

### C.3 Philosophie visuelle
Verre flou iOS 15+, fond `#0a0a14`, accents rose magenta `#e08efe` + secondary `#fd6c9c` + cyan `#81ecff`. Glow soft (jamais hard-edged). Transitions 180–260ms `cubic-bezier(0.4, 1.3, 0.5, 1)` pour effet luxe. Highlight inset top + ombre inset bottom = bevel 3D microscopique.

**Tier glows** animés : VIP doré (2.4s loop), Admin orange (2.6s loop) — réutilisables pour signaler le mode actif (Edit / Play / Live).

---

## D — Figma_mini (inspiration UX, port partiel)

### D.1 Arbre source vérifié (37 fichiers, source `Figma_mini/src/`)
```
app/{App.tsx, ErrorBoundary.tsx, sampleDocument.ts}
canvas/{CanvasStage.tsx, StreamStage.tsx, exporters.ts, renderer.ts}
core/{commands.ts(+test), defaults.ts, document.ts, history.ts, id.ts, layout.ts, persistence.ts, store.tsx, streamScene.ts, types.ts}
geometry/{bounds.ts, geometry.test.ts, guides.ts, hitTest.ts, matrix.ts, spatialIndex.ts, transform.ts}
input/shortcuts.ts
stream/{assetRegistry.ts, overlayTemplates.ts}
ui/{ColorControl.tsx, CommandPalette.tsx, LayersPanel.tsx, PropertiesPanel.tsx, StatusBar.tsx, Toolbar.tsx, icons.tsx}
main.tsx, styles.css
```

⚠️ **Pas de** `canvas/Canvas.tsx`, `canvas/SelectionBox.tsx`, `modes/*Mode.tsx`, `input/mouse.ts` (l'agent halluciné). Les modes sont gérés inline dans `app/App.tsx` via `mode === "stream" ? <StreamStage /> : <CanvasStage />`.

### D.2 Catégorisation des 37 fichiers

| Path | Catégorie | Verdict v2 |
|------|-----------|------------|
| `app/App.tsx` | shell | **Inspirer** — pattern toolbar/panels collapsibles |
| `app/ErrorBoundary.tsx` | shell | **Conserver pattern** |
| `app/sampleDocument.ts` | data | **Ignorer** — fixtures 2D |
| `canvas/CanvasStage.tsx` (785 L) | 2D-vector | **Ignorer** — éditeur vectoriel pur |
| `canvas/StreamStage.tsx` (746 L) | 3D | **Inspirer** — patterns Three.js + VRM rig + overlay bounds projection |
| `canvas/exporters.ts` | 2D | Ignorer |
| `canvas/renderer.ts` | 2D | Ignorer |
| `core/commands.ts` | infra | **Inspirer** — pattern command undo/redo, à adapter 3D |
| `core/history.ts` | infra | **Inspirer** — undo/redo stack (160 cmds) — Shugu utilise zundo, comparer |
| `core/store.tsx` | infra | **Inspirer** — pattern store + execute/updateNodesDirect |
| `core/document.ts` | infra | Ignorer (2D-spécifique) |
| `core/persistence.ts` | infra | **Ignorer** — Shugu a son backend, pas localStorage |
| `core/streamScene.ts` | 3D | **Inspirer** — STREAM_SHOTS camera presets (wide/close/gaming/brb) |
| `core/types.ts` | infra | **Inspirer** — type `Mixed<T>` pour multi-selection |
| `core/{defaults,id,layout}.ts` | infra | Évaluer cas par cas |
| `geometry/{bounds,matrix,transform}.ts` | infra | Ignorer 2D — Three.js fournit déjà ces helpers |
| `geometry/guides.ts` | infra | **Inspirer** — smart guides (3D = snap-to-grid/axes) |
| `geometry/hitTest.ts` | infra | Ignorer — Three.js raycaster utilisé dans scene-composer |
| `geometry/spatialIndex.ts` | infra | Ignorer 2D |
| `input/shortcuts.ts` | infra | **Inspirer** — bindings Mod+Z/Y/D/A/G/etc |
| `stream/assetRegistry.ts` | 3D | **Inspirer schéma** — typage avatars/outfits/scenes/vfx/animations/overlays. Backend Shugu fournit la data. |
| `stream/overlayTemplates.ts` | 2D-overlay | **Inspirer** — pattern template DOM pour overlays |
| `ui/CommandPalette.tsx` | UX | **PORTER** — Ctrl+K, énorme valeur |
| `ui/Toolbar.tsx` | UX | **Inspirer** — header menu-based (Tools/File/Edit/Insert) + workspace switcher |
| `ui/LayersPanel.tsx` | UX | **Inspirer** — outliner hiérarchique + asset library collapsible groups |
| `ui/PropertiesPanel.tsx` | UX | **Inspirer** — properties contextuelles avec multi-selection "Mixed" |
| `ui/StatusBar.tsx` | UX | **Inspirer** — fps/zoom/tool hint |
| `ui/ColorControl.tsx` | UX | **Inspirer** — pour material color editor |
| `ui/icons.tsx` | UX | **Inspirer** — convention SVG inline |
| `core/commands.test.ts` | test | Ignorer (tests 2D) |
| `geometry/geometry.test.ts` | test | Ignorer (tests 2D) |
| `main.tsx` | bootstrap | Ignorer (Vite, pas Next) |
| `styles.css` (1664 L) | UX | **Inspirer densité layout** ; tokens viennent de liquid-glass |

### D.3 Fonctionnalités à AJOUTER dans v2 (manquent dans Shugu)
1. **Command Palette `Ctrl+K`** — recherche commandes (HIGH ROI)
2. **Multi-selection avec état Mixed** — bulk edits sur plusieurs objets 3D
3. **Smart guides 3D** — snap-to-axes/grid/objets, threshold configurable
4. **Outliner hiérarchique** — arbre scène avec drag-reorder + visibility/lock toggles par item
5. **Workspace splittable Blender-like** — panneaux redimensionnables, perspectives sauvegardées
6. **Properties Panel multi-section** — Transform / Material / Animation / Lighting / Effets
7. **Asset Library searchable** — filtrage temps réel sur registry
8. **Hotkeys uniformes** — Mod+Z/Y/D/A/G + arrow keys nudge + nombre = workspace
9. **Status bar avec metrics live** — fps render, latence stream, bitrate, dropped frames

---

## E — Verdict refonte

### E.1 Garder & étendre
- **scene-composer** au cœur de v2 : viewer/three-stage, useGizmoBinding, useDragDropTarget, useAfkLoops, store.
- **scene-editor/hotkeys.tsx** comme base hotkeys, étendu avec patterns figma_mini.
- **lib/VRMAnimation/** + **lib/VRMLookAtSmootherLoaderPlugin/** : intacts, alimentent loadVrm.
- **liquid-glass primitives** : intacts, habillent toute la nouvelle UI.
- **components/SubGoalBar + BottomTitleBand** : refondus en templates pluggables dans workspace 2D.

### E.2 Réécrire
- **Application shell scene-editor** : nouveau `features/scene-editor-v2/app/SceneEditorApp.tsx` avec workspace switcher.
- **Panneaux** : nouveaux Outliner / Properties / Library / Timeline qui consomment scene-composer en interne.
- **Overlay editor 2D** : workspace dédié, pas un canvas vectoriel.
- **Show/Preview compositing** : nouveau workspace combinant 3D viewport + overlays superposés.

### E.3 Supprimer (PR cleanup finale, pas avant)
- `features/admin/scene-editor-legacy/` (6 fichiers)
- `features/scene-editor/SceneEditorApp.tsx`, `panels-main`, `panels-aux`, `viewer-adapter`, `mock-data` (5 fichiers)
- `features/scene-composer/SceneComposerApp.tsx` (la coque seulement, le viewer/store/panels reste)

### E.4 Routes finales attendues
- `/[username]/admin/scene-editor` → v2 (3 workspaces)
- `/[username]/admin/scene-composer` → redirige vers `/scene-editor` (legacy gentle redirect)
- `/[username]/admin/assets` → redirige vers `/scene-editor?workspace=3D&panel=library`
- `/shugu/admin/scene-editor-popout` → fenêtre opérateur (v2 popout réutilisé)
- `/[username]/admin/creator-home` → désactivée + retirée sidebar (PR séparée)

---

## F — Points ouverts (à valider avant DESIGN.md)

1. **Backend API exacte** : confirmer les routes `/api/scenes` et `/api/assets` (endpoints, payloads) en PR2 avant le branchement réel. Pas d'hypothèse maintenant.
2. **WebSocket events** : confirmer le contrat scene update / director events.
3. **zundo vs command pattern figma_mini** : Shugu utilise déjà `zundo` (middleware Zustand undo). Décision : on **garde zundo**, on n'importe pas le pattern Command de figma_mini. Plus simple, déjà testé.
4. **Tailwind vs CSS** : liquid-glass utilise CSS pur. Tailwind est dispo. Décision pour v2 : **liquid-glass classes** pour le chrome (panneaux, boutons, sections) + **Tailwind utilities** pour le layout (flex, grid, spacing). Pas de CSS modules custom.
