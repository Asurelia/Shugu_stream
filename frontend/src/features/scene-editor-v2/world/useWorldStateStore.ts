/**
 * useWorldStateStore — Zustand store for the L4 World State viewer.
 *
 * Maintains the current snapshot of WorldState received via world.delta
 * WebSocket events from the backend (see useWorldDelta hook).
 *
 * Design:
 * - applyDelta: merges a partial delta (Partial<WorldState>) into the current
 *   state. Mirrors the backend publisher.diff() semantics — only changed
 *   fields are present in the delta.
 * - reset: replaces the entire state with a fresh snapshot (useful on
 *   reconnect or when a full state is available).
 *
 * Single-store rule: this store is separate from useSceneStore (scene graph /
 * editor interaction) to maintain clear responsibility boundaries:
 * - useSceneStore = editor interaction (nodes, selection, transforms).
 * - useWorldStateStore = agent-driven live world state (pose, mood, props, …).
 *
 * @module world/useWorldStateStore
 */

import { create } from "zustand";

/** Mood values mirror backend shugu/world/types.py Mood Literal. */
export type Mood = "neutral" | "happy" | "angry" | "sad" | "relaxed" | "surprised";

/** A prop placed in the scene — mirrors backend Prop dataclass. */
export type WorldProp = {
  prop_id: string;
  x: number;
  y: number;
  z: number;
};

/** Complete world snapshot — mirrors backend WorldState dataclass. */
export type WorldState = {
  avatar_pose: string;
  scene_id: string;
  mood: Mood;
  props: WorldProp[];
  clock_ms: number;
};

/**
 * Partial world update — emitted by backend publish_world_delta().
 * Only fields that changed are present.
 */
export type WorldDelta = Partial<WorldState>;

/** Zustand store shape. */
type WorldStore = {
  state: WorldState;
  /** Merges a partial delta into the current state. */
  applyDelta: (delta: WorldDelta) => void;
  /** Replaces the entire state with a fresh snapshot. */
  reset: (next: WorldState) => void;
};

/** Default initial state — matches backend WorldState defaults. */
const INITIAL_STATE: WorldState = {
  avatar_pose: "idle",
  scene_id: "default",
  mood: "neutral",
  props: [],
  clock_ms: 0,
};

export const useWorldStateStore = create<WorldStore>((set) => ({
  state: INITIAL_STATE,

  applyDelta: (delta) =>
    set((s) => ({ state: { ...s.state, ...delta } })),

  reset: (next) => set({ state: next }),
}));

/**
 * Reset utility for Vitest — restores store to initial state between tests.
 * Not exported in index.ts (test-only).
 */
export function __resetWorldStateStoreForTest(): void {
  useWorldStateStore.setState({ state: { ...INITIAL_STATE, props: [] } });
}
