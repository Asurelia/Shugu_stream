/**
 * Tests — `ViewerEventsClient` (Sprint D PR D-7).
 *
 * Couverture :
 *   - `connect()` ouvre une WebSocket avec le token comme `Sec-WebSocket-Protocol`.
 *   - Réception d'un payload `scene.apply` valide → `onSceneApply` callback.
 *   - Réception d'un payload `voice.interrupt` valide → `onInterrupt` callback.
 *   - Réception du `hello` initial → ignoré silencieusement (pas de warn).
 *   - Payload mal formé / unknown type → ignoré + log warn (pas de crash).
 *   - Reconnect exponentiel après close non-terminal (1006).
 *   - Pas de reconnect après close terminal (1008 policy / 4xxx auth).
 *   - `disconnect()` ferme la socket et stoppe les reconnect.
 *   - `isConnected()` reflète l'état WebSocket.
 *
 * Stratégie : on stub `globalThis.WebSocket` avec une classe mock qui expose
 * `__triggerOpen`, `__triggerMessage`, `__triggerClose` pour piloter le cycle
 * de vie depuis les tests. jsdom 24 ne ship pas de WebSocket, donc on doit
 * fournir notre propre stub (pattern miroir de LiveKitClient.test.ts qui
 * vi.mock le SDK).
 */

import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";

// ─── Mock WebSocket ──────────────────────────────────────────────────────────
//
// jsdom 24 ne ship pas de WebSocket — on stub un mock minimal qui :
//   - capture `url` + `protocols` (auth subprotocol)
//   - expose `readyState` (CONNECTING/OPEN/CLOSED)
//   - permet aux tests de piloter le cycle de vie via __triggerOpen/Message/Close
//
// On utilise une class plutôt qu'une interface + factory pour rester proche
// de l'API browser native (constructor signature + readonly constants).

class MockWebSocket {
  public static readonly CONNECTING = 0;
  public static readonly OPEN = 1;
  public static readonly CLOSING = 2;
  public static readonly CLOSED = 3;

  // Constants exposés sur l'instance (cohérence avec WebSocket browser).
  public readonly CONNECTING = 0;
  public readonly OPEN = 1;
  public readonly CLOSING = 2;
  public readonly CLOSED = 3;

  public url: string;
  public protocols: string | string[] | undefined;
  public readyState: number = MockWebSocket.CONNECTING;
  public onopen: ((ev: Event) => void) | null = null;
  public onmessage: ((ev: MessageEvent) => void) | null = null;
  public onclose: ((ev: CloseEvent) => void) | null = null;
  public onerror: ((ev: Event) => void) | null = null;

  // `close` est une vi.fn() pour permettre les assertions
  // `expect(socket.close).toHaveBeenCalled()`.
  public close = vi.fn((code?: number, reason?: string): void => {
    this.readyState = MockWebSocket.CLOSED;
    this.onclose?.({ code: code ?? 1000, reason: reason ?? "" } as CloseEvent);
  });
  public send = vi.fn();

  constructor(url: string, protocols?: string | string[]) {
    this.url = url;
    this.protocols = protocols;
    sockets.push(this);
  }

  /** Trigger l'event `open` (handshake terminée). */
  public __triggerOpen(): void {
    this.readyState = MockWebSocket.OPEN;
    this.onopen?.(new Event("open"));
  }

  /** Trigger un `message` reçu (auto-stringify si non-string). */
  public __triggerMessage(data: unknown): void {
    const payload = typeof data === "string" ? data : JSON.stringify(data);
    this.onmessage?.({ data: payload } as MessageEvent);
  }

  /** Trigger un `close` avec code + reason (simule le serveur qui ferme). */
  public __triggerClose(code: number, reason: string = ""): void {
    this.readyState = MockWebSocket.CLOSED;
    this.onclose?.({ code, reason } as CloseEvent);
  }
}

const sockets: MockWebSocket[] = [];

// On installe le stub avant tout import qui pourrait toucher `WebSocket`.
beforeEach(() => {
  sockets.length = 0;
  vi.useFakeTimers();
  // @ts-expect-error — assignation runtime pour stub global jsdom.
  globalThis.WebSocket = MockWebSocket;
});

afterEach(() => {
  vi.useRealTimers();
  vi.clearAllMocks();
});

// Import APRÈS le stub pour que tout import implicite voit MockWebSocket.
import { ViewerEventsClient } from "../ViewerEventsClient";

// ─── Helpers ─────────────────────────────────────────────────────────────────

const FAKE_URL = "ws://localhost:8000/ws/viewer/events";
const FAKE_TOKEN = "header.payload.signature";

