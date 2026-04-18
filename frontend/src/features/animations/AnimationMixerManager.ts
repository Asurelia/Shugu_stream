import * as THREE from "three";
import type { VRM } from "@pixiv/three-vrm";
import { loadVRMAnimation } from "@/lib/VRMAnimation/loadVRMAnimation";
import { loadMixamoFbxAsVrmAnimation } from "./fbxRetarget";

/**
 * Idle + one-shot animation orchestrator.
 *
 *  - Keeps a looping idle clip alive on the mixer.
 *  - Crossfades idle ↔ idle when the active scene requests a different ambient pose.
 *  - Layers a one-shot clip (wave, bow, shrug…) over the idle for gesture moments,
 *    then crossfades back to idle when the clip ends.
 *
 * Missing .vrma files fail gracefully: log + keep the current pose running.
 */
export class AnimationMixerManager {
  public readonly mixer: THREE.AnimationMixer;

  private vrm: VRM;
  private clipCache = new Map<string, THREE.AnimationClip>();

  private idleAction: THREE.AnimationAction | null = null;
  private currentIdleUrl: string | null = null;

  private oneShotAction: THREE.AnimationAction | null = null;
  private pendingFallback = false;

  constructor(vrm: VRM) {
    this.vrm = vrm;
    this.mixer = new THREE.AnimationMixer(vrm.scene);
    this.mixer.addEventListener("finished", this.handleFinished);
  }

  public update(delta: number): void {
    this.mixer.update(delta);
  }

  public async setIdle(url: string, crossfadeSec = 0.8): Promise<void> {
    if (url === this.currentIdleUrl && this.idleAction) return;
    const clip = await this.loadClip(url);
    if (!clip) {
      // Leave current idle running — don't starve the rig.
      return;
    }
    const next = this.mixer.clipAction(clip);
    next.setLoop(THREE.LoopRepeat, Infinity);
    next.clampWhenFinished = false;
    next.reset();
    next.setEffectiveWeight(1);
    next.play();

    const prev = this.idleAction;
    if (prev && prev !== next) {
      next.crossFadeFrom(prev, crossfadeSec, true);
    }

    this.idleAction = next;
    this.currentIdleUrl = url;
  }

  public async playOneShot(url: string, opts?: { fadeInSec?: number }): Promise<void> {
    const fadeIn = opts?.fadeInSec ?? 0.25;
    const clip = await this.loadClip(url);
    if (!clip) return;

    // Cancel any in-flight one-shot immediately — the latest action wins.
    if (this.oneShotAction) {
      this.oneShotAction.stop();
      this.oneShotAction = null;
    }

    const action = this.mixer.clipAction(clip);
    action.setLoop(THREE.LoopOnce, 1);
    action.clampWhenFinished = false;
    action.reset();
    action.setEffectiveWeight(1);
    action.play();

    if (this.idleAction) {
      action.crossFadeFrom(this.idleAction, fadeIn, true);
    }

    this.oneShotAction = action;
    this.pendingFallback = true;
  }

  public dispose(): void {
    this.mixer.removeEventListener("finished", this.handleFinished);
    this.mixer.stopAllAction();
    this.clipCache.clear();
  }

  private handleFinished = (ev: any) => {
    const action = ev?.action as THREE.AnimationAction | undefined;
    if (!this.pendingFallback || !action) return;
    if (action !== this.oneShotAction) return;
    if (this.idleAction) {
      this.idleAction.reset();
      this.idleAction.setEffectiveWeight(1);
      this.idleAction.play();
      this.idleAction.crossFadeFrom(action, 0.3, true);
    }
    this.oneShotAction = null;
    this.pendingFallback = false;
  };

  private async loadClip(url: string): Promise<THREE.AnimationClip | null> {
    const cached = this.clipCache.get(url);
    if (cached) return cached;
    try {
      const lower = url.toLowerCase();
      const vrma = lower.endsWith(".fbx")
        ? await loadMixamoFbxAsVrmAnimation(url)
        : await loadVRMAnimation(url);
      if (!vrma) return null;
      const clip = vrma.createAnimationClip(this.vrm);
      this.clipCache.set(url, clip);
      return clip;
    } catch (err) {
      console.warn(`[AnimationMixer] failed to load ${url}`, err);
      return null;
    }
  }
}
