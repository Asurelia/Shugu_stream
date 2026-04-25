/**
 * Tests unit — `ViewerAdapter` (Phase F).
 *
 * Couverture :
 *   1. mount → le viewer legacy est bien monté avec les props dérivées du
 *      store (selectedId "shugu" seeded par MOCK_INSPECTOR).
 *   2. updateInspectorField côté store → props passées au viewer mises à
 *      jour au prochain render (feedback inverse slider → viewer).
 *   3. gizmo event simulé (simulate via le prop `onAvatarTransformChange`
 *      capturé du mock) → updateInspectorField appelé avec les bons args.
 *   4. debounce : 3 events gizmo synchrones en < 16 ms → UN seul call
 *      updateInspectorField au flush raf suivant.
 *   5. unmount → raf pending cancellé (pas de setState post-unmount) +
 *      cleanup sans throw.
 *
 * On mocke `SceneEditorViewer` du legacy pour ne pas toucher Three.js /
 * WebGL / le VRM loader — inutile pour tester l'adapter, et l'environment
 * jsdom ne ship pas WebGL. Le mock capture les props à chaque render dans
 * un ref exposé via un global window hack (tests only).
 */

import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render } from "@testing-library/react";
import { createRef } from "react";
import { useSceneEditorStore } from "@/stores/useSceneEditorStore";

/* ───────────────── MOCK DU VIEWER LEGACY ─────────────────
 * On remplace `SceneEditorViewer` par un stub React qui :
 *   - stocke les props reçues dans `lastViewerProps` (export nommé) pour
 *     que les tests puissent les inspecter ;
 *   - expose `onAvatarTransformChange` via un ref partagé pour que les
 *     tests simulent un event gizmo sans DOM Three.js.
 *
 * `vi.mock` est hoisté avant tout import → on utilise `vi.hoisted` pour
 * partager les refs entre mock et tests (un objet créé hors mock serait
 * `undefined` au moment où le mock factory execute).
 */
const mocks = vi.hoisted(() => ({
  lastViewerProps: null as unknown as Record<string, unknown> | null,
  mountCount: 0,
  unmountCount: 0,
}));

vi.mock("@/features/admin/scene-editor-legacy/SceneEditorViewer", () => {
  // Import React inside le factory : le module host ne peut pas être
  // capturé via closure externe (vi.mock tourne avant le import du test).
  const React = require("react") as typeof import("react");
  return {
    SceneEditorViewer: (props: Record<string, unknown>) => {
      // Snapshot des props à chaque render → le dernier call l'emporte.
      mocks.lastViewerProps = props;
      React.useEffect(() => {
        mocks.mountCount++;
        return () => {
          mocks.unmountCount++;
        };
      }, []);
      return React.createElement("canvas", {
        "data-testid": "viewer-legacy-stub",
        width: 16,
        height: 9,
      });
    },
  };
});

// `next/dynamic` en environnement Vitest : Phase F passe le viewer legacy
// par `dynamic(() => import(...).then(m => m.SceneEditorViewer))` pour
// alléger le bundle initial et débloquer les tests E2E (cf. doc en tête
// de viewer-adapter.tsx). En jsdom, le wrapper React.lazy de Next attend
// un microtask pour résoudre la promise — pas pratique en tests
// synchrones. On remplace donc `dynamic` par une factory qui invoque
// immédiatement le loader (toujours synchrone vu que le module ciblé est
// mocké ci-dessus, donc l'import résout à l'instant) et expose le composant
// au premier render.
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
          return () => {
            cancelled = true;
          };
        }, [tick]);
        if (!Resolved) return null;
        return React.createElement(Resolved, props);
      }
      DynamicProxy.displayName = "DynamicProxy";
      return DynamicProxy;
    },
  };
});

// Import APRÈS vi.mock pour que l'import résolu utilise le stub.
import { ViewerAdapter, type ViewerAdapterHandle } from "../viewer-adapter";

