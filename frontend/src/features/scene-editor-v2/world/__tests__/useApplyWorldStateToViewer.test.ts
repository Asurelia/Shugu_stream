/**
 * Tests for useApplyWorldStateToViewer hook.
 *
 * L4-viewer.1: scene_id → setSelectedSceneId (direct match).
 * L4-viewer.2:
 *   - avatar_pose → setCurrentVrmaUrl (via pose-registry; warn on unknown)
 *   - mood → setCurrentMood
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useApplyWorldStateToViewer } from "../useApplyWorldStateToViewer";
import {
  useWorldStateStore,
  __resetWorldStateStoreForTest,
} from "../useWorldStateStore";
import { useSceneComposerStore } from "../../../scene-composer/store/useSceneComposerStore";

// ─── Setup / teardown ─────────────────────────────────────────────────────────

beforeEach(() => {
  __resetWorldStateStoreForTest();
  // Reset SceneComposerStore to initial state
  useSceneComposerStore.getState().resetUI();
});

afterEach(() => {
  vi.restoreAllMocks();
});

// ─── T1: mounts without error ─────────────────────────────────────────────────

describe("useApplyWorldStateToViewer — T1: mounts without error", () => {
  it("renders the hook without throwing", () => {
    expect(() => renderHook(() => useApplyWorldStateToViewer())).not.toThrow();
  });
});

// ─── T2: scene_id change calls setSelectedSceneId ────────────────────────────

describe("useApplyWorldStateToViewer — T2: scene_id → setSelectedSceneId", () => {
  it("calls setSelectedSceneId when scene_id changes in the world store", () => {
    const setSelectedSceneId = vi.spyOn(
      useSceneComposerStore.getState(),
      "setSelectedSceneId",
    );

    renderHook(() => useApplyWorldStateToViewer());

    act(() => {
      useWorldStateStore.getState().applyDelta({ scene_id: "forest" });
    });

    expect(setSelectedSceneId).toHaveBeenCalledWith("forest");
  });
});

// ─── T3: mood change does not call setSelectedSceneId ────────────────────────

describe("useApplyWorldStateToViewer — T3: unrelated field does not trigger scene_id sync", () => {
  it("does not RE-call setSelectedSceneId when only mood changes after first snapshot", () => {
    renderHook(() => useApplyWorldStateToViewer());

    // 1er delta — ouvre le gate (hasReceivedSnapshot=true) et propage le
    // scene_id courant. C'est le comportement attendu post-fix P2 #58.
    act(() => {
      useWorldStateStore.getState().applyDelta({ scene_id: "kitchen" });
    });

    // À partir d'ici, on spy + on émet un delta SANS scene_id : pas de re-call.
    const setSelectedSceneId = vi.spyOn(
      useSceneComposerStore.getState(),
      "setSelectedSceneId",
    );

    act(() => {
      useWorldStateStore.getState().applyDelta({ mood: "happy" });
    });

    expect(setSelectedSceneId).not.toHaveBeenCalled();
  });
});

// ─── T4 (L4-viewer.2): avatar_pose known → setCurrentVrmaUrl called ──────────

describe("useApplyWorldStateToViewer — T4: avatar_pose known → calls setCurrentVrmaUrl", () => {
  it("calls setCurrentVrmaUrl with the VRMA URL when a known pose arrives", () => {
    const setCurrentVrmaUrl = vi.spyOn(
      useSceneComposerStore.getState(),
      "setCurrentVrmaUrl",
    );

    renderHook(() => useApplyWorldStateToViewer());

    act(() => {
      // "wave" is in the registry → /assets/vrma/wave.vrma
      useWorldStateStore.getState().applyDelta({ avatar_pose: "wave" });
    });

    expect(setCurrentVrmaUrl).toHaveBeenCalledWith("/assets/vrma/wave.vrma");
  });

  it("calls setCurrentVrmaUrl with idle_loop URL for the default 'idle' pose", () => {
    const setCurrentVrmaUrl = vi.spyOn(
      useSceneComposerStore.getState(),
      "setCurrentVrmaUrl",
    );

    renderHook(() => useApplyWorldStateToViewer());

    // First snapshot sets hasReceivedSnapshot=true AND triggers the avatarPose effect
    // (INITIAL_STATE.avatar_pose = "idle"). Expect idle → idle_loop.vrma.
    act(() => {
      useWorldStateStore.getState().applyDelta({ avatar_pose: "idle" });
    });

    expect(setCurrentVrmaUrl).toHaveBeenCalledWith("/assets/vrma/idle_loop.vrma");
  });
});

// ─── T5 (L4-viewer.2): avatar_pose unknown → warn, no setCurrentVrmaUrl ──────

describe("useApplyWorldStateToViewer — T5: avatar_pose unknown → warn, no setter call", () => {
  it("emits [L4] console.warn and does NOT call setCurrentVrmaUrl for unknown pose", () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const setCurrentVrmaUrl = vi.spyOn(
      useSceneComposerStore.getState(),
      "setCurrentVrmaUrl",
    );

    renderHook(() => useApplyWorldStateToViewer());

    act(() => {
      useWorldStateStore.getState().applyDelta({ avatar_pose: "unknown_pose_xyz" });
    });

    const l4Warns = warnSpy.mock.calls
      .map((c) => String(c[0]))
      .filter((msg) => msg.includes("[L4]"));
    expect(l4Warns.length).toBeGreaterThan(0);
    expect(l4Warns[0]).toContain("unknown_pose_xyz");
    expect(setCurrentVrmaUrl).not.toHaveBeenCalled();
  });
});

// ─── T6 (L4-viewer.2): mood change → setCurrentMood ─────────────────────────

describe("useApplyWorldStateToViewer — T6: mood change → calls setCurrentMood", () => {
  it("calls setCurrentMood when mood changes in the world store", () => {
    const setCurrentMood = vi.spyOn(
      useSceneComposerStore.getState(),
      "setCurrentMood",
    );

    renderHook(() => useApplyWorldStateToViewer());

    act(() => {
      useWorldStateStore.getState().applyDelta({ mood: "happy" });
    });

    expect(setCurrentMood).toHaveBeenCalledWith("happy");
  });

  it("calls setCurrentMood for each distinct mood value", () => {
    const setCurrentMood = vi.spyOn(
      useSceneComposerStore.getState(),
      "setCurrentMood",
    );

    renderHook(() => useApplyWorldStateToViewer());

    act(() => {
      useWorldStateStore.getState().applyDelta({ mood: "sad" });
    });
    act(() => {
      useWorldStateStore.getState().applyDelta({ mood: "angry" });
    });

    expect(setCurrentMood).toHaveBeenCalledWith("sad");
    expect(setCurrentMood).toHaveBeenCalledWith("angry");
  });
});

// ─── T7: unmount does not throw (no leak) ────────────────────────────────────

describe("useApplyWorldStateToViewer — T7: unmount cleans up", () => {
  it("unmounts without throwing or leaking subscriptions", () => {
    const { unmount } = renderHook(() => useApplyWorldStateToViewer());

    expect(() => {
      unmount();
      // Post-unmount delta should not trigger any effect
      act(() => {
        useWorldStateStore.getState().applyDelta({ mood: "sad" });
      });
    }).not.toThrow();
  });
});

// ─── T8 (review fix P2 #58): initial mount NE PROPAGE PAS le placeholder ──────

describe("useApplyWorldStateToViewer — T8: gated until first snapshot", () => {
  it("does NOT call setSelectedSceneId on initial mount before any server payload", () => {
    const setSelectedSceneId = vi.spyOn(
      useSceneComposerStore.getState(),
      "setSelectedSceneId",
    );

    // Mount le hook — sans avoir appelé applyDelta/reset, hasReceivedSnapshot=false
    renderHook(() => useApplyWorldStateToViewer());

    // Le hook NE DOIT PAS propager le placeholder INITIAL_STATE.scene_id="default".
    expect(setSelectedSceneId).not.toHaveBeenCalled();
  });

  it("does NOT emit [L4] warns before first snapshot", () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    renderHook(() => useApplyWorldStateToViewer());
    const l4Warns = warnSpy.mock.calls
      .map((c) => String(c[0]))
      .filter((msg) => msg.includes("[L4]"));
    expect(l4Warns).toEqual([]);
  });

  it("starts propagating after first applyDelta (gate opens)", () => {
    const setSelectedSceneId = vi.spyOn(
      useSceneComposerStore.getState(),
      "setSelectedSceneId",
    );

    renderHook(() => useApplyWorldStateToViewer());

    // 1er server payload — gate s'ouvre, le scene_id reçu est propagé.
    act(() => {
      useWorldStateStore.getState().applyDelta({ scene_id: "kitchen" });
    });

    expect(setSelectedSceneId).toHaveBeenCalledWith("kitchen");
  });
});
