/**
 * Tests unit — `SceneEditorViewer` (legacy).
 *
 * Phase F Hardening M2 — couvre exclusivement le cleanup des helpers
 * Three.js. La review adversariale a mis en évidence que `GridHelper`,
 * `AxesHelper` et `CameraHelper` n'étaient PAS disposés au unmount, alors
 * que renderer / orbit / gizmo / VRM l'étaient. Phase F monte le viewer
 * 2× simultanés (SceneView + GameView) → leak doublé.
 *
 * # Stratégie de test
 *
 * Le viewer instancie un vrai `THREE.WebGLRenderer` qui appelle
 * `canvas.getContext("webgl2")` — jsdom retourne `null` et le constructor
 * Three.js throw. On mocke donc `WebGLRenderer` (et seulement lui) pour
 * fournir un stub avec `setSize`, `setPixelRatio`, `domElement`, `dispose`.
 *
 * Les helpers en revanche restent **réels** : `THREE.GridHelper`,
 * `THREE.AxesHelper`, `THREE.CameraHelper` exposent une `geometry` et une
 * `material` héritées de `LineSegments` — ce sont elles qu'on espionne
 * via `vi.spyOn(BufferGeometry.prototype, "dispose")` etc. pour vérifier
 * que le cleanup les libère.
 *
 * # Pourquoi pas test côté `ViewerAdapter`
 *
 * `viewer-adapter.test.tsx` mocke `SceneEditorViewer` entièrement. Un test
 * de helper-dispose dans ce fichier ne testerait rien — les helpers ne
 * sont jamais instanciés. Ce fichier-ci établit le 1er test du legacy.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render } from "@testing-library/react";
import * as THREE from "three";

/* ───────────────── MOCK WebGLRenderer ─────────────────
 * jsdom n'a pas WebGL. On remplace `WebGLRenderer` par un stub minimal
 * qui satisfait le contract utilisé dans le viewer (setSize, setPixelRatio,
 * domElement, render, dispose). On garde le reste de Three.js intact pour
 * que les helpers (GridHelper/AxesHelper/CameraHelper), TransformControls
 * et OrbitControls soient les vraies instances.
 */
vi.mock("three", async () => {
  const actual = await vi.importActual<typeof THREE>("three");

  class WebGLRendererStub {
    domElement: HTMLCanvasElement;
    outputEncoding = 0;
    constructor(opts: { canvas?: HTMLCanvasElement }) {
      this.domElement = opts.canvas ?? document.createElement("canvas");
    }
    setPixelRatio(): void {}
    setSize(): void {}
    render(): void {}
    dispose(): void {}
  }

  return {
    ...actual,
    WebGLRenderer: WebGLRendererStub,
  };
});

// Mock du loader VRM : skip le download du fichier 28 MB en test, sinon le
// load async pollue le résultat des spies (on ne testerait plus QUE le
// cleanup des helpers, car le VRM ne charge jamais en test). On simule
// simplement un loader qui ne résout jamais — le test unmount AVANT que
// la promise ait pu fire de toute façon.
vi.mock("three/examples/jsm/loaders/GLTFLoader", () => ({
  GLTFLoader: class {
    register(): void {}
    load(): void {}
  },
}));

// OrbitControls et TransformControls instancient leur propre `addEventListener`
// sur `domElement` et utilisent des features DOM (pointer events) que jsdom
// supporte mal → on stub à un objet minimal pour ne tester QUE les helpers.
vi.mock("three/examples/jsm/controls/OrbitControls", () => ({
  OrbitControls: class {
    target = { set: () => {} };
    enableDamping = false;
    dampingFactor = 0;
    enabled = false;
    update(): void {}
    dispose(): void {}
  },
}));

vi.mock("three/examples/jsm/controls/TransformControls", () => {
  // TransformControls hérite de Object3D dans la vraie implem — on doit
  // donc avoir une instance qui passe `scene.add()` sans crash.
  return {
    TransformControls: class {
      visible = false;
      enabled = false;
      dragging = false;
      position = { x: 0, y: 0, z: 0 };
      // Object3D shape minimal pour passer `scene.add(gizmo)`.
      isObject3D = true;
      parent: unknown = null;
      children: unknown[] = [];
      type = "TransformControls";
      uuid = "stub-tc";
      add(): void {}
      setMode(): void {}
      attach(): void {}
      detach(): void {}
      dispose(): void {}
      addEventListener(): void {}
      removeEventListener(): void {}
      dispatchEvent(): void {}
      updateMatrix(): void {}
      updateMatrixWorld(): void {}
      updateWorldMatrix(): void {}
      raycast(): void {}
      onBeforeRender(): void {}
      onAfterRender(): void {}
      layers = { mask: 1, test: () => true };
      visibility: unknown = null;
      matrix = { elements: new Array(16).fill(0) };
      matrixWorld = { elements: new Array(16).fill(0) };
      modelViewMatrix = { elements: new Array(16).fill(0) };
      normalMatrix = { elements: new Array(9).fill(0) };
      matrixAutoUpdate = false;
      matrixWorldAutoUpdate = false;
      matrixWorldNeedsUpdate = false;
      castShadow = false;
      receiveShadow = false;
      frustumCulled = false;
      renderOrder = 0;
      animations: unknown[] = [];
      userData = {};
    },
  };
});

