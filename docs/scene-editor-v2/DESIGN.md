# Scene Editor v2 — Design (2026-04-27)

Spec d'interface de la refonte du Scene Editor en 3 workspaces, mix cohérent **liquid-glass** (esthétique) + **figma_mini** (UX éditeur) + **Blender** (layout ouvert), au service des fonctionnalités 3D Shugu.

> **Statut** : doc de validation. Aucune ligne de code écrite tant que ce doc n'est pas approuvé.

---

## 1. Principes directeurs

1. **Open layout Blender-like** — panneaux splittables/redimensionnables, pas de grille figée.
2. **Workspace = perspective** — chaque workspace est une organisation préréglée des panneaux, pas une page séparée. Switch instantané (`1` / `2` / `3` ou clic onglet).
3. **Liquid-glass partout** — chaque panneau, modal, toolbar utilise les primitives `GlassSurface` / `GlassButton` / `GlassPill` / `GlassTabs`. Aucun composant nu.
4. **Densité figma_mini** — toolbar fine (32–40 px), labels typographiques 10–12 px uppercase mono, contenu dense mais pas tassé.
5. **Trois workspaces, un seul state** — la scène 3D et les overlays 2D sont des facettes du même document. Pas de duplication de state.
6. **Hotkeys partout** — toute action atteignable au clavier. Command Palette (`Ctrl+K`) liste tout.
7. **Fail-soft** — si le viewer 3D crash, l'éditeur reste utilisable (ErrorBoundary autour du viewport).

---

## 2. Layout global (constant entre workspaces)

```
┌─────────────────────────────────────────────────────────────────────┐
│ Topbar  [Shugu logo]  Scene: <name>•  [1 Scene 3D] [2 Overlays] [3] │ ← 36px
│         Mod+S Save • Mod+Z Undo • Mod+Y Redo                        │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│              ZONE WORKSPACE (panneaux splittables)                  │
│                                                                     │
├─────────────────────────────────────────────────────────────────────┤
│ Statusbar  fps:60  ws:OK  latency:46ms  selected:Shugu  Mode:Edit   │ ← 28px
└─────────────────────────────────────────────────────────────────────┘
```

- **Topbar** (36 px) : `GlassSurface variant=plain` translucide, `backdrop-filter blur(10px)`. Logo Shugu (16px), nom scène inline-editable, dot rose si dirty (`unsaved`), workspace switcher = `GlassTabs` central, menu Mod (...) à droite (Save / Save As / Settings / Help).
- **Statusbar** (28 px) : `GlassSurface variant=plain tone=weak`, infos live (fps render, ws latency, selection name, mode actuel). Cliquer un metric ouvre un détail (popover).
- **Zone workspace** : zone centrale qui change avec le workspace actif. Splittable horizontalement et verticalement. Dividers 4px draggables avec hover glow rose.

---

## 3. Workspace 1 — `Scene 3D`

### 3.1 Layout par défaut

```
┌──────────┬────────────────────────────┬──────────┐
│ Outliner │                            │ Properties│
│          │     3D Viewport            │           │
│ Hiérar-  │     (Three.js + VRM)       │ Transform │
│ chie     │                            │ Material  │
│ scène    │     gizmos W/E/R           │ Animation │
│          │     orbit cam              │ Lighting  │
│ Library  │                            │ FX        │
│ d'assets │     [Top: shot toolbar]    │           │
│          │     [Bot: timeline]        │           │
│          │                            │           │
└──────────┴────────────────────────────┴──────────┘
   240px            flex                  280px
```

### 3.2 Panneaux

#### 3.2.1 Outliner (gauche, haut, ~50% hauteur)
- `GlassSection` titre "Hierarchy".
- Arbre indenté : root → environnement / personnages / props / lights / cameras / VFX.
- Chaque ligne : `GlassRow` avec :
  - Icône type (16px) — VRM / mesh / light / camera / fx / outfit / accessory
  - Nom (renommable inline double-clic)
  - Trailing : visibility eye (toggle) + lock (toggle)
