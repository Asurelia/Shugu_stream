/**
 * Tests for pose-registry.ts
 *
 * Verifies that the pose-name → VRMA URL registry resolves known poses
 * to their real asset URLs and returns null for unknown poses.
 *
 * The registry is sourced from the actual VRMA bank in
 * frontend/public/assets/vrma/ — no invented paths.
 */

import { describe, it, expect } from "vitest";
import { resolvePoseToVrmaUrl, POSE_TO_VRMA_URL } from "../pose-registry";

// ─── T1: known pose returns VRMA URL ─────────────────────────────────────────

describe("pose-registry — T1: known pose returns vrma URL", () => {
  it("resolves 'wave' to its VRMA URL", () => {
    const url = resolvePoseToVrmaUrl("wave");
    expect(url).toBe("/assets/vrma/wave.vrma");
  });

  it("resolves 'bow' to its VRMA URL", () => {
    const url = resolvePoseToVrmaUrl("bow");
    expect(url).toBe("/assets/vrma/bow.vrma");
  });

  it("resolves 'thinking' to its VRMA URL", () => {
    const url = resolvePoseToVrmaUrl("thinking");
    expect(url).toBe("/assets/vrma/thinking.vrma");
  });
});

// ─── T2: unknown pose returns null ───────────────────────────────────────────

describe("pose-registry — T2: unknown pose returns null", () => {
  it("returns null for a pose not in the registry", () => {
    expect(resolvePoseToVrmaUrl("nonexistent_pose_xyz")).toBeNull();
  });

  it("returns null for an empty string", () => {
    expect(resolvePoseToVrmaUrl("")).toBeNull();
  });
});

// ─── T3: idle pose resolves ───────────────────────────────────────────────────

describe("pose-registry — T3: idle pose resolves (default pose from INITIAL_STATE)", () => {
  it("resolves 'idle' to idle_loop.vrma (real file on disk, no invented path)", () => {
    // The world store INITIAL_STATE.avatar_pose = "idle", so "idle" MUST resolve.
    // The actual file on disk is idle_loop.vrma — this is an alias, not invention.
    const url = resolvePoseToVrmaUrl("idle");
    expect(url).toBe("/assets/vrma/idle_loop.vrma");
  });

  it("POSE_TO_VRMA_URL contains 'idle' key", () => {
    expect(Object.prototype.hasOwnProperty.call(POSE_TO_VRMA_URL, "idle")).toBe(true);
  });
});
