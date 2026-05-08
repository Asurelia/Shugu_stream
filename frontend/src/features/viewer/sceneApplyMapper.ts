/**
 * sceneApplyMapper — mapping pur kind+id → ViewerAction (Sprint D PR D-7).
 *
 * Convertit un payload `scene.apply` reçu sur `/ws/viewer/events` en
 * `ViewerAction` consommable par `EmoteController.applyDirectorAction`.
 *
 * Pourquoi un module à part plutôt qu'inline dans `EmoteController` ?
 *  - Découplage backend (kind/id sémantique) et moteur de rendu (preset VRM,
 *    nom de clip, slug VFX). Si on change de moteur d'avatar, le backend
 *    reste inchangé (cf spec §2.2).
 *  - Tests purs sans VRM : le mapping est une pure fonction
 *    `(payload) → action`, idéal pour validation TDD exhaustive.
 *
 * Tables de mapping :
 *  - `SAY_EMOTION_TO_VRM_PRESET` : aligné sur backend `SAY_EMOTION_WHITELIST`
 *    (`backend/shugu/director/workers/say.py:30-37`).
 *  - `FACE_TO_VRM_PRESET`        : aligné sur backend `FACE_WHITELIST`
 *    (`backend/shugu/director/workers/face.py:26-33`). Identique au mapping
 *    say_emotion par contrat (cf spec §3.2 et commentaires backend).
 *
 * Décision de design — `thinking → Neutral` :
 *  VRM 1.0 (`@pixiv/three-vrm`) ne définit pas de preset "Thinking" dans
 *  `VRMExpressionPresetName`. Le set valide est :
 *    Aa, Ih, Ou, Ee, Oh, Blink, Happy, Angry, Sad, Relaxed, LookUp,
 *    Surprised, LookDown, LookLeft, LookRight, BlinkLeft, BlinkRight,
 *    Neutral.
 *  On fallback `thinking → Neutral` plutôt que `Relaxed` car la spec D-7
 *  documentait ce choix explicitement. Si l'expérience subjective est
 *  insuffisante, D-8 pourra introduire un preset custom blendshape.
 *
 * Référence spec : docs/specs/2026-05-08-voice-body-pipeline-design.md §3.2.
 */

import { VRMExpressionPresetName } from "@pixiv/three-vrm";
import type { ViewerSceneApply } from "./ViewerEventsClient";

/**
 * Table de mapping `say_emotion:<id>` → preset VRM.
 *
 * Les clés DOIVENT couvrir l'intégralité de `SAY_EMOTION_WHITELIST` côté
 * backend. Si un id n'est pas listé ici, `mapSceneApply` retourne `noop`.
 *
 * IMPORTANT : si la whitelist backend évolue (ajout d'une émotion par
 * Sprint E ou ultérieur), il FAUT mettre à jour cette table en parallèle.
 * Pas de mécanisme de reload à chaud — un test du mapper sans cette
 * mise à jour produit un noop silencieux.
 */
export const SAY_EMOTION_TO_VRM_PRESET: Readonly<
  Record<string, VRMExpressionPresetName>
> = Object.freeze({
  neutral: VRMExpressionPresetName.Neutral,
  joy: VRMExpressionPresetName.Happy,
  surprised: VRMExpressionPresetName.Surprised,
  sad: VRMExpressionPresetName.Sad,
  angry: VRMExpressionPresetName.Angry,
  // VRM 1.0 n'a pas de preset Thinking → fallback documenté Neutral.
  thinking: VRMExpressionPresetName.Neutral,
});

/**
 * Table de mapping `face:<id>` → preset VRM.
 *
 * Identique à `SAY_EMOTION_TO_VRM_PRESET` car les deux whitelists backend
 * sont contractuellement alignées (cf spec §3.2 + commentaires de
 * `backend/shugu/director/workers/say.py:27-29`). Si l'une diverge dans
 * le futur, dupliquer le contenu plutôt que de garder le spread.
 */
export const FACE_TO_VRM_PRESET: Readonly<
  Record<string, VRMExpressionPresetName>
> = Object.freeze({ ...SAY_EMOTION_TO_VRM_PRESET });

/**
 * Action retournée par le mapper. Discriminée par `type` pour faciliter
 * le dispatch dans `EmoteController.applyDirectorAction`.
 */
export type ViewerAction =
  | { type: "playEmotion"; preset: VRMExpressionPresetName }
  | { type: "playAnim"; clipName: string }
  | { type: "triggerVfx"; slug: string }
  | { type: "noop"; reason: string };

/**
 * Convertit un event `scene.apply` validé en `ViewerAction`.
 *
 * Cette fonction est PURE : pas d'effets de bord (logging fait par le caller).
 * Elle ne valide PAS le payload — c'est la responsabilité de
 * `ViewerEventsClient.parseAndDispatch` (Zod en amont).
 *
 * @param event payload `scene.apply` typé statiquement par TS.
 * @returns une `ViewerAction` (jamais null — `noop` est le fallback).
 */
export function mapSceneApply(event: ViewerSceneApply): ViewerAction {
  switch (event.kind) {
    case "say_emotion": {
      const preset = SAY_EMOTION_TO_VRM_PRESET[event.id];
      if (!preset) {
        return {
          type: "noop",
          reason: `unknown say_emotion id: ${event.id}`,
        };
      }
      return { type: "playEmotion", preset };
    }
    case "face": {
      const preset = FACE_TO_VRM_PRESET[event.id];
      if (!preset) {
        return {
          type: "noop",
          reason: `unknown face id: ${event.id}`,
        };
      }
      return { type: "playEmotion", preset };
    }
    case "anim":
      // Pas de whitelist côté frontend : `AnimationMixerManager` (D-8) sera
      // source de vérité sur les clips disponibles côté VRM. Le clipName brut
      // est forwarded tel quel.
      return { type: "playAnim", clipName: event.id };
    case "vfx":
      // Idem : `VFXLayer` (D-8/D-9) gérera les slugs disponibles. Pas de
      // whitelist côté mapper.
      return { type: "triggerVfx", slug: event.id };
    case "camera":
      // Out of MVP scope D-7 — log only via le caller.
      return {
        type: "noop",
        reason: `kind camera not yet handled (out of D-7 scope)`,
      };
    case "outfit":
      return {
        type: "noop",
        reason: `kind outfit not yet handled (out of D-7 scope)`,
      };
    default: {
      // Forward-compat : si le backend introduit un nouveau kind avant que le
      // frontend soit mis à jour, on ne crash pas — juste un noop loggué.
      // La narrow TS atteint `never` ici, on cast pour exfiltrer le kind brut
      // dans le message de debug.
      const unknownKind = (event as { kind?: string }).kind ?? "(missing)";
      return {
        type: "noop",
        reason: `unknown kind: ${unknownKind}`,
      };
    }
  }
}