function buildClient(overrides: Partial<{
  onSceneApply: ReturnType<typeof vi.fn>;
  onInterrupt: ReturnType<typeof vi.fn>;
  onConnected: ReturnType<typeof vi.fn>;
  onDisconnected: ReturnType<typeof vi.fn>;
}> = {}): {
  client: ViewerEventsClient;
  onSceneApply: ReturnType<typeof vi.fn>;
  onInterrupt: ReturnType<typeof vi.fn>;
  onConnected: ReturnType<typeof vi.fn>;
  onDisconnected: ReturnType<typeof vi.fn>;
} {
  const onSceneApply = overrides.onSceneApply ?? vi.fn();
  const onInterrupt = overrides.onInterrupt ?? vi.fn();
  const onConnected = overrides.onConnected ?? vi.fn();
  const onDisconnected = overrides.onDisconnected ?? vi.fn();

  const client = new ViewerEventsClient({
    url: FAKE_URL,
    token: FAKE_TOKEN,
    onSceneApply,
    onInterrupt,
    onConnected,
    onDisconnected,
  });

  return { client, onSceneApply, onInterrupt, onConnected, onDisconnected };
}

// ─── Tests ──────────────────────────────────────────────────────────────────

describe("ViewerEventsClient — connect & auth", () => {
  it("connect() ouvre une WebSocket vers l'URL avec le token comme Sec-WebSocket-Protocol", async () => {
    const { client } = buildClient();
    await client.connect();
    expect(sockets).toHaveLength(1);
    expect(sockets[0].url).toBe(FAKE_URL);
    // Le SDK browser passe le subprotocol comme 2e arg du constructeur.
    // Une string simple correspond à `Sec-WebSocket-Protocol: <token>`.
    expect(sockets[0].protocols).toBe(FAKE_TOKEN);
  });

  it("onConnected est appelé après le hello-frame du backend", async () => {
    const { client, onConnected } = buildClient();
    await client.connect();
    sockets[0].__triggerOpen();
    sockets[0].__triggerMessage({
      type: "hello",
      session_id: "voice-sess-abc",
      expires_at: 1234567890,
    });
    expect(onConnected).toHaveBeenCalledTimes(1);
  });

  it("isConnected() reflète l'état OPEN de la socket", async () => {
    const { client } = buildClient();
    expect(client.isConnected()).toBe(false);
    await client.connect();
    expect(client.isConnected()).toBe(false); // toujours CONNECTING
    sockets[0].__triggerOpen();
    expect(client.isConnected()).toBe(true);
  });
});

describe("ViewerEventsClient — dispatch des events", () => {
  it("scene.apply valide → onSceneApply appelé avec le payload typé", async () => {
    const { client, onSceneApply } = buildClient();
    await client.connect();
    sockets[0].__triggerOpen();

    const event = {
      type: "scene.apply",
      kind: "say_emotion",
      id: "joy",
      ts: "2026-05-08T14:23:11.456Z",
      audio_at_ms: 1240,
      session_id: "voice-sess-abc",
    };
    sockets[0].__triggerMessage(event);

    expect(onSceneApply).toHaveBeenCalledTimes(1);
    expect(onSceneApply).toHaveBeenCalledWith(event);
  });

  it("voice.interrupt valide → onInterrupt appelé avec le payload typé", async () => {
    const { client, onInterrupt } = buildClient();
    await client.connect();
    sockets[0].__triggerOpen();

    const event = {
      type: "voice.interrupt",
      session_id: "voice-sess-abc",
      reason: "vad_detected",
      ts: "2026-05-08T14:23:13.001Z",
    };
    sockets[0].__triggerMessage(event);

    expect(onInterrupt).toHaveBeenCalledTimes(1);
    expect(onInterrupt).toHaveBeenCalledWith(event);
  });

  it("hello-frame initial → silencieusement ignoré (pas d'appel callback)", async () => {
    const { client, onSceneApply, onInterrupt } = buildClient();
    await client.connect();
    sockets[0].__triggerOpen();

    sockets[0].__triggerMessage({
      type: "hello",
      session_id: "voice-sess-abc",
      expires_at: 1234567890,
    });

    expect(onSceneApply).not.toHaveBeenCalled();
    expect(onInterrupt).not.toHaveBeenCalled();
  });

  it("payload type inconnu → ignoré (forward-compat) sans crash", async () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const { client, onSceneApply, onInterrupt } = buildClient();
    await client.connect();
    sockets[0].__triggerOpen();

    sockets[0].__triggerMessage({
      type: "future.event_type",
      foo: "bar",
    });

    expect(onSceneApply).not.toHaveBeenCalled();
    expect(onInterrupt).not.toHaveBeenCalled();
    warnSpy.mockRestore();
  });

  it("payload mal formé (kind invalide) → ignoré + warn", async () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const { client, onSceneApply } = buildClient();
    await client.connect();
    sockets[0].__triggerOpen();

    sockets[0].__triggerMessage({
      type: "scene.apply",
      kind: "not_a_real_kind",
      // missing `id`, missing `ts` → Zod refuse
    });

    expect(onSceneApply).not.toHaveBeenCalled();
    expect(warnSpy).toHaveBeenCalled();
    warnSpy.mockRestore();
  });

  it("payload non-JSON → ignoré + warn (pas de crash)", async () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const { client, onSceneApply } = buildClient();
    await client.connect();
    sockets[0].__triggerOpen();

    sockets[0].__triggerMessage("not valid json {{{");

    expect(onSceneApply).not.toHaveBeenCalled();
    expect(warnSpy).toHaveBeenCalled();
    warnSpy.mockRestore();
  });
});

