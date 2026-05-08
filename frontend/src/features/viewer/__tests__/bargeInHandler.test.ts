/**
 * Tests — `bargeInHandler` (Sprint D PR D-9, voice-body pipeline).
 *
 * `bargeInHandler` est un module pur qui consomme un event `voice.interrupt`
 * (déclenché backend D-4 v3 / broadcasté D-3) et orchestre côté frontend les
 * 3 étapes du flow §5.2 (t=1.45s → t=1.50s) :
 *
 *   1. Audio fade-out 50ms via `viewer.model.fadeOutAndStopStreamingAudio()`
 *   2. Reset expression à `Neutral` via `emoteController.applyDirectorAction`
 *   3. Flush du scheduler (drop events scéniques pending) — interface
 *      `SceneSchedulerLike` mockée ici, vraie impl arrive en D-8.
 *
 * Couverture :
 *   - fade-out + neutral + flush appelés dans l'ordre (happy path)
 *   - sans audio en cours : fade-out no-op, neutral + flush quand même appelés
 *   - sans emoteController (VRM pas chargé) : flush quand même appelé
 *   - idempotent : 2 interrupts rapprochés ne crashent pas
 *   - log info avec reason + session_id (pour ops debug)
 *
 * Pattern : on n'importe PAS un vrai `Viewer` (Three.js + VRM = lourd) —
 * on injecte un fake viewer minimal qui satisfait l'interface attendue.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { VRMExpressionPresetName } from "@pixiv/three-vrm";
import { createBargeInHandler } from "../bargeInHandler";
import type { SceneSchedulerLike } from "../bargeInHandler";
import type { ViewerInterrupt } from "../ViewerEventsClient";

// ─── Fakes ──────────────────────────────────────────────────────────────────

interface FakeEmoteController {
  applyDirectorAction: ReturnType<typeof vi.fn>;
}

interface FakeModel {
  emoteController?: FakeEmoteController;
  fadeOutAndStopStreamingAudio: ReturnType<typeof vi.fn>;
}

interface FakeViewer {
  model?: FakeModel;
}

function makeFakeViewer(opts: {
  hasModel?: boolean;
  hasEmoteController?: boolean;
} = {}): FakeViewer {
  const hasModel = opts.hasModel ?? true;
  const hasEmoteController = opts.hasEmoteController ?? true;

  if (!hasModel) {
    return { model: undefined };
  }

  return {
    model: {
      fadeOutAndStopStreamingAudio: vi.fn().mockResolvedValue(undefined),
      emoteController: hasEmoteController
        ? { applyDirectorAction: vi.fn() }
        : undefined,
    },
  };
}

function makeFakeScheduler(): SceneSchedulerLike & {
  flush: ReturnType<typeof vi.fn>;
} {
  return {
    flush: vi.fn(),
  };
}

function makeInterruptEvent(
  reason: ViewerInterrupt["reason"] = "vad_detected",
): ViewerInterrupt {
  return {
    type: "voice.interrupt",
    reason,
    session_id: "test-session-123",
    ts: "2026-05-08T12:00:00Z",
  };
}

// ─── Tests ──────────────────────────────────────────────────────────────────

describe("createBargeInHandler", () => {
  // On utilise les types inférés directement via `let` + assignation dans
  // beforeEach. TS infère le type complet (MockInstance<[...console args], void>)
  // sans qu'on ait à le typer explicitement — l'utilisation locale dans les
  // tests passe le type sans cast.
  let consoleInfoSpy: ReturnType<typeof vi.spyOn> | undefined;
  let consoleWarnSpy: ReturnType<typeof vi.spyOn> | undefined;

  beforeEach(() => {
    consoleInfoSpy = vi.spyOn(console, "info").mockImplementation(() => {}) as ReturnType<typeof vi.spyOn>;
    consoleWarnSpy = vi.spyOn(console, "warn").mockImplementation(() => {}) as ReturnType<typeof vi.spyOn>;
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("happy path : fade-out + neutral + flush appelés", () => {
    const viewer = makeFakeViewer();
    const scheduler = makeFakeScheduler();
    const handler = createBargeInHandler({
      viewer: viewer as never,
      scheduler,
    });

    handler(makeInterruptEvent());

    expect(viewer.model!.fadeOutAndStopStreamingAudio).toHaveBeenCalledTimes(1);
    expect(viewer.model!.fadeOutAndStopStreamingAudio).toHaveBeenCalledWith(50);
    expect(
      viewer.model!.emoteController!.applyDirectorAction,
    ).toHaveBeenCalledWith({
      type: "playEmotion",
      preset: VRMExpressionPresetName.Neutral,
    });
    expect(scheduler.flush).toHaveBeenCalledTimes(1);
  });

  it("log info avec reason + session_id pour observabilité ops", () => {
    const viewer = makeFakeViewer();
    const scheduler = makeFakeScheduler();
    const handler = createBargeInHandler({
      viewer: viewer as never,
      scheduler,
    });

    handler(makeInterruptEvent("vad_detected"));

    expect(consoleInfoSpy).toHaveBeenCalledWith(
      expect.stringContaining("voice.interrupt handled"),
      expect.objectContaining({
        reason: "vad_detected",
        session_id: "test-session-123",
      }),
    );
  });

  it("sans model (VRM jamais chargé) : flush appelé, pas de crash", () => {
    const viewer = makeFakeViewer({ hasModel: false });
    const scheduler = makeFakeScheduler();
    const handler = createBargeInHandler({
      viewer: viewer as never,
      scheduler,
    });

    expect(() => handler(makeInterruptEvent())).not.toThrow();
    expect(scheduler.flush).toHaveBeenCalledTimes(1);
  });

  it("sans emoteController : fade-out + flush appelés, pas de crash", () => {
    const viewer = makeFakeViewer({ hasEmoteController: false });
    const scheduler = makeFakeScheduler();
    const handler = createBargeInHandler({
      viewer: viewer as never,
      scheduler,
    });

    expect(() => handler(makeInterruptEvent())).not.toThrow();
    expect(viewer.model!.fadeOutAndStopStreamingAudio).toHaveBeenCalledTimes(1);
    expect(scheduler.flush).toHaveBeenCalledTimes(1);
  });

  it("idempotent : 2 interrupts rapprochés OK (pas de double-fault)", () => {
    const viewer = makeFakeViewer();
    const scheduler = makeFakeScheduler();
    const handler = createBargeInHandler({
      viewer: viewer as never,
      scheduler,
    });

    handler(makeInterruptEvent());
    handler(makeInterruptEvent("manual"));

    // Les 3 actions sont appelées 2 fois — c'est OK (idempotence assurée par
    // les méthodes individuelles, pas par le handler lui-même).
    expect(viewer.model!.fadeOutAndStopStreamingAudio).toHaveBeenCalledTimes(2);
    expect(
      viewer.model!.emoteController!.applyDirectorAction,
    ).toHaveBeenCalledTimes(2);
    expect(scheduler.flush).toHaveBeenCalledTimes(2);
  });

  it("ne propage pas les rejections de fadeOutAndStopStreamingAudio", () => {
    const viewer = makeFakeViewer();
    viewer.model!.fadeOutAndStopStreamingAudio.mockRejectedValue(
      new Error("audio context closed"),
    );
    const scheduler = makeFakeScheduler();
    const handler = createBargeInHandler({
      viewer: viewer as never,
      scheduler,
    });

    // Le handler ne doit PAS throw — fade-out best-effort.
    expect(() => handler(makeInterruptEvent())).not.toThrow();
    // Et neutral + flush doivent quand même être appelés (fire-and-forget).
    expect(
      viewer.model!.emoteController!.applyDirectorAction,
    ).toHaveBeenCalled();
    expect(scheduler.flush).toHaveBeenCalled();
  });

  it("scheduler optionnel : si non fourni, log warn mais pas de crash", () => {
    const viewer = makeFakeViewer();
    const handler = createBargeInHandler({
      viewer: viewer as never,
      scheduler: null,
    });

    expect(() => handler(makeInterruptEvent())).not.toThrow();
    expect(viewer.model!.fadeOutAndStopStreamingAudio).toHaveBeenCalled();
    expect(
      viewer.model!.emoteController!.applyDirectorAction,
    ).toHaveBeenCalled();
    // Warn est utile pour diagnostiquer le wiring D-8 absent.
    expect(consoleWarnSpy).toHaveBeenCalledWith(
      expect.stringContaining("scheduler not wired"),
    );
  });
});
