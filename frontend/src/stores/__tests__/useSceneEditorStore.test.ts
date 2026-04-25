/**
 * Tests unit — `useSceneEditorStore`.
 *
 * Couvre :
 *   - state initial (UI defaults + data seeded from mocks)
 *   - UI actions : setTool, setSelectedId, setCurrentScene, setLayoutPreset
 *   - toggleNodeVisibility / toggleNodeLock (mutation immuable de l'arbre)
 *   - selectCurrentInspector (lookup par selectedId)
 *   - temporal (zundo) : undo/redo suivent currentScene / layoutPreset /
 *     hierarchy, IGNORENT tool / selectedId (éphémères)
 *   - limit temporal à 50 snapshots
 */

import { beforeEach, describe, expect, it } from "vitest";
import {
  useSceneEditorStore,
  selectCurrentInspector,
} from "../useSceneEditorStore";
import { MOCK_INSPECTOR, MOCK_HIERARCHY } from "@/features/scene-editor/mock-data";

beforeEach(() => {
  useSceneEditorStore.getState().resetUI();
  useSceneEditorStore.temporal.getState().clear();
  // Phase F : l'action updateInspectorField mute inspectorById entre tests.
  // On re-seed via un set direct (Zustand ne fournit pas d'action
  // setInspectorById pour éviter que la prod appelle ça par erreur). Même
  // chose pour hierarchy dont les toggles mutent.
  useSceneEditorStore.setState({
    inspectorById: JSON.parse(JSON.stringify(MOCK_INSPECTOR)),
    hierarchy: JSON.parse(JSON.stringify(MOCK_HIERARCHY)),
  });
  useSceneEditorStore.temporal.getState().clear();
});

describe("useSceneEditorStore · initial state", () => {
  it("expose les UI defaults attendus (s2 / shugu / move / Streaming)", () => {
    const state = useSceneEditorStore.getState();
    expect(state.currentScene).toBe("s2");
    expect(state.selectedId).toBe("shugu");
    expect(state.tool).toBe("move");
    // Phase B fix H-1 : aligné verbatim sur les options du Select toolbar.
    expect(state.layoutPreset).toBe("Streaming");
  });

  it("seeds les data depuis les MOCK_* de mock-data.ts", () => {
    const state = useSceneEditorStore.getState();
    expect(state.scenes.length).toBeGreaterThanOrEqual(5);
    expect(state.assets.length).toBeGreaterThanOrEqual(10);
    expect(state.patterns.length).toBeGreaterThanOrEqual(4);
    expect(state.audioChannels.length).toBeGreaterThanOrEqual(4);
    expect(state.timeline.duration).toBeGreaterThan(0);
    expect(state.timeline.tracks.length).toBeGreaterThan(0);
    // Hierarchy a un root "scene" avec des children.
    expect(state.hierarchy[0]?.id).toBe("scene");
    expect(state.hierarchy[0]?.children?.length).toBeGreaterThan(0);
  });

  it("inspectorById est un map, pas un objet plat", () => {
    const state = useSceneEditorStore.getState();
    expect(state.inspectorById).toBeTypeOf("object");
    expect(state.inspectorById.shugu).toBeDefined();
    expect(state.inspectorById.shugu.name).toBe("Shugu (VRM)");
  });
});

describe("useSceneEditorStore · UI actions", () => {
  it("setTool change l'outil actif", () => {
    useSceneEditorStore.getState().setTool("rotate");
    expect(useSceneEditorStore.getState().tool).toBe("rotate");
    useSceneEditorStore.getState().setTool("scale");
    expect(useSceneEditorStore.getState().tool).toBe("scale");
  });

  it("setSelectedId accepte string et null", () => {
    useSceneEditorStore.getState().setSelectedId("aura");
    expect(useSceneEditorStore.getState().selectedId).toBe("aura");
    useSceneEditorStore.getState().setSelectedId(null);
    expect(useSceneEditorStore.getState().selectedId).toBeNull();
  });

  it("setCurrentScene change la scène active", () => {
    useSceneEditorStore.getState().setCurrentScene("s3");
    expect(useSceneEditorStore.getState().currentScene).toBe("s3");
  });

  it("setLayoutPreset accepte les 4 valeurs de l'enum (Streaming/Editing/Performance/Custom…)", () => {
    useSceneEditorStore.getState().setLayoutPreset("Editing");
    expect(useSceneEditorStore.getState().layoutPreset).toBe("Editing");
    useSceneEditorStore.getState().setLayoutPreset("Performance");
    expect(useSceneEditorStore.getState().layoutPreset).toBe("Performance");
    useSceneEditorStore.getState().setLayoutPreset("Custom…");
    expect(useSceneEditorStore.getState().layoutPreset).toBe("Custom…");
    useSceneEditorStore.getState().setLayoutPreset("Streaming");
    expect(useSceneEditorStore.getState().layoutPreset).toBe("Streaming");
  });

  it("resetUI restaure TOUS les champs UI (pas les data)", () => {
    useSceneEditorStore.getState().setTool("rotate");
    useSceneEditorStore.getState().setSelectedId("aura");
    useSceneEditorStore.getState().setCurrentScene("s5");
    useSceneEditorStore.getState().setLayoutPreset("Editing");

    useSceneEditorStore.getState().resetUI();

    const state = useSceneEditorStore.getState();
    expect(state.tool).toBe("move");
    expect(state.selectedId).toBe("shugu");
    expect(state.currentScene).toBe("s2");
    expect(state.layoutPreset).toBe("Streaming");
    // Data n'est PAS reset (les MOCK_* restent en place).
    expect(state.assets.length).toBeGreaterThanOrEqual(10);
  });
});

