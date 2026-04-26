/**
 * useSceneComposerStore — état UI du Scene Composer.
 *
 * Responsabilité unique : gérer l'état de l'interface utilisateur du Scene
 * Composer (sélection de scène, mode viewer, preset caméra, layout des
 * panneaux, sélection mesh 3D, instances de props, mode de transformation).
 * Ne stocke PAS les données métier (AuthoredScene) — celles-ci
 * sont fetchées au runtime via les API clients.
 *
 * Pattern Zustand sans middleware temporal (pas d'undo/redo en E5.2 — UI
 * seulement). Selectors granulaires exportés en fonctions pures pour
 * éviter les re-renders inutiles.
 *
 * Développement : le store est exposé sur `window.__SHUGU_COMPOSER_STORE__`
 * pour les tests Playwright.
 *
 * Extensions E5.3 :
 *   - `selectedMeshId` : ID du mesh 3D sélectionné dans le viewer (null = aucun)
 *   - `propInstances` : instances de props 3D droppées dans la scène
 *   - `transformMode` : mode du gizmo TransformControls (translate/rotate/scale)
 *   - `updateMeshTransform` : mutation bidirectionnelle gizmo ↔ inspector
 *
 * @module store/useSceneComposerStore
 */

import { create } from "zustand";
import type { CameraPreset } from "../viewer/three-stage/createCamera";

// ─── Types ────────────────────────────────────────────────────────────────────

/** Disposition des panneaux latéraux du Composer. */
export type PanelLayout = "split-right" | "split-bottom" | "fullscreen";

/** Mode du viewer 3D. */
export type ViewerMode = "edit" | "preview";

/** Mode de transformation du gizmo TransformControls. */
export type TransformMode = "translate" | "rotate" | "scale";

/**
 * Transform d'un objet 3D dans la scène.
 *
 * Convention : position en mètres, rotation en degrés (conversion radians
 * à la frontière gizmo ↔ store, cohérent avec SceneEditorViewer legacy),
 * scale sans unité (1.0 = taille native).
 */
export interface ObjectTransform {
  position: [number, number, number];
  rotation: [number, number, number];
  scale: [number, number, number];
}

/**
 * Instance d'un prop 3D dans la scène.
 *
 * Identifié par un `id` unique (UUID-like généré au drop) et référencé
 * par `assetSlug` (clé dans le catalogue — correspond à `Prop3DEntry.slug`).
 */
export interface PropInstance {
  /** Identifiant unique de l'instance (généré au drop). */
  id: string;
  /** Slug de l'asset dans le catalogue (Prop3DEntry.slug). */
  assetSlug: string;
  /** Transform 3D de l'instance. */
  transform: ObjectTransform;
}

export interface SceneComposerState {
  // ── Sélection scène ──────────────────────────────────────────────────────
  /** ID de la scène authoriée actuellement sélectionnée (null = aucune). */
  selectedSceneId: string | null;

  // ── Viewer ───────────────────────────────────────────────────────────────
  viewerMode: ViewerMode;
  cameraPreset: CameraPreset;

  // ── Layout ───────────────────────────────────────────────────────────────
  panelLayout: PanelLayout;

  // ── Interactivité 3D (E5.3) ──────────────────────────────────────────────
  /** ID du mesh 3D actuellement sélectionné dans le viewer (null = aucun). */
  selectedMeshId: string | null;
  /** Mode de transformation du gizmo (translate W / rotate E / scale R). */
  transformMode: TransformMode;
  /** Map des instances de props droppées dans la scène. */
  propInstances: Record<string, PropInstance>;

  // ── Actions ──────────────────────────────────────────────────────────────
  setSelectedSceneId: (id: string | null) => void;
  setViewerMode: (mode: ViewerMode) => void;
  setCameraPreset: (preset: CameraPreset) => void;
  setPanelLayout: (layout: PanelLayout) => void;
  resetUI: () => void;

