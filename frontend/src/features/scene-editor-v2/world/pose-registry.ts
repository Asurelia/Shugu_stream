/**
 * Pose-name → VRMA URL registry.
 *
 * Maps the abstract pose names emitted by the agent (e.g. "wave", "bow",
 * "idle_loop") to concrete VRMA asset URLs the viewer can load via
 * useSceneComposerStore.setCurrentVrmaUrl().
 *
 * Source of truth: the actual VRMA files present in
 * frontend/public/assets/vrma/ at the time of this PR (10 files).
 * Only poses with a real .vrma file on disk are registered.
 *
 * Aliases:
 *   - "idle" → idle_loop.vrma: the agent emits "idle" (world INITIAL_STATE),
 *     but the real asset is idle_loop.vrma. Alias maps the logical name.
 *   - "excited_wave" → excited_wave.vrma: slug order matches proposed_animations.json
 *
 * Future: lazy-load from /api/vrma/registry endpoint when the backend
 * exposes a pose-slug → URL map directly.
 *
 * @module world/pose-registry
 */

/**
 * Mapping from abstract agent pose name to concrete VRMA asset URL.
 *
 * Sourced from frontend/public/assets/vrma/ catalogue (not invented).
 * Extend this record when new .vrma files are added to the asset bank.
 */
export const POSE_TO_VRMA_URL: Record<string, string> = {
  // Alias: agent emits "idle"; actual file is idle_loop.vrma
  idle: "/assets/vrma/idle_loop.vrma",
  idle_loop: "/assets/vrma/idle_loop.vrma",
  // Greetings
  wave: "/assets/vrma/wave.vrma",
  excited_wave: "/assets/vrma/excited_wave.vrma",
  bow: "/assets/vrma/bow.vrma",
  peace_sign: "/assets/vrma/peace_sign.vrma",
  // Reactions
  thumbs_up: "/assets/vrma/thumbs_up.vrma",
  clap: "/assets/vrma/clap.vrma",
  // Emotes
  dance: "/assets/vrma/dance.vrma",
  shy_giggle: "/assets/vrma/shy_giggle.vrma",
  thinking: "/assets/vrma/thinking.vrma",
};

/**
 * Resolves an agent pose name to a concrete VRMA asset URL.
 *
 * Returns null if the pose name is not registered (unknown or not yet
 * mapped). Callers should emit a warning and skip the animation in that case.
 *
 * P1 fix review #60: must use `Object.hasOwn` to guard against prototype
 * pollution. `avatar_pose` is an arbitrary string from world deltas — names
 * like `"toString"`, `"constructor"`, `"__proto__"`, `"hasOwnProperty"` would
 * resolve to inherited Object.prototype members instead of `undefined`. The
 * `?? null` short-circuit would NOT trigger (a function reference is truthy),
 * and the caller would `setCurrentVrmaUrl(<function>)` → invalid animation
 * load + viewer desync. The own-property check ensures only explicitly
 * registered keys can resolve to a URL.
 *
 * @param pose - The abstract pose name emitted by the agent (e.g. "wave").
 * @returns The VRMA asset URL (e.g. "/assets/vrma/wave.vrma") or null.
 *
 * @example
 * const url = resolvePoseToVrmaUrl("wave");
 * // → "/assets/vrma/wave.vrma"
 *
 * const missing = resolvePoseToVrmaUrl("unknown_pose");
 * // → null
 *
 * const proto = resolvePoseToVrmaUrl("toString");
 * // → null (prototype-pollution guarded)
 */
export function resolvePoseToVrmaUrl(pose: string): string | null {
  if (!Object.hasOwn(POSE_TO_VRMA_URL, pose)) {
    return null;
  }
  return POSE_TO_VRMA_URL[pose];
}
