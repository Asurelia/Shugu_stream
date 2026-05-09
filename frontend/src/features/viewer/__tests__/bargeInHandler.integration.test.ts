/**
 * Tests integration — `bargeInHandler` × `Model.fadeOutAndStopStreamingAudio`
 * (Sprint D PR D-9).
 *
 * Assemble le handler avec une vraie instance `Model` (Web Audio mocké) et
 * vérifie le flow §5.2 complet :
 *
 *   1. Mount Model + attachStreamingAudio.
 *   2. Émet un `voice.interrupt` event.
 *   3. Vérifie en <60ms (ramp 50ms + safety 10ms) :
 *      - GainNode.gain.linearRampToValueAtTime(0, currentTime + 0.05) appelé
 *      - emoteController.applyDirectorAction({type:"playEmotion", preset:Neutral}) appelé
 *      - sceneScheduler.flush() appelé
 *      - audio.pause() appelé
 *
 * Ce test cible explicitement la métrique cible spec §7.2 :
 *   "Barge-in cut-off : < 200 ms entre détection VAD et silence audio".
 *   Côté frontend, le budget est <50ms entre réception event et silence
 *   complet — le test asserte qu'on appelle l'API Web Audio avec la bonne
 *   `endTime`, ce qui garantit la précision sample-accurate du ramp.
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

// ─── Mock AudioContext (réutilise pattern model.fadeOut.test.ts) ────────────

interface FakeGainNode {
  gain: {
    value: number;
    linearRampToValueAtTime: ReturnType<typeof vi.fn>;
    cancelScheduledValues: ReturnType<typeof vi.fn>;
    setValueAtTime: ReturnType<typeof vi.fn>;
  };
  connect: ReturnType<typeof vi.fn>;
  disconnect: ReturnType<typeof vi.fn>;
}

interface FakeAudioContext {
  state: AudioContextState;
  currentTime: number;
  destination: { __isDestination: true };
  createGain: ReturnType<typeof vi.fn>;
  createMediaElementSource: ReturnType<typeof vi.fn>;
  createAnalyser: ReturnType<typeof vi.fn>;
  resume: ReturnType<typeof vi.fn>;
  close: ReturnType<typeof vi.fn>;
  __lastGain: FakeGainNode | null;
}

function makeFakeAudioContext(): FakeAudioContext {
  const ctx: FakeAudioContext = {
    state: "running",
    currentTime: 1.0,
    destination: { __isDestination: true },
    createGain: vi.fn(),
    createMediaElementSource: vi.fn(),
    createAnalyser: vi.fn(),
    resume: vi.fn().mockResolvedValue(undefined),
    close: vi.fn().mockResolvedValue(undefined),
    __lastGain: null,
  };

  ctx.createGain.mockImplementation(() => {
    const gain: FakeGainNode = {
      gain: {
        value: 1,
        linearRampToValueAtTime: vi.fn(),
        cancelScheduledValues: vi.fn(),
        setValueAtTime: vi.fn(),
      },
      connect: vi.fn(),
      disconnect: vi.fn(),
    };
    ctx.__lastGain = gain;
    return gain;
  });

  ctx.createMediaElementSource.mockImplementation((audio: HTMLAudioElement) => ({
    connect: vi.fn(),
    disconnect: vi.fn(),
    mediaElement: audio,
  }));

  ctx.createAnalyser.mockImplementation(() => ({
    connect: vi.fn(),
    getFloatTimeDomainData: vi.fn(),
  }));

  return ctx;
}

let currentFakeCtx: FakeAudioContext;

beforeEach(() => {
  currentFakeCtx = makeFakeAudioContext();
  vi.stubGlobal(
    "AudioContext",
    vi.fn().mockImplementation(() => currentFakeCtx),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

// Imports APRÈS le stub global (model constructor crée un AudioContext interne).
import { Model } from "@/features/vrmViewer/model";
import { createBargeInHandler } from "../bargeInHandler";
import type { ViewerInterrupt } from "../ViewerEventsClient";

// ─── Test ──────────────────────────────────────────────────────────────────

describe("bargeInHandler × Model — integration E2E barge-in", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("voice.interrupt → audio fade + neutral expression + scheduler flush en <60ms", async () => {
    // 1. Instancie un Model + attache un audio streaming.
    const lookAt = new THREE.Object3D();
    const model = new Model(lookAt);
    const audio = document.createElement("audio");
    audio.pause = vi.fn();
    model.attachStreamingAudio(audio);

    // 2. Stub un emoteController sur le model (le vrai est créé via loadVRM,
    //    qu'on n'appelle pas ici — pas de fichier .vrm en jsdom).
    const applyDirectorActionSpy = vi.fn();
    // @ts-expect-error — patch direct, EmoteController non instancié sans VRM
    model.emoteController = { applyDirectorAction: applyDirectorActionSpy };

    // 3. Mock scheduler D-8 (interface SceneSchedulerLike).
    const scheduler = { flush: vi.fn() };

    // 4. Crée le handler.
    const fakeViewer = { model } as unknown as Parameters<
      typeof createBargeInHandler
    >[0]["viewer"];
    const handler = createBargeInHandler({
      viewer: fakeViewer,
      scheduler,
    });

    // 5. Émet le voice.interrupt event (forme reçue de WS, validée par Zod).
    const event: ViewerInterrupt = {
      type: "voice.interrupt",
      reason: "vad_detected",
      session_id: "integration-test-session",
      ts: "2026-05-08T12:00:00Z",
    };

    handler(event);

    // ─── Assertions immédiates (synchrones après handler) ──────────────────

    // 5a. Le ramp Web Audio a été armé.
    const gain = currentFakeCtx.__lastGain;
    expect(gain).not.toBeNull();
    expect(gain!.gain.linearRampToValueAtTime).toHaveBeenCalledWith(
      0,
      currentFakeCtx.currentTime + 0.05, // 50ms = 0.05s
    );

    // 5b. Expression neutral appliquée (sync dans le handler).
    expect(applyDirectorActionSpy).toHaveBeenCalledWith({
      type: "playEmotion",
      preset: VRMExpressionPresetName.Neutral,
    });

    // 5c. Scheduler flush appelé (sync).
    expect(scheduler.flush).toHaveBeenCalledTimes(1);

    // ─── Assertion timing : pause après ramp+safety = 60ms ─────────────────

    // Avant 60ms : pas encore pause-é.
    vi.advanceTimersByTime(59);
    expect(audio.pause).not.toHaveBeenCalled();

    // Au-delà du seuil 60ms (50 ramp + 10 safety) : audio.pause() fire.
    vi.advanceTimersByTime(2);
    expect(audio.pause).toHaveBeenCalledTimes(1);

    // Bilan : 3 actions appliquées + audio silencieux en <60ms wall-clock.
    // Cible spec §7.2 : barge-in cut-off <200ms (largement tenu côté frontend).
  });
});