  // ── Actions E5.3 ─────────────────────────────────────────────────────────
  /** Sélectionne (ou désélectionne) un mesh 3D dans le viewer. */
  setSelectedMeshId: (id: string | null) => void;
  /** Change le mode de transformation du gizmo. */
  setTransformMode: (mode: TransformMode) => void;
  /** Ajoute une instance de prop dans la scène. */
  addPropInstance: (instance: PropInstance) => void;
  /** Retire une instance de prop de la scène (libère l'Object3D via le viewer). */
  removePropInstance: (id: string) => void;
  /**
   * Met à jour le transform d'une instance existante.
   *
   * Mutation partielle : seuls les champs fournis sont mis à jour.
   * Source bidirectionnelle : appelé depuis le gizmo (drag) ET depuis l'Inspector (sliders).
   */
  updateMeshTransform: (id: string, transform: Partial<ObjectTransform>) => void;
}

// ─── État initial ─────────────────────────────────────────────────────────────

const INITIAL_STATE = {
  selectedSceneId: null,
  viewerMode: "edit" as ViewerMode,
  cameraPreset: "free" as CameraPreset,
  panelLayout: "split-right" as PanelLayout,
  // E5.3
  selectedMeshId: null,
  transformMode: "translate" as TransformMode,
  propInstances: {} as Record<string, PropInstance>,
};

// ─── Store ────────────────────────────────────────────────────────────────────

export const useSceneComposerStore = create<SceneComposerState>()((set) => ({
  ...INITIAL_STATE,

  setSelectedSceneId: (id) => set({ selectedSceneId: id }),

  setViewerMode: (mode) => set({ viewerMode: mode }),

  setCameraPreset: (preset) => set({ cameraPreset: preset }),

  setPanelLayout: (layout) => set({ panelLayout: layout }),

  resetUI: () => set({ ...INITIAL_STATE }),

  // Actions E5.3
  setSelectedMeshId: (id) => set({ selectedMeshId: id }),

  setTransformMode: (mode) => set({ transformMode: mode }),

  addPropInstance: (instance) =>
    set((state) => ({
      propInstances: { ...state.propInstances, [instance.id]: instance },
    })),

  removePropInstance: (id) =>
    set((state) => {
      const next = { ...state.propInstances };
      delete next[id];
      return {
        propInstances: next,
        selectedMeshId: state.selectedMeshId === id ? null : state.selectedMeshId,
      };
    }),

  updateMeshTransform: (id, transform) =>
    set((state) => {
      const existing = state.propInstances[id];
      if (!existing) return state;
      return {
        propInstances: {
          ...state.propInstances,
          [id]: {
            ...existing,
            transform: { ...existing.transform, ...transform },
          },
        },
      };
    }),
}));

// ─── Selectors granulaires ────────────────────────────────────────────────────

export const selectSelectedSceneId = (s: SceneComposerState): string | null =>
  s.selectedSceneId;

export const selectViewerMode = (s: SceneComposerState): ViewerMode =>
  s.viewerMode;

export const selectCameraPreset = (s: SceneComposerState): CameraPreset =>
  s.cameraPreset;

export const selectPanelLayout = (s: SceneComposerState): PanelLayout =>
  s.panelLayout;

// Selectors E5.3
export const selectSelectedMeshId = (s: SceneComposerState): string | null =>
  s.selectedMeshId;

export const selectTransformMode = (s: SceneComposerState): TransformMode =>
  s.transformMode;

export const selectPropInstances = (
  s: SceneComposerState,
): Record<string, PropInstance> => s.propInstances;

export const selectPropInstance =
  (id: string) =>
  (s: SceneComposerState): PropInstance | undefined =>
    s.propInstances[id];

// ─── Dev global ───────────────────────────────────────────────────────────────

if (typeof window !== "undefined" && process.env.NODE_ENV !== "production") {
  (window as unknown as Record<string, unknown>).__SHUGU_COMPOSER_STORE__ =
    useSceneComposerStore;
}
