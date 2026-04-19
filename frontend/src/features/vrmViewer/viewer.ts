import * as THREE from "three";
import { Model } from "./model";
import { buildUrl } from "@/utils/buildUrl";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls";

/**
 * three.js-based 3D viewer for the VRM avatar.
 *
 * Camera behavior differs from the stock ChatVRM viewer:
 *  - OrbitControls is wired for target tracking only. rotate/zoom/pan are disabled
 *    (visitor can't drag Shugu around — that kills the stream immersion).
 *  - A sub-millimeter cinematic idle (sine wave on the camera position) keeps the
 *    shot from feeling dead. Layer B of the UI/UX plan.
 *
 * Call order: new Viewer() → setup(canvas) → loadVrm(url)
 */
export class Viewer {
  public isReady: boolean;
  public model?: Model;

  private _renderer?: THREE.WebGLRenderer;
  private _clock: THREE.Clock;
  private _scene: THREE.Scene;
  private _camera?: THREE.PerspectiveCamera;
  private _cameraControls?: OrbitControls;
  // Celestial Veil framing: plan tête→genoux équilibré. FOV 26° à Z=2.8 donne
  // ~1.29m de hauteur visible, centre à la poitrine (tête - 0.30m). Offset
  // choisi pour laisser ~35cm de marge au-dessus de la tête (libère le header
  // fixé h-16 + backdrop-blur) tout en gardant les genoux dans le cadre.
  private _cameraBase = new THREE.Vector3(0, 1.2, 2.8);
  private _cameraBaseTarget = new THREE.Vector3(0, 1.2, 2.8);
  private _lookAtCurrent = new THREE.Vector3(0, 1.2, 0);
  private _lookAtTarget = new THREE.Vector3(0, 1.2, 0);
  private _fovCurrent = 26;
  private _fovTarget = 26;
  // Décalage vertical du centre de cadrage par rapport à la tête. -0.30m = poitrine.
  private _cameraHeadOffset = -0.30;
  private _sceneLerpRate = 2.0;   // per-second lerp rate toward scene targets (~500ms settle)
  private _cinematicTime = 0;

  // Avatar transform — the scene can shift Shugu in world space so she's not
  // glued to the origin between scenes. Subtle idle drift keeps her alive.
  // `_avatarRotYRest` captures the initial rotation after VRM load (e.g. the
  // 180° Y flip applied by VRMUtils.rotateVRM0 on VRM0 models); scene-driven
  // yaw is layered ON TOP of it so we never face the model backwards.
  private _avatarPosBase = new THREE.Vector3(0, 0, 0);
  private _avatarPosTarget = new THREE.Vector3(0, 0, 0);
  private _avatarPosRest = new THREE.Vector3(0, 0, 0);
  private _avatarRotYBase = 0;
  private _avatarRotYTarget = 0;
  private _avatarRotYRest = 0;
  private _avatarRestCaptured = false;
  private _avatarLerpRate = 1.2;   // ~800 ms glide on scene change
  // Cursor tracking intentionally disabled: letting Shugu's eyes follow the
  // viewer's mouse felt intrusive ("creepy stalker" per user feedback).
  // Look-at now defaults to camera eye-contact via the procedural layer,
  // with brief chat-glances triggered on new messages.

  constructor() {
    this.isReady = false;

    const scene = new THREE.Scene();
    this._scene = scene;

    const directionalLight = new THREE.DirectionalLight(0xffffff, 0.6);
    directionalLight.position.set(1.0, 1.0, 1.0).normalize();
    scene.add(directionalLight);

    const ambientLight = new THREE.AmbientLight(0xffffff, 0.4);
    scene.add(ambientLight);

    this._clock = new THREE.Clock();
    this._clock.start();
  }

  public async loadVrm(url: string): Promise<void> {
    if (this.model?.vrm) {
      this.unloadVRM();
    }

    // Re-capture rest transform on each (re)load so a model swap doesn't lock
    // us to a stale 180° offset.
    this._avatarRestCaptured = false;

    this.model = new Model(this._camera || new THREE.Object3D());
    await this.model.loadVRM(url);
    if (!this.model?.vrm) return;

    this.model.vrm.scene.traverse((obj) => {
      obj.frustumCulled = false;
    });

    this._scene.add(this.model.vrm.scene);

    await this.model.loadIdleAnimation(buildUrl("/idle_loop.vrma"));

    requestAnimationFrame(() => {
      this.resetCamera();
    });
  }

  public unloadVRM(): void {
    if (this.model?.vrm) {
      this._scene.remove(this.model.vrm.scene);
      this.model?.unLoadVrm();
    }
  }

  public setup(canvas: HTMLCanvasElement) {
    const parentElement = canvas.parentElement;
    const width = parentElement?.clientWidth || canvas.width;
    const height = parentElement?.clientHeight || canvas.height;

    this._renderer = new THREE.WebGLRenderer({
      canvas: canvas,
      alpha: true,
      antialias: true,
    });
    this._renderer.outputEncoding = THREE.sRGBEncoding;
    this._renderer.setSize(width, height);
    this._renderer.setPixelRatio(window.devicePixelRatio);

    // Celestial Veil framing — plan 3/4 tête→genoux. FOV 24° et Z=2.8 laissent
    // de la respiration autour du modèle pour les rails overlay gauche/droit.
    this._camera = new THREE.PerspectiveCamera(this._fovCurrent, width / height, 0.1, 20.0);
    this._camera.position.copy(this._cameraBase);

    this._cameraControls = new OrbitControls(this._camera, this._renderer.domElement);
    this._cameraControls.target.copy(this._lookAtCurrent);
    // Lock ALL interactive controls. The viewer is a streamer audience, not a 3D
    // model inspector. OrbitControls is still used purely as a lookAt helper.
    this._cameraControls.enableRotate = false;
    this._cameraControls.enableZoom = false;
    this._cameraControls.enablePan = false;
    this._cameraControls.enableDamping = false;
    this._cameraControls.update();

    window.addEventListener("resize", () => {
      this.resize();
    });

    this.isReady = true;
    this.update();
  }

