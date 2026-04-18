import * as THREE from "three";
import { VRM, VRMHumanBoneName } from "@pixiv/three-vrm";

/**
 * Subtle involuntary head twitches — small random rotations on the neck bone
 * every 0.8–2.5 s. Amplitude drops during speech (concentration). The twitch
 * lerps to a new target over ~300 ms then holds until the next one fires.
 *
 * Applied additively after the animation mixer.
 */
export class HeadTwitch {
  private _time = 0;
  private _nextFireAt = 0;
  private _targetQuat = new THREE.Quaternion();
  private _currentQuat = new THREE.Quaternion();
  private _restQuat: THREE.Quaternion | null = null;

  private _scheduleNext() {
    const interval = 0.8 + Math.random() * 1.7;
    this._nextFireAt = this._time + interval;
    // Max rotation ±3°, biased slightly (slight head tilt / nod)
    const pitch = (Math.random() - 0.5) * THREE.MathUtils.degToRad(3);
    const yaw = (Math.random() - 0.5) * THREE.MathUtils.degToRad(4);
    const roll = (Math.random() - 0.5) * THREE.MathUtils.degToRad(2);
    this._targetQuat.setFromEuler(new THREE.Euler(pitch, yaw, roll, "YXZ"));
  }

  update(delta: number, vrm: VRM, speaking: boolean): void {
    this._time += delta;
    if (this._time >= this._nextFireAt) this._scheduleNext();

    const neck = vrm.humanoid.getNormalizedBoneNode("neck" as VRMHumanBoneName);
    if (!neck) return;

    if (!this._restQuat) this._restQuat = neck.quaternion.clone();

    // Smooth toward the target — exponential damping.
    const k = 1 - Math.exp(-6 * delta);   // ~300 ms settle
    this._currentQuat.slerp(this._targetQuat, k);

    // Reduce amplitude by half when speaking.
    const amplitude = speaking ? 0.5 : 1.0;
    const scaled = new THREE.Quaternion().slerpQuaternions(
      new THREE.Quaternion(),
      this._currentQuat,
      amplitude,
    );

    // Compose on top of the animation-posed neck (restQuat captured first time).
    neck.quaternion.copy(this._restQuat).multiply(scaled);
  }
}