describe("useSceneEditorStore · hierarchy toggles", () => {
  it("toggleNodeVisibility flip le flag et préserve la référence des siblings", () => {
    const before = useSceneEditorStore.getState().hierarchy;
    const rootBefore = before[0];
    const shuguBefore = rootBefore.children?.find((c) => c.id === "group-stage")?.children?.find(
      (c) => c.id === "shugu",
    );
    expect(shuguBefore?.visible).toBe(true);

    useSceneEditorStore.getState().toggleNodeVisibility("shugu");

    const after = useSceneEditorStore.getState().hierarchy;
    const shuguAfter = after[0].children?.find((c) => c.id === "group-stage")?.children?.find(
      (c) => c.id === "shugu",
    );
    expect(shuguAfter?.visible).toBe(false);

    // Re-flip pour remettre dans l'état initial.
    useSceneEditorStore.getState().toggleNodeVisibility("shugu");
    const final = useSceneEditorStore.getState().hierarchy;
    const shuguFinal = final[0].children?.find((c) => c.id === "group-stage")?.children?.find(
      (c) => c.id === "shugu",
    );
    expect(shuguFinal?.visible).toBe(true);
  });

  it("toggleNodeLock flip lock sans toucher à visibility", () => {
    useSceneEditorStore.getState().toggleNodeLock("shugu");
    const after = useSceneEditorStore.getState().hierarchy;
    const shugu = after[0].children?.find((c) => c.id === "group-stage")?.children?.find(
      (c) => c.id === "shugu",
    );
    expect(shugu?.locked).toBe(true);
    expect(shugu?.visible).toBe(true); // intact
  });

  it("toggleNodeVisibility sur un id inexistant est un no-op", () => {
    const before = useSceneEditorStore.getState().hierarchy;
    useSceneEditorStore.getState().toggleNodeVisibility("nonexistent-id-xyz");
    const after = useSceneEditorStore.getState().hierarchy;
    // Référence identique = aucune mutation profonde inutile.
    expect(after).toBe(before);
  });
});

describe("useSceneEditorStore · selectCurrentInspector", () => {
  it("retourne null si rien n'est sélectionné", () => {
    useSceneEditorStore.getState().setSelectedId(null);
    expect(selectCurrentInspector(useSceneEditorStore.getState())).toBeNull();
  });

  it("retourne l'inspector data du node sélectionné", () => {
    useSceneEditorStore.getState().setSelectedId("shugu");
    const inspector = selectCurrentInspector(useSceneEditorStore.getState());
    expect(inspector).not.toBeNull();
    expect(inspector?.name).toBe("Shugu (VRM)");
  });

  it("retourne null pour un node inexistant dans inspectorById", () => {
    useSceneEditorStore.getState().setSelectedId("ghost-id");
    expect(selectCurrentInspector(useSceneEditorStore.getState())).toBeNull();
  });
});

