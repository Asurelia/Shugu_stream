import { describe, it, expect, beforeEach } from "vitest";
import {
  useWorldStateStore,
  __resetWorldStateStoreForTest,
  type WorldState,
} from "../useWorldStateStore";

beforeEach(() => __resetWorldStateStoreForTest());

describe("useWorldStateStore — initial state", () => {
  it("starts with idle avatar_pose and neutral mood", () => {
    const { state } = useWorldStateStore.getState();
    expect(state.avatar_pose).toBe("idle");
    expect(state.mood).toBe("neutral");
    expect(state.scene_id).toBe("default");
    expect(state.props).toEqual([]);
    expect(state.clock_ms).toBe(0);
  });
});

describe("useWorldStateStore — applyDelta", () => {
  it("applyDelta merges partial update into state", () => {
    useWorldStateStore.getState().applyDelta({ avatar_pose: "wave" });
    const { state } = useWorldStateStore.getState();
    expect(state.avatar_pose).toBe("wave");
    // Other fields unchanged
    expect(state.mood).toBe("neutral");
    expect(state.scene_id).toBe("default");
  });

  it("applyDelta with multiple fields updates all", () => {
    useWorldStateStore.getState().applyDelta({ mood: "happy", clock_ms: 1500 });
    const { state } = useWorldStateStore.getState();
    expect(state.mood).toBe("happy");
    expect(state.clock_ms).toBe(1500);
    expect(state.avatar_pose).toBe("idle");
  });

  it("applyDelta with props replaces the props list", () => {
    const newProps = [{ prop_id: "glass", x: 1, y: 0, z: 0.5 }];
    useWorldStateStore.getState().applyDelta({ props: newProps });
    expect(useWorldStateStore.getState().state.props).toEqual(newProps);
  });

  it("applyDelta with empty delta leaves state unchanged", () => {
    const before = { ...useWorldStateStore.getState().state };
    useWorldStateStore.getState().applyDelta({});
    const after = useWorldStateStore.getState().state;
    expect(after).toEqual(before);
  });
});

describe("useWorldStateStore — reset", () => {
  it("reset replaces the entire state with provided snapshot", () => {
    useWorldStateStore.getState().applyDelta({ mood: "angry", clock_ms: 9999 });

    const freshState: WorldState = {
      avatar_pose: "bow",
      scene_id: "kitchen",
      mood: "relaxed",
      props: [{ prop_id: "chair", x: 0, y: 0, z: 0 }],
      clock_ms: 42,
    };
    useWorldStateStore.getState().reset(freshState);
    expect(useWorldStateStore.getState().state).toEqual(freshState);
  });

  it("reset after multiple deltas produces clean slate", () => {
    useWorldStateStore.getState().applyDelta({ mood: "angry" });
    useWorldStateStore.getState().applyDelta({ avatar_pose: "wave" });
    useWorldStateStore.getState().applyDelta({ clock_ms: 500 });

    const fresh: WorldState = {
      avatar_pose: "idle",
      scene_id: "default",
      mood: "neutral",
      props: [],
      clock_ms: 0,
    };
    useWorldStateStore.getState().reset(fresh);
    expect(useWorldStateStore.getState().state).toEqual(fresh);
  });
});
