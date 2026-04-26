/**
 * Tests — `useSceneComposerStore` (Phase E5.2 + E5.3).
 *
 * Couverture E5.2 :
 *   1. État initial correct.
 *   2. setSelectedSceneId → met à jour selectedSceneId.
 *   3. setViewerMode → met à jour viewerMode.
 *   4. setCameraPreset → met à jour cameraPreset.
 *   5. setPanelLayout → met à jour panelLayout.
 *   6. resetUI → revient à l'état initial.
 *   7. Selectors granulaires retournent la valeur correcte.
 *
 * Couverture E5.3 :
 *   8. État initial E5.3 : selectedMeshId null, transformMode translate, propInstances vide.
 *   9. setSelectedMeshId met à jour selectedMeshId.
 *  10. setTransformMode met à jour transformMode.
 *  11. addPropInstance ajoute une instance dans propInstances.
 *  12. removePropInstance retire l'instance correcte.
 *  13. updateMeshTransform met à jour partiellement le transform.
 *  14. updateMeshTransform sur un ID inexistant : no-op (pas de crash).
 *  15. addPropInstance multiple : les instances coexistent.
 *  16. resetUI remet les champs E5.3 à leur valeur initiale.
 *
 * Pattern : pas de mock React — on teste le store Zustand directement via
 * `getState()` / `setState()`.
 */

import { beforeEach, describe, expect, it } from "vitest";
import {
  useSceneComposerStore,
  selectSelectedSceneId,
  selectViewerMode,
  selectCameraPreset,
  selectPanelLayout,
  selectSelectedMeshId,
  selectTransformMode,
  selectPropInstances,
  selectPropInstance,
  type PropInstance,
  type ObjectTransform,
} from "../store/useSceneComposerStore";

// ── Helpers ───────────────────────────────────────────────────────────────────

function makePropInstance(id: string, slug = "test_prop"): PropInstance {
  return {
    id,
    assetSlug: slug,
    transform: {
      position: [0, 0, 0],
      rotation: [0, 0, 0],
      scale: [1, 1, 1],
    },
  };
}

// ── Setup ─────────────────────────────────────────────────────────────────────

beforeEach(() => {
  useSceneComposerStore.getState().resetUI();
});

// ── Tests E5.2 ────────────────────────────────────────────────────────────────

