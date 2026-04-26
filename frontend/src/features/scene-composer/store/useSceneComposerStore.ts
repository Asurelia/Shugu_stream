/**
 * useSceneComposerStore — état UI du Scene Composer.
 *
 * Responsabilité unique : gérer l'état de l'interface utilisateur du Scene
 * Composer (sélection de scène, mode viewer, preset caméra, layout des
 * panneaux, sélection mesh 3D, instances de props, mode de transformation,
 * mode play/stop, boucles AFK déterministes).
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
 * Extensions E5.4 :
 *   - `playMode` : "stopped" | "playing" (contrôle la barre de lecture)
 *   - `afkLoops` : config des boucles AFK déterministes (activé, seuil viewers, délai inactivité)
 *   - `currentVrmaUrl` : URL VRMA actuellement jouée (piloté par useAfkLoops ou UI)
 *   - `setPlayMode` : bascule playMode + applique règle de cohérence viewerMode
 *   - `setAfkLoops` : merge partiel config AFK
 *   - `setCurrentVrmaUrl` : pilote l'animation VRMA jouée dans le viewer
 *
 * Règles de cohérence E5.4 :
 *   - setPlayMode("playing") → force viewerMode="preview"
 *   - setPlayMode("stopped") → force viewerMode="edit" (round-trip symétrique)
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
 * Mode de lecture du Scene Composer.
 *
 * - "stopped" : mode édition, scène arrêtée (viewerMode="edit")
 * - "playing" : mode lecture, scène en cours (viewerMode="preview")
 */
export type PlayMode = "stopped" | "playing";

/**
 * Configuration des boucles AFK déterministes (E5.4).
 *
 * Les boucles AFK jouent automatiquement une animation VRMA "idle" quand :
 * - `enabled` est true
 * - `currentViewerCount < viewerThreshold`
 * - pas d'interaction utilisateur depuis `idleSeconds` secondes
 *
 * Aucun appel LLM — sélection purement déterministe basée sur le catalogue.
 */
export interface AfkLoopsConfig {
  /** Active/désactive les boucles AFK. */
  enabled: boolean;
  /**
   * Seuil de viewers connectés en dessous duquel les AFK loops se déclenchent.
   * Par exemple, viewerThreshold=5 : AFK si moins de 5 viewers.
   */
  viewerThreshold: number;
  /**
   * Délai d'inactivité en secondes avant déclenchement de l'AFK loop.
   * Minimum recommandé : 10s. Maximum : 300s (5 min).
   */
  idleSeconds: number;
}

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

  // ── Play Mode + AFK Loops (E5.4) ─────────────────────────────────────────
  /**
   * Mode de lecture. "playing" implique viewerMode="preview" (cohérence
   * garantie par setPlayMode — ne pas modifier viewerMode directement si
   * playMode="playing").
   */
  playMode: PlayMode;
  /** Configuration des boucles AFK déterministes. */
  afkLoops: AfkLoopsConfig;
  /**
   * URL VRMA actuellement jouée dans le viewer (null = aucune animation AFK).
   *
   * Pilotée par useAfkLoops ou par l'UI directement. Le viewer sync cette
   * valeur → appel playVrmaAnimation sur le VRM chargé.
   */
  currentVrmaUrl: string | null;

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

  // ── Actions E5.4 ─────────────────────────────────────────────────────────
  /**
   * Bascule le mode lecture.
   *
   * Règles de cohérence (appliquées atomiquement) :
   * - setPlayMode("playing") → viewerMode="preview"
   * - setPlayMode("stopped") → viewerMode="edit" (round-trip symétrique)
   *
   * @example
   * store.setPlayMode("playing"); // → playMode="playing", viewerMode="preview"
   * store.setPlayMode("stopped"); // → playMode="stopped", viewerMode="edit"
   */
  setPlayMode: (mode: PlayMode) => void;
  /**
   * Merge partiel de la configuration AFK Loops.
   *
   * @example
   * store.setAfkLoops({ enabled: false }); // désactive sans changer le reste
   * store.setAfkLoops({ idleSeconds: 60, viewerThreshold: 3 });
   */
  setAfkLoops: (partial: Partial<AfkLoopsConfig>) => void;
  /**
   * Définit l'URL VRMA actuellement jouée par le viewer.
   *
   * Appelé par useAfkLoops quand une animation idle est sélectionnée.
   * null = arrêt de l'animation AFK (retour à l'animation de base ou silence).
   */
  setCurrentVrmaUrl: (url: string | null) => void;
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
  // E5.4
  playMode: "stopped" as PlayMode,
  afkLoops: {
    enabled: true,
    viewerThreshold: 5,
    idleSeconds: 30,
  } as AfkLoopsConfig,
  currentVrmaUrl: null as string | null,
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

  // Actions E5.4
  setPlayMode: (mode) =>
    set({
      playMode: mode,
      // Cohérence bidirectionnelle :
      // playing → preview (pour masquer helpers/gizmo en lecture)
      // stopped → edit (round-trip symétrique prévisible)
      viewerMode: mode === "playing" ? "preview" : "edit",
    }),

  setAfkLoops: (partial) =>
    set((state) => ({
      afkLoops: { ...state.afkLoops, ...partial },
    })),

  setCurrentVrmaUrl: (url) => set({ currentVrmaUrl: url }),
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

// Selectors E5.4
/** Retourne le mode de lecture actuel. */
export const selectPlayMode = (s: SceneComposerState): PlayMode => s.playMode;

/** Retourne la configuration des boucles AFK. */
export const selectAfkLoops = (s: SceneComposerState): AfkLoopsConfig => s.afkLoops;

/** Retourne l'URL VRMA actuellement jouée (null = aucune). */
export const selectCurrentVrmaUrl = (s: SceneComposerState): string | null =>
  s.currentVrmaUrl;

// ─── Dev global ───────────────────────────────────────────────────────────────

if (typeof window !== "undefined" && process.env.NODE_ENV !== "production") {
  (window as unknown as Record<string, unknown>).__SHUGU_COMPOSER_STORE__ =
    useSceneComposerStore;
}
