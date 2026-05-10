/**
 * Tests — `Model.unLoadVrm` AudioContext tear-down (U4 follow-up).
 *
 * Contexte du bug
 * ----------------
 * `VrmViewer.tsx` expose un retry (`doLoad`) qui ré-appelle `viewer.loadVrm()`.
 * Chaque appel passe par `viewer.unloadVRM()` puis `new Model(...)`. Le
 * constructor de `Model` crée `new AudioContext()` via `LipSync`. Si
 * `unLoadVrm` ne ferme PAS l'AudioContext de l'instance précédente, chaque
 * retry-click leak un AudioContext — Chrome cap à ~6 contexts/page avant de
 * jeter `NotAllowedError`, ce qui rend le retry inutilisable après quelques
 * essais.
 *
 * Stratégie de test
 * -----------------
 *  - Stub global `AudioContext` avec une factory qui retourne une INSTANCE
 *    DIFFÉRENTE par `new` (différent du test fadeOut sibling qui utilise un
 *    singleton). On garde un tableau pour pouvoir asserter sur la première
 *    instance après le second `new Model()`.
 *  - On vérifie : après un 2e instanciation de `Model`, l'AudioContext de
 *    la première instance a reçu un `close()`.
 *  - On vérifie : `_streamingGain`, `_streamingAudio` et `_fadeStopTimer`
 *    sont clear (pas de mocks à inspecter directement, on teste via les
 *    side-effects observables : pas de pause() en attente sur un audio
 *    détaché après tear-down).
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
  __id: number;
}

function makeFakeGain(): FakeGainNode {
  return {
    gain: {
      value: 1,
      linearRampToValueAtTime: vi.fn(),
      cancelScheduledValues: vi.fn(),
      setValueAtTime: vi.fn(),
    },
    connect: vi.fn(),
    disconnect: vi.fn(),
  };
}

let createdContexts: FakeAudioContext[];

function makeFakeAudioContext(): FakeAudioContext {
  const ctx: FakeAudioContext = {
    state: "running",
    currentTime: 1.0,
    destination: { __isDestination: true },
    createGain: vi.fn().mockImplementation(makeFakeGain),
    createMediaElementSource: vi.fn().mockImplementation(
      (audio: HTMLAudioElement): FakeMediaElementSource => ({
        connect: vi.fn(),
        disconnect: vi.fn(),
        mediaElement: audio,
      }),
    ),
    createAnalyser: vi.fn().mockImplementation((): FakeAnalyserNode => ({
      connect: vi.fn(),
      getFloatTimeDomainData: vi.fn(),
    })),
    resume: vi.fn().mockResolvedValue(undefined),
    close: vi.fn().mockResolvedValue(undefined),
    __id: createdContexts.length,
  };
  return ctx;
}

beforeEach(() => {
  createdContexts = [];
  vi.stubGlobal(
    "AudioContext",
    vi.fn().mockImplementation(() => {
      const ctx = makeFakeAudioContext();
      createdContexts.push(ctx);
      return ctx;
    }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

import { Model } from "../model";

function makeFakeAudioElement(): HTMLAudioElement {
  const audio = document.createElement("audio");
  audio.pause = vi.fn();
  return audio;
}

describe("Model.unLoadVrm — AudioContext tear-down", () => {
  it("ferme l'AudioContext de l'instance précédente quand un nouveau Model est créé", () => {
    // 1er Model — crée AudioContext #0.
    const lookAtParent = new THREE.Object3D();
    const first = new Model(lookAtParent);
    expect(createdContexts).toHaveLength(1);
    expect(createdContexts[0].close).not.toHaveBeenCalled();

    // Simule le retry : viewer.unloadVRM() appelle model.unLoadVrm().
    first.unLoadVrm();

    // L'AudioContext du premier Model doit être fermé.
    expect(createdContexts[0].close).toHaveBeenCalledTimes(1);

    // 2e Model — crée AudioContext #1 distinct.
    const second = new Model(lookAtParent);
    expect(createdContexts).toHaveLength(2);
    expect(createdContexts[0]).not.toBe(createdContexts[1]);
    // Le 2e n'a PAS été touché par l'unload du premier.
    expect(createdContexts[1].close).not.toHaveBeenCalled();

    // Cleanup.
    second.unLoadVrm();
  });

  it("appels successifs à unLoadVrm — 2e appel n'explose pas (idempotence)", () => {
    const model = new Model(new THREE.Object3D());

    expect(() => model.unLoadVrm()).not.toThrow();
    // 2e call : _lipSync est déjà undefined, on ne doit PAS re-close.
    expect(() => model.unLoadVrm()).not.toThrow();

    // close() appelé exactement 1 fois — pas de double-close (qui throw
    // InvalidStateError sur un contexte déjà fermé).
    expect(createdContexts[0].close).toHaveBeenCalledTimes(1);
  });

  it("clear le _fadeStopTimer en attente : pause() ne fire PAS après tear-down", async () => {
    vi.useFakeTimers();
    try {
      const model = new Model(new THREE.Object3D());
      const audio = makeFakeAudioElement();
      model.attachStreamingAudio(audio);

      // Arme un fade — pose un setTimeout pour pause à durationMs+10.
      void model.fadeOutAndStopStreamingAudio(50);

      // Tear-down AVANT que le timer fire.
      model.unLoadVrm();

      // Avance le temps au-delà du delay (50+10+marge). Sans le clearTimeout,
      // pause() serait appelé sur un audio orphelin.
      vi.advanceTimersByTime(200);

      expect(audio.pause).not.toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
    }
  });

  it("swallow silently l'éventuel reject de close() (browser sans WebAudio support)", async () => {
    // Simule un contexte qui rejette close (rare, mais le Promise rejection
    // ne doit jamais bubble vers un unhandled rejection).
    const model = new Model(new THREE.Object3D());
    const ctx = createdContexts[0];
    ctx.close.mockRejectedValueOnce(
      new DOMException("InvalidStateError", "InvalidStateError"),
    );

    expect(() => model.unLoadVrm()).not.toThrow();
    // Laisse la microtask se flush — pas d'unhandled rejection ici.
    await Promise.resolve();
  });
});
