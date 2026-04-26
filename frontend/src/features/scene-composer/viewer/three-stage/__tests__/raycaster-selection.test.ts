/**
 * Tests — `raycaster-selection.ts` (E5.3).
 *
 * Couverture :
 *   1. `setupRaycasterSelection` retourne un handle avec `dispose`.
 *   2. Clic sur un mesh non-ignoré → onSelect appelé avec l'objet.
 *   3. Clic dans le vide (aucun intersect) → onSelect appelé avec null.
 *   4. Clic sur un objet avec `userData.selectable === false` → onSelect(null).
 *   5. Clic sur un objet avec nom préfixé ignoré → onSelect(null).
 *   6. `dispose()` retire le listener pointerdown → plus de callback.
 *   7. Remonter aux parents : clic sur sous-mesh d'un groupe → sélection du groupe.
 *   8. Option `ignoreNames` : objet avec nom exact ignoré → onSelect(null).
 *
 * Stratégie : mock THREE.Raycaster pour contrôler les intersects retournés.
 * Simulation pointerdown via `dispatchEvent` sur un canvas DOM.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as THREE from "three";
import { setupRaycasterSelection } from "../raycaster-selection";

// ── Mock Raycaster ────────────────────────────────────────────────────────────

// On mocke la méthode `intersectObjects` de Raycaster pour contrôler les résultats.
let mockIntersects: Array<{ object: THREE.Object3D }> = [];

vi.spyOn(THREE.Raycaster.prototype, "intersectObjects").mockImplementation(
  () => mockIntersects as THREE.Intersection[],
);

// `setFromCamera` ne fait rien dans jsdom (pas de vrai WebGL).
vi.spyOn(THREE.Raycaster.prototype, "setFromCamera").mockImplementation(() => {});

// ── Helpers ───────────────────────────────────────────────────────────────────

function makePointerDownEvent(canvas: HTMLCanvasElement): Event {
  const rect = { left: 0, top: 0, width: 800, height: 600 } as DOMRect;
  vi.spyOn(canvas, "getBoundingClientRect").mockReturnValue(rect);

  // On utilise MouseEvent (mieux supporté dans jsdom) émis comme "pointerdown".
  return new MouseEvent("pointerdown", {
    clientX: 400,
    clientY: 300,
    bubbles: true,
  });
}

// ── Tests ─────────────────────────────────────────────────────────────────────

beforeEach(() => {
  mockIntersects = [];
  vi.clearAllMocks();
  vi.spyOn(THREE.Raycaster.prototype, "setFromCamera").mockImplementation(() => {});
  vi.spyOn(THREE.Raycaster.prototype, "intersectObjects").mockImplementation(
    () => mockIntersects as THREE.Intersection[],
  );
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("setupRaycasterSelection · handle", () => {
  it("retourne un handle avec dispose()", () => {
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera();
    const canvas = document.createElement("canvas");
    const onSelect = vi.fn();

    const handle = setupRaycasterSelection(scene, camera, canvas, onSelect);

    expect(handle).toBeDefined();
    expect(typeof handle.dispose).toBe("function");
  });
});

describe("setupRaycasterSelection · sélection mesh", () => {
  it("clic sur mesh sélectionnable → onSelect(mesh)", () => {
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera();
    const canvas = document.createElement("canvas");
    const onSelect = vi.fn();

    const mesh = new THREE.Mesh();
    mesh.name = "prop_abc";
    mesh.userData["selectable"] = true;
    scene.add(mesh);
    // Le parent direct du mesh est la scène → on retourne mesh lui-même.
    mockIntersects = [{ object: mesh }];

    setupRaycasterSelection(scene, camera, canvas, onSelect);
    canvas.dispatchEvent(makePointerDownEvent(canvas));

    expect(onSelect).toHaveBeenCalledWith(mesh);
  });

  it("clic dans le vide (aucun intersect) → onSelect(null)", () => {
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera();
    const canvas = document.createElement("canvas");
    const onSelect = vi.fn();

    mockIntersects = [];

    setupRaycasterSelection(scene, camera, canvas, onSelect);
    canvas.dispatchEvent(makePointerDownEvent(canvas));

    expect(onSelect).toHaveBeenCalledWith(null);
  });

  it("mesh avec userData.selectable=false → onSelect(null)", () => {
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera();
    const canvas = document.createElement("canvas");
    const onSelect = vi.fn();

    const mesh = new THREE.Mesh();
    mesh.userData["selectable"] = false;
    scene.add(mesh);
    mockIntersects = [{ object: mesh }];

    setupRaycasterSelection(scene, camera, canvas, onSelect);
    canvas.dispatchEvent(makePointerDownEvent(canvas));

    expect(onSelect).toHaveBeenCalledWith(null);
  });

  it("mesh avec nom préfixé ignoré → onSelect(null)", () => {
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera();
    const canvas = document.createElement("canvas");
    const onSelect = vi.fn();

    const mesh = new THREE.Mesh();
    mesh.name = "__helper_grid";
    scene.add(mesh);
    mockIntersects = [{ object: mesh }];

    setupRaycasterSelection(scene, camera, canvas, onSelect);
    canvas.dispatchEvent(makePointerDownEvent(canvas));

    expect(onSelect).toHaveBeenCalledWith(null);
  });

  it("mesh dans un groupe → remonte au groupe parent (racine scène)", () => {
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera();
    const canvas = document.createElement("canvas");
    const onSelect = vi.fn();

    // Groupe racine → enfant mesh.
    const group = new THREE.Group();
    group.name = "prop_group_xyz";
    group.userData["instanceId"] = "xyz";
    const childMesh = new THREE.Mesh();
    childMesh.name = "submesh";
    group.add(childMesh);
    scene.add(group);

    // Le raycaster intersecte le sous-mesh, pas le groupe.
    mockIntersects = [{ object: childMesh }];

    setupRaycasterSelection(scene, camera, canvas, onSelect);
    canvas.dispatchEvent(makePointerDownEvent(canvas));

    // onSelect doit recevoir le groupe (racine dans la scène), pas le sous-mesh.
    expect(onSelect).toHaveBeenCalledWith(group);
  });

  it("option ignoreNames : objet avec nom exact ignoré → onSelect(null)", () => {
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera();
    const canvas = document.createElement("canvas");
    const onSelect = vi.fn();

    const mesh = new THREE.Mesh();
    mesh.name = "floor_mesh";
    scene.add(mesh);
    mockIntersects = [{ object: mesh }];

    setupRaycasterSelection(scene, camera, canvas, onSelect, {
      ignoreNames: ["floor_mesh"],
    });
    canvas.dispatchEvent(makePointerDownEvent(canvas));

    expect(onSelect).toHaveBeenCalledWith(null);
  });
});

describe("setupRaycasterSelection · dispose", () => {
  it("dispose() retire le listener → pointerdown ne déclenche plus onSelect", () => {
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera();
    const canvas = document.createElement("canvas");
    const onSelect = vi.fn();

    const mesh = new THREE.Mesh();
    scene.add(mesh);
    mockIntersects = [{ object: mesh }];

    const handle = setupRaycasterSelection(scene, camera, canvas, onSelect);
    handle.dispose();

    canvas.dispatchEvent(makePointerDownEvent(canvas));

    // Pas d'appel après dispose.
    expect(onSelect).not.toHaveBeenCalled();
  });
});