- Sélection via clic. Multi-select Ctrl/Shift. Drag pour reparenter. Right-click → menu (Duplicate / Delete / Group / Rename / Focus camera).
- Search field en tête (`GlassInput` pill) : filtre live.
- Vide → empty state avec hint "Drag an asset from Library".

#### 3.2.2 Library (gauche, bas, ~50% hauteur)
- `GlassSection` titre "Library", droite = bouton `GlassButton ghost sm` "Import".
- `GlassTabs` interne : `Models` / `Outfits` / `Anims` / `Props` / `Decor` / `VFX`.
- Recherche `GlassInput` pill.
- Vue grille (3 colonnes) ou liste (toggle en haut à droite). Vignette + nom + tag tier (VIP/Admin si applicable via `GlassPill tone=warn/admin`).
- Drag d'une vignette → drop dans le viewport ajoute l'item à la scène (relais `useDragDropTarget`).
- Hover preview : agrandissement vignette + tooltip métadonnées.

#### 3.2.3 3D Viewport (centre, flex)
- Composant racine `<SceneViewport />` qui consomme `useSceneRig` (réutilise `scene-composer/viewer/three-stage/`).
- Top inline toolbar (32 px) flottant en `GlassSurface variant=pill` :
  - Camera shot dropdown : `wide / close / gaming / brb / custom`
  - Gizmo mode : `Move (W) / Rotate (E) / Scale (R)` → `GlassTabs`
  - Snap toggle (`GlassSwitch` + dropdown `0.1 / 0.5 / 1.0` units)
  - Coord system : `World / Local`
- Coin haut-droit : grid + axes + view cube (clic snap caméra à face).
- Coin bas-gauche : zoom % + reset (`Mod+0`) + frame selection (`Mod+1`).
- Bot inline timeline (40 px, escamotable) : si une animation est en cours, scrubber + play/pause + loop toggle.
- Click viewport vide = désélectionner. Click objet = select. Drag gizmo = transform.

#### 3.2.4 Properties (droite, full hauteur)
- `GlassSection` titre = nom de la sélection courante. Empty state si rien sélectionné.
- Multi-section accordéon `GlassTabs` vertical ou sections collapsibles :
  - **Transform** : XYZ position / rotation Euler / scale uniforme + lock proportions. `AxisSlider` réutilisé. Multi-select → "Mixed" si valeurs différentes.
  - **Outfit** (si VRM sélectionné) : dropdown outfit + preview swatch + bouton ouvrir Library Outfits.
  - **Expression** (si VRM) : sliders blendshapes (joy / angry / sorrow / fun + custom).
  - **Animation** (si VRM) : dropdown animation actuelle + play/pause + speed + loop. Bouton "Add to Timeline".
  - **Material** (si mesh) : color + metalness + roughness + emissive + textures. Réutilise `GlassInput` + `ColorControl` (à porter de figma_mini).
  - **Lighting** (si light) : type / intensity / color / range / decay / shadow toggle.
  - **Camera** (si camera) : fov / near / far / focal length.
  - **Effects/VFX** : liste VFX attachés + bouton "Add VFX".
- Footer panneau : actions destructives `GlassButton danger sm` (Delete / Reset transform).

### 3.3 Hotkeys workspace 3D
| Key | Action |
|-----|--------|
| `1`/`2`/`3` | Switch workspace |
| `W`/`E`/`R` | Move/Rotate/Scale gizmo |
| `Mod+Z`/`Y` | Undo/Redo |
| `Mod+D` | Duplicate selection |
| `Mod+G` | Group selection |
| `Mod+A` | Select all |
| `Mod+0` | Reset viewport |
| `Mod+1` | Frame selection |
| `Mod+S` | Save scene |
| `Del` | Delete selection |
| `F` | Focus camera on selection |
| `H` | Hide/show selection |
| Arrows | Nudge (1u) / +Shift = 10u / +Alt = 0.1u |
| `Mod+K` | Command Palette |

---

## 4. Workspace 2 — `Overlays 2D`

### 4.1 Concept clé

