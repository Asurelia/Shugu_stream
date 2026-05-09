/**
 * Tests — LiveKitClient (Sprint D PR D-6).
 *
 * Couverture :
 *   - `connect()` appelle `Room.connect(url, token)` avec les bons paramètres.
 *   - `disconnect()` ferme la Room et reset l'état interne.
 *   - Le callback `onAudioTrack` est invoqué quand une RemoteAudioTrack est
 *     subscribed → fournit un `HTMLAudioElement` attaché au track.
 *   - Les callbacks de lifecycle (Connected / Reconnecting / Reconnected /
 *     Disconnected) sont câblés sur les bons RoomEvent.
 *   - `isConnected()` reflète l'état de la Room.
 *   - Edge cases : double connect, disconnect avant connect, video track
 *     ignoré (only audio).
 *
 * Stratégie de mock : on stub `livekit-client` au niveau module pour exposer
 * une fake `Room` avec un EventEmitter manuel. Les events RoomEvent sont
 * déclenchés à la main via `room.__emit(event, ...)` pour valider le câblage.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// ─── Mock livekit-client (le vrai package est `livekit-client`, sans scope) ──
//
// Note vi.mock + hoisting : le factory est hoisté au top du fichier par Vitest.
// Toute variable capturée dans le factory doit donc vivre dans `vi.hoisted()`
// — sinon la TDZ (temporal dead zone) renvoie undefined au moment où le factory
// s'exécute. On stocke `roomInstances` via vi.hoisted pour que les tests
// puissent y accéder après l'import.

interface FakeRoom {
  connect: ReturnType<typeof vi.fn>;
  disconnect: ReturnType<typeof vi.fn>;
  on: ReturnType<typeof vi.fn>;
  state: string;
  __handlers: Map<string, Array<(...args: unknown[]) => void>>;
  __emit: (event: string, ...args: unknown[]) => void;
}

const hoisted = vi.hoisted(() => ({
  roomInstances: [] as FakeRoom[],
}));

vi.mock("livekit-client", () => {
  // On déclare une vraie classe — `new RoomMock()` retourne une instance dont
  // les propriétés sont assignées dans le constructeur. Avec `vi.fn()` seul,
  // le mock instance écrase le retour du factory et `room.on` se retrouve
  // undefined. Une classe explicite contourne le problème.
  class RoomMock {
    public connect: ReturnType<typeof vi.fn>;
    public disconnect: ReturnType<typeof vi.fn>;
    public on: ReturnType<typeof vi.fn>;
    public state: string;
    public __handlers: Map<string, Array<(...args: unknown[]) => void>>;
    public __emit: (event: string, ...args: unknown[]) => void;

    constructor() {
      const handlers = new Map<
        string,
        Array<(...args: unknown[]) => void>
      >();
      this.__handlers = handlers;
      this.state = "disconnected";

      this.connect = vi.fn().mockImplementation(() => {
        this.state = "connected";
        return Promise.resolve();
      });
      this.disconnect = vi.fn().mockImplementation(() => {
        this.state = "disconnected";
        return Promise.resolve();
      });
      this.on = vi
        .fn()
        .mockImplementation(
          (event: string, handler: (...args: unknown[]) => void) => {
            const list = handlers.get(event) ?? [];
            list.push(handler);
            handlers.set(event, list);
            return this;
          },
        );
      this.__emit = (event: string, ...args: unknown[]): void => {
        (handlers.get(event) ?? []).forEach((h) => h(...args));
      };

      hoisted.roomInstances.push(this as unknown as FakeRoom);
    }
  }

  return {
    Room: RoomMock,
    RoomEvent: {
      Connected: "connected",
      Disconnected: "disconnected",
      Reconnecting: "reconnecting",
      Reconnected: "reconnected",
      TrackSubscribed: "trackSubscribed",
    },
    Track: {
      Kind: { Audio: "audio", Video: "video", Unknown: "unknown" },
    },
  };
});

// Import APRÈS le vi.mock pour que LiveKitClient utilise la version mockée.
import { LiveKitClient } from "../LiveKitClient";

const roomInstances = hoisted.roomInstances;

// ─── Helpers ─────────────────────────────────────────────────────────────────

/** Crée un faux RemoteAudioTrack avec une méthode `attach()` qui retourne
 *  un HTMLAudioElement détaché du DOM. */
function makeFakeAudioTrack(): {
  track: { kind: string; attach: ReturnType<typeof vi.fn> };
  audioElement: HTMLAudioElement;
} {
  const audioElement = document.createElement("audio");
  return {
    track: {
      kind: "audio",
      attach: vi.fn().mockReturnValue(audioElement),
    },
    audioElement,
  };
}

function makeFakeVideoTrack(): { kind: string; attach: ReturnType<typeof vi.fn> } {
  return {
    kind: "video",
    attach: vi.fn(),
  };
}

beforeEach(() => {
  roomInstances.length = 0;
});

