/**
 * useApplyWorldStateToViewer — synchronises useWorldStateStore → useSceneComposerStore.
 *
 * Bridges the agent-driven world state (received via WebSocket /ws/world and
 * stored in useWorldStateStore) to the Three.js viewer controls exposed by
 * useSceneComposerStore.
 *
 * Mapping decisions (L4-viewer.1 + L4-viewer.2):
 *
 * | world field      | viewer API                          | status (PR)         |
 * |------------------|-------------------------------------|---------------------|
 * | state.scene_id   | setSelectedSceneId(scene_id)        | WIRED (L4-viewer.1) |
 * | state.avatar_pose| setCurrentVrmaUrl(resolvedUrl)      | WIRED (L4-viewer.2) |
 * | state.mood       | setCurrentMood(mood)                | WIRED (L4-viewer.2) |
 *
 * avatar_pose resolution (L4-viewer.2):
 *   The viewer expects a full VRMA URL via setCurrentVrmaUrl (e.g.
 *   "/assets/vrma/wave.vrma"), but the world state carries a logical pose
 *   name ("wave"). pose-registry.ts provides the mapping.
 *   If the pose name is not in the registry (new animation added to backend
 *   but not yet to frontend registry), a console.warn is emitted and the
 *   animation is skipped. Extend pose-registry.ts to fix.
 *
 * mood resolution (L4-viewer.2):
 *   setCurrentMood() stores the mood in useSceneComposerStore.currentMood.
 *   The Three.js lighting consumer (not yet implemented) will read that value.
 *   The setter is the API boundary — lighting implementation is a future PR.
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
import { resolvePoseToVrmaUrl } from "./pose-registry";

/**
 * Synchronises all world state fields to the viewer store.
 *
 * Granular selectors ensure each useEffect fires only for its own field,
 * avoiding spurious re-triggers when unrelated world fields change.
 */
export function useApplyWorldStateToViewer(): void {
  // ── Select individual fields so effects are granular ───────────────────────
  const sceneId = useWorldStateStore((s) => s.state.scene_id);
  const avatarPose = useWorldStateStore((s) => s.state.avatar_pose);
  const mood = useWorldStateStore((s) => s.state.mood);

  // Régression P2 review #58 : gate sur le 1er snapshot serveur reçu.
  // Sans ça, useEffect tire au premier render avec INITIAL_STATE
  // (scene_id="default", etc.), écrasant la sélection UI courante avant que
  // /ws/world délivre la vraie valeur. Un consumer downstream
  // (SceneInspectorPanel.getScene(selectedSceneId)) verrait un fetch raté +
  // flicker. Le flag est mis à true au premier applyDelta/reset du store.
  const hasReceivedSnapshot = useWorldStateStore((s) => s.hasReceivedSnapshot);

  // ── scene_id → setSelectedSceneId (direct match, gated) ───────────────────
  useEffect(() => {
    if (!hasReceivedSnapshot) return;
    useSceneComposerStore.getState().setSelectedSceneId(sceneId);
  }, [sceneId, hasReceivedSnapshot]);

  // ── avatar_pose → setCurrentVrmaUrl (via pose registry) ───────────────────
  useEffect(() => {
    if (!hasReceivedSnapshot) return;
    const url = resolvePoseToVrmaUrl(avatarPose);
    if (url === null) {
      console.warn(
        `[L4] unknown avatar_pose '${avatarPose}' — no VRMA URL in registry. ` +
          "Update pose-registry.ts to add this pose.",
      );
      return;
    }
    useSceneComposerStore.getState().setCurrentVrmaUrl(url);
  }, [avatarPose, hasReceivedSnapshot]);

  // ── mood → setCurrentMood (lighting API, L4-viewer.2) ─────────────────────
  useEffect(() => {
    if (!hasReceivedSnapshot) return;
    useSceneComposerStore.getState().setCurrentMood(mood);
  }, [mood, hasReceivedSnapshot]);
}
