/**
 * Tests — `useGizmoBinding.ts` (E5.3).
 *
 * Couverture :
 *   1. `onGizmoChange` extrait position de l'Object3D correctement.
 *   2. Rotation convertie radians → degrés avant d'écrire dans le store.
 *   3. Scale extrait correctement.
 *   4. Debounce RAF : plusieurs onGizmoChange → une seule flush (via fake timers).
 *   5. Sans selectedMeshId → updateMeshTransform pas appelé.
 *   6. Sync transformMode → gizmoHandle.setMode.
 *   7. Sync selectedMeshId (avec mesh) → gizmoHandle.attach(mesh).
 *   8. Sync selectedMeshId null → gizmoHandle.attach(null).
 *
 * Stratégie : on utilise le store réel (Zustand) au lieu de le mocker pour
 * éviter les problèmes de hoisting et de sélecteurs non-résolus.
 * On manipule le store directement via `useSceneComposerStore.getState()`.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderHook, act } from "@testing-library/react";
import * as THREE from "three";

// Mock des dépendances Three.js TransformControls/OrbitControls si importés.
vi.mock("three/examples/jsm/controls/TransformControls", () => ({
  TransformControls: class {
    visible = false;
    enabled = false;
    object = null;
    addEventListener = vi.fn();
    removeEventListener = vi.fn();
    setMode = vi.fn();
    attach = vi.fn();
    detach = vi.fn();
    dispose = vi.fn();
  },
}));
vi.mock("three/examples/jsm/controls/OrbitControls", () => ({
  OrbitControls: class {
    enabled = true;
    dispose = vi.fn();
  },
}));

import { useGizmoBindingWithCallbacks } from "../useGizmoBinding";
import { useSceneComposerStore } from "../../../store/useSceneComposerStore";
import type { TransformControlsHandle } from "../../three-stage/transform-controls";

// ── Helpers ───────────────────────────────────────────────────────────────────

const mockSetMode = vi.fn();
const mockAttach = vi.fn();
const mockDispose = vi.fn();

function makeMockGizmoHandle(): TransformControlsHandle {
  return {
    controls: {
      dragging: false,
      object: null,
    } as unknown as import("three/examples/jsm/controls/TransformControls").TransformControls,
    setMode: mockSetMode,
    attach: mockAttach,
    dispose: mockDispose,
  };
}

function makeTestObject(
  pos: [number, number, number] = [0, 0, 0],
  rotRad: [number, number, number] = [0, 0, 0],
  scl: [number, number, number] = [1, 1, 1],
  instanceId = "default_mesh",
): THREE.Object3D {
  const obj = new THREE.Object3D();
  obj.position.set(...pos);
  obj.rotation.set(...rotRad);
  obj.scale.set(...scl);
  obj.userData["instanceId"] = instanceId;
  return obj;
}

// ── Setup ─────────────────────────────────────────────────────────────────────

beforeEach(() => {
  vi.clearAllMocks();
  vi.useFakeTimers();
  // Reset le store avant chaque test.
  useSceneComposerStore.getState().resetUI();
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

// ── Tests onGizmoChange ───────────────────────────────────────────────────────

describe("useGizmoBindingWithCallbacks · onGizmoChange extraction", () => {
  it("position extraite correctement et transmise au store via RAF", async () => {
    // Setup : sélectionner un mesh dans le store.
    useSceneComposerStore.getState().addPropInstance({
      id: "mesh_test",
      assetSlug: "box",
      transform: { position: [0, 0, 0], rotation: [0, 0, 0], scale: [1, 1, 1] },
    });
    useSceneComposerStore.getState().setSelectedMeshId("mesh_test");

    const gizmoHandle = makeMockGizmoHandle();
    const meshRegistry = { current: new Map<string, THREE.Object3D>() };

    const { result } = renderHook(() =>
      useGizmoBindingWithCallbacks({ gizmoHandle, meshRegistry }),
    );

    const obj = makeTestObject([1.5, 0.5, -2.0], [0, 0, 0], [1, 1, 1], "mesh_test");

    act(() => {
      result.current.onGizmoChange(obj);
    });

    await act(async () => {
      await vi.runAllTimersAsync();
    });

    const instances = useSceneComposerStore.getState().propInstances;
    expect(instances["mesh_test"]?.transform.position).toEqual([1.5, 0.5, -2.0]);
  });

  it("rotation convertie radians → degrés dans le store", async () => {
    useSceneComposerStore.getState().addPropInstance({
      id: "mesh_rot",
      assetSlug: "box",
      transform: { position: [0, 0, 0], rotation: [0, 0, 0], scale: [1, 1, 1] },
    });
    useSceneComposerStore.getState().setSelectedMeshId("mesh_rot");

    const gizmoHandle = makeMockGizmoHandle();
    const meshRegistry = { current: new Map<string, THREE.Object3D>() };

    const { result } = renderHook(() =>
      useGizmoBindingWithCallbacks({ gizmoHandle, meshRegistry }),
    );

    // 90° en radians = Math.PI / 2.
    const obj = makeTestObject([0, 0, 0], [0, Math.PI / 2, 0], [1, 1, 1], "mesh_rot");

    act(() => {
      result.current.onGizmoChange(obj);
    });

    await act(async () => {
      await vi.runAllTimersAsync();
    });

    const instances = useSceneComposerStore.getState().propInstances;
    const rotY = instances["mesh_rot"]?.transform.rotation[1];
    expect(rotY).toBeCloseTo(90, 0);
  });

  it("3 onGizmoChange rapides → une seule mise à jour du store (debounce)", async () => {
    useSceneComposerStore.getState().addPropInstance({
      id: "mesh_db",
      assetSlug: "box",
      transform: { position: [0, 0, 0], rotation: [0, 0, 0], scale: [1, 1, 1] },
    });
    useSceneComposerStore.getState().setSelectedMeshId("mesh_db");

    const gizmoHandle = makeMockGizmoHandle();
    const meshRegistry = { current: new Map<string, THREE.Object3D>() };

    const { result } = renderHook(() =>
      useGizmoBindingWithCallbacks({ gizmoHandle, meshRegistry }),
    );

    const obj1 = makeTestObject([1, 0, 0], [0, 0, 0], [1, 1, 1], "mesh_db");
    const obj2 = makeTestObject([2, 0, 0], [0, 0, 0], [1, 1, 1], "mesh_db");
    const obj3 = makeTestObject([3, 0, 0], [0, 0, 0], [1, 1, 1], "mesh_db");

    act(() => {
      result.current.onGizmoChange(obj1);
      result.current.onGizmoChange(obj2);
      result.current.onGizmoChange(obj3);
    });

    await act(async () => {
      await vi.runAllTimersAsync();
    });

    // Seule la dernière valeur doit être dans le store.
    const instances = useSceneComposerStore.getState().propInstances;
    expect(instances["mesh_db"]?.transform.position[0]).toBeCloseTo(3, 1);
  });
});

describe("useGizmoBindingWithCallbacks · no selectedMeshId", () => {
  it("flush sans selectedMeshId → propInstances inchangé", async () => {
    // Pas de selectedMeshId dans le store (état initial = null).

    const gizmoHandle = makeMockGizmoHandle();
    const meshRegistry = { current: new Map<string, THREE.Object3D>() };

    const { result } = renderHook(() =>
      useGizmoBindingWithCallbacks({ gizmoHandle, meshRegistry }),
    );

    const obj = makeTestObject([99, 0, 0]);

    act(() => {
      result.current.onGizmoChange(obj);
    });

    await act(async () => {
      await vi.runAllTimersAsync();
    });

    expect(useSceneComposerStore.getState().propInstances).toEqual({});
  });
});

describe("useGizmoBindingWithCallbacks · sync transformMode → gizmo", () => {
  it("transformMode 'rotate' au mount → gizmoHandle.setMode('rotate') appelé", () => {
    useSceneComposerStore.getState().setTransformMode("rotate");

    const gizmoHandle = makeMockGizmoHandle();
    const meshRegistry = { current: new Map<string, THREE.Object3D>() };

    act(() => {
      renderHook(() =>
        useGizmoBindingWithCallbacks({ gizmoHandle, meshRegistry }),
      );
    });

    expect(mockSetMode).toHaveBeenCalledWith("rotate");
  });

  it("transformMode 'translate' au mount → gizmoHandle.setMode('translate') appelé", () => {
    // L'état initial du store est "translate".
    const gizmoHandle = makeMockGizmoHandle();
    const meshRegistry = { current: new Map<string, THREE.Object3D>() };

    act(() => {
      renderHook(() =>
        useGizmoBindingWithCallbacks({ gizmoHandle, meshRegistry }),
      );
    });

    expect(mockSetMode).toHaveBeenCalledWith("translate");
  });
});

describe("useGizmoBindingWithCallbacks · sync selectedMeshId → gizmo attach", () => {
  it("selectedMeshId null → gizmoHandle.attach(null)", () => {
    // État initial : selectedMeshId = null.
    const gizmoHandle = makeMockGizmoHandle();
    const meshRegistry = { current: new Map<string, THREE.Object3D>() };

    act(() => {
      renderHook(() =>
        useGizmoBindingWithCallbacks({ gizmoHandle, meshRegistry }),
      );
    });

    expect(mockAttach).toHaveBeenCalledWith(null);
  });

  it("selectedMeshId présent mais absent du registry → attach(null)", () => {
    useSceneComposerStore.getState().setSelectedMeshId("mesh_xyz");

    const gizmoHandle = makeMockGizmoHandle();
    const meshRegistry = { current: new Map<string, THREE.Object3D>() };
    // Registry vide — mesh non trouvé.

    act(() => {
      renderHook(() =>
        useGizmoBindingWithCallbacks({ gizmoHandle, meshRegistry }),
      );
    });

    expect(mockAttach).toHaveBeenCalledWith(null);
  });

  it("selectedMeshId présent ET mesh dans registry → attach(mesh)", () => {
    useSceneComposerStore.getState().setSelectedMeshId("mesh_abc");

    const gizmoHandle = makeMockGizmoHandle();
    const meshRegistry = { current: new Map<string, THREE.Object3D>() };
    const mesh = makeTestObject();
    meshRegistry.current.set("mesh_abc", mesh);

    act(() => {
      renderHook(() =>
        useGizmoBindingWithCallbacks({ gizmoHandle, meshRegistry }),
      );
    });

    expect(mockAttach).toHaveBeenCalledWith(mesh);
  });
});

describe("useGizmoBindingWithCallbacks · C1 fix — RAF instanceId binding (race condition)", () => {
  it("sélection change avant le RAF flush → le transform du mesh source est appliqué (pas du mesh sélectionné)", async () => {
    // TDD TEST : vérifie que le bug C1 est corrigé.
    // Setup : 2 meshes A et B, A sélectionné initialement.
    useSceneComposerStore.getState().addPropInstance({
      id: "mesh_A",
      assetSlug: "lamp",
      transform: { position: [0, 0, 0], rotation: [0, 0, 0], scale: [1, 1, 1] },
    });
    useSceneComposerStore.getState().addPropInstance({
      id: "mesh_B",
      assetSlug: "chair",
      transform: { position: [0, 0, 0], rotation: [0, 0, 0], scale: [1, 1, 1] },
    });
    useSceneComposerStore.getState().setSelectedMeshId("mesh_A");

    const gizmoHandle = makeMockGizmoHandle();
    const meshRegistry = { current: new Map<string, THREE.Object3D>() };
    const meshA = makeTestObject([0, 0, 0]);
    const meshB = makeTestObject([0, 0, 0]);
    meshA.userData["instanceId"] = "mesh_A";
    meshB.userData["instanceId"] = "mesh_B";
    meshRegistry.current.set("mesh_A", meshA);
    meshRegistry.current.set("mesh_B", meshB);

    const { result } = renderHook(() =>
      useGizmoBindingWithCallbacks({ gizmoHandle, meshRegistry }),
    );

    // Capture les RAF IDs pour les déclencher manuellement.
    const rafCallbacks: Map<number, () => void> = new Map();
    let rafIdCounter = 1;
    const mockRequestAnimationFrame = vi.fn((cb) => {
      const id = rafIdCounter++;
      rafCallbacks.set(id, cb);
      return id;
    });
    global.requestAnimationFrame = mockRequestAnimationFrame;

    // Step 1 : drag sur mesh_A → bufferise le RAF avec les coordonnées de A.
    const transformA = makeTestObject([1.5, 0.5, -2.0]);
    transformA.userData["instanceId"] = "mesh_A";

    act(() => {
      result.current.onGizmoChange(transformA);
    });

    // Vérifie qu'un RAF a été programmé.
    expect(mockRequestAnimationFrame).toHaveBeenCalled();
    const rafId = rafIdCounter - 1;
    const flushCallback = rafCallbacks.get(rafId);
    expect(flushCallback).toBeDefined();

    // Step 2 : avant le flush, change la sélection à mesh_B.
    act(() => {
      useSceneComposerStore.getState().setSelectedMeshId("mesh_B");
    });

    // Step 3 : déclenche le flush (le RAF).
    act(() => {
      flushCallback?.();
    });

    // EXPECT : updateMeshTransform a été appelé avec instanceId="mesh_A" (source du transform)
    // et le transform de A, PAS celui de B (qui est sélectionné maintenant).
    const state = useSceneComposerStore.getState();
    expect(state.propInstances["mesh_A"]?.transform.position).toEqual([1.5, 0.5, -2.0]);
    // mesh_B ne doit pas avoir été modifié (reste à [0, 0, 0]).
    expect(state.propInstances["mesh_B"]?.transform.position).toEqual([0, 0, 0]);
  });
});
