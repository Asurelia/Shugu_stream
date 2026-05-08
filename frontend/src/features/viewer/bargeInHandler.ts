/**
 * bargeInHandler — orchestration côté frontend du flow barge-in §5.2
 * (Sprint D PR D-9, voice-body pipeline).
 *
 * Quand un event `voice.interrupt` arrive sur `/ws/viewer/events` (publié
 * par le backend D-3 sur déclenchement de D-4 v3 `cancel_speaking`), ce
 * handler exécute les 3 étapes spec §5.2 (t=1.45s → t=1.50s) :
 *
 *   1. **Audio fade-out 50ms** via `viewer.model.fadeOutAndStopStreamingAudio()`
 *      (insertion d'un GainNode dans le graph WebAudio + linearRampToValueAtTime
 *      sample-accurate, cf §6.2 ligne 244 spec).
 *   2. **Reset expression** à `VRMExpressionPresetName.Neutral` via
 *      `emoteController.applyDirectorAction({type: "playEmotion", preset: Neutral})`.
 *      Évite de rester sur l'émotion de la phrase coupée (joy/angry/etc.).
 *   3. **Flush du scheduler** (`SceneSchedulerLike.flush()`) — drop tous les
 *      events scéniques pending pour éviter qu'une expression schedulée AVANT
 *      l'interrupt soit appliquée APRÈS, créant un effet de "rebond" hors
 *      contexte.
 *
 * Architecture — pourquoi un module pur plutôt qu'un Provider React :
 *  - Le wiring `ViewerEventsClient → onInterrupt` n'existe pas encore ; D-8
 *    introduira un Provider qui mutualisera le client WS + le `sceneScheduler`.
 *    En exposant un factory `(viewer, scheduler) → handler`, D-9 reste neutre
 *    sur le lifecycle React et D-8 plug le tout sans refactor.
 *  - Tests purs : pas besoin de monter Three.js + jsdom WebAudio. Le handler
 *    est une fonction callable avec des fakes minimaux.
 *
 * Référence spec : docs/specs/2026-05-08-voice-body-pipeline-design.md §5.2 + §6.2 + §7.2.
 */

import { VRMExpressionPresetName } from "@pixiv/three-vrm";
import type { Viewer } from "@/features/vrmViewer/viewer";
import type { ViewerInterrupt } from "./ViewerEventsClient";

/**
 * Interface minimale du `sceneScheduler` consommée par le handler.
 *
 * D-8 implémentera `sceneScheduler.flush()` qui annule tous les `setTimeout`
 * armés pour des events `scene.apply` schedulés via `audio_at_ms`. Ici on
 * type uniquement le contrat utile à D-9 — l'implémentation D-8 fournira
 * une `flush()` compatible (elle peut avoir d'autres méthodes ; on ne
 * dépend que de celle-ci).
 *
 * Si D-9 merge AVANT D-8 (cf documentation PR), le caller passera `null`
 * et le handler skipera le flush avec un warn (cf test "scheduler optionnel").
 */
export interface SceneSchedulerLike {
  /** Annule tous les events `scene.apply` pending (drop, pas reschedule). */
  flush(): void;
}

/** Options du factory `createBargeInHandler`. */
export interface BargeInHandlerOptions {
  /**
   * Viewer Three.js exposant `viewer.model.fadeOutAndStopStreamingAudio` +
   * `viewer.model.emoteController`. Une `Viewer` instance non-loadée (model
   * undefined) est gérée gracieusement — le handler skip les étapes audio +
   * expression et flush quand même le scheduler.
   */
  viewer: Viewer;
  /**
   * Scheduler D-8. Passer `null` autorisé si D-8 pas encore mergé : le
   * handler log un warn mais continue (audio fade + neutral toujours appliqués).
   */
  scheduler: SceneSchedulerLike | null;
}

/**
 * Factory qui retourne le handler à brancher sur `ViewerEventsClient.onInterrupt`.
 *
 * Le handler retourné est synchrone : il **fire-and-forget** la promise du
 * fade-out audio (qui fait un `setTimeout` interne pour pause après le ramp).
 * On ne `await` pas pour ne pas bloquer la réception des events suivants —
 * la précision du fade vient de `linearRampToValueAtTime` (sample-accurate
 * Web Audio), pas du timing JS.
 *
 * Ordre d'exécution :
 *   1. fade-out audio (fire-and-forget)
 *   2. neutral expression (sync)
 *   3. scheduler.flush() (sync)
 *   4. log info pour ops
 *
 * Cet ordre assure que même si le fade-out audio rejette (AudioContext
 * fermé, etc.), l'expression et le scheduler sont toujours reset.
 *
 * @param opts.viewer    Viewer global (typiquement `ViewerContext`).
 * @param opts.scheduler Scheduler D-8 (ou null si pas encore wiré).
 * @returns Handler `(event: ViewerInterrupt) => void` à passer à
 *          `ViewerEventsClient.onInterrupt`.
 */
export function createBargeInHandler(
  opts: BargeInHandlerOptions,
): (event: ViewerInterrupt) => void {
  const { viewer, scheduler } = opts;

  return (event: ViewerInterrupt): void => {
    // 1. Audio fade-out 50ms — fire-and-forget. Si pas de model, no-op.
    //    On catch les rejections pour ne pas faire crasher le handler.
    const model = viewer.model;
    if (model) {
      try {
        const fadePromise = model.fadeOutAndStopStreamingAudio(50);
        // `fadeOutAndStopStreamingAudio` peut retourner une Promise rejected
        // si l'AudioContext est fermé ou l'audio déjà déconnecté. On swallow
        // pour préserver le flow neutral + flush.
        fadePromise.catch((fadeErr: unknown) => {
          console.warn(
            "[bargeInHandler] fadeOutAndStopStreamingAudio failed:",
            fadeErr instanceof Error ? fadeErr.message : String(fadeErr),
          );
        });
      } catch (syncErr) {
        // Cas ultra-rare : la méthode throw synchrone (avant la promise).
        console.warn(
          "[bargeInHandler] fadeOutAndStopStreamingAudio sync throw:",
          syncErr instanceof Error ? syncErr.message : String(syncErr),
        );
      }
    }

    // 2. Reset expression à Neutral via le pipeline D-7 standard.
    //    Si emoteController absent (VRM pas encore chargé), on skip
    //    silencieusement — pas un état d'erreur, juste un timing.
    if (model?.emoteController) {
      model.emoteController.applyDirectorAction({
        type: "playEmotion",
        preset: VRMExpressionPresetName.Neutral,
      });
    }

    // 3. Flush du scheduler D-8 (drop events scéniques pending).
    //    Critique : si on omet ce flush, un `scene.apply` schedulé via
    //    audio_at_ms juste avant l'interrupt s'appliquerait APRÈS le reset
    //    Neutral, créant un effet de "rebond" d'expression hors contexte.
    if (scheduler) {
      scheduler.flush();
    } else {
      console.warn(
        "[bargeInHandler] scheduler not wired — pending scene.apply events may leak after barge-in. Wire D-8 sceneScheduler.",
      );
    }

    // 4. Log info pour observabilité ops (Sentry / Datadog / Prometheus).
    //    Pas besoin de log warn : c'est un flux nominal, pas une anomalie.
    console.info("[bargeInHandler] voice.interrupt handled", {
      reason: event.reason,
      session_id: event.session_id,
    });
  };
}
