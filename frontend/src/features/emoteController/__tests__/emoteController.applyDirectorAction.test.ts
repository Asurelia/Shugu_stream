/**
 * Tests — `EmoteController.applyDirectorAction` (Sprint D PR D-7).
 *
 * `applyDirectorAction` est la nouvelle méthode publique qui consomme la sortie
 * du `sceneApplyMapper` (PR D-7). Elle dispatch sur le type d'action :
 *
 *   - `playEmotion`  → délègue à `expressionController.playEmotion(preset)`
 *   - `playAnim`     → log warn pour MVP (intégration AnimationMixerManager → D-8)
 *   - `triggerVfx`   → log warn pour MVP (VFXLayer → D-8/D-9)
 *   - `noop`         → log debug avec reason
 *
 * On ne mock PAS le VRM ici — on instancie un EmoteController avec un faux
 * VRM minimal (juste `expressionManager.setValue` mockable). Pattern : on
 * pose un spy sur `EmoteController.playEmotion` (qui est l'API publique
 * existante) puis on vérifie qu'`applyDirectorAction({type:"playEmotion"})`
 * y délègue. Pour `playAnim`/`triggerVfx`/`noop`, on vérifie les logs
 * (`console.warn` / `console.debug`) sans toucher au VRM.
 */

import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";
import * as THREE from "three";
import { VRMExpressionPresetName } from "@pixiv/three-vrm";
import { EmoteController } from "../emoteController";

/**
 * Construit un VRM minimal compatible avec EmoteController :
 *  - `expressionManager.setValue` mockable
 *  - un objet 3D pour `vrm.scene` n'est pas requis ici (on n'appelle pas
 *    update())
 *
 * On bypasse le typage strict via cast — c'est un test, pas du code prod.
 */
function makeFakeVrm(): {
  vrm: ConstructorParameters<typeof EmoteController>[0];
  setValue: ReturnType<typeof vi.fn>;
} {
  const setValue = vi.fn();
  const vrm = {
    expressionManager: {
      setValue,
      getExpression: vi.fn(),
      expressions: [],
    },
    // EmoteController instancie ExpressionController qui instancie AutoLookAt
    // — ce dernier accède à `vrm.lookAt` (peut être undefined sans crash).
    lookAt: undefined,
    // ExpressionController crée AutoBlink seulement si expressionManager existe
    // — déjà couvert ci-dessus.
  } as unknown as ConstructorParameters<typeof EmoteController>[0];
  return { vrm, setValue };
}

describe("EmoteController.applyDirectorAction", () => {
  let camera: THREE.Object3D;

  beforeEach(() => {
    camera = new THREE.Object3D();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("playEmotion action → délègue à expressionController.playEmotion", () => {
    const { vrm } = makeFakeVrm();
    const controller = new EmoteController(vrm, camera);
    const playEmotionSpy = vi.spyOn(controller, "playEmotion");

    controller.applyDirectorAction({
      type: "playEmotion",
      preset: VRMExpressionPresetName.Happy,
    });

    expect(playEmotionSpy).toHaveBeenCalledTimes(1);
    expect(playEmotionSpy).toHaveBeenCalledWith(
      VRMExpressionPresetName.Happy,
    );
  });

  it("playEmotion(Sad) → délègue avec le preset Sad", () => {
    const { vrm } = makeFakeVrm();
    const controller = new EmoteController(vrm, camera);
    const playEmotionSpy = vi.spyOn(controller, "playEmotion");

    controller.applyDirectorAction({
      type: "playEmotion",
      preset: VRMExpressionPresetName.Sad,
    });

    expect(playEmotionSpy).toHaveBeenCalledWith(VRMExpressionPresetName.Sad);
  });

  it("playAnim action → log warn (stub MVP, intégration D-8)", () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const { vrm } = makeFakeVrm();
    const controller = new EmoteController(vrm, camera);

    controller.applyDirectorAction({ type: "playAnim", clipName: "wave" });

    expect(warnSpy).toHaveBeenCalledTimes(1);
    expect(warnSpy.mock.calls[0]?.join(" ")).toMatch(/wave/);
    expect(warnSpy.mock.calls[0]?.join(" ")).toMatch(/D-8|anim/);
    warnSpy.mockRestore();
  });

  it("triggerVfx action → log warn (stub MVP, intégration D-8/D-9)", () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const { vrm } = makeFakeVrm();
    const controller = new EmoteController(vrm, camera);

    controller.applyDirectorAction({
      type: "triggerVfx",
      slug: "sparkle",
    });

    expect(warnSpy).toHaveBeenCalledTimes(1);
    expect(warnSpy.mock.calls[0]?.join(" ")).toMatch(/sparkle/);
    warnSpy.mockRestore();
  });

  it("noop action → log debug avec la reason fournie", () => {
    const debugSpy = vi.spyOn(console, "debug").mockImplementation(() => {});
    const { vrm } = makeFakeVrm();
    const controller = new EmoteController(vrm, camera);

    controller.applyDirectorAction({
      type: "noop",
      reason: "kind camera not yet handled",
    });

    expect(debugSpy).toHaveBeenCalledTimes(1);
    expect(debugSpy.mock.calls[0]?.join(" ")).toMatch(/camera/);
    debugSpy.mockRestore();
  });

  it("API existante (playEmotion direct) reste intacte", () => {
    // Sanity check : on ne casse pas le cas d'usage actuel
    // (Model.speak() appelle directement `emoteController.playEmotion()`).
    const { vrm, setValue } = makeFakeVrm();
    const controller = new EmoteController(vrm, camera);

    controller.playEmotion(VRMExpressionPresetName.Surprised);
    // L'expressionController applique la valeur après un setTimeout(0)
    // (animation autoBlink). On ne valide donc que l'absence d'erreur.
    expect(controller).toBeDefined();
    // setValue est appelé pour resetter l'émotion précédente (neutral → 0
    // n'est pas appelé car `_currentEmotion === "neutral"` au start).
    expect(setValue).not.toHaveBeenCalled(); // au sync : queue setTimeout
  });
});