/* ───────────────── RAF HARNESS ─────────────────
 * jsdom ne polyfill pas `requestAnimationFrame`. On installe un fake
 * contrôlable : les tests poussent manuellement un tick via `flushRaf()`
 * pour observer le debounce.
 */
type RafQueue = Array<() => void>;
let rafQueue: RafQueue = [];
let rafId = 0;
let nextCbId = 1;

function installFakeRaf() {
  rafQueue = [];
  nextCbId = 1;
  // Le wrapper garde l'id de chaque cb pour que cancel puisse l'effacer
  // précisément — pas juste "clear tout" (le test d'unmount vérifie qu'on
  // n'avale pas un cb suivant).
  const pending: Array<{ id: number; cb: () => void }> = [];
  globalThis.requestAnimationFrame = ((cb: FrameRequestCallback) => {
    const id = nextCbId++;
    pending.push({ id, cb: () => cb(performance.now()) });
    return id as unknown as number;
  }) as typeof requestAnimationFrame;
  globalThis.cancelAnimationFrame = ((id: number) => {
    const idx = pending.findIndex((p) => p.id === id);
    if (idx >= 0) pending.splice(idx, 1);
  }) as typeof cancelAnimationFrame;
  rafQueue = pending.map((p) => p.cb);
  // On garde la ref vers le tableau pour que flushRaf puisse le drainer.
  // Ré-assigner rafQueue à `pending.map` casse le partage — on utilise le
  // tableau brut à la place.
  rafQueue = pending as unknown as RafQueue;
  rafId = 0;
}

function flushRaf() {
  // Drain : exécute TOUS les callbacks pending. Un cb peut re-schedule un
  // nouveau raf — on s'arrête quand plus aucun pending.
  let iterations = 0;
  while (rafQueue.length > 0 && iterations < 100) {
    const snapshot = (rafQueue as unknown as Array<{ id: number; cb: () => void }>)
      .splice(0, rafQueue.length);
    for (const { cb } of snapshot) {
      cb();
    }
    iterations++;
  }
  if (iterations >= 100) {
    throw new Error("flushRaf: infinite raf loop detected");
  }
}

function rafPendingCount(): number {
  return rafQueue.length;
}

/**
 * Flush les microtasks pour résoudre le `dynamic()` Promise + les setState
 * post-render. Couplé à `act()` pour que React commit les updates avant
 * que le test inspecte le DOM / les mocks.
 */
async function flushDynamicLoad() {
  await act(async () => {
    // Deux awaits = on laisse passer 2 microtasks (1 pour la promise
    // resolved par le loader, 1 pour le setState dans le useEffect du
    // DynamicProxy).
    await Promise.resolve();
    await Promise.resolve();
  });
}

/**
 * Wrapper render + flushDynamicLoad pour les tests. Évite la duplication
 * `await flushDynamicLoad()` à chaque test, et signe que tous nos tests
 * doivent attendre le résolveur dynamique.
 */
async function renderAdapter(
  ...args: Parameters<typeof render>
): Promise<ReturnType<typeof render>> {
  const result = render(...args);
  await flushDynamicLoad();
  return result;
}

/**
 * Wrapper rerender + flush. Couvre le cas où un test re-render après une
 * mutation du store.
 */
async function rerenderAdapter(
  rerender: ReturnType<typeof render>["rerender"],
  ui: Parameters<ReturnType<typeof render>["rerender"]>[0],
): Promise<void> {
  rerender(ui);
  await flushDynamicLoad();
}

/* ───────────────── SETUP ───────────────── */

beforeEach(() => {
  // Reset store état UI (mais PAS le data seed : on veut shugu sélectionné).
  useSceneEditorStore.getState().resetUI();
  useSceneEditorStore.temporal.getState().clear();
  mocks.lastViewerProps = null;
  mocks.mountCount = 0;
  mocks.unmountCount = 0;
  installFakeRaf();
  cleanup();
});

