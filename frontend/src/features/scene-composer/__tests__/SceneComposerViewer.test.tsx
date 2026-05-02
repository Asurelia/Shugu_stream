/**
 * Tests — `SceneComposerViewer` (Phase E5.2).
 *
 * Couverture :
 *   1. mount/unmount : dispose géometry + material de GridHelper et AxesHelper.
 *   2. Stabilité remount : N cycles → N disposes (pas de fuite monotonique).
 *   3. Régression : 10 cycles mount/unmount sans throw.
 *
 * Stratégie de mock :
 *   - `WebGLRenderer` → stub minimal (jsdom n'a pas WebGL).
 *   - `GLTFLoader` → stub no-op (évite le download 28 MB VRM en test).
 *   - `OrbitControls` → stub minimal (pointer events non supportés en jsdom).
 *   - `@pixiv/three-vrm` → stub minimal.
 *   - `next/dynamic` → résolveur synchrone (identique à viewer-adapter.test.tsx).
 *   - `@/lib/VRMAnimation/loadVRMAnimation` → stub no-op.
 *
 * Les helpers (GridHelper, AxesHelper) restent **réels** pour que les spies
 * `BufferGeometry.prototype.dispose` et `Material.prototype.dispose` captent
 * les vrais appels du module `helpers.ts`.
 *
 * Ref : `SceneEditorViewer.test.tsx` (legacy Phase F M2) pour le pattern.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, act } from "@testing-library/react";
import * as THREE from "three";

// ─── MOCK WebGLRenderer ───────────────────────────────────────────────────────

vi.mock("three", async () => {
  const actual = await vi.importActual<typeof THREE>("three");

  class WebGLRendererStub {
    domElement: HTMLCanvasElement;
    // Three.js r152+ renamed `outputEncoding` → `outputColorSpace`. Stub keeps
    // the field assignable without enforcing a specific colorspace value.
    outputColorSpace = "srgb";
    constructor(opts: { canvas?: HTMLCanvasElement } = {}) {
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

// ─── MOCK GLTFLoader ──────────────────────────────────────────────────────────

vi.mock("three/examples/jsm/loaders/GLTFLoader.js", () => ({
  GLTFLoader: class {
    register(): void {}
    load(): void {}
    loadAsync(): Promise<never> {
      // Ne résout jamais → le VRM n'est jamais monté, le test unmount avant.
      return new Promise(() => {});
    }
  },
}));

// ─── MOCK OrbitControls ───────────────────────────────────────────────────────

vi.mock("three/examples/jsm/controls/OrbitControls.js", () => ({
  OrbitControls: class {
    target = { copy: () => {}, set: () => {} };
    enableDamping = false;
    dampingFactor = 0;
    minDistance = 0;
    maxDistance = Infinity;
    maxPolarAngle = Math.PI;
    enabled = false;
    update(): void {}
    dispose(): void {}
  },
}));

// ─── MOCK VRMLoaderPlugin ─────────────────────────────────────────────────────

vi.mock("@pixiv/three-vrm", () => ({
  VRMLoaderPlugin: class {
    constructor() {}
  },
}));

// ─── MOCK loadVRMAnimation ────────────────────────────────────────────────────

vi.mock("@/lib/VRMAnimation/loadVRMAnimation", () => ({
  loadVRMAnimation: (): Promise<null> => Promise.resolve(null),
}));

// ─── MOCK next/dynamic ────────────────────────────────────────────────────────
// Résolveur synchrone : contourne le lazy-loading de Next pour que le viewer
// soit disponible dès le premier render en jsdom.

vi.mock("next/dynamic", () => {
  const React = require("react") as typeof import("react");
  return {
    default: (loader: () => Promise<unknown>) => {
      let Resolved: React.ComponentType<Record<string, unknown>> | null = null;
      let pending: Promise<void> | null = null;
      function ensureLoaded() {
        if (Resolved || pending) return;
        pending = Promise.resolve(loader()).then((mod) => {
          Resolved = mod as React.ComponentType<Record<string, unknown>>;
        });
      }
      function DynamicProxy(props: Record<string, unknown>) {
        ensureLoaded();
        const [tick, setTick] = React.useState(0);
        React.useEffect(() => {
          if (Resolved) return;
          let cancelled = false;
          pending!.then(() => {
            if (!cancelled) setTick((n) => n + 1);
          });
          return () => { cancelled = true; };
        }, [tick]);
        if (!Resolved) return null;
        return React.createElement(Resolved, props);
      }
      DynamicProxy.displayName = "DynamicProxy";
      return DynamicProxy;
    },
  };
});

// ─── Import après les mocks ───────────────────────────────────────────────────

import { SceneComposerViewer } from "../viewer/SceneComposerViewer";

// ─── Helpers ─────────────────────────────────────────────────────────────────

const DEFAULT_PROPS = {
  vrmUrl: "",
  cameraPreset: "free" as const,
  viewMode: "edit" as const,
};

/** Flush microtasks pour que les useEffects React s'exécutent. */
async function flush(): Promise<void> {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

// ─── TESTS ───────────────────────────────────────────────────────────────────

describe("SceneComposerViewer · dispose helpers (Phase E5.2)", () => {
  beforeEach(() => {
    cleanup();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    cleanup();
  });

  it("unmount : dispose la geometry de GridHelper et AxesHelper (≥2 calls)", async () => {
    const geometryDisposeSpy = vi.spyOn(
      THREE.BufferGeometry.prototype,
      "dispose",
    );

    const { unmount } = render(<SceneComposerViewer {...DEFAULT_PROPS} />);
    await flush();
    const callsBefore = geometryDisposeSpy.mock.calls.length;

    unmount();
    const callsAfter = geometryDisposeSpy.mock.calls.length;

    // Au moins 2 : Grid + Axes (pas de CameraHelper en E5.2 — ajouté E5.3).
    expect(callsAfter - callsBefore).toBeGreaterThanOrEqual(2);
  });

  it("unmount : dispose la material de GridHelper et AxesHelper (≥2 calls)", async () => {
    const materialDisposeSpy = vi.spyOn(THREE.Material.prototype, "dispose");

    const { unmount } = render(<SceneComposerViewer {...DEFAULT_PROPS} />);
    await flush();
    const callsBefore = materialDisposeSpy.mock.calls.length;

    unmount();
    const callsAfter = materialDisposeSpy.mock.calls.length;

    expect(callsAfter - callsBefore).toBeGreaterThanOrEqual(2);
  });

  it("unmount : le RAF est cancelé (pas de requestAnimationFrame orphan)", async () => {
    const cancelSpy = vi.spyOn(globalThis, "cancelAnimationFrame");

    const { unmount } = render(<SceneComposerViewer {...DEFAULT_PROPS} />);
    await flush();

    unmount();

    // cancelAnimationFrame doit avoir été appelé au moins une fois.
    expect(cancelSpy).toHaveBeenCalled();
  });

  it("stabilité : 5 cycles mount/unmount → delta dispose constant (pas de leak)", async () => {
    const geomSpy = vi.spyOn(THREE.BufferGeometry.prototype, "dispose");

    let lastDelta = -1;
    for (let i = 0; i < 5; i++) {
      const before = geomSpy.mock.calls.length;
      const { unmount } = render(<SceneComposerViewer {...DEFAULT_PROPS} />);
      await flush();
      unmount();
      const after = geomSpy.mock.calls.length;
      const delta = after - before;

      if (lastDelta === -1) {
        lastDelta = delta;
      } else {
        // Tolérance ±2 selon l'ordre StrictMode — l'important est que le
        // delta ne croît pas de façon monotone (pas de fuite mémoire).
        expect(Math.abs(delta - lastDelta)).toBeLessThanOrEqual(2);
      }
    }
    expect(lastDelta).toBeGreaterThanOrEqual(2);
  });

  it("régression : 10 cycles mount/unmount sans throw", async () => {
    for (let i = 0; i < 10; i++) {
      const { unmount } = render(<SceneComposerViewer {...DEFAULT_PROPS} />);
      await flush();
      unmount();
    }
  });
});

describe("SceneComposerViewer · preset caméra", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    cleanup();
  });

  it("mount avec preset 'front' ne throw pas", async () => {
    expect(() => {
      const { unmount } = render(
        <SceneComposerViewer {...DEFAULT_PROPS} cameraPreset="front" />,
      );
      unmount();
    }).not.toThrow();
  });

  it("changement de preset (free→side) ne throw pas", async () => {
    const { rerender, unmount } = render(
      <SceneComposerViewer {...DEFAULT_PROPS} />,
    );
    await flush();

    expect(() => {
      rerender(<SceneComposerViewer {...DEFAULT_PROPS} cameraPreset="side" />);
    }).not.toThrow();

    unmount();
  });

  it("changement de viewMode (edit→preview) modifie la visibilité des helpers sans throw", async () => {
    const { rerender, unmount } = render(
      <SceneComposerViewer {...DEFAULT_PROPS} viewMode="edit" />,
    );
    await flush();

    expect(() => {
      rerender(
        <SceneComposerViewer {...DEFAULT_PROPS} viewMode="preview" />,
      );
    }).not.toThrow();

    unmount();
  });
});