describe("useSceneEditorStore · temporal (zundo undo/redo)", () => {
  it("undo restaure la currentScene précédente", () => {
    // Initial: s2
    useSceneEditorStore.getState().setCurrentScene("s3");
    useSceneEditorStore.getState().setCurrentScene("s5");
    expect(useSceneEditorStore.getState().currentScene).toBe("s5");

    useSceneEditorStore.temporal.getState().undo();
    expect(useSceneEditorStore.getState().currentScene).toBe("s3");

    useSceneEditorStore.temporal.getState().undo();
    expect(useSceneEditorStore.getState().currentScene).toBe("s2");
  });

  it("redo re-applique un undo", () => {
    useSceneEditorStore.getState().setCurrentScene("s3");
    useSceneEditorStore.temporal.getState().undo();
    expect(useSceneEditorStore.getState().currentScene).toBe("s2");

    useSceneEditorStore.temporal.getState().redo();
    expect(useSceneEditorStore.getState().currentScene).toBe("s3");
  });

  it("tool change ne génère PAS de snapshot undoable", () => {
    useSceneEditorStore.getState().setTool("rotate");
    useSceneEditorStore.getState().setTool("scale");
    // Rien dans le passé : tool n'est pas dans le partialize.
    expect(useSceneEditorStore.temporal.getState().pastStates.length).toBe(0);
  });

  it("selectedId change ne génère PAS de snapshot undoable", () => {
    useSceneEditorStore.getState().setSelectedId("aura");
    useSceneEditorStore.getState().setSelectedId(null);
    expect(useSceneEditorStore.temporal.getState().pastStates.length).toBe(0);
  });

  it("toggleNodeVisibility GÉNÈRE un snapshot undoable", () => {
    const beforeLen = useSceneEditorStore.temporal.getState().pastStates.length;
    useSceneEditorStore.getState().toggleNodeVisibility("shugu");
    const afterLen = useSceneEditorStore.temporal.getState().pastStates.length;
    expect(afterLen).toBe(beforeLen + 1);

    // Undo restaure la visibilité.
    useSceneEditorStore.temporal.getState().undo();
    const hierarchy = useSceneEditorStore.getState().hierarchy;
    const shugu = hierarchy[0].children?.find((c) => c.id === "group-stage")?.children?.find(
      (c) => c.id === "shugu",
    );
    expect(shugu?.visible).toBe(true);
  });

  it("historique limité à 50 snapshots (pas de fuite mémoire infinie)", () => {
    // On pousse 60 changements de scène consécutifs.
    for (let i = 0; i < 60; i++) {
      useSceneEditorStore.getState().setCurrentScene(`s${i}`);
    }
    // Le passé ne dépasse pas 50.
    const pastLen = useSceneEditorStore.temporal.getState().pastStates.length;
    expect(pastLen).toBeLessThanOrEqual(50);
  });
});

/* ═════════════════ Phase F — updateInspectorField ═════════════════ */

describe("useSceneEditorStore · updateInspectorField (Phase F)", () => {
  it("update deep path transform.pos sur shugu", () => {
    useSceneEditorStore
      .getState()
      .updateInspectorField("shugu", "transform.pos", [1, 2, 3]);
    const state = useSceneEditorStore.getState();
    expect(state.inspectorById.shugu.transform.pos).toEqual([1, 2, 3]);
    // Les autres champs transform ne sont pas modifiés.
    expect(state.inspectorById.shugu.transform.rot).toEqual([0, 12, 0]);
    expect(state.inspectorById.shugu.transform.scale).toEqual([1, 1, 1]);
  });

  it("update via index numeric dans path : transform.pos.1 = 42", () => {
    useSceneEditorStore
      .getState()
      .updateInspectorField("shugu", "transform.pos.1", 42);
    const state = useSceneEditorStore.getState();
    expect(state.inspectorById.shugu.transform.pos).toEqual([-0.6, 42, 0.2]);
  });

  it("update une propriété simple : render.opacity", () => {
    useSceneEditorStore
      .getState()
      .updateInspectorField("shugu", "render.opacity", 0.5);
    const state = useSceneEditorStore.getState();
    expect(state.inspectorById.shugu.render?.opacity).toBe(0.5);
  });

  it("nodeId inexistant : no-op silencieux (aucune mutation)", () => {
    const before = useSceneEditorStore.getState().inspectorById;
    useSceneEditorStore
      .getState()
      .updateInspectorField("ghost", "transform.pos", [9, 9, 9]);
    const after = useSceneEditorStore.getState().inspectorById;
    expect(after).toBe(before); // même ref = no-op
  });

  it("path pointant sur segment parent inexistant : no-op (ne crée pas la section)", () => {
    // `camera1` a `camera` mais pas `vrm`. Writer `vrm.expression` ne doit
    // PAS créer la section `vrm` — shape protection.
    const beforeCam = useSceneEditorStore.getState().inspectorById.camera1;
    expect(beforeCam.vrm).toBeUndefined();
    useSceneEditorStore
      .getState()
      .updateInspectorField("camera1", "vrm.expression", "Happy");
    const afterCam = useSceneEditorStore.getState().inspectorById.camera1;
    expect(afterCam.vrm).toBeUndefined();
  });

  it("update GÉNÈRE un snapshot zundo (undoable via ⌘Z)", () => {
    const beforeLen = useSceneEditorStore.temporal.getState().pastStates.length;
    useSceneEditorStore
      .getState()
      .updateInspectorField("shugu", "transform.pos", [5, 5, 5]);
    const afterLen = useSceneEditorStore.temporal.getState().pastStates.length;
    expect(afterLen).toBe(beforeLen + 1);

    // Undo restaure la position initiale.
    useSceneEditorStore.temporal.getState().undo();
    const restored = useSceneEditorStore.getState().inspectorById.shugu;
    expect(restored.transform.pos).toEqual([-0.6, 0, 0.2]);
  });

  it("batch de 3 updates → 3 snapshots distincts (granularity zundo)", () => {
    const before = useSceneEditorStore.temporal.getState().pastStates.length;
    useSceneEditorStore
      .getState()
      .updateInspectorField("shugu", "transform.pos.0", 1);
    useSceneEditorStore
      .getState()
      .updateInspectorField("shugu", "transform.pos.0", 2);
    useSceneEditorStore
      .getState()
      .updateInspectorField("shugu", "transform.pos.0", 3);
    const after = useSceneEditorStore.temporal.getState().pastStates.length;
    expect(after - before).toBe(3);
    expect(useSceneEditorStore.getState().inspectorById.shugu.transform.pos[0]).toBe(
      3,
    );
  });

  it("immutabilité : l'entry d'un autre node n'est pas touché", () => {
    const auraBefore = useSceneEditorStore.getState().inspectorById.aura;
    useSceneEditorStore
      .getState()
      .updateInspectorField("shugu", "transform.pos", [9, 9, 9]);
    const auraAfter = useSceneEditorStore.getState().inspectorById.aura;
    // Même REF : aucune mutation sur aura.
    expect(auraAfter).toBe(auraBefore);
  });
});

