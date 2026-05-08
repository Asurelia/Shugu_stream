import * as THREE from "three";
import { VRM, VRMExpressionPresetName, VRMLoaderPlugin, VRMUtils } from "@pixiv/three-vrm";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
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

  /**
   * GainNode inséré entre la source MediaElement et la destination AudioContext
   * pour le streaming audio (D-6 + D-9). Permet le fade-out barge-in
   * (`fadeOutAndStopStreamingAudio`) via `linearRampToValueAtTime` sample-accurate.
   * Null tant qu'aucun audio n'a été attaché — créé à la demande dans
   * `attachStreamingAudio` (D-9).
   */
  private _streamingGain: GainNode | null = null;
  /**
   * Référence vers le HTMLAudioElement courant (pour pause() après fade).
   * Mis à jour à chaque `attachStreamingAudio`. Réinitialisé à null par le
   * fade-out une fois le pause appliqué.
   */
  private _streamingAudio: HTMLAudioElement | null = null;
  /**
   * Timer du `setTimeout` qui appelle `audio.pause()` après le ramp. Stocké
   * pour permettre l'annulation propre si `attachStreamingAudio` est rappelé
   * pendant un fade en cours (ex : LiveKit reconnect).
   */
  private _fadeStopTimer: ReturnType<typeof setTimeout> | null = null;

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
   * Branche un HTMLAudioElement (typiquement issu de LiveKit
   * `RemoteAudioTrack.attach()`) sur l'analyser lipSync, sans toucher à
   * l'expression faciale.
   *
   * Sprint D PR D-6 : la voix TTS arrive en streaming via WebRTC LiveKit.
   * Le mapping émotion ↔ phrase est géré séparément par `sceneApplyMapper`
   * + `emoteController.applyDirectorAction` (PR D-7), donc cette méthode
   * NE déclenche PAS `playEmotion` (contrairement à `startStreamingSpeak`).
   * Seule la lecture audio + lipSync est branchée.
   *
   * Sprint D PR D-9 : insère un GainNode entre la source MediaElement et la
   * destination AudioContext pour permettre le fade-out barge-in. Le graph
   * audio devient :
   *
   *   `MediaElementSource` → `analyser` (lipSync, lecture seule)
   *   `MediaElementSource` → `GainNode` → `destination` (sortie audible)
   *
   * Le GainNode est singleton par Model (une session = un VRM = une voix
   * Shugu). Si une nouvelle audio track arrive (LiveKit reconnect), on
   * réutilise le même GainNode et on le reset à 1 pour rendre le nouveau
   * flux audible. Le timer de pause armé par un fade précédent est aussi
   * annulé (sinon il pause-erait le NOUVEAU flux).
   */
  public attachStreamingAudio(audio: HTMLAudioElement): void {
    if (!this._lipSync) return;

    // Cancel un fade en cours : le caller veut écouter ce nouveau flux.
    if (this._fadeStopTimer !== null) {
      clearTimeout(this._fadeStopTimer);
      this._fadeStopTimer = null;
    }

    // 1. Le pattern existant lipSync attache source → analyser ET source →
    //    destination. On le laisse faire son taff lipSync (analyser).
    this._lipSync.attachMediaElement(audio);

    // 2. Récupère le source node créé par lipSync (caché sur l'élément
    //    via `__lipsyncSource`, cf lipSync.ts:65). Si absent, on n'a rien
    //    à modifier (cas dégénéré ; le test vérifie l'attach normal).
    const anyAudio = audio as HTMLAudioElement & {
      __lipsyncSource?: MediaElementAudioSourceNode;
    };
    const source = anyAudio.__lipsyncSource;
    const ctx = this._lipSync.audio;

    if (!source) {
      // lipSync n'a pas réussi à créer le source (browser/jsdom sans
      // createMediaElementSource fonctionnel) — on tracke l'audio quand
      // même pour pouvoir le pause au fade.
      this._streamingAudio = audio;
      return;
    }

    // 3. Crée le GainNode si pas déjà fait, sinon réutilise + reset à 1.
    //    `setValueAtTime(1, currentTime)` cancel un ramp précédent ET pose
    //    la nouvelle valeur stable, sans glitch audio.
    if (!this._streamingGain) {
      this._streamingGain = ctx.createGain();
      this._streamingGain.connect(ctx.destination);
    } else {
      this._streamingGain.gain.cancelScheduledValues(ctx.currentTime);
      this._streamingGain.gain.setValueAtTime(1, ctx.currentTime);
    }

    // 4. Re-route source : on disconnect le path direct → destination
    //    (créé par lipSync.attachMediaElement), puis on connect via le gain.
    //    `disconnect(node)` cible spécifiquement la connexion vers `node` ;
    //    si elle n'existe pas, on ignore (idempotent : 2e attach du même
    //    audio passe par le early-return de lipSync, pas ici).
    try {
      source.disconnect(ctx.destination);
    } catch {
      // Pas de connexion directe (ex : elem déjà géré au tour précédent) —
      // safe à ignorer.
    }
    try {
      source.connect(this._streamingGain);
    } catch {
      // connect() peut throw si déjà connecté à ce gain (rare mais possible
      // sur reconnect avec même element) — on ignore, le graph reste cohérent.
    }

    this._streamingAudio = audio;
  }

  /**
   * Fade-out l'audio streaming en cours sur `durationMs` puis pause l'élément
   * audio. Pattern §6.2 spec : `gainNode.gain.linearRampToValueAtTime(0,
   * ctx.currentTime + durationMs/1000)` — précision sample-accurate (Web
   * Audio scheduler), pas de jank JS.
   *
   * Comportement :
   *  - Si jamais d'audio attaché : no-op (resolve immédiatement).
   *  - Sinon : ramp à 0 sur `durationMs`, puis `audio.pause()` après un
   *    safety margin de +10ms (assure que le ramp est terminé avant pause).
   *  - Idempotent : 2e appel cancel le ramp en cours et re-arme un nouveau
   *    fade depuis la valeur actuelle (évite click / restart depuis 1.0).
   *  - Cancellable : un `attachStreamingAudio` ultérieur clear le timer de
   *    pause (le nouveau flux ne doit pas être pause-é par le fade précédent).
   *
   * @param durationMs Durée du ramp en ms. Default 50ms (cible spec §7.2).
   * @returns Promise qui resolve dès le ramp armé (PAS à la fin du fade) —
   *          le pause() est asynchrone via setTimeout pour ne pas bloquer.
   */
  public async fadeOutAndStopStreamingAudio(
    durationMs: number = 50,
  ): Promise<void> {
    if (!this._lipSync || !this._streamingAudio) {
      // No-audio path : no-op silencieux (cf bargeInHandler test).
      return;
    }
    const ctx = this._lipSync.audio;

    // Si on a un GainNode (graph WebAudio normal), on ramp via Web Audio.
    if (this._streamingGain) {
      const gain = this._streamingGain.gain;
      // Cancel ramp précédent + ancrer la valeur courante avant le nouveau
      // ramp. Sans ça, un 2e fade rapproché re-rampe depuis 1.0 → glitch.
      gain.cancelScheduledValues(ctx.currentTime);
      gain.setValueAtTime(gain.value, ctx.currentTime);
      gain.linearRampToValueAtTime(0, ctx.currentTime + durationMs / 1000);
    }
    // Sinon (cas dégénéré sans WebAudio) : skip le ramp, fallback pause sec.

    // Pause après le ramp + 10ms de marge. On stocke le timer pour pouvoir
    // l'annuler depuis attachStreamingAudio si un nouveau flux arrive.
    if (this._fadeStopTimer !== null) {
      clearTimeout(this._fadeStopTimer);
    }
    const audioRef = this._streamingAudio;
    this._fadeStopTimer = setTimeout(() => {
      this._fadeStopTimer = null;
      try {
        audioRef.pause();
      } catch {
        // pause() peut throw si l'élément est déjà détaché du DOM — safe.
      }
      // Review D-9 fix : null la ref pour matcher la JSDoc + libère le pointeur
      // si une 2e fadeOut est déclenchée (le double-pause sur élément déjà
      // pausé est benign mais le contrat documenté reste cohérent).
      if (this._streamingAudio === audioRef) {
        this._streamingAudio = null;
      }
    }, durationMs + 10);
  }

  /**
   * Retourne l'AudioContext interne du lipSync (pour gérer la policy autoplay
   * du browser : `audioContext.resume()` après un user-gesture). Undefined si
   * le LipSync n'est pas encore initialisé.
   *
   * Cas d'usage principal : LiveKitProvider expose un overlay "click to start"
   * quand `audioContext.state === "suspended"` après attach. Le click déclenche
   * `audioContext.resume()` sur CETTE instance — on ne crée jamais de second
   * AudioContext côté Provider, sinon les deux graphs deviennent désynchronisés.
   */
  public get audioContext(): AudioContext | undefined {
    return this._lipSync?.audio;
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