  /** Fire a quick glance toward the given NDC target — used when a new chat
   *  message arrives so Shugu appears to notice it. */
  public triggerChatGlance(ndc: { x: number; y: number }): void {
    this.model?.procedural?.triggerChatGlance(ndc);
  }

  /** Request a new shot: scene manager hands us the camera pose + framing for
   *  the next scene. Values lerp over ~500ms inside `update()`. */
  public setShot(shot: { cameraBase: THREE.Vector3; lookAt: THREE.Vector3; fov: number }): void {
    this._cameraBaseTarget.copy(shot.cameraBase);
    this._lookAtTarget.copy(shot.lookAt);
    this._fovTarget = shot.fov;
  }

  /** Scene-level avatar placement (world offset + yaw). Lerps in update(). */
  public setAvatarTransform(position: THREE.Vector3, rotationY: number): void {
    this._avatarPosTarget.copy(position);
    this._avatarRotYTarget = rotationY;
  }

  public get animationManager() {
    return this.model?.animationManager;
  }

  public resize() {
    if (!this._renderer) return;

    const parentElement = this._renderer.domElement.parentElement;
    if (!parentElement) return;

    this._renderer.setPixelRatio(window.devicePixelRatio);
    this._renderer.setSize(
      parentElement.clientWidth,
      parentElement.clientHeight
    );

    if (!this._camera) return;
    this._camera.aspect =
      parentElement.clientWidth / parentElement.clientHeight;
    this._camera.updateProjectionMatrix();
  }

  public resetCamera() {
    const headNode = this.model?.vrm?.humanoid.getNormalizedBoneNode("head");

    if (headNode && this._camera) {
      const headWPos = headNode.getWorldPosition(new THREE.Vector3());
      // Centre de cadrage = tête + offset (≈ hanches). La caméra et le lookAt
      // se collent à ce Y : le plan reste stable à tête→genoux quelle que soit
      // la taille du modèle chargé.
      const centerY = headWPos.y + this._cameraHeadOffset;
      this._camera.position.set(this._cameraBase.x, centerY, this._cameraBase.z);
      this._cameraBase.y = centerY;
      this._cameraBaseTarget.y = centerY;
      this._lookAtCurrent.set(headWPos.x, centerY, headWPos.z);
      this._lookAtTarget.copy(this._lookAtCurrent);
      this._cameraControls?.target.copy(this._lookAtCurrent);
      this._cameraControls?.update();
    }
  }

  public update = () => {
    requestAnimationFrame(this.update);
    const delta = this._clock.getDelta();
    this._cinematicTime += delta;

    // Scene lerp — slide cameraBase / lookAt / FOV toward the active shot.
    const alpha = Math.min(1, delta * this._sceneLerpRate);
    this._cameraBase.lerp(this._cameraBaseTarget, alpha);
    this._lookAtCurrent.lerp(this._lookAtTarget, alpha);
    if (Math.abs(this._fovCurrent - this._fovTarget) > 0.01) {
      this._fovCurrent = THREE.MathUtils.lerp(this._fovCurrent, this._fovTarget, alpha);
      if (this._camera) {
        this._camera.fov = this._fovCurrent;
        this._camera.updateProjectionMatrix();
      }
    }
    if (this._cameraControls) {
      this._cameraControls.target.copy(this._lookAtCurrent);
    }

    // Cinematic idle camera — 5 mm amplitude on X, ~21 s period. Imperceptible
    // per-frame but kills the "dead camera" feel at the 3–5 s timescale.
    if (this._camera) {
      this._camera.position.x = this._cameraBase.x + Math.sin(this._cinematicTime * 0.3) * 0.005;
      this._camera.position.y = this._cameraBase.y + Math.sin(this._cinematicTime * 0.22) * 0.003;
      this._camera.position.z = this._cameraBase.z;
    }

    // Avatar body drift — settle toward scene target + breathing-like micro
    // sway on top so she never looks frozen to the spot.
    if (this.model?.vrm) {
      const s = this.model.vrm.scene;
      if (!this._avatarRestCaptured) {
        this._avatarPosRest.copy(s.position);
        this._avatarRotYRest = s.rotation.y;
        this._avatarRestCaptured = true;
      }
      const avatarAlpha = Math.min(1, delta * this._avatarLerpRate);
      this._avatarPosBase.lerp(this._avatarPosTarget, avatarAlpha);
      this._avatarRotYBase = THREE.MathUtils.lerp(
        this._avatarRotYBase, this._avatarRotYTarget, avatarAlpha,
      );
      const t = this._cinematicTime;
      s.position.set(
        this._avatarPosRest.x + this._avatarPosBase.x + Math.sin(t * 0.35) * 0.018,
        this._avatarPosRest.y + this._avatarPosBase.y + Math.sin(t * 0.55) * 0.006,
        this._avatarPosRest.z + this._avatarPosBase.z + Math.sin(t * 0.22) * 0.012,
      );
      s.rotation.y = this._avatarRotYRest + this._avatarRotYBase + Math.sin(t * 0.3) * 0.04;
    }

    if (this.model) {
      // No cursor tracking — procedural look-at falls back to camera eye-contact
      // plus the transient chat glance on new messages.
      this.model.update(delta, null);
    }

    if (this._renderer && this._camera) {
      this._renderer.render(this._scene, this._camera);
    }
  };
}