**Pas un éditeur vectoriel.** C'est un **éditeur de templates DOM** : chaque overlay (sub goal, follow alert, lower third, etc.) est un composant React paramétré, posé sur une **safe area 1920×1080**, avec position/taille/style/data-binding configurables.

### 4.2 Layout

```
┌──────────┬──────────────────────────────┬──────────┐
│ Templates│                              │ Inspector│
│          │   Safe area 1920×1080        │           │
│ Sub goal │   (background neutre/grille) │ Position │
│ Alert    │                              │ Size     │
│ Lower    │   [overlay items posés]      │ Style    │
│  third   │                              │ Animation│
│ Status   │                              │ Data bind│
│ Ticker   │                              │           │
│ Custom+  │   Zoom controls              │           │
│          │                              │           │
└──────────┴──────────────────────────────┴──────────┘
   240px           flex                    280px
```

### 4.3 Panneaux

#### 4.3.1 Templates (gauche)
`GlassSection` titre "Templates". Liste de templates disponibles (cards avec preview vignette). Drag-drop dans la safe area → instancie un overlay.

Templates de base (Phase 1) :
- **Sub Goal Bar** — basé sur `components/SubGoalBar.tsx` existant
- **Lower Third** — basé sur `components/viewer/BottomTitleBand.tsx`
- **Follow Alert** — nouveau (popup animé)
- **Donation Alert** — nouveau
- **Status Badge** — nouveau (LIVE / BRB / STARTING SOON)
- **Event Ticker** — nouveau (défilement bas écran)
- **Top Supporters** — nouveau (liste latérale)
- **Custom HTML** — slot vide pour HTML/CSS custom

#### 4.3.2 Safe area 1920×1080 (centre)
- Conteneur `position: relative` aux dimensions natives stream, avec wrapper zoom (50% / 75% / 100% / 150% / fit).
- Background = grille 8px ou rendering du dernier frame du viewport 3D (toggle "Show 3D bg" dans la toolbar).
- Outils overlay au survol : drag (déplacer), poignées de coin (resize), bouton X (delete), point d'ancrage (top-left/center/bottom-right etc).
- Smart guides : snap aux bords safe area, centre, items voisins (réutilise `geometry/guides.ts` figma_mini → adapté 2D).
- Sélection multi : drag rectangle sur zone vide.
- Zoom : `Mod++/-`, pan : space + drag, reset : `Mod+0`.

#### 4.3.3 Inspector (droite)
Sections collapsibles selon overlay sélectionné :
- **Position** : X / Y absolus ou relatifs (anchor toggle 9 points).
- **Size** : W / H / ratio lock + min/max (responsive).
- **Style** : background (color/gradient/blur), border, radius, shadow, font (family/size/weight), color, alignement.
- **Animation** : entrée (slide/fade/scale) + sortie + durée + easing.
- **Data binding** : pour overlays dynamiques (sub goal counter, last follower) — sélection de la source (event WebSocket, state, statique).
- **Visibility** : conditions (live only / always / scheduled).

### 4.4 Hotkeys workspace 2D
Mêmes hotkeys que 3D pour Mod+Z/Y/D/A/G + arrows nudge. En plus :
- `Mod+]`/`[` : send forward / back
- `V` : tool select
- `T` : tool text (édition typo overlay)

---

## 5. Workspace 3 — `Show / Preview`

### 5.1 Concept

Compositing **temps réel** : viewport 3D (workspace 1) **+** overlays 2D (workspace 2) superposés à l'échelle 1:1. C'est exactement ce que voit le spectateur en stream.

### 5.2 Layout

