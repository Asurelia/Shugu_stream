# Scene Editor v2 — Plan d'implémentation (2026-04-27)

Plan d'implémentation incrémental TDD avec stop conditions explicites. Aucune ligne de code n'est écrite tant que ce plan + AUDIT + DESIGN ne sont pas validés par l'utilisateur.

> Méthode : **TDD réel + verification-before-completion non négociable + review subagent obligatoire** (cf. memory `feedback_workflow_discipline`).

---

## 0. Workflow appliqué à chaque PR

Chaque PR de ce plan suit le cycle suivant. Aucune exception.

```
1. Crée la branche (git flow): claude/scene-editor-v2-{phase}-{YYYYMMDD-HHMMSS}-001
2. Écris la TODO list (TodoWrite) avec les sous-tâches.
3. Pour chaque sous-tâche :
   a. Écris le test qui échoue (Vitest unit OU Playwright e2e).
   b. Lance la suite : `npm run test` ou `npm run e2e` → constate l'échec.
   c. Implémente le code minimum pour faire passer le test.
   d. Lance la suite → vert.
   e. Si rouge persistent : NE PAS modifier le test. Investiguer le code.
4. Verification batch finale :
   - `npm run lint`        → 0 error
   - `npm run build`       → succès, no warnings critiques
   - `npm test`            → 100% pass
   - `npm run e2e` (relevant subset)
   - `npm run dev` + smoke manuel sur les pages touchées (screenshots dans le PR)
5. Si subagent Haiku délégué : reviewer chaque diff, relancer la suite manuellement.
6. PR avec :
   - Description précise (what/why/how)
   - Screenshots before/after pour chaque écran touché
   - Liste explicite des stop conditions rencontrées (s'il y en a)
   - Liste des trous restants (rien de "presque fini" déguisé)
7. Merge SEULEMENT après validation visuelle utilisateur.
```

