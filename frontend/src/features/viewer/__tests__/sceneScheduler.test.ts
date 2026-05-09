/**
 * Tests — `SceneScheduler` (Sprint D PR D-8).
 *
 * Le scheduler convertit `audio_at_ms` (offset depuis le début de la chunk
 * audio TTS courante, calculé backend par `audio_bridge`) en délai relatif au
 * `performance.now()` pour `setTimeout` ou apply immédiat (rAF / sync).
 *
 * Couverture :
 *   - audio_at_ms absent → apply immédiat (sync, dans le tick courant).
 *   - audio_at_ms positif → setTimeout(delta_ms, onApply).
 *   - audio_at_ms < 16ms → apply au prochain rAF.
 *   - audio_at_ms en retard >500ms → apply immédiat + warn `viewer.late_event`.
 *   - audio_at_ms négatif léger → apply immédiat (clamp à 0 + warn).
 *   - getChunkStartedAtPerfNow null → apply immédiat (pas de référence audio).
 *   - flush() annule tous les timers pending.
 *   - flush() est idempotent + safe sur scheduler fresh.
 *
 * Stratégie : `vi.useFakeTimers()` + on injecte un fake `performance.now()`
 * pour contrôler la base time des deltas.
 *
 * Référence spec : docs/specs/2026-05-08-voice-body-pipeline-design.md §3.2 + §6.2.
 */

import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";
import { SceneScheduler } from "../sceneScheduler";
import type { ViewerSceneApply } from "../ViewerEventsClient";
import type { ViewerAction } from "../sceneApplyMapper";

// ─── Helpers ────────────────────────────────────────────────────────────────

function makeEvent(overrides: Partial<ViewerSceneApply> = {}): ViewerSceneApply {
  return {
    type: "scene.apply",
    kind: "say_emotion",
    id: "joy",
    ts: "2026-05-08T14:23:11.456Z",
    ...overrides,
  };
}

function makeAction(): ViewerAction {
  return { type: "playEmotion", preset: "happy" as never };
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("SceneScheduler — apply immédiat (sans audio_at_ms)", () => {
  it("event sans audio_at_ms → onApply appelé immédiatement (sync, même tick)", () => {
    const onApply = vi.fn();
    const scheduler = new SceneScheduler({
      getAudioContext: () => undefined,
      getChunkStartedAtPerfNow: () => null,
      onApply,
    });

    scheduler.schedule(makeEvent({ audio_at_ms: undefined }), makeAction());

    // Pas de timer attendu : apply doit être synchrone.
    expect(onApply).toHaveBeenCalledTimes(1);
    expect(onApply).toHaveBeenCalledWith(makeAction());
  });

  it("getChunkStartedAtPerfNow retourne null → apply immédiat (pas de référence audio)", () => {
    const onApply = vi.fn();
    const scheduler = new SceneScheduler({
      getAudioContext: () => undefined,
      getChunkStartedAtPerfNow: () => null,
      onApply,
    });

    // audio_at_ms est défini, mais on n'a pas de horloge audio frontend.
    scheduler.schedule(makeEvent({ audio_at_ms: 1000 }), makeAction());

    expect(onApply).toHaveBeenCalledTimes(1);
  });
});

describe("SceneScheduler — schedule selon delta_ms", () => {
  it("delta < 16ms → apply au prochain rAF (pas via setTimeout long)", () => {
    // Stub rAF pour pouvoir le déclencher manuellement.
    const rafCallbacks: FrameRequestCallback[] = [];
    vi.stubGlobal(
      "requestAnimationFrame",
      vi.fn((cb: FrameRequestCallback) => {
        rafCallbacks.push(cb);
        return rafCallbacks.length;
      }),
    );

    const onApply = vi.fn();
    // Performance.now() = 1000ms ; chunk a démarré à 1000ms ; audio_at_ms = 5
    // → delta = 5 - (1000 - 1000) = 5ms < 16ms → rAF.
    vi.spyOn(performance, "now").mockReturnValue(1000);

    const scheduler = new SceneScheduler({
      getAudioContext: () => undefined,
      getChunkStartedAtPerfNow: () => 1000,
      onApply,
    });

    scheduler.schedule(makeEvent({ audio_at_ms: 5 }), makeAction());

    // Pas encore appelé : on attend le rAF.
    expect(onApply).not.toHaveBeenCalled();
    expect(rafCallbacks).toHaveLength(1);

    // Trigger rAF manuellement.
    rafCallbacks[0](performance.now());
    expect(onApply).toHaveBeenCalledTimes(1);
  });

  it("delta >= 16ms → setTimeout avec le bon délai", () => {
    const onApply = vi.fn();
    vi.spyOn(performance, "now").mockReturnValue(1000);

    const scheduler = new SceneScheduler({
      getAudioContext: () => undefined,
      getChunkStartedAtPerfNow: () => 1000,
      onApply,
    });

    // delta = 250 - (1000 - 1000) = 250ms.
    scheduler.schedule(makeEvent({ audio_at_ms: 250 }), makeAction());

    expect(onApply).not.toHaveBeenCalled();
    vi.advanceTimersByTime(249);
    expect(onApply).not.toHaveBeenCalled();
    vi.advanceTimersByTime(2);
    expect(onApply).toHaveBeenCalledTimes(1);
  });

  it("audio_at_ms en retard >500ms → apply immédiat + warn viewer.late_event", () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const onApply = vi.fn();
    // chunk a démarré à 1000ms ; perf.now() = 2000 → 1000ms écoulé.
    // audio_at_ms = 100 → delta = 100 - 1000 = -900 (very late).
    vi.spyOn(performance, "now").mockReturnValue(2000);

    const scheduler = new SceneScheduler({
      getAudioContext: () => undefined,
      getChunkStartedAtPerfNow: () => 1000,
      onApply,
    });

    scheduler.schedule(makeEvent({ audio_at_ms: 100 }), makeAction());

    expect(onApply).toHaveBeenCalledTimes(1);
    expect(warnSpy).toHaveBeenCalled();
    const msg = String(warnSpy.mock.calls[0][0]);
    expect(msg).toMatch(/late_event/);
  });

  it("audio_at_ms en retard léger (-100ms) → rAF (pas de warn late_event, pas de freeze)", () => {
    // Cas nominal au démarrage : event arrive 100ms après chunk start mais
    // audio_at_ms = 0 (premier event de la phrase). delta = -100ms est dans
    // la fenêtre [-500, 16) → rAF. Pas de warn fatal car pas dans late_event.
    const rafCallbacks: FrameRequestCallback[] = [];
    vi.stubGlobal(
      "requestAnimationFrame",
      vi.fn((cb: FrameRequestCallback) => {
        rafCallbacks.push(cb);
        return rafCallbacks.length;
      }),
    );
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const onApply = vi.fn();
    vi.spyOn(performance, "now").mockReturnValue(1100);

    const scheduler = new SceneScheduler({
      getAudioContext: () => undefined,
      getChunkStartedAtPerfNow: () => 1000,
      onApply,
    });

    scheduler.schedule(makeEvent({ audio_at_ms: 0 }), makeAction());

    // rAF programmé, pas encore appelé.
    expect(rafCallbacks).toHaveLength(1);
    expect(onApply).not.toHaveBeenCalled();
    rafCallbacks[0](performance.now());
    expect(onApply).toHaveBeenCalledTimes(1);
    // Pas de warn late_event pour delta = -100ms (limite -500 non franchie).
    const lateWarn = warnSpy.mock.calls.find((c) =>
      String(c[0]).includes("late_event"),
    );
    expect(lateWarn).toBeUndefined();
  });
});

