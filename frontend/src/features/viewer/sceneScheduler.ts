/**
 * SceneScheduler — sync `audio_at_ms` ↔ wall clock frontend (Sprint D PR D-8).
 *
 * Convertit le `audio_at_ms` (offset depuis le début de la chunk audio TTS
 * courante, calculé backend par `audio_bridge.publish_pcm`) en délai relatif
 * au `performance.now()` puis schedule l'application via :
 *   - apply immédiat (sync) : pas de référence audio, ou event en retard >500ms.
 *   - `requestAnimationFrame` : delta ∈ [-500, 16) ms — apply au prochain frame.
 *   - `setTimeout(delta_ms)`  : delta >= 16ms — délai mesurable.
 *
 * Pourquoi cette logique ? Cf spec §3.2 + §6.2 :
 *   - audio_at_ms est conçu pour aligner expression faciale + clip audio à <50ms.
 *   - Si on apply systématiquement via setTimeout (même 5ms), on accumule du
 *     jitter event-loop noise + on disperse les events sur plusieurs frames →
 *     l'avatar saccade visuellement.
 *   - Si on apply systématiquement immédiatement, on désynchronise volontaire-
 *     ment l'expression du début de la chunk audio.
 *   - Compromis : sub-frame delays (< 16ms) sont folded dans le prochain rAF
 *     du moteur three.js (donc co-frame avec le rendering VRM), delays plus
 *     longs vivent dans setTimeout pour ne pas bloquer la frame courante.
 *
 * Le scheduler est aussi le point d'entrée de la stratégie barge-in :
 * `flush()` annule TOUS les events pending (typiquement appelé par
 * `ViewerEventsClient.onInterrupt` quand le VAD détecte la voix user).
 *
 * Référence spec : docs/specs/2026-05-08-voice-body-pipeline-design.md §3.2 + §6.2.
 */

import type { ViewerSceneApply } from "./ViewerEventsClient";
import type { ViewerAction } from "./sceneApplyMapper";

// ─── Constantes ─────────────────────────────────────────────────────────────

/** Seuil sub-frame en dessous duquel on bascule de setTimeout vers rAF.
 *  16ms = 1 frame à 60Hz — au-dessus de cette valeur on a un délai mesurable. */
const RAF_THRESHOLD_MS = 16;

/** Seuil "event en retard" : au-delà, on apply immédiatement et on log warn.
 *  Spec §6.2 : "audio_at_ms reçu après que l'audio soit déjà passé (event en
 *  retard > 500ms) → apply immédiatement (best-effort) + log viewer.late_event". */
const LATE_EVENT_THRESHOLD_MS = 500;

// ─── Types publics ──────────────────────────────────────────────────────────

/** Options de configuration du SceneScheduler. */
export interface SceneSchedulerOptions {
  /**
   * Provider qui retourne l'AudioContext courant (depuis viewer.model.audioContext).
   *
   * Réservé pour une future variante où on alignerait via `audioContext.currentTime`
   * plutôt que `performance.now()` (sub-ms precision). Pas utilisé en MVP D-8 —
   * `performance.now()` suffit pour les seuils 16ms/500ms.
   */
  getAudioContext: () => AudioContext | undefined;

  /**
   * Provider qui retourne le timestamp `performance.now()` du moment où la
   * chunk audio LiveKit courante a commencé à jouer côté frontend.
   *
   * Mécanique : `LiveKitProvider.onAudioTrack` reçoit un `HTMLAudioElement`.
   * On peut écouter l'event `playing` pour capturer `performance.now()` à ce
   * moment-là, et l'exposer via une ref que le scheduler interroge.
   *
   * Si `null`/`undefined`, le scheduler ne tente pas de calculer un delta —
   * il apply immédiatement. C'est le comportement MVP acceptable au démarrage
   * (cf spec §6.2 "Drift acceptable au démarrage, mieux que freeze").
   */
  getChunkStartedAtPerfNow: () => number | null;

  /**
   * Action à exécuter quand l'event est due. Appelé soit immédiatement (sync),
   * soit dans un rAF, soit dans un setTimeout. Les exceptions levées par
   * `onApply` sont attrapées + loggées par le scheduler — elles ne remontent
   * pas au caller pour ne pas casser le pipeline.
   */
  onApply: (action: ViewerAction) => void;
}

// ─── Implémentation ─────────────────────────────────────────────────────────

/**
 * Scheduler qui aligne `audio_at_ms` ↔ wall-clock frontend.
 *
 * Lifecycle :
 *   1. `new SceneScheduler(options)` — capture des callbacks/providers.
 *   2. `scheduler.schedule(event, action)` — décide rAF / setTimeout / sync
 *      selon `event.audio_at_ms` et `getChunkStartedAtPerfNow()`.
 *   3. `scheduler.flush()` — annule tous les pending (utilisé par barge-in D-9).
 */
