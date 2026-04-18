import * as THREE from "three";
import { VRM, VRMHumanBoneName } from "@pixiv/three-vrm";

/**
 * Subtle breathing — a sine wave applied to the spine + chest Z offset.
 * Amplitude is sub-cm, period ~4 s at rest, ~2 s when speaking (mild arousal).
 *
 * Applied *after* the animation mixer so it layers over the idle_loop.vrma
 * without conflicting. Each update, reset to the additive offset computed
 * from scratch (not accumulating) so we don't drift.
 */
export class ProceduralBreathing {
  private _time = 0;
  private _spineBase: THREE.Vector3 | null = null;
  private _chestBase: THREE.Vector3 | null = null;

  update(delta: number, vrm: VRM, lipSyncVolume: number): void {
    this._time += delta;

    const spine = vrm.humanoid.getNormalizedBoneNode("spine" as VRMHumanBoneName);
    const chest = vrm.humanoid.getNormalizedBoneNode("chest" as VRMHumanBoneName);
    if (!spine) return;

    // Capture rest-pose offsets once. `mixer.update()` writes position each frame,
    // so "rest" here means "what the animation just wrote before we added breathing".
    if (!this._spineBase) this._spineBase = spine.position.clone();
    if (chest && !this._chestBase) this._chestBase = chest.position.clone();

    // Frequency ramps up slightly when Shugu is speaking (excited breath).
    const freq = 1.6 + lipSyncVolume * 1.2;  // rad/s
    const amplitude = 0.002 + lipSyncVolume * 0.003;  // 2-5 mm
    const wave = Math.sin(this._time * freq);

    // Reset from the animation-written position, then add our breath offset.
    spine.position.z = this._spineBase.z + wave * amplitude * 0.6;
    spine.position.y = this._spineBase.y + wave * amplitude * 0.3;
    if (chest && this._chestBase) {
      chest.position.z = this._chestBase.z + wave * amplitude;
    }
  }
}