describe("SceneScheduler — flush()", () => {
  it("flush() annule tous les setTimeout pending", () => {
    const onApply = vi.fn();
    vi.spyOn(performance, "now").mockReturnValue(1000);

    const scheduler = new SceneScheduler({
      getAudioContext: () => undefined,
      getChunkStartedAtPerfNow: () => 1000,
      onApply,
    });

    // Schedule 3 events à T+200, T+400, T+600.
    scheduler.schedule(makeEvent({ audio_at_ms: 200 }), makeAction());
    scheduler.schedule(
      makeEvent({ audio_at_ms: 400, id: "sad" }),
      { type: "playEmotion", preset: "sad" as never },
    );
    scheduler.schedule(
      makeEvent({ audio_at_ms: 600, id: "angry" }),
      { type: "playEmotion", preset: "angry" as never },
    );

    // Avant flush : aucun event appliqué.
    expect(onApply).not.toHaveBeenCalled();

    scheduler.flush();

    // Avance largement : aucun event ne doit fire.
    vi.advanceTimersByTime(10_000);
    expect(onApply).not.toHaveBeenCalled();
  });

  it("flush() sur scheduler fresh est un no-op safe (pas de throw)", () => {
    const scheduler = new SceneScheduler({
      getAudioContext: () => undefined,
      getChunkStartedAtPerfNow: () => null,
      onApply: vi.fn(),
    });
    expect(() => scheduler.flush()).not.toThrow();
  });

  it("flush() est idempotent — peut être appelé plusieurs fois sans effet", () => {
    const onApply = vi.fn();
    vi.spyOn(performance, "now").mockReturnValue(1000);

    const scheduler = new SceneScheduler({
      getAudioContext: () => undefined,
      getChunkStartedAtPerfNow: () => 1000,
      onApply,
    });

    scheduler.schedule(makeEvent({ audio_at_ms: 500 }), makeAction());
    scheduler.flush();
    scheduler.flush(); // 2e appel — pas de throw.
    scheduler.flush(); // 3e appel — toujours safe.

    vi.advanceTimersByTime(1000);
    expect(onApply).not.toHaveBeenCalled();
  });

  it("après flush(), schedule() peut continuer à fonctionner", () => {
    const onApply = vi.fn();
    vi.spyOn(performance, "now").mockReturnValue(1000);

    const scheduler = new SceneScheduler({
      getAudioContext: () => undefined,
      getChunkStartedAtPerfNow: () => 1000,
      onApply,
    });

    scheduler.schedule(makeEvent({ audio_at_ms: 200 }), makeAction());
    scheduler.flush();

    // Re-schedule après flush.
    scheduler.schedule(
      makeEvent({ audio_at_ms: 100, id: "sad" }),
      { type: "playEmotion", preset: "sad" as never },
    );

    vi.advanceTimersByTime(150);
    expect(onApply).toHaveBeenCalledTimes(1);
    expect(onApply).toHaveBeenCalledWith({
      type: "playEmotion",
      preset: "sad",
    });
  });
});

describe("SceneScheduler — robustesse", () => {
  it("schedule() avec onApply qui throw → exception attrapée + log error (pas de crash silencieux du scheduler)", () => {
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const onApply = vi.fn(() => {
      throw new Error("test boom");
    });

    const scheduler = new SceneScheduler({
      getAudioContext: () => undefined,
      getChunkStartedAtPerfNow: () => null,
      onApply,
    });

    // Ne doit pas remonter l'exception au caller.
    expect(() => {
      scheduler.schedule(makeEvent(), makeAction());
    }).not.toThrow();
    expect(errSpy).toHaveBeenCalled();
  });
});
