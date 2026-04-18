import * as THREE from "three";
import { VRM, VRMExpressionPresetName } from "@pixiv/three-vrm";
import { ProceduralBreathing } from "./breathing";
import { HeadTwitch } from "./headTwitch";
import { LookAtTargetManager } from "./lookAtTarget";
import { SpeechSway } from "./speechSway";
import { EmotionDecay } from "./emotionDecay";

export type ProceduralContext = {
  lipSyncVolume: number;
  cursorNDC: { x: number; y: number } | null;
  camera: THREE.Camera;
};

/**
 * Orchestrator for all procedural animation layers.
 * Each layer is independent; any that errors mid-update is caught per-layer
 * so one buggy bone lookup doesn't freeze the avatar.
 */
export class ProceduralOrchestrator {
  private _breathing = new ProceduralBreathing();
  private _twitch = new HeadTwitch();
  private _lookAt = new LookAtTargetManager();
  private _sway = new SpeechSway();
  private _decay: EmotionDecay | null = null;

  private _vrm: VRM | null = null;
  private _attached = false;

  attach(vrm: VRM, camera: THREE.Camera): void {
    this._vrm = vrm;
    this._lookAt.attach(vrm, camera);
    if (vrm.expressionManager) {
      this._decay = new EmotionDecay(vrm.expressionManager);
    }
    this._attached = true;
  }

  triggerEmotion(preset: VRMExpressionPresetName): void {
    this._decay?.trigger(preset);
  }

  triggerChatGlance(ndc: { x: number; y: number }): void {
    if (!this._vrm) return;
    // Camera is resolved via the LookAt manager which already holds it.
    // We re-project using the current camera at update time — stash and consume.
    this._pendingGlance = ndc;
  }
  private _pendingGlance: { x: number; y: number } | null = null;

  update(delta: number, ctx: ProceduralContext): void {
    if (!this._attached || !this._vrm) return;
    const vrm = this._vrm;
    const speaking = ctx.lipSyncVolume > 0.08;

    // Propagate cursor to the lookAt manager (which knows the camera).
    this._lookAt.setCursorNDC(ctx.cursorNDC, ctx.camera);
    if (this._pendingGlance) {
      this._lookAt.triggerChatGlance(this._pendingGlance, ctx.camera);
      this._pendingGlance = null;
    }

    try { this._breathing.update(delta, vrm, ctx.lipSyncVolume); } catch (e) { console.warn("breathing:", e); }
    try { this._twitch.update(delta, vrm, speaking); } catch (e) { console.warn("twitch:", e); }
    try { this._lookAt.update(delta, vrm); } catch (e) { console.warn("lookAt:", e); }
    try { this._sway.update(delta, vrm, ctx.lipSyncVolume); } catch (e) { console.warn("sway:", e); }
    try { this._decay?.update(delta); } catch (e) { console.warn("decay:", e); }
  }
}
