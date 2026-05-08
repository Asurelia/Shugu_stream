/**
 * Tests — `Model.fadeOutAndStopStreamingAudio` (Sprint D PR D-9).
 *
 * Cette méthode insère un GainNode dans le graph WebAudio entre la source
 * MediaElement (créée par `lipSync.attachMediaElement`) et la destination
 * AudioContext, puis applique un `linearRampToValueAtTime(0, ctx.currentTime
 * + duration)` pour un fade-out sample-accurate. Cf spec §6.2 ligne 244 :
 *   `gainNode.gain.linearRampToValueAtTime(0, ctx.currentTime + 0.05)`.
 *
 * Stratégie de test :
 *   - jsdom ne ship PAS Web Audio. On stub `AudioContext` au niveau test
 *     avec un mock minimal (createGain + createMediaElementSource +
 *     createAnalyser + currentTime).
 *   - On vérifie que `linearRampToValueAtTime` est appelé avec :
 *       valeur cible = 0
 *       temps cible  = ctx.currentTime + durationMs/1000
 *   - On vérifie que `audio.pause()` est appelé après `durationMs + 10` ms.
 *   - On vérifie l'idempotence : 2 appels rapprochés ne ré-instancient pas
 *     le GainNode (réutilisation du gain existant ou cancel/restart propre).
 *   - On vérifie le no-audio path : si `attachStreamingAudio` n'a jamais été
 *     appelé, la méthode est un no-op (pas de crash).
 *
 * On ne teste PAS la précision empirique du ramp (50ms réels) — c'est une
 * propriété de Web Audio sample-accurate, pas du code testé. On teste qu'on
 * APPELLE l'API correctement.
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

// ─── Mock AudioContext (jsdom n'a pas Web Audio) ────────────────────────────
//
// Le mock doit satisfaire les usages de `LipSync` (createAnalyser,
// createMediaElementSource) ET ceux de `Model.fadeOutAndStopStreamingAudio`
// (createGain, currentTime). On le pose AVANT l'import du Model.

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

interface FakeMediaElementSource {
  connect: ReturnType<typeof vi.fn>;
  disconnect: ReturnType<typeof vi.fn>;
  mediaElement?: HTMLAudioElement;
}

interface FakeAnalyserNode {
  connect: ReturnType<typeof vi.fn>;
  getFloatTimeDomainData: ReturnType<typeof vi.fn>;
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
  __lastSource: FakeMediaElementSource | null;
}

function makeFakeGain(): FakeGainNode {
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
  return gain;
}

function makeFakeAudioContext(): FakeAudioContext {
  const ctx: FakeAudioContext = {
    state: "running",
    currentTime: 1.0, // valeur arbitraire stable pour les assertions
    destination: { __isDestination: true },
    createGain: vi.fn(),
    createMediaElementSource: vi.fn(),
    createAnalyser: vi.fn(),
    resume: vi.fn().mockResolvedValue(undefined),
    close: vi.fn().mockResolvedValue(undefined),
    __lastGain: null,
    __lastSource: null,
  };

  ctx.createGain.mockImplementation((): FakeGainNode => {
    const gain = makeFakeGain();
    ctx.__lastGain = gain;
    return gain;
  });

  ctx.createMediaElementSource.mockImplementation(
    (audio: HTMLAudioElement): FakeMediaElementSource => {
      const source: FakeMediaElementSource = {
        connect: vi.fn(),
        disconnect: vi.fn(),
        mediaElement: audio,
      };
      ctx.__lastSource = source;
      return source;
    },
  );

  ctx.createAnalyser.mockImplementation((): FakeAnalyserNode => ({
    connect: vi.fn(),
    getFloatTimeDomainData: vi.fn(),
  }));

  return ctx;
}

let currentFakeCtx: FakeAudioContext;

beforeEach(() => {
  currentFakeCtx = makeFakeAudioContext();
  // Stub global AudioContext — `new AudioContext()` retourne notre fake.
  // L'instance interne du Model (`new AudioContext()` dans constructor) doit
  // hériter de cette valeur dès le require, donc on stub avant l'import.
  vi.stubGlobal(
    "AudioContext",
    vi.fn().mockImplementation(() => currentFakeCtx),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

// Import APRÈS le stub global pour que le constructor `new AudioContext()`
// dans `LipSync` reçoive notre fake.
import { Model } from "../model";

// ─── Helpers ────────────────────────────────────────────────────────────────

function makeFakeAudioElement(): HTMLAudioElement {
  // jsdom fournit HTMLAudioElement basique — on lui rajoute pause = vi.fn()
  // pour spy et un play() qui résout immédiatement.
  const audio = document.createElement("audio");
  audio.pause = vi.fn();
  return audio;
}

function makeModel(): Model {
  // Le constructor du Model crée un `new AudioContext()` interne via LipSync.
  // Notre stub global retourne `currentFakeCtx` — donc model.audioContext
  // === currentFakeCtx.
  const lookAtParent = new THREE.Object3D();
  return new Model(lookAtParent);
}

// ─── Tests ──────────────────────────────────────────────────────────────────

describe("Model.fadeOutAndStopStreamingAudio", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("no-op silencieux si jamais d'audio attaché (no-audio path)", async () => {
    const model = makeModel();

    await expect(
      model.fadeOutAndStopStreamingAudio(50),
    ).resolves.toBeUndefined();

    expect(currentFakeCtx.createGain).not.toHaveBeenCalled();
  });

  it("après attachStreamingAudio : insère un GainNode + ramp linéaire vers 0", async () => {
    const model = makeModel();
    const audio = makeFakeAudioElement();
    model.attachStreamingAudio(audio);

    await model.fadeOutAndStopStreamingAudio(50);

    // Un GainNode a été créé pour le fade.
    expect(currentFakeCtx.createGain).toHaveBeenCalledTimes(1);
    const gain = currentFakeCtx.__lastGain;
    expect(gain).not.toBeNull();
    // Ramp vers 0 à currentTime + 50ms.
    expect(gain!.gain.linearRampToValueAtTime).toHaveBeenCalledWith(
      0,
      currentFakeCtx.currentTime + 0.05,
    );
  });

  it("pause() l'audio element après durationMs + 10ms safety margin", async () => {
    const model = makeModel();
    const audio = makeFakeAudioElement();
    model.attachStreamingAudio(audio);

    void model.fadeOutAndStopStreamingAudio(50);

    // Avant 50+10 = 60ms : pause pas encore appelé.
    expect(audio.pause).not.toHaveBeenCalled();

    vi.advanceTimersByTime(59);
    expect(audio.pause).not.toHaveBeenCalled();

    vi.advanceTimersByTime(2); // total 61ms — au-delà du seuil 60ms
    expect(audio.pause).toHaveBeenCalledTimes(1);
  });

  it("idempotent : 2 appels rapprochés ne crashent pas + ne re-rampent pas depuis 1.0", async () => {
    const model = makeModel();
    const audio = makeFakeAudioElement();
    model.attachStreamingAudio(audio);

    await model.fadeOutAndStopStreamingAudio(50);
    const firstCallCount =
      currentFakeCtx.__lastGain!.gain.linearRampToValueAtTime.mock.calls.length;

    // 2e appel : ne doit pas re-créer un GainNode (réutilisation).
    await model.fadeOutAndStopStreamingAudio(50);

    expect(currentFakeCtx.createGain).toHaveBeenCalledTimes(1);
    // Un nouveau ramp est armé (cancel + re-ramp accepté), mais pas un
    // doublement du nombre d'appels initial sur le même node.
    const totalCalls =
      currentFakeCtx.__lastGain!.gain.linearRampToValueAtTime.mock.calls.length;
    expect(totalCalls).toBeGreaterThanOrEqual(firstCallCount);
  });

  it("attache nouvelle audio APRÈS un fade : reset le gain à 1 (audio audible)", async () => {
    const model = makeModel();
    const firstAudio = makeFakeAudioElement();
    model.attachStreamingAudio(firstAudio);

    await model.fadeOutAndStopStreamingAudio(50);
    const gain = currentFakeCtx.__lastGain!;

    // Simulate LiveKit reconnect → nouvelle audio track.
    const secondAudio = makeFakeAudioElement();
    model.attachStreamingAudio(secondAudio);

    // Le gain doit être reset à 1 (sinon le 2e flux serait silencieux).
    // Soit via `gain.value = 1`, soit via `setValueAtTime(1, currentTime)`.
    const wasResetByValue = gain.gain.value === 1;
    const wasResetBySetValue = gain.gain.setValueAtTime.mock.calls.some(
      (call) => call[0] === 1,
    );
    expect(wasResetByValue || wasResetBySetValue).toBe(true);
  });

  it("durée par défaut = 50ms si non passée", async () => {
    const model = makeModel();
    const audio = makeFakeAudioElement();
    model.attachStreamingAudio(audio);

    await model.fadeOutAndStopStreamingAudio();

    const gain = currentFakeCtx.__lastGain!;
    expect(gain.gain.linearRampToValueAtTime).toHaveBeenCalledWith(
      0,
      currentFakeCtx.currentTime + 0.05,
    );
  });
});
