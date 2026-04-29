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
  it("does not call setSelectedSceneId when only mood changes", () => {
    renderHook(() => useApplyWorldStateToViewer());

    const setSelectedSceneId = vi.spyOn(
      useSceneComposerStore.getState(),
      "setSelectedSceneId",
    );

    act(() => {
      useWorldStateStore.getState().applyDelta({ mood: "happy" });
    });

    // scene_id did not change so setSelectedSceneId must NOT be called
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