describe("ViewerEventsClient — reconnect exponentiel", () => {
  it("close 1006 (transient) → reconnect après ~200ms", async () => {
    const { client, onDisconnected } = buildClient();
    await client.connect();
    sockets[0].__triggerOpen();

    sockets[0].__triggerClose(1006, "abrupt");
    expect(onDisconnected).toHaveBeenCalledTimes(1);
    expect(sockets).toHaveLength(1); // pas encore reconnecté

    await vi.advanceTimersByTimeAsync(250);
    expect(sockets).toHaveLength(2); // nouvelle socket créée
    expect(sockets[1].protocols).toBe(FAKE_TOKEN);
  });

  it("backoff exponentiel : 200 → 500 → 1000 → 2000ms cap", async () => {
    const { client } = buildClient();
    await client.connect();

    // 1ère tentative : initiale échoue avant open.
    sockets[0].__triggerClose(1006);
    await vi.advanceTimersByTimeAsync(250);
    expect(sockets).toHaveLength(2);

    // 2ème tentative.
    sockets[1].__triggerClose(1006);
    await vi.advanceTimersByTimeAsync(550);
    expect(sockets).toHaveLength(3);

    // 3ème tentative.
    sockets[2].__triggerClose(1006);
    await vi.advanceTimersByTimeAsync(1100);
    expect(sockets).toHaveLength(4);

    // 4ème tentative — cap à 2000ms.
    sockets[3].__triggerClose(1006);
    await vi.advanceTimersByTimeAsync(2100);
    expect(sockets).toHaveLength(5);

    // 5ème tentative — toujours capé à 2000.
    sockets[4].__triggerClose(1006);
    await vi.advanceTimersByTimeAsync(2100);
    expect(sockets).toHaveLength(6);
  });

  it("close 1000 (normal) → pas de reconnect", async () => {
    const { client } = buildClient();
    await client.connect();
    sockets[0].__triggerOpen();

    sockets[0].__triggerClose(1000, "normal closure");
    await vi.advanceTimersByTimeAsync(5000);

    expect(sockets).toHaveLength(1); // pas de nouvelle socket
  });

  it("close 1008 (policy violation) → pas de reconnect (terminal)", async () => {
    const { client } = buildClient();
    await client.connect();
    sockets[0].__triggerOpen();

    sockets[0].__triggerClose(1008, "session_id mismatch");
    await vi.advanceTimersByTimeAsync(5000);

    expect(sockets).toHaveLength(1);
  });

  it("close 4001 (auth invalid, custom range) → pas de reconnect (terminal)", async () => {
    const { client } = buildClient();
    await client.connect();
    sockets[0].__triggerOpen();

    sockets[0].__triggerClose(4001, "token expired");
    await vi.advanceTimersByTimeAsync(5000);

    expect(sockets).toHaveLength(1);
  });

  it("backoff reset après reconnect réussi (open + hello)", async () => {
    const { client } = buildClient();
    await client.connect();
    sockets[0].__triggerOpen();

    // Drop, reconnect tentative #1 (200ms).
    sockets[0].__triggerClose(1006);
    await vi.advanceTimersByTimeAsync(250);
    expect(sockets).toHaveLength(2);

    // Reconnect réussi → hello.
    sockets[1].__triggerOpen();
    sockets[1].__triggerMessage({
      type: "hello",
      session_id: "abc",
      expires_at: 0,
    });

    // Nouveau drop → backoff doit repartir à 200ms (pas continuer à 500).
    sockets[1].__triggerClose(1006);
    await vi.advanceTimersByTimeAsync(250);
    expect(sockets).toHaveLength(3);
  });
});

describe("ViewerEventsClient — disconnect", () => {
  it("disconnect() ferme la socket et empêche tout reconnect", async () => {
    const { client } = buildClient();
    await client.connect();
    sockets[0].__triggerOpen();

    client.disconnect();
    expect(sockets[0].close).toHaveBeenCalled();

    // Même si la close handler fire avec un code transient, on ne doit pas
    // reconnect après un disconnect explicite.
    await vi.advanceTimersByTimeAsync(5000);
    expect(sockets).toHaveLength(1);
  });

  it("disconnect() avant connect est un no-op", () => {
    const { client } = buildClient();
    expect(() => client.disconnect()).not.toThrow();
    expect(client.isConnected()).toBe(false);
  });

  it("disconnect() pendant la phase de reconnect annule le timer", async () => {
    const { client } = buildClient();
    await client.connect();
    sockets[0].__triggerOpen();

    sockets[0].__triggerClose(1006);
    expect(sockets).toHaveLength(1);

    // disconnect() avant l'écoulement des 200ms.
    client.disconnect();
    await vi.advanceTimersByTimeAsync(5000);

    expect(sockets).toHaveLength(1); // aucun reconnect armé
  });
});