afterEach(() => {
  vi.clearAllMocks();
});

// ─── Tests ──────────────────────────────────────────────────────────────────

describe("LiveKitClient", () => {
  it("connect() appelle Room.connect avec url + token", async () => {
    const client = new LiveKitClient({
      url: "wss://livekit.test",
      token: "fake-token",
    });

    await client.connect();

    expect(roomInstances).toHaveLength(1);
    expect(roomInstances[0].connect).toHaveBeenCalledWith(
      "wss://livekit.test",
      "fake-token",
    );
  });

  it("disconnect() ferme la Room et reset isConnected", async () => {
    const client = new LiveKitClient({
      url: "wss://livekit.test",
      token: "fake-token",
    });
    await client.connect();
    expect(client.isConnected()).toBe(true);

    client.disconnect();

    expect(roomInstances[0].disconnect).toHaveBeenCalled();
    expect(client.isConnected()).toBe(false);
  });

  it("onAudioTrack callback fired quand RemoteAudioTrack subscribed", async () => {
    const onAudioTrack = vi.fn();
    const client = new LiveKitClient({
      url: "wss://livekit.test",
      token: "tk",
      onAudioTrack,
    });
    await client.connect();

    const { track, audioElement } = makeFakeAudioTrack();
    roomInstances[0].__emit("trackSubscribed", track, {}, {});

    expect(onAudioTrack).toHaveBeenCalledTimes(1);
    expect(onAudioTrack).toHaveBeenCalledWith(track, audioElement);
    expect(track.attach).toHaveBeenCalledTimes(1);
  });

  it("track non-audio est ignoré (pas de callback)", async () => {
    const onAudioTrack = vi.fn();
    const client = new LiveKitClient({
      url: "wss://livekit.test",
      token: "tk",
      onAudioTrack,
    });
    await client.connect();

    const videoTrack = makeFakeVideoTrack();
    roomInstances[0].__emit("trackSubscribed", videoTrack, {}, {});

    expect(onAudioTrack).not.toHaveBeenCalled();
    expect(videoTrack.attach).not.toHaveBeenCalled();
  });

  it("onConnected callback fired sur RoomEvent.Connected", async () => {
    const onConnected = vi.fn();
    const client = new LiveKitClient({
      url: "wss://livekit.test",
      token: "tk",
      onConnected,
    });
    await client.connect();

    roomInstances[0].__emit("connected");

    expect(onConnected).toHaveBeenCalledTimes(1);
  });

  it("onDisconnected callback fired sur RoomEvent.Disconnected avec la reason", async () => {
    const onDisconnected = vi.fn();
    const client = new LiveKitClient({
      url: "wss://livekit.test",
      token: "tk",
      onDisconnected,
    });
    await client.connect();

    // Reason = enum numérique côté livekit-client (DisconnectReason.CLIENT_INITIATED = 1).
    roomInstances[0].__emit("disconnected", 1);

    expect(onDisconnected).toHaveBeenCalledTimes(1);
    expect(onDisconnected).toHaveBeenCalledWith(1);
  });

  it("onReconnecting / onReconnected fired sur les RoomEvent correspondants", async () => {
    const onReconnecting = vi.fn();
    const onReconnected = vi.fn();
    const client = new LiveKitClient({
      url: "wss://livekit.test",
      token: "tk",
      onReconnecting,
      onReconnected,
    });
    await client.connect();

    roomInstances[0].__emit("reconnecting");
    roomInstances[0].__emit("reconnected");

    expect(onReconnecting).toHaveBeenCalledTimes(1);
    expect(onReconnected).toHaveBeenCalledTimes(1);
  });

  it("isConnected() reflète l'état Room", async () => {
    const client = new LiveKitClient({
      url: "wss://livekit.test",
      token: "tk",
    });

    expect(client.isConnected()).toBe(false);

    await client.connect();
    expect(client.isConnected()).toBe(true);

    client.disconnect();
    expect(client.isConnected()).toBe(false);
  });

  it("connect() 2 fois ne re-instancie pas la Room", async () => {
    const client = new LiveKitClient({
      url: "wss://livekit.test",
      token: "tk",
    });

    await client.connect();
    await client.connect();

    expect(roomInstances).toHaveLength(1);
    expect(roomInstances[0].connect).toHaveBeenCalledTimes(1);
  });

  it("disconnect() avant connect est un no-op", () => {
    const client = new LiveKitClient({
      url: "wss://livekit.test",
      token: "tk",
    });

    expect(() => client.disconnect()).not.toThrow();
    expect(client.isConnected()).toBe(false);
  });

  it("getRoom() retourne null avant connect, l'instance après", async () => {
    const client = new LiveKitClient({
      url: "wss://livekit.test",
      token: "tk",
    });
    expect(client.getRoom()).toBeNull();

    await client.connect();
    expect(client.getRoom()).toBe(roomInstances[0]);

    client.disconnect();
    expect(client.getRoom()).toBeNull();
  });
});
