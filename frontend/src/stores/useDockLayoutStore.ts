/**
 * Scene Editor — store persistant du layout de docks.
 *
 * Ce store contient UNIQUEMENT l'état "ergonomie" qui doit survivre aux
 * reloads de l'onglet navigateur :
 *   - `dockLayout` : quels panneaux vivent dans quel dock + onglet actif ;
 *   - `leftW` / `rightW` / `bottomH` : largeurs/hauteurs des splitters
 *     (Hierarchy gauche, docks droit, dock bas).
 *
 * Le reste de l'état éditeur (`currentScene`, `selectedId`, `tool`,
 * `layoutPreset`, snapshots undo/redo) vit dans `useSceneEditorStore` et
 * n'est **pas** persisté — on veut repartir "clean" sur une nouvelle
 * session, sauf pour la manière dont l'utilisateur a customisé son UI.
 *
 * Pattern Zustand `persist` middleware → localStorage (clé stable
 * `shugu:scene-editor:dock-layout:v1`, versionnée pour permettre une
 * migration plus tard sans détruire les layouts existants).
 *
 * # Résilience SSR
 *
 * La page `[username]/admin/scene-editor` est rendue avec
 * `dynamic({ssr:false})`, donc on ne devrait jamais importer ce module
 * côté serveur. Mais on protège quand même via un check `typeof window`
 * pour que d'éventuels tests jsdom sans localStorage ne crashent pas.
 */

import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";

import type { DockablePanelKey } from "@/features/editor-shared";

/* ─────────────────────────── TYPES ─────────────────────────── */

export type DockId = "viewport" | "right" | "bottom";

/**
 * Re-export pour les consumers historiques de ce store. La source de vérité
 * pour le set de panels est `dnd-context.DockablePanelKey` — ce store ne
 * gère QUE les panels qui peuvent vivre dans un dock (donc pas `hierarchy`).
 */
export type PanelKey = DockablePanelKey;

export type DockLayout = Record<DockId, { tabs: PanelKey[]; active: PanelKey }>;

/** Par défaut, layout identique à `SceneEditorApp.tsx:162` verbatim. */
export const DEFAULT_DOCK_LAYOUT: DockLayout = {
  viewport: { tabs: ["scene", "live"], active: "scene" },
  right: { tabs: ["inspector", "effects", "stream", "perf"], active: "inspector" },
  bottom: { tabs: ["assets", "timeline", "patterns", "mixer"], active: "assets" },
};

/** Valeurs initiales identiques à `SceneEditorApp.tsx:537-539`. */
export const DEFAULT_LEFT_W = 240;
export const DEFAULT_RIGHT_W = 320;
export const DEFAULT_BOTTOM_H = 260;

/** Bornes min/max respectant les splitter clamps de `SceneEditorApp.tsx`. */
const LEFT_W_MIN = 180;
const LEFT_W_MAX = 400;
const RIGHT_W_MIN = 260;
const RIGHT_W_MAX = 460;
const BOTTOM_H_MIN = 160;
const BOTTOM_H_MAX = 500;

/* ─────────────────────────── STATE ─────────────────────────── */

export interface DockLayoutState {
  dockLayout: DockLayout;
  leftW: number;
  rightW: number;
  bottomH: number;

  /** Remplace l'intégralité du layout (drop/drag tab, reset, etc.). */
  setDockLayout: (layout: DockLayout | ((prev: DockLayout) => DockLayout)) => void;

  /** Modifie la largeur gauche en préservant les bornes [180, 400]. */
  adjustLeftW: (delta: number) => void;
  /** Modifie la largeur droite en préservant les bornes [260, 460]. */
  adjustRightW: (delta: number) => void;
  /** Modifie la hauteur bas en préservant les bornes [160, 500]. */
  adjustBottomH: (delta: number) => void;

  /** Force la valeur exacte (utile pour des tests et pour des presets). */
  setLeftW: (value: number) => void;
  setRightW: (value: number) => void;
  setBottomH: (value: number) => void;

  /** Remet dockLayout + tailles à leurs valeurs par défaut. */
  resetLayout: () => void;
}

/** Clamp number entre [min, max] inclusif. Utilitaire partagé. */
const clamp = (value: number, min: number, max: number): number =>
  Math.max(min, Math.min(max, value));

/* ─────────────────────────── STORE ─────────────────────────── */

export const useDockLayoutStore = create<DockLayoutState>()(
  persist(
    (set) => ({
      dockLayout: DEFAULT_DOCK_LAYOUT,
      leftW: DEFAULT_LEFT_W,
      rightW: DEFAULT_RIGHT_W,
      bottomH: DEFAULT_BOTTOM_H,

      setDockLayout: (layout) =>
        set((state) => ({
          dockLayout: typeof layout === "function" ? layout(state.dockLayout) : layout,
        })),

      adjustLeftW: (delta) =>
        set((state) => ({ leftW: clamp(state.leftW + delta, LEFT_W_MIN, LEFT_W_MAX) })),
      adjustRightW: (delta) =>
        // Note : dans SceneEditorApp, le splitter droit fait `w - delta` car
        // le dock grossit quand on tire vers la gauche. On garde la même
        // sémantique ici : `delta > 0` réduit la largeur (convention inverse
        // du splitter gauche mais alignée sur le comportement original).
        set((state) => ({ rightW: clamp(state.rightW - delta, RIGHT_W_MIN, RIGHT_W_MAX) })),
      adjustBottomH: (delta) =>
        // Idem : le splitter bas fait `h - delta` car le dock grossit vers
        // le haut.
        set((state) => ({ bottomH: clamp(state.bottomH - delta, BOTTOM_H_MIN, BOTTOM_H_MAX) })),

      setLeftW: (value) => set({ leftW: clamp(value, LEFT_W_MIN, LEFT_W_MAX) }),
      setRightW: (value) => set({ rightW: clamp(value, RIGHT_W_MIN, RIGHT_W_MAX) }),
      setBottomH: (value) => set({ bottomH: clamp(value, BOTTOM_H_MIN, BOTTOM_H_MAX) }),

      resetLayout: () =>
        set({
          dockLayout: DEFAULT_DOCK_LAYOUT,
          leftW: DEFAULT_LEFT_W,
          rightW: DEFAULT_RIGHT_W,
          bottomH: DEFAULT_BOTTOM_H,
        }),
    }),
    {
      name: "shugu:scene-editor:dock-layout:v1",
      // On persiste TOUT (dockLayout + splitter sizes). Pas de functions dans
      // l'état donc JSON-safe out of the box.
      storage: createJSONStorage(() =>
        // Garde-fou SSR : si `localStorage` n'existe pas (jsdom sans setup,
        // SSR accidentel), on retourne un stub no-op qui ne persiste rien.
        typeof window !== "undefined" && window.localStorage
          ? window.localStorage
          : {
              getItem: () => null,
              setItem: () => {},
              removeItem: () => {},
            },
      ),
      version: 1,
    },
  ),
);

/* ─────────────────────────── SELECTORS ─────────────────────────── */

/** Helpers typés pour éviter les re-renders quand on ne lit qu'un champ. */
export const selectDockLayout = (s: DockLayoutState): DockLayout => s.dockLayout;
export const selectSplitterWidths = (s: DockLayoutState): {
  leftW: number;
  rightW: number;
  bottomH: number;
} => ({ leftW: s.leftW, rightW: s.rightW, bottomH: s.bottomH });