```
┌──────────────────────────────────────────────────────────┐
│ Toolbar: [Play ▶ / Stop ■]  AFK [On/Off]  Quality [HD ▾]│
├────────────────────────────┬─────────────────────────────┤
│                            │ Live State                  │
│   Compositing 1920×1080    │  • Active scene             │
│   (3D + overlays superposés)│  • Active outfit            │
│                            │  • Active animation         │
│                            │  • VFX en cours             │
│                            │  • Camera shot              │
│                            ├─────────────────────────────┤
│   [16:9 letterboxed if needed]│ Quick Triggers           │
│                            │  • [Wave] [Bow] [Dance]     │
│                            │  • [Outfit: Streamer] [Cozy]│
│                            │  • [Camera: wide / close]   │
│                            ├─────────────────────────────┤
│                            │ Stream Metrics              │
│                            │  fps / latency / bitrate    │
│                            │  Sparkline last 60s         │
└────────────────────────────┴─────────────────────────────┘
       flex                          320px
```

### 5.3 Panneaux

#### 5.3.1 Compositing viewport (centre)
- Composite stack : `<SceneViewport />` en bg + `<OverlayLayer />` en fg pointer-events scope géré.
- Toolbar haut (40 px) :
  - **Play / Stop** : démarre/arrête le Play Mode (réutilise `useAfkLoops` + `PlayModeToolbar` patterns).
  - **AFK toggle + config** : ouvre modal (`GlassModal`) — viewer threshold + idle seconds + animation pool.
  - **Quality dropdown** : Low / Med / High / Stream (mappé sur `previewProfile` de figma_mini StreamStage).
  - **Snapshot** : capture PNG du compositing courant.
  - **Push Live** : envoie les updates au backend (apply scene state).
- Borders du frame stream visualisées (filet rose 1px). Hors-frame visible mais grisé.

#### 5.3.2 Live State (droite haut)
`GlassSection` titre "Live State" + lecture seule de l'état actuel : scene name, outfit, animation, vfx, camera shot. Chaque ligne `GlassRow`. Edit redirige vers workspace correspondant (clic outfit → workspace 3D, panel Outfit).

