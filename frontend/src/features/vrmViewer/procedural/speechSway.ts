import * as THREE from "three";
import { VRM, VRMHumanBoneName } from "@pixiv/three-vrm";

/**
 * Body sways gently during speech — torso x/z offset synced to lipSync volume.
 * Goes to 0 smoothly when she stops talking (spring damping).
 */
export class SpeechSway {
  private _time = 0;
  private _chestBase: THREE.Vector3 | null = null;
  private _smoothedVolume = 0;

  update(delta: number, vrm: VRM, lipSyncVolume: number): void {
    this._time += delta;

    const chest = vrm.humanoid.getNormalizedBoneNode("chest" as VRMHumanBoneName)
      || vrm.humanoid.getNormalizedBoneNode("upperChest" as VRMHumanBoneName)
      || vrm.humanoid.getNormalizedBoneNode("spine" as VRMHumanBoneName);
    if (!chest) return;

    if (!this._chestBase) this._chestBase = chest.position.clone();

    // Smooth the volume envelope so the sway doesn't judder with word boundaries.
    const volK = 1 - Math.exp(-3 * delta);
    this._smoothedVolume += (lipSyncVolume - this._smoothedVolume) * volK;

    const swayX = Math.sin(this._time * 2.5) * this._smoothedVolume * 0.012;
    const swayZ = Math.sin(this._time * 1.8 + 0.7) * this._smoothedVolume * 0.008;

    chest.position.x = this._chestBase.x + swayX;
    chest.position.z = chest.position.z + swayZ;   // additive to breathing
  }
}
