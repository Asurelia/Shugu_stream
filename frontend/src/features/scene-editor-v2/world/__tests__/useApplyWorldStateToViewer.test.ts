/**
 * Tests for useApplyWorldStateToViewer hook.
 *
 * Strategy: since avatar_pose → VRMA URL conversion has no catalog mapping
 * (the viewer expects full URLs, world state holds pose names), the hook
 * emits console.warn("[L4] ...") for unresolvable mappings.
 *
 * For scene_id we use useSceneComposerStore.setSelectedSceneId — direct match.
 * For avatar_pose and mood we verify the TODO-log path (console.warn called).
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

// ─── T4: avatar_pose change emits TODO warn ───────────────────────────────────

describe("useApplyWorldStateToViewer — T4: avatar_pose TODO-log", () => {
  it("emits console.warn with [L4] tag when avatar_pose changes", () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

    renderHook(() => useApplyWorldStateToViewer());

    act(() => {
      useWorldStateStore.getState().applyDelta({ avatar_pose: "wave" });
    });

    const calls = warnSpy.mock.calls.map((c) => String(c[0]));
    const hasL4Warn = calls.some((msg) => msg.includes("[L4]"));
    expect(hasL4Warn).toBe(true);
  });
});

// ─── T5: unmount does not throw (no leak) ────────────────────────────────────

describe("useApplyWorldStateToViewer — T5: unmount cleans up", () => {
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

// ─── T6 (review fix P2 #58) : initial mount NE PROPAGE PAS le placeholder ─────

describe("useApplyWorldStateToViewer — T6: gated until first snapshot", () => {
  it("does NOT call setSelectedSceneId on initial mount before any server payload", () => {
    const setSelectedSceneId = vi.spyOn(
      useSceneComposerStore.getState(),
      "setSelectedSceneId",
    );

    // Mount le hook — sans avoir appelé applyDelta/reset, hasReceivedSnapshot=false
    renderHook(() => useApplyWorldStateToViewer());

    // Le hook NE DOIT PAS propager le placeholder INITIAL_STATE.scene_id="default".
    // Sinon un consumer (SceneInspectorPanel.getScene("default")) ferait un fetch
    // raté + flicker UI avant que le vrai world.delta arrive.
    expect(setSelectedSceneId).not.toHaveBeenCalled();
  });

  it("does NOT emit avatar_pose/mood TODO logs before first snapshot", () => {
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
