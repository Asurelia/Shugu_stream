import * as THREE from "three";
import { VRM, VRMExpressionPresetName, VRMLoaderPlugin, VRMUtils } from "@pixiv/three-vrm";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader";
import { VRMLookAtSmootherLoaderPlugin } from "@/lib/VRMLookAtSmootherLoaderPlugin/VRMLookAtSmootherLoaderPlugin";
import { LipSync } from "../lipSync/lipSync";
import { EmoteController } from "../emoteController/emoteController";
import { Screenplay } from "../messages/messages";
import { ProceduralOrchestrator } from "./procedural";
import { AnimationMixerManager } from "../animations/AnimationMixerManager";

/**
 * VRM character wrapper: loads the model, drives lip-sync, expressions,
 * and the procedural animation layer (breathing / head-twitch / look-at /
 * sway / emotion-decay).
 *
 * The public `lipSyncVolume` is a getter reading the last-frame volume from
 * the internal LipSync — it's consumed by the ProceduralOrchestrator.
 */
export class Model {
  public vrm?: VRM | null;
  public animationManager?: AnimationMixerManager;
  public emoteController?: EmoteController;
  public procedural?: ProceduralOrchestrator;

  private _lookAtTargetParent: THREE.Object3D;
  private _lipSync?: LipSync;
  private _lastVolume = 0;
  private _camera: THREE.Object3D;

  private prevPlayedEmotion: string | null = null;

  constructor(lookAtTargetParent: THREE.Object3D) {
    this._lookAtTargetParent = lookAtTargetParent;
    this._camera = lookAtTargetParent;
    this._lipSync = new LipSync(new AudioContext());
  }

  public get lipSyncVolume(): number {
    return this._lastVolume;
  }

  public async loadVRM(url: string): Promise<void> {
    const loader = new GLTFLoader();
    loader.register(
      (parser) =>
        new VRMLoaderPlugin(parser, {
          lookAtPlugin: new VRMLookAtSmootherLoaderPlugin(parser),
        })
    );

    const gltf = await loader.loadAsync(url);

    const vrm = (this.vrm = gltf.userData.vrm);
    vrm.scene.name = "VRMRoot";

    VRMUtils.rotateVRM0(vrm);
    this.animationManager = new AnimationMixerManager(vrm);

    this.emoteController = new EmoteController(vrm, this._lookAtTargetParent);

    // Attach the procedural layer after the VRM is fully loaded. The camera
    // lives in the lookAtTargetParent (Viewer passes its camera in).
    this.procedural = new ProceduralOrchestrator();
    if (this._camera instanceof THREE.Camera) {
      this.procedural.attach(vrm, this._camera);
    }
  }

  public unLoadVrm() {
    if (this.vrm) {
      VRMUtils.deepDispose(this.vrm.scene);
      this.vrm = null;
    }
    this.animationManager?.dispose();
    this.animationManager = undefined;
  }

  public async loadIdleAnimation(url: string): Promise<void> {
    if (!this.animationManager) return;
    await this.animationManager.setIdle(url, 0);
  }

  public async speak(buffer: ArrayBuffer | null, screenplay: Screenplay) {
    if (this.prevPlayedEmotion !== screenplay.expression) {
      this.emoteController?.playEmotion(screenplay.expression);
      this.procedural?.triggerEmotion(screenplay.expression as VRMExpressionPresetName);
      this.prevPlayedEmotion = screenplay.expression;
    }

    if (!buffer) return;

    await new Promise((resolve) => {
      this._lipSync?.playFromArrayBuffer(buffer, () => {
        resolve(true);
      });
    });
  }

  /** Streaming variant of `speak`: the audio is already being decoded by the
   *  browser (MSE). We just set the emotion and wire the media element into
   *  the lip-sync analyser so per-frame volume still drives the mouth. */
  public startStreamingSpeak(audio: HTMLAudioElement, screenplay: Screenplay) {
    if (this.prevPlayedEmotion !== screenplay.expression) {
      this.emoteController?.playEmotion(screenplay.expression);
      this.procedural?.triggerEmotion(screenplay.expression as VRMExpressionPresetName);
      this.prevPlayedEmotion = screenplay.expression;
    }
    this._lipSync?.attachMediaElement(audio);
  }

  /**
   * Per-frame update. Called from Viewer.update() with the frame delta AND
   * the viewer-captured cursor NDC (used by the look-at manager).
   */
  public update(delta: number, cursorNDC?: { x: number; y: number } | null): void {
    if (this._lipSync) {
      const { volume } = this._lipSync.update();
      this._lastVolume = volume;

      const expression = this.vrm?.expressionManager?.getExpression("JawOpen");
      if (expression) {
        // @ts-ignore — Perfect Sync standard
        this.emoteController?.lipSync("JawOpen", volume);
      } else {
        this.emoteController?.lipSync("aa", volume);
      }
    }

    this.emoteController?.update(delta);
    this.animationManager?.update(delta);

    // Procedural layers run AFTER the mixer so their offsets are additive and
    // non-destructive to the idle_loop.vrma pose.
    if (this.procedural && this.vrm && this._camera instanceof THREE.Camera) {
      this.procedural.update(delta, {
        lipSyncVolume: this._lastVolume,
        cursorNDC: cursorNDC ?? null,
        camera: this._camera,
      });
    }

    this.vrm?.update(delta);
  }
}
