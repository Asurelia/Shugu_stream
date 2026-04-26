/**
 * Tests — `prop-instances.ts` (E5.3).
 *
 * Couverture :
 *   1. `createPropInstance` retourne un Object3D (Mesh).
 *   2. L'objet a le bon `name` (`__prop_${instanceId}`).
 *   3. L'objet a les bons `userData` (instanceId, assetSlug, selectable).
 *   4. La position initiale est correctement appliquée.
 *   5. La rotation initiale (option) est correctement appliquée.
 *   6. Le scale initial (option) est correctement appliqué.
 *   7. Sans options de rotation/scale → valeurs par défaut.
 *   8. Couleur déterministe par slug (même slug → même couleur).
 *   9. `disposePropInstance` : appelle geometry.dispose() sans crash.
 *  10. `disposePropInstance` : round-trip create → dispose sans fuite.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as THREE from "three";
import { createPropInstance, disposePropInstance } from "../prop-instances";
import type { PropAsset } from "../prop-instances";

// ── Helpers ───────────────────────────────────────────────────────────────────

function makeAsset(slug = "test_prop"): PropAsset {
  return { slug, file: `/assets/props/${slug}.glb` };
}

// ── Tests ─────────────────────────────────────────────────────────────────────

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("createPropInstance · création", () => {
  it("retourne un Object3D (isMesh = true)", () => {
    const asset = makeAsset();
    const position = new THREE.Vector3(1, 0, 2);
    const obj = createPropInstance(asset, position, "inst_001");

    expect(obj).toBeInstanceOf(THREE.Mesh);
  });

  it("name = '__prop_${instanceId}'", () => {
    const asset = makeAsset("prop_box");
    const obj = createPropInstance(asset, new THREE.Vector3(), "abc123");

    expect(obj.name).toBe("__prop_abc123");
  });

  it("userData.instanceId = instanceId", () => {
    const obj = createPropInstance(makeAsset(), new THREE.Vector3(), "xyz789");
    expect(obj.userData["instanceId"]).toBe("xyz789");
  });

  it("userData.assetSlug = asset.slug", () => {
    const asset = makeAsset("cool_prop");
    const obj = createPropInstance(asset, new THREE.Vector3(), "inst");
    expect(obj.userData["assetSlug"]).toBe("cool_prop");
  });

  it("userData.selectable = true", () => {
    const obj = createPropInstance(makeAsset(), new THREE.Vector3(), "inst");
    expect(obj.userData["selectable"]).toBe(true);
  });

  it("position initiale appliquée correctement", () => {
    const position = new THREE.Vector3(3.5, 0, -2.1);
    const obj = createPropInstance(makeAsset(), position, "pos_test");

    expect(obj.position.x).toBeCloseTo(3.5);
    expect(obj.position.y).toBeCloseTo(0);
    expect(obj.position.z).toBeCloseTo(-2.1);
  });
});

describe("createPropInstance · options", () => {
  it("sans options : rotation = (0,0,0), scale = (1,1,1)", () => {
    const obj = createPropInstance(makeAsset(), new THREE.Vector3(), "defaults");

    expect(obj.rotation.x).toBeCloseTo(0);
    expect(obj.rotation.y).toBeCloseTo(0);
    expect(obj.rotation.z).toBeCloseTo(0);
    expect(obj.scale.x).toBeCloseTo(1);
    expect(obj.scale.y).toBeCloseTo(1);
    expect(obj.scale.z).toBeCloseTo(1);
  });

  it("initialRotation appliquée si fournie", () => {
    const rotation = new THREE.Euler(0.5, 1.0, 0.3);
    const obj = createPropInstance(makeAsset(), new THREE.Vector3(), "rot_test", {
      initialRotation: rotation,
    });

    expect(obj.rotation.x).toBeCloseTo(0.5);
    expect(obj.rotation.y).toBeCloseTo(1.0);
    expect(obj.rotation.z).toBeCloseTo(0.3);
  });

  it("initialScale appliqué si fourni", () => {
    const scale = new THREE.Vector3(2, 3, 0.5);
    const obj = createPropInstance(makeAsset(), new THREE.Vector3(), "scale_test", {
      initialScale: scale,
    });

    expect(obj.scale.x).toBeCloseTo(2);
    expect(obj.scale.y).toBeCloseTo(3);
    expect(obj.scale.z).toBeCloseTo(0.5);
  });

  it("couleur déterministe : même slug → même couleur (matériau identique)", () => {
    const asset = makeAsset("deterministic_prop");
    const obj1 = createPropInstance(asset, new THREE.Vector3(), "id1");
    const obj2 = createPropInstance(asset, new THREE.Vector3(), "id2");

    const mat1 = (obj1 as THREE.Mesh).material as THREE.MeshStandardMaterial;
    const mat2 = (obj2 as THREE.Mesh).material as THREE.MeshStandardMaterial;

    expect(mat1.color.getHex()).toBe(mat2.color.getHex());
  });
});

describe("disposePropInstance · cleanup", () => {
  it("dispose sans crash sur un Mesh simple", () => {
    const obj = createPropInstance(makeAsset(), new THREE.Vector3(), "dispose_test");
    expect(() => disposePropInstance(obj)).not.toThrow();
  });

  it("geometry.dispose() est appelé", () => {
    const obj = createPropInstance(makeAsset(), new THREE.Vector3(), "geo_dispose");
    const mesh = obj as THREE.Mesh;
    const geoDisposeSpy = vi.spyOn(mesh.geometry, "dispose");

    disposePropInstance(obj);

    expect(geoDisposeSpy).toHaveBeenCalled();
  });

  it("material.dispose() est appelé", () => {
    const obj = createPropInstance(makeAsset(), new THREE.Vector3(), "mat_dispose");
    const mesh = obj as THREE.Mesh;
    const mat = mesh.material as THREE.MeshStandardMaterial;
    const matDisposeSpy = vi.spyOn(mat, "dispose");

    disposePropInstance(obj);

    expect(matDisposeSpy).toHaveBeenCalled();
  });

  it("round-trip create → dispose → pas de double-dispose crash", () => {
    const obj = createPropInstance(makeAsset(), new THREE.Vector3(), "roundtrip");
    disposePropInstance(obj);
    // Un deuxième dispose ne doit pas crasher (guard géré par Three.js).
    expect(() => disposePropInstance(obj)).not.toThrow();
  });
});
