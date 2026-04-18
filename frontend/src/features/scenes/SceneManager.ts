import type { Viewer } from "../vrmViewer/viewer";
import { DEFAULT_SCENE, SCENES, SceneConfig, SceneName, isSceneName } from "./scenes";

type BackgroundListener = (background: string) => void;

type SceneManagerOptions = {
  viewer: Viewer;
  onBackgroundChange?: BackgroundListener;
  /** Minimum seconds between scene switches. Prevents LLM thrashing. */
  cooldownSec?: number;
};

/**
 * Applies a scene change across three surfaces:
 *   1. Camera (viewer.setShot)
 *   2. Avatar idle animation (viewer.animationManager.setIdle)
 *   3. Page background (onBackgroundChange listener)
 *
 * Cooldown guards against the LLM emitting `[scene=X]` on every message.
 * Re-requesting the active scene is a no-op regardless of cooldown.
 */
export class SceneManager {
  private viewer: Viewer;
  private onBackgroundChange?: BackgroundListener;
  private cooldownSec: number;

  private current: SceneName = DEFAULT_SCENE;
  private lastSwitchAt = 0;

  constructor(opts: SceneManagerOptions) {
    this.viewer = opts.viewer;
    this.onBackgroundChange = opts.onBackgroundChange;
    this.cooldownSec = opts.cooldownSec ?? 10;
  }

  public getCurrent(): SceneName {
    return this.current;
  }

  /** Apply the default scene without cooldown — called once after the VRM loads. */
  public applyInitial(): void {
    this.applyScene(SCENES[this.current]);
  }

  public requestScene(name: string): void {
    if (!isSceneName(name)) {
      console.warn(`[SceneManager] unknown scene: ${name}`);
      return;
    }
    if (name === this.current) return;
    const now = performance.now() / 1000;
    if (now - this.lastSwitchAt < this.cooldownSec) {
      return;
    }
    this.current = name;
    this.lastSwitchAt = now;
    this.applyScene(SCENES[name]);
  }

  private applyScene(cfg: SceneConfig): void {
    this.viewer.setShot({
      cameraBase: cfg.cameraBase,
      lookAt: cfg.cameraTarget,
      fov: cfg.fov,
    });
    this.viewer.setAvatarTransform(cfg.avatarPosition, cfg.avatarRotationY);
    const mgr = this.viewer.animationManager;
    if (mgr) {
      void mgr.setIdle(cfg.idleAnimation, 0.8);
    }
    this.onBackgroundChange?.(cfg.background);
  }
}
