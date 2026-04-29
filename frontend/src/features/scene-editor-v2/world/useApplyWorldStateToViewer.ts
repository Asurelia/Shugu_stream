/**
 * useApplyWorldStateToViewer — synchronises useWorldStateStore → useSceneComposerStore.
 *
 * Bridges the agent-driven world state (received via WebSocket /ws/world and
 * stored in useWorldStateStore) to the Three.js viewer controls exposed by
 * useSceneComposerStore.
 *
 * Mapping decisions:
 *
 * | world field   | viewer API                        | status        |
 * |---------------|-----------------------------------|---------------|
 * | state.scene_id | setSelectedSceneId(scene_id)      | WIRED         |
 * | state.avatar_pose | no pose-name→URL catalog exists | TODO log      |
 * | state.mood     | no mood lighting API exists yet   | TODO log      |
 *
 * avatar_pose: the viewer (useSceneComposerStore + SceneComposerViewer) expects
 * a full VRMA URL via setCurrentVrmaUrl (e.g. "/assets/vrma/wave.vrma"), but
 * the world state only carries a pose *name* like "wave". Inventing a path
 * convention would break the catalog contract — this is tracked as TODO and
 * will be resolved when a pose-name → asset-URL registry is wired (next PR).
 *
 * mood: no mood-lighting API exists in useSceneComposerStore yet.
 * Logged as TODO when the mood changes.
 *
 * Call this hook once at the top of the 3D Workspace component, alongside
 * useWorldDelta(), so the full pipeline is active while the workspace is
 * mounted.
 *
 * @example
 * function Workspace3D() {
 *   useWorldDelta();               // subscribe to WS
 *   useApplyWorldStateToViewer();  // bridge to Three.js viewer
 *   return <...>;
 * }
 *
 * @module world/useApplyWorldStateToViewer
 */

import { useEffect } from "react";
import { useWorldStateStore } from "./useWorldStateStore";
import { useSceneComposerStore } from "../../scene-composer/store/useSceneComposerStore";

/**
 * Synchronises the world state fields that have a direct viewer API match,
 * and emits console.warn TODO notices for fields that still need a resolver.
 *
 * Granular selectors ensure each useEffect fires only for its own field,
 * avoiding spurious re-triggers when unrelated world fields change.
 */
export function useApplyWorldStateToViewer(): void {
  // ── Select individual fields so effects are granular ───────────────────────
  const sceneId = useWorldStateStore((s) => s.state.scene_id);
  const avatarPose = useWorldStateStore((s) => s.state.avatar_pose);
  const mood = useWorldStateStore((s) => s.state.mood);

  // ── scene_id → setSelectedSceneId (direct match) ──────────────────────────
  useEffect(() => {
    useSceneComposerStore.getState().setSelectedSceneId(sceneId);
  }, [sceneId]);

  // ── avatar_pose → TODO log (no pose-name→VRMA-URL resolver yet) ───────────
  useEffect(() => {
    console.warn(
      `[L4] avatar pose change not wired yet: ${avatarPose}. ` +
        "A pose-name → VRMA asset URL registry is needed before this can " +
        "call setCurrentVrmaUrl(). Track in next PR.",
    );
  }, [avatarPose]);

  // ── mood → TODO log (no mood-lighting API in useSceneComposerStore yet) ───
  useEffect(() => {
    console.warn(
      `[L4] mood change not wired yet: ${mood}. ` +
        "A mood-lighting API on useSceneComposerStore is needed. " +
        "Track in next PR.",
    );
  }, [mood]);
}
