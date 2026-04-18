import * as THREE from "three";
import { VRM } from "@pixiv/three-vrm";

/**
 * Priority-stacked look-at target manager.
 *
 * Priority (highest first):
 *   1. Chat glance — triggered by chat.message_arrived, holds ~1.2 s
 *   2. Mouse cursor — active if mouse moved in the last 5 s
 *   3. Camera — default, Shugu makes eye contact with the viewer
 *
 * Writes to `vrm.lookAt.target` (the VRMLookAtSmoother handles smoothing).
 * A hidden Object3D is added to the camera to act as the target carrier.
 */
export class LookAtTargetManager {
  private _target: THREE.Object3D;
  private _cameraFallback: THREE.Object3D;

  private _lastMouseMoveAt = -999;    // seconds
  private _mouseTargetWorld = new THREE.Vector3();
  private _mouseTargetRaw = new THREE.Vector3();     // newest cursor position
  private _mouseHasTarget = false;

  private _glanceTargetWorld = new THREE.Vector3();
  private _glanceExpiresAt = -999;
  private _time = 0;

  // Damping factor for the mouse follow — smaller = slower / more laggy.
  // 0.05 = head reaches ~63 % of the cursor position in 20 frames (~330 ms
  // @ 60 fps). Feels natural — no instant snapping.
  private readonly _mouseSmoothRate = 2.5;  // exp-damping rate, rad/s

  constructor() {
    this._target = new THREE.Object3D();
    this._target.name = "shugu-lookat-target";
    this._cameraFallback = new THREE.Object3D();
  }

  /** Call once after VRM is loaded. */
  attach(vrm: VRM, camera: THREE.Camera): void {
    // Place the fallback target 2 m in front of the camera (so default = eye contact).
    camera.add(this._cameraFallback);
    this._cameraFallback.position.set(0, 0, -2);

    // The actual target is the one three-vrm reads. We move it each frame.
    (vrm.lookAt as any).target = this._target;
    // Smoother saccades are already enabled by the plugin.
  }

  setCursorNDC(ndc: { x: number; y: number } | null, camera: THREE.Camera) {
    if (!ndc) {
      this._lastMouseMoveAt = -999;
      return;
    }
    this._lastMouseMoveAt = this._time;
    // Project NDC → world-space 2 m in front of the camera. This is the RAW
    // cursor target; the smoothed target position is lerped toward it each
    // frame inside update() to create natural tracking lag.
    const v = new THREE.Vector3(ndc.x, ndc.y, 0.5).unproject(camera as THREE.PerspectiveCamera);
    const dir = v.sub(camera.position).normalize();
    this._mouseTargetRaw.copy(camera.position).addScaledVector(dir, 2);
    if (!this._mouseHasTarget) {
      this._mouseTargetWorld.copy(this._mouseTargetRaw);
      this._mouseHasTarget = true;
    }
  }

  triggerChatGlance(screenPos: { x: number; y: number }, camera: THREE.Camera, durationS = 1.2) {
    // screenPos in NDC too.
    const v = new THREE.Vector3(screenPos.x, screenPos.y, 0.5)
      .unproject(camera as THREE.PerspectiveCamera);
    const dir = v.sub(camera.position).normalize();
    this._glanceTargetWorld.copy(camera.position).addScaledVector(dir, 2);
    this._glanceExpiresAt = this._time + durationS;
  }

  update(delta: number, _vrm: VRM): void {
    this._time += delta;

    // Damp the mouse-follow target toward the raw cursor position each frame.
    // Exponential damping feels more natural than linear lerp.
    if (this._mouseHasTarget) {
      const k = 1 - Math.exp(-this._mouseSmoothRate * delta);
      this._mouseTargetWorld.lerp(this._mouseTargetRaw, k);
    }

    // Priority 1 — chat glance (also damped so it doesn't snap)
    if (this._time < this._glanceExpiresAt) {
      const k = 1 - Math.exp(-4 * delta);
      this._target.position.lerp(this._glanceTargetWorld, k);
      return;
    }

    // Priority 2 — mouse (if active in last 5 s)
    if (this._time - this._lastMouseMoveAt < 5) {
      const k = 1 - Math.exp(-5 * delta);
      this._target.position.lerp(this._mouseTargetWorld, k);
      return;
    }

    // Priority 3 — camera (eye contact with viewer)
    const cam = new THREE.Vector3();
    this._cameraFallback.getWorldPosition(cam);
    const k = 1 - Math.exp(-3 * delta);
    this._target.position.lerp(cam, k);
  }
}
