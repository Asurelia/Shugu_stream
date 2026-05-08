import * as THREE from "three";
import { VRM, VRMExpressionPresetName } from "@pixiv/three-vrm";
import { ExpressionController } from "./expressionController";
import type { ViewerAction } from "../viewer/sceneApplyMapper";

/**
 * 感情表現としてExpressionとMotionを操作する為のクラス
 * デモにはExpressionのみが含まれています
 *
 * Sprint D PR D-7 : étendu avec `applyDirectorAction` qui consomme la sortie
 * du `sceneApplyMapper` pour driver l'avatar depuis les events Director
 * `scene.apply` (cf spec §3.2). L'API existante (`playEmotion`, `lipSync`,
 * `update`) reste 100% compatible avec les call-sites historiques de
 * `Model.speak` / `Model.startStreamingSpeak`.
 */
export class EmoteController {
  private _expressionController: ExpressionController;

  constructor(vrm: VRM, camera: THREE.Object3D) {
    this._expressionController = new ExpressionController(vrm, camera);
  }

  public playEmotion(preset: VRMExpressionPresetName) {
    this._expressionController.playEmotion(preset);
  }

  public lipSync(preset: VRMExpressionPresetName, value: number) {
    this._expressionController.lipSync(preset, value);
  }

  public update(delta: number) {
    this._expressionController.update(delta);
  }

  /**
   * Consomme la sortie de `sceneApplyMapper.mapSceneApply` pour appliquer
   * l'action correspondante côté avatar.
   *
   * Dispatch :
   *  - `playEmotion` → délègue à `playEmotion(preset)` (API existante).
   *  - `playAnim`    → log warn pour MVP D-7. L'intégration réelle avec
   *    `AnimationMixerManager` arrivera en D-8 (cf spec §3.2).
   *  - `triggerVfx`  → log warn pour MVP. L'intégration `VFXLayer` arrivera
   *    en D-8/D-9.
   *  - `noop`        → log debug avec la `reason` pour faciliter le debug
   *    de tags inconnus / kinds out-of-scope.
   *
   * @param action `ViewerAction` produite par `mapSceneApply`.
   */
  public applyDirectorAction(action: ViewerAction): void {
    switch (action.type) {
      case "playEmotion":
        this.playEmotion(action.preset);
        return;
      case "playAnim":
        // Stub MVP D-7. AnimationMixerManager (frontend/src/features/animations)
        // sera câblé en D-8 quand le mapping clipName ↔ clip réel sera défini.
        console.warn(
          `[emoteController] playAnim action received with clipName="${action.clipName}" — not yet wired (D-8).`,
        );
        return;
      case "triggerVfx":
        // Stub MVP D-7. VFXLayer (cf spec §3.2 ligne 132) arrivera en D-8/D-9.
        console.warn(
          `[emoteController] triggerVfx action received with slug="${action.slug}" — not yet wired (D-8/D-9).`,
        );
        return;
      case "noop":
        // Cas attendu : kind out-of-scope (camera/outfit) ou id hors whitelist.
        // Pas un warn — c'est un comportement nominal, on log à debug pour
        // permettre le diagnostic sans polluer les consoles utilisateurs.
        console.debug(`[emoteController] noop action: ${action.reason}`);
        return;
      default: {
        // Sécurité : si `ViewerAction` évolue dans le futur sans qu'`emoteController`
        // soit mis à jour, TS narrow vers `never` ici. On force un cast pour
        // exfiltrer le `type` brut dans le warn de debug.
        const exhaustive: never = action;
        console.warn(
          "[emoteController] unhandled ViewerAction type:",
          (exhaustive as { type?: string }).type,
        );
      }
    }
  }
}
