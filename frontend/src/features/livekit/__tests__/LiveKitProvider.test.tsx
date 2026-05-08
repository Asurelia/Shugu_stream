/**
 * Tests — LiveKitProvider (Sprint D PR D-6).
 *
 * Couverture :
 *   - Mount → fetch token + connect LiveKitClient.
 *   - Quand un audio track est reçu, on appelle `viewer.model.attachStreamingAudio()`
 *     pour brancher le HTMLAudioElement sur l'analyser lipSync.
 *   - Si AudioContext est suspendu (autoplay policy bloque), `needsUserGesture`
 *     passe à true et `resume()` appelle `audioContext.resume()`.
 *   - Cleanup au unmount (disconnect appelé).
 *
 * Stratégie de mock :
 *   - `LiveKitClient` est mocké au niveau module — on contrôle entièrement le
 *     constructor + connect + le moment où onAudioTrack est invoqué.
 *   - Le ViewerContext est fourni via `<ViewerContext.Provider>` avec un
 *     viewer fabriqué qui expose un `model` avec `attachStreamingAudio` mock.
 *   - `fetch` est stubbé via `vi.stubGlobal` pour retourner le token JSON.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";

// ─── Mock LiveKitClient avant l'import du Provider ──────────────────────────

interface FakeLiveKitOptions {
  url: string;
  token: string;
  onAudioTrack?: (track: unknown, audio: HTMLAudioElement) => void;
  onConnected?: () => void;
  onDisconnected?: (reason?: string) => void;
  onReconnecting?: () => void;
  onReconnected?: () => void;
}

interface FakeLiveKitInstance {
  options: FakeLiveKitOptions;
  connect: ReturnType<typeof vi.fn>;
  disconnect: ReturnType<typeof vi.fn>;
  isConnected: ReturnType<typeof vi.fn>;
  getRoom: ReturnType<typeof vi.fn>;
}

const hoisted = vi.hoisted(() => ({
  liveKitInstances: [] as FakeLiveKitInstance[],
}));

vi.mock("../LiveKitClient", () => {
  // Une vraie classe (pas un `vi.fn().mockImplementation`) — sinon le mock
  // instance écrase les propriétés et `client.connect` devient undefined
  // lorsque le Provider fait `new LiveKitClient(...)`.
  class LiveKitClientMock {
    public options: FakeLiveKitOptions;
    public connect: ReturnType<typeof vi.fn>;
    public disconnect: ReturnType<typeof vi.fn>;
    public isConnected: ReturnType<typeof vi.fn>;
    public getRoom: ReturnType<typeof vi.fn>;

    constructor(options: FakeLiveKitOptions) {
      this.options = options;
      this.connect = vi.fn().mockResolvedValue(undefined);
      this.disconnect = vi.fn();
      this.isConnected = vi.fn().mockReturnValue(true);
      this.getRoom = vi.fn().mockReturnValue(null);
      hoisted.liveKitInstances.push(this as unknown as FakeLiveKitInstance);
    }
  }
  return { LiveKitClient: LiveKitClientMock };
});

// Imports APRÈS les vi.mock pour utiliser les versions stubbées.
import { LiveKitProvider } from "../LiveKitProvider";
import { ViewerContext } from "@/features/vrmViewer/viewerContext";

const liveKitInstances = hoisted.liveKitInstances;

// ─── Helpers ────────────────────────────────────────────────────────────────

interface FakeAudioContext {
  state: "running" | "suspended" | "closed";
  resume: ReturnType<typeof vi.fn>;
}

interface FakeViewer {
  model?: {
    attachStreamingAudio: ReturnType<typeof vi.fn>;
    audioContext?: FakeAudioContext;
  };
}

function makeViewer(audioState: FakeAudioContext["state"] = "running"): FakeViewer {
  const audioContext: FakeAudioContext = {
    state: audioState,
    resume: vi.fn().mockImplementation(() => {
      audioContext.state = "running";
      return Promise.resolve();
    }),
  };
  return {
    model: {
      attachStreamingAudio: vi.fn(),
      audioContext,
    },
  };
}

function renderProvider(viewer: FakeViewer): void {
  render(
    // @ts-expect-error — fake viewer suffisant pour ce test
    <ViewerContext.Provider value={{ viewer }}>
      <LiveKitProvider>
        <div data-testid="child">child</div>
      </LiveKitProvider>
    </ViewerContext.Provider>,
  );
}

beforeEach(() => {
  liveKitInstances.length = 0;
  // fetch stub par défaut : token OK
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () =>
        Promise.resolve({
          token: "test-jwt",
          url: "wss://livekit.test",
          room: "shugu-room",
        }),
    }),
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

// ─── Tests ───────────────────────────────────────────────────────────────────

describe("LiveKitProvider", () => {
  it("fetch /api/voice/token au mount et instantiate LiveKitClient avec le token", async () => {
    renderProvider(makeViewer());

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalled();
    });
    const fetchMock = global.fetch as unknown as ReturnType<typeof vi.fn>;
    const calledUrl = fetchMock.mock.calls[0][0] as string;
    expect(calledUrl).toContain("/api/voice/token");

    await waitFor(() => {
      expect(liveKitInstances).toHaveLength(1);
    });
    expect(liveKitInstances[0].options.token).toBe("test-jwt");
    expect(liveKitInstances[0].options.url).toBe("wss://livekit.test");
    expect(liveKitInstances[0].connect).toHaveBeenCalled();
  });

  it("attache l'audio track au lipSync via viewer.model.attachStreamingAudio quand le Provider reçoit onAudioTrack", async () => {
    const viewer = makeViewer();
    renderProvider(viewer);

    await waitFor(() => {
      expect(liveKitInstances).toHaveLength(1);
    });

    const fakeAudio = document.createElement("audio");
    act(() => {
      liveKitInstances[0].options.onAudioTrack?.({}, fakeAudio);
    });

    expect(viewer.model!.attachStreamingAudio).toHaveBeenCalledWith(fakeAudio);
  });

  it("affiche overlay user-gesture si AudioContext est suspendu après attach audio", async () => {
    const viewer = makeViewer("suspended");
    renderProvider(viewer);

    await waitFor(() => {
      expect(liveKitInstances).toHaveLength(1);
    });

    const fakeAudio = document.createElement("audio");
    act(() => {
      liveKitInstances[0].options.onAudioTrack?.({}, fakeAudio);
    });

    expect(
      await screen.findByRole("button", { name: /click to start audio/i }),
    ).toBeInTheDocument();
  });

  it("resume audio context après user click sur l'overlay", async () => {
    const viewer = makeViewer("suspended");
    renderProvider(viewer);

    await waitFor(() => {
      expect(liveKitInstances).toHaveLength(1);
    });

    const fakeAudio = document.createElement("audio");
    act(() => {
      liveKitInstances[0].options.onAudioTrack?.({}, fakeAudio);
    });

    const button = await screen.findByRole("button", {
      name: /click to start audio/i,
    });
    await act(async () => {
      button.click();
    });

    expect(viewer.model!.audioContext!.resume).toHaveBeenCalledTimes(1);
    await waitFor(() => {
      expect(
        screen.queryByRole("button", { name: /click to start audio/i }),
      ).not.toBeInTheDocument();
    });
  });

  it("cleanup au unmount → LiveKitClient.disconnect appelé", async () => {
    const viewer = makeViewer();
    const { unmount } = render(
      // @ts-expect-error — fake viewer
      <ViewerContext.Provider value={{ viewer }}>
        <LiveKitProvider>
          <div data-testid="child">child</div>
        </LiveKitProvider>
      </ViewerContext.Provider>,
    );

    await waitFor(() => {
      expect(liveKitInstances).toHaveLength(1);
    });

    unmount();

    expect(liveKitInstances[0].disconnect).toHaveBeenCalledTimes(1);
  });

  it("rend les children et n'affiche pas l'overlay quand AudioContext est running", async () => {
    const viewer = makeViewer("running");
    renderProvider(viewer);

    expect(screen.getByTestId("child")).toBeInTheDocument();

    await waitFor(() => {
      expect(liveKitInstances).toHaveLength(1);
    });

    const fakeAudio = document.createElement("audio");
    act(() => {
      liveKitInstances[0].options.onAudioTrack?.({}, fakeAudio);
    });

    expect(
      screen.queryByRole("button", { name: /click to start audio/i }),
    ).not.toBeInTheDocument();
  });

  it("race fix: audio reçu avant viewer.model ready → poll → attach quand model devient dispo", async () => {
    // Cas réaliste : le token-fetch / Room.connect complète plus vite que le
    // chargement du VRM 28 MB (cold-cache). TrackSubscribed fire UNE seule
    // fois par session, donc sans le polling l'audio serait perdu pour toute
    // la session sans signal user. Spec §6.2 + review D-6.

    // Viewer initialement SANS model. On le mute après pour simuler le VRM
    // qui finit de charger.
    const viewer: FakeViewer = {};
    renderProvider(viewer);

    await waitFor(() => {
      expect(liveKitInstances).toHaveLength(1);
    });

    // CRUCIAL : passer en fake timers AVANT le onAudioTrack, sinon le
    // setInterval est créé en real-time et nos vi.advanceTimersByTime()
    // ne déclenchent pas la callback de poll.
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });

    const fakeAudio = document.createElement("audio");
    // Fire onAudioTrack alors que viewer.model est undefined.
    act(() => {
      liveKitInstances[0].options.onAudioTrack?.({}, fakeAudio);
    });

    // Avance 250ms → 2 tentatives de poll (100ms, 200ms). Toujours pas de
    // model → aucun attach, pas d'erreur.
    act(() => {
      vi.advanceTimersByTime(250);
    });
    expect(screen.queryByTestId("livekit-error")).not.toBeInTheDocument();

    // Simule fin du chargement VRM : on attache un model au viewer.
    const lateModel = {
      attachStreamingAudio: vi.fn(),
      audioContext: { state: "running" as const, resume: vi.fn() },
    };
    // Mutation directe — viewer est un singleton de contexte, model est
    // assigné par viewer.loadVrm() dans la vraie app.
    viewer.model = lateModel;

    // Avance 150ms supplémentaires → la prochaine tentative de poll
    // (à 300ms cumulé) doit tryAttach() avec succès.
    act(() => {
      vi.advanceTimersByTime(150);
    });

    expect(lateModel.attachStreamingAudio).toHaveBeenCalledWith(fakeAudio);
    expect(lateModel.attachStreamingAudio).toHaveBeenCalledTimes(1);

    vi.useRealTimers();
  });

  it("race fix: timeout 30s sans model → audio dropped + error remontée", async () => {
    const viewer: FakeViewer = {};
    renderProvider(viewer);

    await waitFor(() => {
      expect(liveKitInstances).toHaveLength(1);
    });

    // Fake timers AVANT onAudioTrack pour capturer le setInterval.
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });

    const fakeAudio = document.createElement("audio");
    act(() => {
      liveKitInstances[0].options.onAudioTrack?.({}, fakeAudio);
    });

    // Avance 31s → 310 tentatives, dépasse le cap 300. Le poll s'auto-stop
    // et set une error.
    act(() => {
      vi.advanceTimersByTime(31_000);
    });

    vi.useRealTimers();

    await waitFor(() => {
      expect(screen.getByTestId("livekit-error")).toBeInTheDocument();
    });
    expect(screen.getByTestId("livekit-error").textContent).toMatch(
      /VRM model never loaded/i,
    );
  });

  it("expose error dans le context si le fetch token échoue", async () => {
    vi.unstubAllGlobals();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 401,
        json: () => Promise.resolve({ detail: "unauthorized" }),
      }),
    );

    const viewer = makeViewer();
    renderProvider(viewer);

    await waitFor(() => {
      expect(screen.getByTestId("livekit-error")).toBeInTheDocument();
    });
    expect(liveKitInstances).toHaveLength(0);
  });
});