/* ───────────────── TESTS ───────────────── */

describe("ViewerAdapter · store wiring", () => {
  it("mount : le viewer legacy reçoit la transform du node sélectionné (shugu)", async () => {
    await renderAdapter(<ViewerAdapter viewMode="edit" />);

    expect(mocks.lastViewerProps).not.toBeNull();
    // shugu.transform.pos = [-0.6, 0, 0.2] dans MOCK_INSPECTOR.
    const pos = mocks.lastViewerProps!.avatarPosition as {
      x: number;
      y: number;
      z: number;
    };
    expect(pos.x).toBeCloseTo(-0.6);
    expect(pos.y).toBeCloseTo(0);
    expect(pos.z).toBeCloseTo(0.2);
    // rot[1] = 12° → 12 * π/180 rad
    const rotY = mocks.lastViewerProps!.avatarRotationY as number;
    expect(rotY).toBeCloseTo((12 * Math.PI) / 180, 4);
    // Mode edit par défaut + gizmoMode traduit depuis tool=move.
    expect(mocks.lastViewerProps!.viewMode).toBe("edit");
    expect(mocks.lastViewerProps!.gizmoMode).toBe("translate");
  });

  it("mount : mode preview transmis tel quel au viewer legacy", async () => {
    await renderAdapter(<ViewerAdapter viewMode="preview" />);
    expect(mocks.lastViewerProps!.viewMode).toBe("preview");
  });

  it("slider → viewer : updateInspectorField depuis le store re-propage les props", async () => {
    const { rerender } = await renderAdapter(<ViewerAdapter viewMode="edit" />);

    act(() => {
      useSceneEditorStore
        .getState()
        .updateInspectorField("shugu", "transform.pos", [1.5, 2.5, 3.5]);
    });
    await rerenderAdapter(rerender, <ViewerAdapter viewMode="edit" />);

    const pos = mocks.lastViewerProps!.avatarPosition as {
      x: number;
      y: number;
      z: number;
    };
    expect(pos.x).toBeCloseTo(1.5);
    expect(pos.y).toBeCloseTo(2.5);
    expect(pos.z).toBeCloseTo(3.5);
  });

  it("tool → gizmoMode : setTool(rotate) dans le store remonte au viewer", async () => {
    const { rerender } = await renderAdapter(<ViewerAdapter viewMode="edit" />);
    expect(mocks.lastViewerProps!.gizmoMode).toBe("translate");

    act(() => {
      useSceneEditorStore.getState().setTool("rotate");
    });
    await rerenderAdapter(rerender, <ViewerAdapter viewMode="edit" />);
    expect(mocks.lastViewerProps!.gizmoMode).toBe("rotate");

    act(() => {
      useSceneEditorStore.getState().setTool("scale");
    });
    await rerenderAdapter(rerender, <ViewerAdapter viewMode="edit" />);
    expect(mocks.lastViewerProps!.gizmoMode).toBe("scale");
  });
});