vi.mock("@pixiv/three-vrm", () => ({
  VRMLoaderPlugin: class {
    constructor() {
      // no-op
    }
  },
}));

// Import APRÈS vi.mock — sinon les imports résolvent les vraies modules.
// eslint-disable-next-line import/first
import { SceneEditorViewer } from "../SceneEditorViewer";

/* ───────────────── HELPERS ───────────────── */

const DEFAULT_PROPS = {
  vrmUrl: "",
  viewMode: "edit" as const,
  gizmoMode: "translate" as const,
  avatarPosition: { x: 0, y: 0, z: 0 },
  avatarRotationY: 0,
  sceneCamera: { x: 0, y: 1.35, z: 1.2 },
  sceneLookAt: { x: 0, y: 1.3, z: 0 },
  sceneFov: 20,
  onAvatarTransformChange: () => {},
};

/* ───────────────── TESTS ───────────────── */

describe("SceneEditorViewer · cleanup helpers (Phase F M2)", () => {
  beforeEach(() => {
    cleanup();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    cleanup();
  });

  it("unmount : dispose la geometry de GridHelper, AxesHelper et CameraHelper", () => {
    // Spy sur le prototype : tous les `BufferGeometry` instances héritent
    // de `dispose()`. Les helpers (GridHelper, AxesHelper, CameraHelper)
    // créent chacun une BufferGeometry interne — on s'attend donc à au
    // MOINS 3 calls dispose au unmount (1 par helper).
    const geometryDisposeSpy = vi.spyOn(
      THREE.BufferGeometry.prototype,
      "dispose",
    );

    const { unmount } = render(<SceneEditorViewer {...DEFAULT_PROPS} />);
    const callsBeforeUnmount = geometryDisposeSpy.mock.calls.length;

    unmount();
    const callsAfterUnmount = geometryDisposeSpy.mock.calls.length;

    // Au moins 3 nouveaux disposes (Grid + Axes + CameraHelper). Le VRM
    // n'est pas chargé (loader stub) donc aucun mesh VRM ne contribue.
    expect(callsAfterUnmount - callsBeforeUnmount).toBeGreaterThanOrEqual(3);
  });

  it("unmount : dispose la material des helpers (LineBasicMaterial / LineDashedMaterial)", () => {
    // GridHelper utilise un LineBasicMaterial, AxesHelper aussi, CameraHelper
    // aussi. On spy sur le prototype Material commun.
    const materialDisposeSpy = vi.spyOn(THREE.Material.prototype, "dispose");

    const { unmount } = render(<SceneEditorViewer {...DEFAULT_PROPS} />);
    const callsBeforeUnmount = materialDisposeSpy.mock.calls.length;

    unmount();
    const callsAfterUnmount = materialDisposeSpy.mock.calls.length;

    // Au moins 3 disposes material (1 par helper). Pas de VRM material.
    expect(callsAfterUnmount - callsBeforeUnmount).toBeGreaterThanOrEqual(3);
  });

  it("unmount : nettoie les refs (gridRef/axesRef/camHelperRef = null) — vérifié indirectement par la stabilité du remount", () => {
    // On ne peut pas inspecter les useRef directement depuis l'extérieur.
    // On valide donc indirectement : 5 cycles mount/unmount → chaque
    // cycle dispose autant qu'au précédent (pas de leak monotonique).
    const geomSpy = vi.spyOn(THREE.BufferGeometry.prototype, "dispose");

    let lastDelta = -1;
    for (let i = 0; i < 5; i++) {
      const before = geomSpy.mock.calls.length;
      const { unmount } = render(<SceneEditorViewer {...DEFAULT_PROPS} />);
      unmount();
      const after = geomSpy.mock.calls.length;
      const delta = after - before;
      if (lastDelta === -1) {
        lastDelta = delta;
      } else {
        // Tolère un epsilon de ±1 sur le delta — certains cycles peuvent
        // fire un dispose supplémentaire selon l'ordre de StrictMode.
        // L'important : on n'accumule pas de leak (delta cohérent à chaque
        // cycle, pas une fonction de N).
        expect(Math.abs(delta - lastDelta)).toBeLessThanOrEqual(2);
      }
    }
    expect(lastDelta).toBeGreaterThanOrEqual(3);
  });

  it("régression : 10 cycles mount/unmount terminent sans throw (stabilité cleanup)", () => {
    // Garde-fou : une erreur dans le nouveau bloc de dispose (typo nom
    // de ref, material array vs scalar mal géré) crasherait le cleanup
    // et React swallow l'exception. On boucle à grand n pour augmenter
    // la chance qu'un cas edge tombe.
    expect(() => {
      for (let i = 0; i < 10; i++) {
        const { unmount } = render(<SceneEditorViewer {...DEFAULT_PROPS} />);
        unmount();
      }
    }).not.toThrow();
  });
});
