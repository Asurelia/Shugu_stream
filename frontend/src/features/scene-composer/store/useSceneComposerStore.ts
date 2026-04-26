/**
 * useSceneComposerStore — état UI du Scene Composer.
 *
 * Responsabilité unique : gérer l'état de l'interface utilisateur du Scene
 * Composer (sélection de scène, mode viewer, preset caméra, layout des
 * panneaux). Ne stocke PAS les données métier (AuthoredScene) — celles-ci
 * sont fetchées au runtime via les API clients.
 *
 * Pattern Zustand sans middleware temporal (pas d'undo/redo en E5.2 — UI
 * seulement). Selectors granulaires exportés en fonctions pures pour
 * éviter les re-renders inutiles.
 *
 * Développement : le store est exposé sur `window.__SHUGU_COMPOSER_STORE__`
 * pour les tests Playwright.
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

export interface SceneComposerState {
  // ── Sélection ────────────────────────────────────────────────────────────
  /** ID de la scène authoriée actuellement sélectionnée (null = aucune). */
  selectedSceneId: string | null;

  // ── Viewer ───────────────────────────────────────────────────────────────
  viewerMode: ViewerMode;
  cameraPreset: CameraPreset;

  // ── Layout ───────────────────────────────────────────────────────────────
  panelLayout: PanelLayout;

  // ── Actions ──────────────────────────────────────────────────────────────
  setSelectedSceneId: (id: string | null) => void;
  setViewerMode: (mode: ViewerMode) => void;
  setCameraPreset: (preset: CameraPreset) => void;
  setPanelLayout: (layout: PanelLayout) => void;
  resetUI: () => void;
}

// ─── État initial ─────────────────────────────────────────────────────────────

const INITIAL_STATE = {
  selectedSceneId: null,
  viewerMode: "edit" as ViewerMode,
  cameraPreset: "free" as CameraPreset,
  panelLayout: "split-right" as PanelLayout,
};

// ─── Store ────────────────────────────────────────────────────────────────────

export const useSceneComposerStore = create<SceneComposerState>()((set) => ({
  ...INITIAL_STATE,

  setSelectedSceneId: (id) => set({ selectedSceneId: id }),

  setViewerMode: (mode) => set({ viewerMode: mode }),

  setCameraPreset: (preset) => set({ cameraPreset: preset }),

  setPanelLayout: (layout) => set({ panelLayout: layout }),

  resetUI: () => set({ ...INITIAL_STATE }),
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

// ─── Dev global ───────────────────────────────────────────────────────────────

if (typeof window !== "undefined" && process.env.NODE_ENV !== "production") {
  (window as unknown as Record<string, unknown>).__SHUGU_COMPOSER_STORE__ =
    useSceneComposerStore;
}