#### 5.3.3 Quick Triggers (droite milieu)
Boutons rapides (`GlassButton primary sm`) configurables (drag-drop d'un asset depuis la library = ajout en quick trigger). Clic = applique immédiat (sans changer la scène persistée si "Hold mode" activé).

#### 5.3.4 Stream Metrics (droite bas)
`MetricTile` réutilisés depuis liquid-glass/dataviz : fps render, latence WS, bitrate stream, dropped frames, viewers count. Sparkline 60s.

### 5.4 Hotkeys workspace Show
| Key | Action |
|-----|--------|
| `Space` | Play/Stop |
| `Shift+S` | Snapshot |
| `Mod+P` | Push Live |
| `Q1`/`Q2`/... | Quick Trigger 1/2/... |

---

## 6. Système transversal

### 6.1 Command Palette `Mod+K`
Modal `GlassModal` largeur 600px. `GlassInput` recherche fuzzy. Liste de commandes (toutes les actions atteignables clavier dans toolbar, panels, gizmos). Catégories pliables. Hotkey à droite de chaque commande. Enter exécute. ESC ferme.

Commandes initiales (~40) :
- File: New / Open / Save / Save As / Recent
- Edit: Undo / Redo / Cut / Copy / Paste / Duplicate / Delete / Select All
- View: Reset / Frame selection / Toggle outliner / Toggle inspector / Zoom in/out
- Workspace: Scene 3D / Overlays 2D / Show
- Scene: New scene / Switch scene / Delete scene
- 3D Tools: Move / Rotate / Scale gizmo / Toggle snap / World↔Local
- Stream: Play / Stop / AFK on/off / Push Live / Snapshot
- Insert: Add light / Add camera / Add prop / Add VFX / Add overlay
- Help: Shortcuts cheat-sheet / Open docs

### 6.2 Outliner persistance
- État panneaux (largeurs, expanded sections) sauvegardé en localStorage par workspace.
- Sauvegarde scene et overlays = backend (autosave debounce 500ms après dernière mutation, indicator "saved 2s ago" dans topbar).

### 6.3 Multi-selection & Mixed
- Sélection 2+ objets → properties affichant valeurs communes, "Mixed" si différentes.
- Édition d'un champ Mixed = applique à tous les sélectionnés (propagation explicite, pas implicite — confirmation visuelle pulse rose).

### 6.4 Undo/Redo
- Réutilise `zundo` (Zustand middleware) déjà dans le projet. Stack 200 limites.
- Chaque mutation non triviale produit une entrée. Drags continus collapsés en une entrée unique (debounce 250ms après release).

### 6.5 Hotkeys conflit avec Next.js / browser
- `Mod+S` = Save scene (preventDefault Browser save HTML).
- Tab navigation : standard, sauf dans canvas (capture viewport).
- Avertissement BeforeUnload si dirty et pas autosaved.

### 6.6 Modes UI
- `Edit` : mode par défaut, full edit.
- `Play` : workspace Show, animations actives, sélection bloquée.
- `Locked` : preview seul, lecture seule (pour démo/présentation).

Indicator dans topbar : pastille `GlassPill` colorée (Edit gris / Play vert / Locked rouge).

### 6.7 Responsive & low-spec
- < 1280px : panneaux gauche/droite collapsibles via boutons sidebar-tab (pattern figma_mini existant).
- WebGL fallback : si Three.js fail, afficher message d'erreur + offrir mode "view scene metadata only" (pas de viewport).
- GPU bas : Quality Stream "Low" auto si fps < 24 sustained 5s.

---

## 7. Wireframes ASCII consolidés

### 7.1 Workspace 3D
```
┌── TOPBAR ────────────────────────────────────────────────┐
│ ◇Shugu  scene_main • [1•Scene 3D] [2 Overlays] [3 Show] ⋯│
├──────────┬──────────────────────────────────┬────────────┤
│ HIERARCHY│  ╭──[wide ▾] [W][E][R] snap[●] L─╮│ TRANSFORM  │
│ search…  │  │                              │ │ x ─────── │
│ ▶ World  │  │                              │ │ y ─────── │
│  ▶ Shugu │  │       3D viewport            │ │ z ─────── │
│   ─ Hair │  │       gizmos visible         │ │ rot ──────│
│   ─ Top  │  │                              │ │           │
│  ▶ Decor │  │                              │ │ OUTFIT    │
│  ▶ Lights│  │                              │ │ default ▾ │
│  ▶ VFX   │  │                              │ │           │
├──────────┤  │                              │ │ ANIMATION │
│ LIBRARY  │  │                              │ │ idle ▶    │
│ [Models] │  │                              │ │           │
│ [Outfits]│  │                              │ │ MATERIAL  │
│ search…  │  │                              │ │ …         │
│ ▦ ▦ ▦   │  ╰──[scrubber ─────────────────]─╯│           │
│ ▦ ▦ ▦   │                                   │ [Delete]  │
└──────────┴───────────────────────────────────┴────────────┘
│ STATUSBAR  fps:60 ws:OK lat:46ms sel:Shugu Mode:Edit     │
└──────────────────────────────────────────────────────────┘
```

### 7.2 Workspace Overlays 2D
```
┌── TOPBAR ────────────────────────────────────────────────┐
│ ◇Shugu  scene_main • [1 Scene 3D] [2•Overlays] [3 Show] ⋯│
├──────────┬──────────────────────────────────┬────────────┤
│ TEMPLATES│  ╔════ Safe area 1920×1080 ═══════╗│ POSITION   │
│ ▦ SubGoal│  ║ ┌─Lower Third─────┐            ║│ x: 120    │
│ ▦ LowerT │  ║ │ Shugu - Live    │            ║│ y: 980    │
│ ▦ Alert  │  ║ └─────────────────┘            ║│ anchor ▦  │
│ ▦ Donation│ ║                                ║│           │
│ ▦ Status │  ║                                ║│ SIZE      │
│ ▦ Ticker │  ║         [3D bg if toggled]     ║│ w: 600 ─  │
│ ▦ Top Sub│  ║                                ║│ h: 80 ─   │
│ + Custom │  ║                ┌─SubGoal─┐     ║│           │
│          │  ║                │ 12/100  │     ║│ STYLE     │
│ INVOCS:  │  ║                └─────────┘     ║│ bg ▦      │
│  3 active│  ╚════════════════════════════════╝│ blur ─    │
│          │  zoom: 75% [- +] fit              │ animation │
└──────────┴───────────────────────────────────┴────────────┘
```

### 7.3 Workspace Show / Preview
```
┌── TOPBAR ────────────────────────────────────────────────┐
│ ◇Shugu  scene_main • [1 Scene 3D] [2 Overlays] [3•Show] ⋯│
├────────────────────────────────────┬─────────────────────┤
│ [▶Play] [AFK ●] Quality:HD▾  ⌘P    │ LIVE STATE          │
│ ┌──────────────────────────────────┐│ scene main_talk    │
│ │                                  ││ outfit Streamer    │
│ │   Compositing 1920×1080          ││ anim idle_loop     │
│ │   (3D + overlays superposés)     ││ shot wide          │
│ │                                  ││ vfx none           │
│ │      [LIVE!]    [Donation]       │├─────────────────────┤
│ │                                  ││ QUICK TRIGGERS     │
│ │       (Shugu animée)             ││ [Wave][Bow][Dance] │
│ │                                  ││ [Outfit:Cozy]      │
│ │   [Sub Goal: 12/100  ─────]     ││ [Cam:close]        │
│ └──────────────────────────────────┘├─────────────────────┤
│  [16:9]                             │ STREAM METRICS     │
│                                     │ fps 60 ▁▂▃▅▇       │
│                                     │ lat 46ms           │
│                                     │ bitrate 6200kbps   │
└────────────────────────────────────┴─────────────────────┘
```

---

## 8. User stories de validation

1. **Habiller Shugu en 3 clics** :
   1. Workspace 3D → Library → Outfits → drag "Cozy Pajama" sur Shugu.
   2. Inspector → Outfit → confirme. (Save automatique.)
   3. Workspace Show → preview live.

2. **Lancer une danse** :
   1. Workspace 3D → sélectionne Shugu → Inspector → Animation → "Dance" ▶.
   2. Bot timeline scrubber visible, loop toggle disponible.
   3. Mod+K → "Push Live" envoie à Show.

3. **Modifier un sub goal en stream** :
   1. Workspace 2D → sélectionne SubGoal overlay → Inspector → Style → couleur rose.
   2. Workspace Show → vérifie que le rendu compositing est correct.
   3. Mod+S → save.

4. **Switcher scène pendant un brb** :
   1. Workspace Show → Quick Trigger "Camera: brb" → caméra et background changent live.
   2. AFK loop pioche une animation idle automatiquement.

5. **Recover from oops** :
   1. Suppression accidentelle d'un prop → `Mod+Z` revient.
   2. Modification massive → `Mod+Z` répété défait étape par étape.

---

## 9. Hors-scope (à NE PAS faire en v2)

- Pas d'édition vectorielle pure (pen tool, beziers) — figma_mini avait ça, on n'en veut pas.
- Pas de chat in-app — c'est une autre stack.
- Pas de collaboratif multi-utilisateur — solo pour l'instant.
- Pas d'import GLTF/FBX custom upload utilisateur — la library est curatée par le backend.
- Pas de shader graph — material = props simples.

---

## 10. Décisions ouvertes (à trancher avant code)

| # | Décision | Default proposé |
|---|----------|-----------------|
| D1 | Workspace switcher : onglets centraux ou tabs verticaux à gauche ? | **Onglets centraux** (figma_mini style, plus visible) |
| D2 | Outliner toggle visibility = eye ou checkbox ? | **Eye icon** (Blender style) |
| D3 | Multi-selection apply value sans confirmation ? | **Avec pulse rose** (visuel, pas modal) |
| D4 | Drag&drop asset → drop dans Outliner ou viewport seulement ? | **Les deux** (viewport place auto, outliner attache au parent) |
| D5 | Templates 2D = code-only ou data-driven ? | **Mix** : 4 templates code (SubGoal, LowerThird, Alert, Status) + slot Custom HTML |
| D6 | Keyboard `1/2/3` global ou seulement hors champ texte ? | **Hors champ texte** (sinon on tape "1" dans un input et ça switch) |
