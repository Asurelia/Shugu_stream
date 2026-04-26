/**
 * Tests — `useSceneComposerStore` (Phase E5.2).
 *
 * Couverture :
 *   1. État initial correct.
 *   2. setSelectedSceneId → met à jour selectedSceneId.
 *   3. setViewerMode → met à jour viewerMode.
 *   4. setCameraPreset → met à jour cameraPreset.
 *   5. setPanelLayout → met à jour panelLayout.
 *   6. resetUI → revient à l'état initial.
 *   7. Selectors granulaires retournent la valeur correcte.
 *
 * Pattern : pas de mock React — on teste le store Zustand directement via
 * `getState()` / `setState()` (pattern identique à useSceneEditorStore.test.ts).
 *
 * Isolation : `clearMocks: true` + `restoreMocks: true` dans vitest.config.ts
 * garantissent que le store est réinitialisé entre les tests (module state reset).
 * On appelle `resetUI()` dans `beforeEach` par prudence.
 */

import { beforeEach, describe, expect, it } from "vitest";
import {
  useSceneComposerStore,
  selectSelectedSceneId,
  selectViewerMode,
  selectCameraPreset,
  selectPanelLayout,
} from "../store/useSceneComposerStore";

beforeEach(() => {
  useSceneComposerStore.getState().resetUI();
});

describe("useSceneComposerStore · état initial", () => {
  it("selectedSceneId est null", () => {
    expect(selectSelectedSceneId(useSceneComposerStore.getState())).toBeNull();
  });

  it("viewerMode est 'edit'", () => {
    expect(selectViewerMode(useSceneComposerStore.getState())).toBe("edit");
  });

  it("cameraPreset est 'free'", () => {
    expect(selectCameraPreset(useSceneComposerStore.getState())).toBe("free");
  });

  it("panelLayout est 'split-right'", () => {
    expect(selectPanelLayout(useSceneComposerStore.getState())).toBe(
      "split-right",
    );
  });
});

describe("useSceneComposerStore · actions", () => {
  it("setSelectedSceneId met à jour selectedSceneId", () => {
    useSceneComposerStore.getState().setSelectedSceneId("scene-abc");
    expect(
      selectSelectedSceneId(useSceneComposerStore.getState()),
    ).toBe("scene-abc");
  });

  it("setSelectedSceneId(null) remet à null", () => {
    useSceneComposerStore.getState().setSelectedSceneId("scene-abc");
    useSceneComposerStore.getState().setSelectedSceneId(null);
    expect(
      selectSelectedSceneId(useSceneComposerStore.getState()),
    ).toBeNull();
  });

  it("setViewerMode('preview') met à jour viewerMode", () => {
    useSceneComposerStore.getState().setViewerMode("preview");
    expect(selectViewerMode(useSceneComposerStore.getState())).toBe("preview");
  });

  it("setViewerMode('edit') remet viewerMode en 'edit'", () => {
    useSceneComposerStore.getState().setViewerMode("preview");
    useSceneComposerStore.getState().setViewerMode("edit");
    expect(selectViewerMode(useSceneComposerStore.getState())).toBe("edit");
  });

  it("setCameraPreset('front') met à jour cameraPreset", () => {
    useSceneComposerStore.getState().setCameraPreset("front");
    expect(selectCameraPreset(useSceneComposerStore.getState())).toBe("front");
  });

  it("setCameraPreset parcourt tous les presets sans erreur", () => {
    const presets = ["free", "front", "side", "top"] as const;
    for (const p of presets) {
      expect(() => {
        useSceneComposerStore.getState().setCameraPreset(p);
      }).not.toThrow();
      expect(selectCameraPreset(useSceneComposerStore.getState())).toBe(p);
    }
  });

  it("setPanelLayout('split-bottom') met à jour panelLayout", () => {
    useSceneComposerStore.getState().setPanelLayout("split-bottom");
    expect(selectPanelLayout(useSceneComposerStore.getState())).toBe(
      "split-bottom",
    );
  });

  it("setPanelLayout('fullscreen') masque les panneaux", () => {
    useSceneComposerStore.getState().setPanelLayout("fullscreen");
    expect(selectPanelLayout(useSceneComposerStore.getState())).toBe(
      "fullscreen",
    );
  });
});

describe("useSceneComposerStore · resetUI", () => {
  it("resetUI ramène tous les champs à leur valeur initiale", () => {
    // Modifier tous les champs.
    useSceneComposerStore.getState().setSelectedSceneId("scene-123");
    useSceneComposerStore.getState().setViewerMode("preview");
    useSceneComposerStore.getState().setCameraPreset("top");
    useSceneComposerStore.getState().setPanelLayout("fullscreen");

    // Reset.
    useSceneComposerStore.getState().resetUI();

    const state = useSceneComposerStore.getState();
    expect(selectSelectedSceneId(state)).toBeNull();
    expect(selectViewerMode(state)).toBe("edit");
    expect(selectCameraPreset(state)).toBe("free");
    expect(selectPanelLayout(state)).toBe("split-right");
  });
});