describe("ViewerAdapter · gizmo → store (forward)", () => {
  it("un gizmo change event appelle updateInspectorField après flush raf", async () => {
    const updateSpy = vi.spyOn(
      useSceneEditorStore.getState(),
      "updateInspectorField",
    );
    await renderAdapter(<ViewerAdapter viewMode="edit" />);

    // Le viewer legacy (mocké) expose onAvatarTransformChange en prop —
    // on le déclenche avec des valeurs custom.
    const onChange = mocks.lastViewerProps!.onAvatarTransformChange as (
      pos: { x: number; y: number; z: number },
      rotY: number,
    ) => void;

    act(() => {
      onChange({ x: 1, y: 2, z: 3 }, Math.PI / 2);
    });
    // Pas de call immédiat : on est dans le raf, pas encore flushé.
    expect(updateSpy).not.toHaveBeenCalled();

    act(() => {
      flushRaf();
    });

    // Deux calls : un pour pos, un pour rot.1.
    const posCall = updateSpy.mock.calls.find(
      (c) => c[1] === "transform.pos",
    );
    expect(posCall).toBeDefined();
    expect(posCall?.[0]).toBe("shugu");
    expect(posCall?.[2]).toEqual([1, 2, 3]);

    const rotCall = updateSpy.mock.calls.find(
      (c) => c[1] === "transform.rot.1",
    );
    expect(rotCall).toBeDefined();
    // rotY = PI/2 rad → 90 degrees
    expect(rotCall?.[2]).toBeCloseTo(90, 4);
  });

  it("debounce 16ms : 3 events synchrones → 1 seul flush raf (2 calls total : pos + rot)", async () => {
    const updateSpy = vi.spyOn(
      useSceneEditorStore.getState(),
      "updateInspectorField",
    );
    await renderAdapter(<ViewerAdapter viewMode="edit" />);

    const onChange = mocks.lastViewerProps!.onAvatarTransformChange as (
      pos: { x: number; y: number; z: number },
      rotY: number,
    ) => void;

    act(() => {
      onChange({ x: 1, y: 0, z: 0 }, 0);
      onChange({ x: 2, y: 0, z: 0 }, 0);
      onChange({ x: 3, y: 0, z: 0 }, 0);
    });
    // Un seul raf scheduled malgré 3 events.
    expect(rafPendingCount()).toBe(1);

    act(() => {
      flushRaf();
    });

    // Seul le DERNIER event est flushé (conflation) → 2 calls (pos + rot).
    expect(updateSpy).toHaveBeenCalledTimes(2);
    const posCall = updateSpy.mock.calls.find((c) => c[1] === "transform.pos");
    expect(posCall?.[2]).toEqual([3, 0, 0]);
  });

  it("un nouveau burst après flush re-schedule un nouveau raf", async () => {
    const updateSpy = vi.spyOn(
      useSceneEditorStore.getState(),
      "updateInspectorField",
    );
    await renderAdapter(<ViewerAdapter viewMode="edit" />);

    const onChange = mocks.lastViewerProps!.onAvatarTransformChange as (
      pos: { x: number; y: number; z: number },
      rotY: number,
    ) => void;

    act(() => {
      onChange({ x: 1, y: 0, z: 0 }, 0);
      flushRaf();
    });
    const firstCalls = updateSpy.mock.calls.length;
    expect(firstCalls).toBe(2);

    act(() => {
      onChange({ x: 5, y: 0, z: 0 }, 0);
      flushRaf();
    });
    expect(updateSpy.mock.calls.length).toBe(4); // +2 for the second burst
    const lastPosCall = [...updateSpy.mock.calls]
      .reverse()
      .find((c) => c[1] === "transform.pos");
    expect(lastPosCall?.[2]).toEqual([5, 0, 0]);
  });
});