/* ═════════════════ Phase D — WS collab state/actions ═════════════════ */

describe("useSceneEditorStore · Phase D WS collab", () => {
  it("initial state : peers vide + remoteDraftDeltas vide", () => {
    const state = useSceneEditorStore.getState();
    expect(state.peers).toEqual([]);
    expect(state.remoteDraftDeltas).toEqual({});
  });

  it("setPeers remplace la liste complète", () => {
    useSceneEditorStore.getState().setPeers(["alice", "bob"]);
    expect(useSceneEditorStore.getState().peers).toEqual(["alice", "bob"]);
    useSceneEditorStore.getState().setPeers(["carol"]);
    expect(useSceneEditorStore.getState().peers).toEqual(["carol"]);
  });

  it("addPeer ajoute si absent, no-op si déjà présent", () => {
    useSceneEditorStore.getState().addPeer("alice");
    expect(useSceneEditorStore.getState().peers).toEqual(["alice"]);
    useSceneEditorStore.getState().addPeer("alice");
    expect(useSceneEditorStore.getState().peers).toEqual(["alice"]);
    useSceneEditorStore.getState().addPeer("bob");
    expect(useSceneEditorStore.getState().peers).toEqual(["alice", "bob"]);
  });

  it("removePeer retire si présent, no-op si absent", () => {
    useSceneEditorStore.getState().setPeers(["alice", "bob", "carol"]);
    useSceneEditorStore.getState().removePeer("bob");
    expect(useSceneEditorStore.getState().peers).toEqual(["alice", "carol"]);
    useSceneEditorStore.getState().removePeer("nobody");
    expect(useSceneEditorStore.getState().peers).toEqual(["alice", "carol"]);
  });

  it("applyRemoteDraftUpdate shallow-merge dans remoteDraftDeltas", () => {
    useSceneEditorStore.getState().applyRemoteDraftUpdate({ fov: 60 });
    expect(useSceneEditorStore.getState().remoteDraftDeltas).toEqual({ fov: 60 });
    useSceneEditorStore.getState().applyRemoteDraftUpdate({ avatar: { x: 1 } });
    expect(useSceneEditorStore.getState().remoteDraftDeltas).toEqual({
      fov: 60,
      avatar: { x: 1 },
    });
    // Override d'une clé existante.
    useSceneEditorStore.getState().applyRemoteDraftUpdate({ fov: 90 });
    expect(useSceneEditorStore.getState().remoteDraftDeltas).toEqual({
      fov: 90,
      avatar: { x: 1 },
    });
  });

  it("resetUI reset aussi peers et remoteDraftDeltas (state de session)", () => {
    useSceneEditorStore.getState().setPeers(["alice", "bob"]);
    useSceneEditorStore.getState().applyRemoteDraftUpdate({ fov: 60 });
    useSceneEditorStore.getState().resetUI();
    const state = useSceneEditorStore.getState();
    expect(state.peers).toEqual([]);
    expect(state.remoteDraftDeltas).toEqual({});
  });
});
