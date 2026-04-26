/**
 * Tests — `transform-controls.ts` (E5.3).
 *
 * Couverture :
 *   1. `attachTransformControls` crée un handle avec `controls`, `setMode`,
 *      `attach`, `dispose`.
 *   2. Le gizmo est masqué et désactivé par défaut.
 *   3. `setMode` appelle `controls.setMode` avec le bon mode.
 *   4. `attach(obj)` appelle `controls.attach(obj)`.
 *   5. `attach(null)` appelle `controls.detach()`.
 *   6. `dispose` : detach + dispose appelés sans crash.
 *   7. `dragging-changed` event désactive l'orbit quand dragging=true.
 *   8. `dragging-changed` event réactive l'orbit quand dragging=false.
 *   9. `onChange` callback est appelé avec l'objet attaché lors d'un change event.
 *  10. Appel `dispose` sans crash même si controls n'a pas d'objet attaché.
 *
 * Stratégie : on intercepte le TransformControls réel en mockant son comportement
 * via vi.spyOn sur les instances, sans vi.mock de module (évite les hoisting issues).
 *
 * Alternative : on teste le comportement observable (handle interface) plutôt
 * que les détails d'implémentation Three.js, ce qui est plus robuste.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as THREE from "three";

// ── Mocks Three.js TransformControls ─────────────────────────────────────────
// On utilise __mocks__ via vi.mock avec une factory inline (pas de référence
// à des variables top-level pour éviter le hoisting issue).

vi.mock("three/examples/jsm/controls/TransformControls", () => {
  // La factory doit être self-contained — on ne peut pas référencer des
  // variables extérieures déclarées après le hoist.
  type ThreeListener = (e: unknown) => void;

  class TransformControls {
    object: object | null = null;
    visible = true;
    enabled = true;
    private _ls: Map<string, ThreeListener[]> = new Map();

    addEventListener(type: string, fn: ThreeListener) {
      if (!this._ls.has(type)) this._ls.set(type, []);
      this._ls.get(type)!.push(fn);
    }

    removeEventListener(type: string, fn: ThreeListener) {
      this._ls.set(type, (this._ls.get(type) ?? []).filter((l) => l !== fn));
    }

    _emit(type: string, event = {}) {
      (this._ls.get(type) ?? []).forEach((fn) => fn(event));
    }

    setMode = vi.fn();
    attach = vi.fn(function(this: TransformControls, obj: object) { this.object = obj; });
    detach = vi.fn(function(this: TransformControls) { this.object = null; });
    dispose = vi.fn();
  }

  return { TransformControls };
});

vi.mock("three/examples/jsm/controls/OrbitControls", () => {
  class OrbitControls {
    enabled = true;
    dispose = vi.fn();
  }
  return { OrbitControls };
});

// Import après mock.
import { attachTransformControls } from "../transform-controls";
import { TransformControls } from "three/examples/jsm/controls/TransformControls";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls";

// ── Helpers ───────────────────────────────────────────────────────────────────

function makeSetup() {
  const camera = new THREE.PerspectiveCamera();
  const domElement = document.createElement("canvas");
  const scene = new THREE.Scene();
  const orbit = new OrbitControls() as unknown as import("three/examples/jsm/controls/OrbitControls").OrbitControls;

  const onChange = vi.fn();
  const onDraggingChanged = vi.fn();

  const handle = attachTransformControls(camera, domElement, scene, orbit, {
    mode: "translate",
    onChange,
    onDraggingChanged,
  });

  // Accès à l'instance mock via cast.
  const mockCtrl = handle.controls as unknown as {
    _emit: (type: string, event?: Record<string, unknown>) => void;
    object: THREE.Object3D | null;
    setMode: ReturnType<typeof vi.fn>;
    attach: ReturnType<typeof vi.fn>;
    detach: ReturnType<typeof vi.fn>;
    dispose: ReturnType<typeof vi.fn>;
    visible: boolean;
    enabled: boolean;
  };

  return { camera, domElement, scene, orbit, onChange, onDraggingChanged, handle, mockCtrl };
}

// ── Tests ─────────────────────────────────────────────────────────────────────

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("attachTransformControls · création handle", () => {
  it("retourne un handle avec controls, setMode, attach, dispose", () => {
    const { handle } = makeSetup();
    expect(handle.controls).toBeInstanceOf(TransformControls);
    expect(typeof handle.setMode).toBe("function");
    expect(typeof handle.attach).toBe("function");
    expect(typeof handle.dispose).toBe("function");
  });

  it("le gizmo est initialement masqué et désactivé", () => {
    const { mockCtrl } = makeSetup();
    expect(mockCtrl.visible).toBe(false);
    expect(mockCtrl.enabled).toBe(false);
  });
});

describe("attachTransformControls · setMode", () => {
  it("setMode 'rotate' appelle controls.setMode('rotate')", () => {
    const { handle, mockCtrl } = makeSetup();
    handle.setMode("rotate");
    expect(mockCtrl.setMode).toHaveBeenCalledWith("rotate");
  });

  it("setMode 'scale' appelle controls.setMode('scale')", () => {
    const { handle, mockCtrl } = makeSetup();
    handle.setMode("scale");
    expect(mockCtrl.setMode).toHaveBeenCalledWith("scale");
  });
});

describe("attachTransformControls · attach", () => {
  it("attach(obj) appelle controls.attach(obj)", () => {
    const { handle, mockCtrl } = makeSetup();
    const obj = new THREE.Object3D();
    handle.attach(obj);
    expect(mockCtrl.attach).toHaveBeenCalledWith(obj);
  });

  it("attach(null) appelle controls.detach()", () => {
    const { handle, mockCtrl } = makeSetup();
    handle.attach(null);
    expect(mockCtrl.detach).toHaveBeenCalled();
  });
});

describe("attachTransformControls · dragging-changed event", () => {
  it("dragging=true → orbit.enabled = false + onDraggingChanged(true)", () => {
    const { mockCtrl, orbit, onDraggingChanged } = makeSetup();
    mockCtrl._emit("dragging-changed", { value: true });
    expect((orbit as unknown as { enabled: boolean }).enabled).toBe(false);
    expect(onDraggingChanged).toHaveBeenCalledWith(true);
  });

  it("dragging=false → orbit.enabled = true + onDraggingChanged(false)", () => {
    const { mockCtrl, orbit, onDraggingChanged } = makeSetup();
    mockCtrl._emit("dragging-changed", { value: true });
    mockCtrl._emit("dragging-changed", { value: false });
    expect((orbit as unknown as { enabled: boolean }).enabled).toBe(true);
    expect(onDraggingChanged).toHaveBeenLastCalledWith(false);
  });
});

describe("attachTransformControls · onChange event", () => {
  it("change event avec objet attaché appelle onChange(obj)", () => {
    const { handle, mockCtrl, onChange } = makeSetup();
    const obj = new THREE.Object3D();
    handle.attach(obj);
    // Simuler manuellement l'objet attaché (le mock ne fait pas le set réel).
    mockCtrl.object = obj;
    mockCtrl._emit("change", {});
    expect(onChange).toHaveBeenCalledWith(obj);
  });

  it("change event sans objet attaché → onChange pas appelé", () => {
    const { mockCtrl, onChange } = makeSetup();
    mockCtrl.object = null;
    mockCtrl._emit("change", {});
    expect(onChange).not.toHaveBeenCalled();
  });
});

describe("attachTransformControls · dispose", () => {
  it("dispose : detach + dispose appelés sans crash", () => {
    const { handle, mockCtrl } = makeSetup();
    expect(() => handle.dispose()).not.toThrow();
    expect(mockCtrl.detach).toHaveBeenCalled();
    expect(mockCtrl.dispose).toHaveBeenCalled();
  });

  it("dispose sans objet attaché : pas de crash", () => {
    const { handle } = makeSetup();
    expect(() => handle.dispose()).not.toThrow();
  });
});