describe("ViewerAdapter · cleanup", () => {
  it("unmount : cancel le raf pending + décrémente aucun handler post-unmount", async () => {
    const { unmount } = await renderAdapter(<ViewerAdapter viewMode="edit" />);
    expect(mocks.mountCount).toBe(1);

    const onChange = mocks.lastViewerProps!.onAvatarTransformChange as (
      pos: { x: number; y: number; z: number },
      rotY: number,
    ) => void;

    // Schedule un event pending mais PAS de flush.
    act(() => {
      onChange({ x: 9, y: 9, z: 9 }, 0);
    });
    expect(rafPendingCount()).toBe(1);

    unmount();
    // Après unmount : cancelAnimationFrame doit avoir retiré le cb pending.
    expect(rafPendingCount()).toBe(0);
    expect(mocks.unmountCount).toBe(1);
  });

  it("unmount : un flushRaf post-unmount est sans effet (pas de setState after unmount)", async () => {
    const updateSpy = vi.spyOn(
      useSceneEditorStore.getState(),
      "updateInspectorField",
    );
    const { unmount } = await renderAdapter(<ViewerAdapter viewMode="edit" />);
    const onChange = mocks.lastViewerProps!.onAvatarTransformChange as (
      pos: { x: number; y: number; z: number },
      rotY: number,
    ) => void;
    act(() => {
      onChange({ x: 1, y: 1, z: 1 }, 0);
    });
    unmount();

    // Le cb aurait pu rester dans rafQueue sans cancel — ici on a cancel,
    // donc aucun call du store.
    act(() => {
      flushRaf();
    });
    expect(updateSpy).not.toHaveBeenCalled();
  });

  it("remount stable : 10 cycles mount/unmount → N mounts == N unmounts (pas de fuite handler)", async () => {
    for (let i = 0; i < 10; i++) {
      const { unmount } = await renderAdapter(<ViewerAdapter viewMode="edit" />);
      unmount();
    }
    expect(mocks.mountCount).toBe(10);
    expect(mocks.unmountCount).toBe(10);
  });
});

describe("ViewerAdapter · imperative handle", () => {
  it("ref expose swapTexture/playAnimation/setBlendshape/showVfxOverlay (no-ops)", async () => {
    const ref = createRef<ViewerAdapterHandle>();
    await renderAdapter(<ViewerAdapter viewMode="edit" ref={ref} />);
    expect(ref.current).not.toBeNull();
    expect(typeof ref.current!.swapTexture).toBe("function");
    expect(typeof ref.current!.playAnimation).toBe("function");
    expect(typeof ref.current!.setBlendshape).toBe("function");
    expect(typeof ref.current!.showVfxOverlay).toBe("function");
    // Un appel ne doit jamais throw (stub documenté).
    expect(() => {
      ref.current!.swapTexture("/tex.png");
      ref.current!.playAnimation("/anim.vrma");
      ref.current!.setBlendshape("Happy", 0.5);
      ref.current!.showVfxOverlay("bloom");
    }).not.toThrow();
  });
});

describe("ViewerAdapter · safety", () => {
  it("selectedId null : l'adapter passe une pos/rot 0 au viewer sans crash", async () => {
    act(() => {
      useSceneEditorStore.getState().setSelectedId(null);
    });
    await renderAdapter(<ViewerAdapter viewMode="edit" />);

    const pos = mocks.lastViewerProps!.avatarPosition as {
      x: number;
      y: number;
      z: number;
    };
    expect(pos).toEqual({ x: 0, y: 0, z: 0 });
    expect(mocks.lastViewerProps!.avatarRotationY).toBe(0);
  });

  it("selectedId pointant sur un node sans entry inspector : fallback défaut", async () => {
    act(() => {
      // "group-audio" existe dans hierarchy mais pas dans inspectorById.
      useSceneEditorStore.getState().setSelectedId("group-audio");
    });
    await renderAdapter(<ViewerAdapter viewMode="edit" />);

    const pos = mocks.lastViewerProps!.avatarPosition as {
      x: number;
      y: number;
      z: number;
    };
    expect(pos).toEqual({ x: 0, y: 0, z: 0 });
  });

  it("gizmo event avec selectedId=null : updateInspectorField ignoré", async () => {
    act(() => {
      useSceneEditorStore.getState().setSelectedId(null);
    });
    const updateSpy = vi.spyOn(
      useSceneEditorStore.getState(),
      "updateInspectorField",
    );
    await renderAdapter(<ViewerAdapter viewMode="edit" />);

    const onChange = mocks.lastViewerProps!.onAvatarTransformChange as (
      pos: { x: number; y: number; z: number },
      rotY: number,
    ) => void;
    act(() => {
      onChange({ x: 1, y: 0, z: 0 }, 0);
      flushRaf();
    });
    expect(updateSpy).not.toHaveBeenCalled();
  });
});
