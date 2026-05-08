/**
 * Tests — `sceneApplyMapper` (Sprint D PR D-7).
 *
 * Le mapper transforme un payload `scene.apply` reçu via WS `/ws/viewer/events`
 * en `ViewerAction` consommable par `emoteController.applyDirectorAction`.
 *
 * Contrats validés ici :
 *   - say_emotion / face → `playEmotion(preset VRM)` selon la table de mapping
 *     alignée sur les whitelists backend (SAY_EMOTION_WHITELIST + FACE_WHITELIST).
 *   - anim / vfx → action correspondante avec l'`id` brut (pas de validation
 *     côté frontend, le backend reste source de vérité — voir spec §6.1).
 *   - camera / outfit → noop (out of scope D-7, log uniquement).
 *   - id inconnu (ex: `say_emotion:thinking_does_not_exist`) → noop avec reason.
 *   - kind inconnu → noop avec reason.
 *
 * Pourquoi pas de validation Zod dans le mapper ? La validation est faite en
 * AMONT (`ViewerEventsClient.parseAndDispatch`). Le mapper reçoit un objet
 * déjà typé statiquement par TS — sa seule responsabilité est de mapper
 * kind+id → action.
 *
 * Référence spec : docs/specs/2026-05-08-voice-body-pipeline-design.md §3.2.
 */

import { describe, expect, it } from "vitest";
import { VRMExpressionPresetName } from "@pixiv/three-vrm";
import {
  FACE_TO_VRM_PRESET,
  mapSceneApply,
  SAY_EMOTION_TO_VRM_PRESET,
} from "../sceneApplyMapper";
import type { ViewerSceneApply } from "../ViewerEventsClient";

function makeSceneApply(
  kind: ViewerSceneApply["kind"],
  id: string,
  extras: Partial<ViewerSceneApply> = {},
): ViewerSceneApply {
  return {
    type: "scene.apply",
    kind,
    id,
    ts: "2026-05-08T14:23:11.456Z",
    ...extras,
  };
}

describe("sceneApplyMapper — tables de mapping", () => {
  it("SAY_EMOTION_TO_VRM_PRESET couvre la whitelist backend SAY_EMOTION_WHITELIST", () => {
    // Whitelist backend (backend/shugu/director/workers/say.py:30-37) :
    //   { neutral, joy, surprised, sad, angry, thinking }
    expect(SAY_EMOTION_TO_VRM_PRESET).toMatchObject({
      neutral: VRMExpressionPresetName.Neutral,
      joy: VRMExpressionPresetName.Happy,
      surprised: VRMExpressionPresetName.Surprised,
      sad: VRMExpressionPresetName.Sad,
      angry: VRMExpressionPresetName.Angry,
    });
    // VRM 1.0 n'a pas de preset "Thinking" → fallback Neutral.
    expect(SAY_EMOTION_TO_VRM_PRESET.thinking).toBe(
      VRMExpressionPresetName.Neutral,
    );
  });

  it("FACE_TO_VRM_PRESET est aligné sur SAY_EMOTION_TO_VRM_PRESET", () => {
    // Spec §3.2 : `[say_emotion:joy]` et `[face:joy]` doivent avoir le même set.
    // (cf face.py:26 / say.py:30 — whitelists identiques côté backend.)
    expect(FACE_TO_VRM_PRESET).toEqual(SAY_EMOTION_TO_VRM_PRESET);
  });
});

describe("sceneApplyMapper.mapSceneApply", () => {
  it("say_emotion:joy → playEmotion(Happy)", () => {
    const action = mapSceneApply(makeSceneApply("say_emotion", "joy"));
    expect(action).toEqual({
      type: "playEmotion",
      preset: VRMExpressionPresetName.Happy,
    });
  });

  it("say_emotion:sad → playEmotion(Sad)", () => {
    const action = mapSceneApply(makeSceneApply("say_emotion", "sad"));
    expect(action).toEqual({
      type: "playEmotion",
      preset: VRMExpressionPresetName.Sad,
    });
  });

  it("say_emotion:thinking → playEmotion(Neutral) (fallback documenté)", () => {
    const action = mapSceneApply(makeSceneApply("say_emotion", "thinking"));
    expect(action).toEqual({
      type: "playEmotion",
      preset: VRMExpressionPresetName.Neutral,
    });
  });

  it("face:joy → playEmotion(Happy)", () => {
    const action = mapSceneApply(makeSceneApply("face", "joy"));
    expect(action).toEqual({
      type: "playEmotion",
      preset: VRMExpressionPresetName.Happy,
    });
  });

  it("face:angry → playEmotion(Angry)", () => {
    const action = mapSceneApply(makeSceneApply("face", "angry"));
    expect(action).toEqual({
      type: "playEmotion",
      preset: VRMExpressionPresetName.Angry,
    });
  });

  it("anim:wave → playAnim(wave)", () => {
    const action = mapSceneApply(makeSceneApply("anim", "wave"));
    expect(action).toEqual({ type: "playAnim", clipName: "wave" });
  });

  it("vfx:sparkle → triggerVfx(sparkle)", () => {
    const action = mapSceneApply(makeSceneApply("vfx", "sparkle"));
    expect(action).toEqual({ type: "triggerVfx", slug: "sparkle" });
  });

  it("camera:orbit → noop avec reason explicite (out of scope D-7)", () => {
    const action = mapSceneApply(makeSceneApply("camera", "orbit"));
    expect(action.type).toBe("noop");
    if (action.type === "noop") {
      expect(action.reason).toMatch(/camera/);
    }
  });

  it("outfit:formal → noop avec reason explicite (out of scope D-7)", () => {
    const action = mapSceneApply(makeSceneApply("outfit", "formal"));
    expect(action.type).toBe("noop");
    if (action.type === "noop") {
      expect(action.reason).toMatch(/outfit/);
    }
  });

  it("say_emotion:unknown_id → noop avec reason mentionnant l'id", () => {
    const action = mapSceneApply(makeSceneApply("say_emotion", "ecstatic"));
    expect(action.type).toBe("noop");
    if (action.type === "noop") {
      expect(action.reason).toMatch(/ecstatic/);
    }
  });

  it("face:unknown_id → noop avec reason mentionnant l'id", () => {
    const action = mapSceneApply(makeSceneApply("face", "rainbow"));
    expect(action.type).toBe("noop");
    if (action.type === "noop") {
      expect(action.reason).toMatch(/rainbow/);
    }
  });

  it("kind inconnu → noop avec reason (forward-compat)", () => {
    // On simule un nouveau kind backend (ex: futur D-XX) qui arriverait avant
    // que le frontend soit mis à jour. Comportement attendu : pas de crash,
    // noop avec reason explicite pour faciliter le debug.
    const action = mapSceneApply({
      type: "scene.apply",
      kind: "future_kind" as never,
      id: "anything",
      ts: "2026-05-08T14:23:11.456Z",
    });
    expect(action.type).toBe("noop");
    if (action.type === "noop") {
      expect(action.reason).toMatch(/future_kind/);
    }
  });

  it("anim avec id contenant des caractères spéciaux passe-through (no whitelist côté frontend)", () => {
    // Rationale : pour `anim`/`vfx`, le backend est source de vérité — pas de
    // re-validation côté frontend. AnimationMixerManager (D-8) fera le mapping
    // clipName → clip réel, et logguera si le clip n'existe pas.
    const action = mapSceneApply(makeSceneApply("anim", "wave_left.fbx"));
    expect(action).toEqual({ type: "playAnim", clipName: "wave_left.fbx" });
  });
});