describe("useSceneComposerStore · état initial E5.2", () => {
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

describe("useSceneComposerStore · actions E5.2", () => {
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

describe("useSceneComposerStore · resetUI E5.2", () => {
  it("resetUI ramène tous les champs à leur valeur initiale", () => {
    useSceneComposerStore.getState().setSelectedSceneId("scene-123");
    useSceneComposerStore.getState().setViewerMode("preview");
    useSceneComposerStore.getState().setCameraPreset("top");
    useSceneComposerStore.getState().setPanelLayout("fullscreen");

    useSceneComposerStore.getState().resetUI();

    const state = useSceneComposerStore.getState();
    expect(selectSelectedSceneId(state)).toBeNull();
    expect(selectViewerMode(state)).toBe("edit");
    expect(selectCameraPreset(state)).toBe("free");
    expect(selectPanelLayout(state)).toBe("split-right");
  });
});

// ── Tests E5.3 ────────────────────────────────────────────────────────────────

describe("useSceneComposerStore · état initial E5.3", () => {
  it("selectedMeshId est null", () => {
    expect(selectSelectedMeshId(useSceneComposerStore.getState())).toBeNull();
  });

  it("transformMode est 'translate'", () => {
    expect(selectTransformMode(useSceneComposerStore.getState())).toBe("translate");
  });

  it("propInstances est un objet vide", () => {
    expect(selectPropInstances(useSceneComposerStore.getState())).toEqual({});
  });
});

describe("useSceneComposerStore · actions E5.3 — selectedMeshId + transformMode", () => {
  it("setSelectedMeshId met à jour selectedMeshId", () => {
    useSceneComposerStore.getState().setSelectedMeshId("mesh_abc");
    expect(selectSelectedMeshId(useSceneComposerStore.getState())).toBe("mesh_abc");
  });

  it("setSelectedMeshId(null) remet à null", () => {
    useSceneComposerStore.getState().setSelectedMeshId("mesh_abc");
    useSceneComposerStore.getState().setSelectedMeshId(null);
    expect(selectSelectedMeshId(useSceneComposerStore.getState())).toBeNull();
  });

  it("setTransformMode('rotate') met à jour transformMode", () => {
    useSceneComposerStore.getState().setTransformMode("rotate");
    expect(selectTransformMode(useSceneComposerStore.getState())).toBe("rotate");
  });

  it("setTransformMode('scale') met à jour transformMode", () => {
    useSceneComposerStore.getState().setTransformMode("scale");
    expect(selectTransformMode(useSceneComposerStore.getState())).toBe("scale");
  });
});

describe("useSceneComposerStore · actions E5.3 — propInstances", () => {
  it("addPropInstance ajoute une instance dans propInstances", () => {
    const instance = makePropInstance("inst_001");
    useSceneComposerStore.getState().addPropInstance(instance);

    const instances = selectPropInstances(useSceneComposerStore.getState());
    expect(instances["inst_001"]).toEqual(instance);
  });

  it("addPropInstance multiple : les instances coexistent", () => {
    useSceneComposerStore.getState().addPropInstance(makePropInstance("inst_001"));
    useSceneComposerStore.getState().addPropInstance(makePropInstance("inst_002", "other_prop"));

    const instances = selectPropInstances(useSceneComposerStore.getState());
    expect(Object.keys(instances)).toHaveLength(2);
    expect(instances["inst_001"]?.assetSlug).toBe("test_prop");
    expect(instances["inst_002"]?.assetSlug).toBe("other_prop");
  });

  it("removePropInstance retire l'instance correcte", () => {
    useSceneComposerStore.getState().addPropInstance(makePropInstance("inst_001"));
    useSceneComposerStore.getState().addPropInstance(makePropInstance("inst_002"));
    useSceneComposerStore.getState().removePropInstance("inst_001");

    const instances = selectPropInstances(useSceneComposerStore.getState());
    expect(instances["inst_001"]).toBeUndefined();
    expect(instances["inst_002"]).toBeDefined();
  });

  it("selectPropInstance retourne l'instance par ID", () => {
    const instance = makePropInstance("inst_xyz");
    useSceneComposerStore.getState().addPropInstance(instance);

    const selector = selectPropInstance("inst_xyz");
    expect(selector(useSceneComposerStore.getState())).toEqual(instance);
  });

  it("selectPropInstance retourne undefined pour un ID inexistant", () => {
    const selector = selectPropInstance("inexistant");
    expect(selector(useSceneComposerStore.getState())).toBeUndefined();
  });
});

describe("useSceneComposerStore · actions E5.3 — updateMeshTransform", () => {
  it("updateMeshTransform met à jour la position partiellement", () => {
    const instance = makePropInstance("inst_pos");
    useSceneComposerStore.getState().addPropInstance(instance);

    const newPos: Pick<ObjectTransform, "position"> = {
      position: [1.5, 0.5, -2.0],
    };
    useSceneComposerStore.getState().updateMeshTransform("inst_pos", newPos);

    const updated = selectPropInstances(useSceneComposerStore.getState())["inst_pos"];
    expect(updated?.transform.position).toEqual([1.5, 0.5, -2.0]);
    // Les autres champs sont inchangés.
    expect(updated?.transform.rotation).toEqual([0, 0, 0]);
    expect(updated?.transform.scale).toEqual([1, 1, 1]);
  });

  it("updateMeshTransform met à jour rotation et scale", () => {
    const instance = makePropInstance("inst_rot");
    useSceneComposerStore.getState().addPropInstance(instance);

    useSceneComposerStore.getState().updateMeshTransform("inst_rot", {
      rotation: [0, 90, 0],
      scale: [2, 2, 2],
    });

    const updated = selectPropInstances(useSceneComposerStore.getState())["inst_rot"];
    expect(updated?.transform.rotation).toEqual([0, 90, 0]);
    expect(updated?.transform.scale).toEqual([2, 2, 2]);
  });

  it("updateMeshTransform sur ID inexistant : no-op (pas de crash)", () => {
    expect(() => {
      useSceneComposerStore.getState().updateMeshTransform("inexistant", {
        position: [1, 2, 3],
      });
    }).not.toThrow();

    // propInstances toujours vide.
    expect(selectPropInstances(useSceneComposerStore.getState())).toEqual({});
  });
});

describe("useSceneComposerStore · resetUI E5.3", () => {
  it("resetUI remet selectedMeshId, transformMode, propInstances à l'état initial", () => {
    // Modifier les champs E5.3.
    useSceneComposerStore.getState().setSelectedMeshId("mesh_xyz");
    useSceneComposerStore.getState().setTransformMode("scale");
    useSceneComposerStore.getState().addPropInstance(makePropInstance("inst_001"));

    useSceneComposerStore.getState().resetUI();

    const state = useSceneComposerStore.getState();
    expect(selectSelectedMeshId(state)).toBeNull();
    expect(selectTransformMode(state)).toBe("translate");
    expect(selectPropInstances(state)).toEqual({});
  });
});