export class SceneScheduler {
  private readonly _options: SceneSchedulerOptions;
  /** Ids des setTimeout pending — `flush()` les clearTimeout en bulk. */
  private _pendingTimers: Array<ReturnType<typeof setTimeout>> = [];
  /** Ids des rAF pending — `flush()` les cancelAnimationFrame en bulk.
   *  Note : on stocke l'id retourné par `requestAnimationFrame`. */
  private _pendingRafs: number[] = [];

  public constructor(options: SceneSchedulerOptions) {
    this._options = options;
  }

  /**
   * Schedule l'application de l'event selon `audio_at_ms`.
   *
   * Décision :
   *   - `audio_at_ms === undefined` OU `getChunkStartedAtPerfNow() === null`
   *     → apply immédiat (sync).
   *   - delta < -500ms → late_event : apply immédiat (best-effort) + warn.
   *   - delta < 16ms (incluant léger négatif) → apply au prochain rAF.
   *   - delta >= 16ms → setTimeout(delta, onApply).
   */
  public schedule(event: ViewerSceneApply, action: ViewerAction): void {
    // Cas 1 : pas de timestamp audio → apply immédiat.
    if (event.audio_at_ms === undefined) {
      this._applySafe(action);
      return;
    }

    // Cas 2 : pas de référence horloge audio frontend → apply immédiat.
    const chunkStartedAt = this._options.getChunkStartedAtPerfNow();
    if (chunkStartedAt === null || chunkStartedAt === undefined) {
      this._applySafe(action);
      return;
    }

    // Cas 3 : on a tout ce qu'il faut, calcule le delta.
    const elapsedMs = performance.now() - chunkStartedAt;
    const deltaMs = event.audio_at_ms - elapsedMs;

    if (deltaMs < -LATE_EVENT_THRESHOLD_MS) {
      // Late event — best-effort + warn.
      console.warn(
        `[sceneScheduler] viewer.late_event delta=${Math.round(deltaMs)}ms ` +
          `kind=${event.kind} id=${event.id} — applying immediately.`,
      );
      this._applySafe(action);
      return;
    }

    if (deltaMs < RAF_THRESHOLD_MS) {
      // Sub-frame ou léger négatif (jusqu'à -500ms) → rAF (co-frame avec render).
      const rafId = requestAnimationFrame(() => {
        this._removeRaf(rafId);
        this._applySafe(action);
      });
      this._pendingRafs.push(rafId);
      return;
    }

    // delta >= 16ms → setTimeout pour ne pas bloquer la frame courante.
    const timerId = setTimeout(() => {
      this._removeTimer(timerId);
      this._applySafe(action);
    }, deltaMs);
    this._pendingTimers.push(timerId);
  }

  /**
   * Annule TOUS les events pending (timers + rAF). Utilisé par
   * `ViewerEventsClient.onInterrupt` lors d'un barge-in (spec §5.2).
   *
   * Idempotent : peut être appelé plusieurs fois sans effet de bord. Safe
   * sur scheduler fresh (jamais schedule()).
   *
   * Après `flush()`, le scheduler reste utilisable — `schedule()` peut être
   * appelé à nouveau pour la prochaine performance.
   */
  public flush(): void {
    for (const id of this._pendingTimers) {
      clearTimeout(id);
    }
    this._pendingTimers = [];

    for (const rafId of this._pendingRafs) {
      cancelAnimationFrame(rafId);
    }
    this._pendingRafs = [];
  }

  // ─── Internal helpers ──────────────────────────────────────────────────

  /**
   * Wrap `onApply` avec try/catch — protège le pipeline si le mapper
   * produit une action invalide ou si `emoteController.applyDirectorAction`
   * throw (e.g. VRM unloaded). Le scheduler ne propage JAMAIS d'exception.
   */
  private _applySafe(action: ViewerAction): void {
    try {
      this._options.onApply(action);
    } catch (err) {
      console.error(
        "[sceneScheduler] onApply threw — caught to keep pipeline alive:",
        err,
      );
    }
  }

  /** Retire un timer fired du tracker pending (cleanup mémoire). */
  private _removeTimer(id: ReturnType<typeof setTimeout>): void {
    const idx = this._pendingTimers.indexOf(id);
    if (idx >= 0) {
      this._pendingTimers.splice(idx, 1);
    }
  }

  /** Retire un rAF fired du tracker pending. */
  private _removeRaf(id: number): void {
    const idx = this._pendingRafs.indexOf(id);
    if (idx >= 0) {
      this._pendingRafs.splice(idx, 1);
    }
  }
}
