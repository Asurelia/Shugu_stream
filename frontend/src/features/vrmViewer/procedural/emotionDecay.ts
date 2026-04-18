import {
  VRMExpressionManager,
  VRMExpressionPresetName,
} from "@pixiv/three-vrm";

/**
 * Envelope-shaped emotion playback. Classical ASR (attack-sustain-release):
 *   - attack  200 ms : 0 → 1
 *   - sustain 1000 ms: hold at 1
 *   - release 2300 ms: 1 → 0
 * Total ~3.5 s then back to neutral.
 *
 * If a new emotion is triggered mid-decay, the current one is rapidly released
 * (300 ms) while the new one starts its attack from 0 — i.e. a quick crossfade.
 */
const ATTACK_MS = 200;
const SUSTAIN_MS = 1000;
const RELEASE_MS = 2300;
const CROSSFADE_RELEASE_MS = 300;

export class EmotionDecay {
  private _mgr: VRMExpressionManager;
  private _activePreset: VRMExpressionPresetName | null = null;
  private _activeElapsedMs = 0;

  private _fadingPreset: VRMExpressionPresetName | null = null;
  private _fadingWeight = 0;
  private _fadingElapsedMs = 0;

  constructor(mgr: VRMExpressionManager) {
    this._mgr = mgr;
  }

  trigger(preset: VRMExpressionPresetName): void {
    if (preset === "neutral") {
      // Just release whatever is active.
      if (this._activePreset) {
        this._fadingPreset = this._activePreset;
        this._fadingWeight = this._weightAt(this._activeElapsedMs);
        this._fadingElapsedMs = 0;
      }
      this._activePreset = null;
      this._activeElapsedMs = 0;
      return;
    }

    if (this._activePreset && this._activePreset !== preset) {
      // Crossfade: release currently-active quickly, start new.
      this._fadingPreset = this._activePreset;
      this._fadingWeight = this._weightAt(this._activeElapsedMs);
      this._fadingElapsedMs = 0;
    }

    this._activePreset = preset;
    this._activeElapsedMs = 0;
  }

  private _weightAt(elapsedMs: number): number {
    if (elapsedMs < ATTACK_MS) return elapsedMs / ATTACK_MS;
    if (elapsedMs < ATTACK_MS + SUSTAIN_MS) return 1;
    const rel = elapsedMs - ATTACK_MS - SUSTAIN_MS;
    if (rel >= RELEASE_MS) return 0;
    return 1 - rel / RELEASE_MS;
  }

  update(delta: number): void {
    const ms = delta * 1000;

    if (this._activePreset) {
      this._activeElapsedMs += ms;
      const w = this._weightAt(this._activeElapsedMs);
      this._mgr.setValue(this._activePreset, w);
      if (w === 0 && this._activeElapsedMs >= ATTACK_MS + SUSTAIN_MS + RELEASE_MS) {
        this._mgr.setValue(this._activePreset, 0);
        this._activePreset = null;
        this._activeElapsedMs = 0;
      }
    }

    if (this._fadingPreset) {
      this._fadingElapsedMs += ms;
      const k = Math.max(0, 1 - this._fadingElapsedMs / CROSSFADE_RELEASE_MS);
      const w = this._fadingWeight * k;
      this._mgr.setValue(this._fadingPreset, w);
      if (k === 0) {
        this._mgr.setValue(this._fadingPreset, 0);
        this._fadingPreset = null;
      }
    }
  }
}