**Stop conditions globales** (déclencheurs d'arrêt + ping utilisateur, pas d'improvisation) :
- Test qui passe seulement après modification du test → STOP, escalade.
- Build qui passe avec warnings TypeScript ignorés → STOP.
- Subagent qui rapporte "ça marche" sans output testable → STOP.
- Hallucination détectée (fichier cité qui n'existe pas, API inventée) → STOP, doc mis à jour.
- Régression visuelle détectée sur une page non touchée → STOP, revert PR.
- Plus de 3 itérations sur la même erreur → STOP, demande de précision.

---

## 1. Phase 0 — Quick wins UI (PR séparée, débloque l'usage immédiat)

**Branche** : `claude/admin-shell-fix-{ts}-001`
**Scope** : NE TOUCHE PAS à scene-editor. Juste l'AdminShell pour débloquer le visuel des autres pages admin.
**ETA** : 2-4h.

### 1.1 Sous-tâches
1. Fix sidebar `AdminShell.tsx` full-height + scroll interne.
2. Fix « grand vide en haut » sur `moderation`, `schedule`, `community`, `analytics`, `live control` (`index.tsx`).
3. Retirer `creator-home` de la sidebar admin.
4. Désactiver/redirect la route `/[username]/admin/creator-home` (vers live control par défaut).

### 1.2 Tests
- Playwright : pour chaque page admin, screenshot baseline + assert que `<main>` débute à `padding-top` correct (≤ header height).
- Playwright : assert que la sidebar a `height: 100vh`.

### 1.3 Stop conditions Phase 0
- AdminShell utilisé ailleurs (vérifier grep) → impact à mesurer avant fix.
- Si la sidebar contient logique métier → ne PAS toucher, ouvrir issue à part.

---

## 2. Phase 1 — Foundation Scene Editor v2

**Branche** : `claude/scene-editor-v2-foundation-{ts}-001`
**Scope** : crée `frontend/src/features/scene-editor-v2/` avec le shell minimal (3 workspaces vides, switcher, topbar/statusbar liquid-glass).
**ETA** : 1 jour.

### 2.1 Architecture cible
```
frontend/src/features/scene-editor-v2/
├── app/
│   ├── SceneEditorV2App.tsx       # racine, layout topbar/workspace/statusbar
│   ├── ErrorBoundary.tsx
│   └── routes.ts                   # constantes routes / workspaces
├── shell/
│   ├── Topbar.tsx                  # liquid-glass topbar + workspace switcher
│   ├── Statusbar.tsx               # liquid-glass statusbar
│   ├── WorkspaceSwitcher.tsx       # GlassTabs pour 3D/2D/Show
│   └── SplitLayout.tsx             # primitive splittable Blender-like
├── workspaces/
│   ├── scene3d/Workspace3D.tsx     # placeholder
│   ├── overlays2d/Workspace2D.tsx  # placeholder
│   └── show/WorkspaceShow.tsx      # placeholder
├── command-palette/
│   ├── CommandPalette.tsx          # Mod+K modal
│   └── commands.ts                 # registry
├── hooks/
│   ├── useHotkeys.ts               # bindings centralisés
│   └── useWorkspace.ts             # state workspace courant
├── store/
│   └── useSceneEditorStore.ts      # Zustand + zundo (undo/redo)
├── types/
│   └── index.ts
├── __tests__/
│   ├── SceneEditorV2App.test.tsx
│   ├── Topbar.test.tsx
│   ├── WorkspaceSwitcher.test.tsx
│   ├── SplitLayout.test.tsx
│   └── CommandPalette.test.tsx
└── index.ts                         # barrel
```

### 2.2 Tests à écrire AVANT le code
1. `SceneEditorV2App` rend topbar + workspace courant + statusbar.
2. WorkspaceSwitcher change le workspace au clic + propage `aria-selected`.
3. Hotkey `1`/`2`/`3` switch workspace (hors input).
4. `Mod+K` ouvre CommandPalette, `Esc` ferme.
5. SplitLayout rend deux enfants côte-à-côte avec divider draggable, persiste les ratios en localStorage.

### 2.3 Page Next.js
- `frontend/src/pages/[username]/admin/scene-editor.tsx` charge `<SceneEditorV2App />` via `next/dynamic ssr:false`.
- Pas de `AdminShell` autour : v2 a son propre chrome.

### 2.4 Stop conditions Phase 1
- Si liquid-glass primitives ne supportent pas un usage attendu (ex: tablist avec gradient sur tab actif, déjà OK) → adapter primitives, ne pas reécrire CSS local.
- Si `next/dynamic ssr:false` casse l'hydration → diagnostiquer ou bypass via `useEffect`.
- Si Zustand + zundo conflit → revenir au plan simple (Zustand sans zundo, undo manuel).

---

## 3. Phase 2 — Workspace 3D (le plus gros morceau)

**Branche** : `claude/scene-editor-v2-workspace-3d-{ts}-001`
**Scope** : implémente le Workspace 3D complet en réutilisant scene-composer (viewer/three-stage).
**ETA** : 2-3 jours, découpable en sous-PRs.

### 3.1 Sous-PRs proposés

#### 3.1.1 PR 2.A — Outliner panel
- `workspaces/scene3d/panels/Outliner.tsx`
- Tests :
  - rend la hiérarchie depuis store
  - sélection click / multi-select
  - drag pour reparenter
  - search filtre live
  - toggle visibility et lock
- Réutilise `useSceneComposerStore` ou wrap dans nouveau store v2.

#### 3.1.2 PR 2.B — Library panel
- `workspaces/scene3d/panels/Library.tsx`
- Sub-tabs Models / Outfits / Anims / Props / Decor / VFX (`GlassTabs`).
- Source data : appelle `api/catalogClient.ts` existant.
- Drag asset → fire event captable par viewport (HTML5 DnD ou react-dnd ?).
- Tests : rend par tab, filter search, drag start emet event correct.

#### 3.1.3 PR 2.C — 3D Viewport
- `workspaces/scene3d/viewport/SceneViewport.tsx`
- Wrap `SceneComposerViewer` existant avec décor v2 (toolbar shot/gizmo/snap/coords, view cube, zoom indicator).
- Inline timeline conditionnelle (animation active).
- Tests : rend viewport, gizmo mode toggle, raycaster select, drop asset depuis Library.

#### 3.1.4 PR 2.D — Properties panel
- `workspaces/scene3d/panels/Properties.tsx` + sections :
  - `TransformSection.tsx` (réutilise scene-composer/panels/inspector)
  - `OutfitSection.tsx`
  - `ExpressionSection.tsx`
  - `AnimationSection.tsx`
  - `MaterialSection.tsx`
  - `LightingSection.tsx`
  - `CameraSection.tsx`
  - `EffectsSection.tsx`
- Tests : selection vide affiche empty state, sélection unique affiche sections pertinentes selon type, multi-selection affiche valeurs Mixed.

### 3.2 Stop conditions Phase 2
- Si scene-composer/viewer breaks avec wrap v2 → ne PAS forker, ouvrir issue + adapter scene-composer.
- Si performance dégradée (fps < 50 viewport vide sur GPU dev) → STOP profilage avant continuer.
- Si VRMA loading conflict avec scene-composer → revoir lib/VRMAnimation usage.

---

## 4. Phase 3 — Workspace Overlays 2D

**Branche** : `claude/scene-editor-v2-workspace-2d-{ts}-001`
**Scope** : Workspace 2D avec safe area + 4 templates initiaux + Inspector.
**ETA** : 2 jours.

### 4.1 Sous-tâches
1. `workspaces/overlays2d/SafeArea.tsx` (1920×1080 zoomable/pannable).
2. `workspaces/overlays2d/panels/TemplatesPanel.tsx` (drag templates dispo).
3. `workspaces/overlays2d/templates/{SubGoalTemplate,LowerThirdTemplate,FollowAlertTemplate,StatusBadgeTemplate}.tsx` (réutilise SubGoalBar, BottomTitleBand existants).
4. `workspaces/overlays2d/panels/OverlayInspector.tsx` (Position/Size/Style/Animation/DataBind).
5. `workspaces/overlays2d/store/useOverlaysStore.ts` (overlays placés sur la scène).
6. Smart guides (port `geometry/guides.ts` figma_mini, simplifié 2D).

### 4.2 Tests
- Drag template → instancie un overlay au point drop.
- Resize handles → modifie W/H avec smart guides au snap.
- Inspector édite position/style et applique en temps réel.
- Multi-select bulk edit avec valeurs Mixed.

### 4.3 Stop conditions Phase 3
- Si SubGoalBar/BottomTitleBand existants ne supportent pas le re-paramétrage prop-driven → refondre proprement (pas hack).
- Si smart guides figma_mini introduisent dépendance lourde → impl maison plus simple.

---

## 5. Phase 4 — Workspace Show / Preview

**Branche** : `claude/scene-editor-v2-workspace-show-{ts}-001`
**Scope** : compositing 3D + 2D + quick triggers + metrics.
**ETA** : 1-1.5 jour.

### 5.1 Sous-tâches
1. `workspaces/show/Compositing.tsx` : stack `<SceneViewport />` + `<OverlayLayer />` à l'échelle 1920×1080 avec letterbox.
2. `workspaces/show/panels/LiveStatePanel.tsx` (lecture seule).
3. `workspaces/show/panels/QuickTriggersPanel.tsx` (boutons configurables).
4. `workspaces/show/panels/StreamMetricsPanel.tsx` (réutilise `MetricTile` + `Sparkline`).
5. Toolbar Play/Stop/AFK/Quality/Snapshot/PushLive (réutilise `PlayModeToolbar` patterns).

### 5.2 Tests
- Compositing rend bien en stack avec pointer-events scope correct.
- Quick trigger clic applique state au store + feedback visuel.
- Snapshot exporte un PNG du compositing.
- Metrics se mettent à jour avec mock event stream.

### 5.3 Stop conditions Phase 4
- Si `useAfkLoops` couple trop fort à scene-composer → extraire dans un hook plus générique.
- Si Snapshot WebGL → blob PNG fail sur certains navigateurs → fallback canvas.toDataURL après readPixels.

---

## 6. Phase 5 — Branchement backend & assets réels

**Branche** : `claude/scene-editor-v2-backend-wire-{ts}-001`
**Scope** : remplace tous les seeds de dev par les vraies API/WebSocket.
**ETA** : 1-2 jours.

### 6.1 Sous-tâches
1. Audit exact des routes backend (`/api/scenes`, `/api/assets`) + WebSocket events. Doc à mettre à jour dans AUDIT.md.
2. Wire Library panel sur `api/catalogClient.ts` (déjà existant).
3. Wire Save/Load scene via `api/scenesClient.ts`.
4. Wire WebSocket events pour Live State / Push Live.
5. Tests d'intégration backend (mock fetch + WS).

### 6.2 Stop conditions Phase 5
- Si backend manque un endpoint critique → STOP, ouvre issue backend, ne PAS hardcoder.
- Si types frontend ≠ payloads backend → générer types depuis OpenAPI/Pydantic, pas mappage manuel.

---

## 7. Phase 6 — Migration & Cleanup

**Branche** : `claude/scene-editor-v2-cleanup-{ts}-001`
**Scope** : retire les anciennes implémentations.
**ETA** : 0.5-1 jour.

### 7.1 Sous-tâches
1. Vérifier qu'aucune route ne pointe vers scene-editor (ancien) ou scene-editor-legacy.
2. Drop `frontend/src/features/admin/scene-editor-legacy/` (6 fichiers).
3. Drop `frontend/src/features/scene-editor/{SceneEditorApp,panels-main,panels-aux,viewer-adapter,mock-data}.tsx` (5 fichiers).
4. Drop `frontend/src/features/scene-composer/SceneComposerApp.tsx` (la coque seulement, pas viewer/panels/store).
5. Garder `scene-composer/viewer/`, `scene-composer/panels/inspector/TransformSection`, `scene-composer/store/useSceneComposerStore` qui sont consommés par v2.
6. Update imports cassés.
7. Run lint + build + test → tout vert.
8. Update routes admin (`scene-composer.tsx` → redirect vers `scene-editor`).

### 7.2 Stop conditions Phase 6
- Si un test fait référence à code legacy → STOP, mettre à jour test ou supprimer test (jamais ajuster pour passer).
- Si build casse → revert phase, débogage avant relance.

---

## 8. Phase 7 — Polish & accessibilité

**Branche** : `claude/scene-editor-v2-polish-{ts}-001`
**Scope** : finitions, a11y, perf.
**ETA** : 1-2 jours.

### 8.1 Sous-tâches
1. ARIA roles cohérents (tablist/tab/tabpanel, toolbar, treegrid pour Outliner).
2. Focus management (Tab order logique, focus trap dans modals).
3. Keyboard shortcut cheat-sheet (`?` ouvre une modal).
4. Empty states soignés (illustrations + CTAs).
5. Loading states (skeleton avec shimmer liquid-glass).
6. Dark mode déjà OK (liquid-glass est dark-first).
7. Perf : mémoiser sélections, virtualiser Outliner si > 500 items.
8. Tests Playwright e2e couvrant les 5 user stories du DESIGN §8.

---

## 9. Découpe finale en PRs (proposition)

| # | PR | Phase | ETA | Stop si... |
|---|----|----|-----|------------|
| 1 | Admin shell fixes | 0 | 2-4h | Risque régression visuelle |
| 2 | v2 Foundation (shell + workspaces vides + palette) | 1 | 1j | Hydration Next casse |
| 3 | v2 Workspace 3D — Outliner | 2.A | 0.5j | scene-composer store fragile |
| 4 | v2 Workspace 3D — Library | 2.B | 0.5j | catalogClient instable |
| 5 | v2 Workspace 3D — Viewport | 2.C | 1j | Performance < 50fps |
| 6 | v2 Workspace 3D — Properties | 2.D | 1j | Multi-select Mixed cas pénibles |
| 7 | v2 Workspace 2D | 3 | 2j | Templates DOM lourds |
| 8 | v2 Workspace Show | 4 | 1j | Snapshot WebGL fail navigateur |
| 9 | v2 Backend wire | 5 | 1.5j | API backend manquante |
| 10 | v2 Cleanup legacy | 6 | 0.5j | Imports résiduels |
| 11 | v2 Polish & a11y | 7 | 1.5j | — |

**Total estimé** : 12-15 jours homme.

---

## 10. Garde-fous transversaux (rappel memory `feedback_workflow_discipline`)

À chaque PR :
- ❌ JAMAIS modifier un test pour qu'il passe.
- ❌ JAMAIS marquer "done" sans `lint+build+test+e2e+runtime` verts.
- ❌ JAMAIS faire confiance à un subagent Haiku sans review diff + relance des tests.
- ✅ Honnêteté binaire : "testé" = j'ai exécuté X, voici la sortie. Sinon "pas testé" explicite.
- ✅ Stop conditions appliquées sans débat.
- ✅ Pas de "presque fini" — soit vert soit WIP marqué.

---

## 11. Validation utilisateur (avant la première ligne de code)

Trois questions à clore :

**Q1 — Sur les 6 décisions ouvertes du DESIGN.md §10**, valides-tu les defaults proposés ou tu corriges ?

**Q2 — Ordre des PRs** : on commence par PR1 (Admin shell, vite gagné) ou directement PR2 (v2 foundation) ?

**Q3 — Périmètre overlays 2D** : 4 templates initiaux suffisent ? Ou tu en veux d'autres dès la PR initiale (event ticker, supporters list, custom HTML slot) ?

Réponses → branche créée → 1ère PR commence en TDD strict.
