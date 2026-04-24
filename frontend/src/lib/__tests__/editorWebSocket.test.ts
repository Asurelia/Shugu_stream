/**
 * Tests unit — `EditorWebSocket` (Phase D).
 *
 * Approche : on injecte un `WebSocketCtor` mocké via l'option constructor
 * pour ne jamais toucher le WebSocket global du runtime. Chaque instance
 * mocquée expose `triggerOpen()`, `triggerMessage(event)`, `triggerClose()`
 * pour piloter les callbacks de la classe sous test.
 *
 * Coverage :
 *  - subscribe() → envoie la bonne frame JSON
 *  - sendDraftUpdate() → envoie le type + délégation du nonce
 *  - sendPreviewPush() → envoie le bon payload
 *  - réception de hello → onOpen(ou pas, selon le spec) mais onEvent appelé
 *  - réception de ping serveur → envoi automatique de pong
 *  - reconnect après close (backoff 500ms initial, doublé à chaque échec)
 *  - close() après manuel → pas de reconnect
 */

import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  EditorWebSocket,
  type EditorServerEvent,
} from "../editorWebSocket";

/* ────────── MOCK WEBSOCKET ────────── */

/**
 * Mock minimal de l'API WebSocket. Instancié par `EditorWebSocket` via
 * l'option `WebSocketCtor`. Expose `instances[]` (tableau de mocks
 * successifs — utile pour tracer reconnect).
 */
class MockWebSocket {
  static OPEN = 1;
  static CLOSED = 3;

  url: string;
  readyState = 0; // CONNECTING
  sent: string[] = [];

  onopen: ((ev: Event) => void) | null = null;
  onclose: ((ev: CloseEvent) => void) | null = null;
  onerror: ((ev: Event) => void) | null = null;
  onmessage: ((ev: MessageEvent) => void) | null = null;

  // readyState constants (static pas toujours lisibles dans les closures JS
  // mock — on les duplique côté instance pour que `ws.readyState === WebSocket.OPEN`
  // marche bien dans la classe sous test).
  static CONNECTING = 0;
  static CLOSING = 2;

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
  }

  send(data: string): void {
    this.sent.push(data);
  }

  close(): void {
    this.readyState = MockWebSocket.CLOSED;
    // Simulate async close event dispatch
    queueMicrotask(() => this.onclose?.(new CloseEvent("close")));
  }

  /* Helpers pour piloter le mock depuis les tests */
  triggerOpen(): void {
    this.readyState = MockWebSocket.OPEN;
    this.onopen?.(new Event("open"));
  }

  triggerMessage(event: EditorServerEvent): void {
    this.onmessage?.(
      new MessageEvent("message", { data: JSON.stringify(event) }),
    );
  }

  triggerClose(): void {
    this.readyState = MockWebSocket.CLOSED;
    this.onclose?.(new CloseEvent("close"));
  }

  static instances: MockWebSocket[] = [];

  static reset(): void {
    MockWebSocket.instances = [];
  }
}

/* ────────── TESTS ────────── */

beforeEach(() => {
  MockWebSocket.reset();
  vi.useFakeTimers();
});

// Test fixture URL uses wss:// — jamais contactée (MockWebSocket ne fait
// aucune I/O réseau). Secure scheme utilisé par principe même pour les
// tests pour éviter les false positives du scanner de sécurité.
const OPTS_BASE = {
  url: "wss://test.local/ws/editor",
  WebSocketCtor: MockWebSocket as unknown as typeof WebSocket,
};

describe("EditorWebSocket — connect + lifecycle", () => {
  it("crée une WebSocket vers l'url fournie au construct", () => {
    const events: EditorServerEvent[] = [];
    new EditorWebSocket({
      ...OPTS_BASE,
      onEvent: (e) => events.push(e),
    });
    expect(MockWebSocket.instances).toHaveLength(1);
    expect(MockWebSocket.instances[0].url).toBe("wss://test.local/ws/editor");
  });

  it("appelle onOpen + onStatus quand la WS passe OPEN", () => {
    const events: EditorServerEvent[] = [];
    const onOpen = vi.fn();
    const onStatus = vi.fn();
    new EditorWebSocket({
      ...OPTS_BASE,
      onEvent: (e) => events.push(e),
      onOpen,
      onStatus,
    });
    MockWebSocket.instances[0].triggerOpen();
    expect(onOpen).toHaveBeenCalledTimes(1);
    expect(onStatus).toHaveBeenCalledWith("open");
  });

  it("forward les events reçus au callback onEvent", () => {
    const events: EditorServerEvent[] = [];
    new EditorWebSocket({
      ...OPTS_BASE,
      onEvent: (e) => events.push(e),
    });
    const ws = MockWebSocket.instances[0];
    ws.triggerOpen();
    ws.triggerMessage({ type: "hello", operator: "alice", protocol_version: 1 });
    expect(events).toHaveLength(1);
    expect(events[0]).toEqual({
      type: "hello",
      operator: "alice",
      protocol_version: 1,
    });
  });
});

describe("EditorWebSocket — client → server messages", () => {
  it("subscribe(sceneId) envoie la bonne frame JSON", () => {
    const ec = new EditorWebSocket({
      ...OPTS_BASE,
      onEvent: () => {},
    });
    MockWebSocket.instances[0].triggerOpen();
    ec.subscribe("scene-123");
    const frames = MockWebSocket.instances[0].sent.map((s) => JSON.parse(s));
    expect(frames).toEqual([{ type: "subscribe", scene_id: "scene-123" }]);
  });

  it("sendDraftUpdate envoie type + delta + nonce fourni", () => {
    const ec = new EditorWebSocket({
      ...OPTS_BASE,
      onEvent: () => {},
    });
    MockWebSocket.instances[0].triggerOpen();
    ec.sendDraftUpdate("scene-abc", { fov: 60 }, "my-nonce");
    const [frame] = MockWebSocket.instances[0].sent.map((s) => JSON.parse(s));
    expect(frame).toEqual({
      type: "draft.update",
      scene_id: "scene-abc",
      delta: { fov: 60 },
      nonce: "my-nonce",
    });
  });

  it("sendDraftUpdate sans nonce explicite en génère un", () => {
    const ec = new EditorWebSocket({
      ...OPTS_BASE,
      onEvent: () => {},
    });
    MockWebSocket.instances[0].triggerOpen();
    ec.sendDraftUpdate("scene-abc", { fov: 60 });
    const [frame] = MockWebSocket.instances[0].sent.map((s) => JSON.parse(s));
    expect(frame.type).toBe("draft.update");
    expect(typeof frame.nonce).toBe("string");
    expect(frame.nonce.length).toBeGreaterThan(0);
  });

  it("sendPreviewPush envoie le bon payload", () => {
    const ec = new EditorWebSocket({
      ...OPTS_BASE,
      onEvent: () => {},
    });
    MockWebSocket.instances[0].triggerOpen();
    ec.sendPreviewPush("scene-abc", { camera: { fov: 75 } });
    const [frame] = MockWebSocket.instances[0].sent.map((s) => JSON.parse(s));
    expect(frame).toEqual({
      type: "preview.push",
      scene_id: "scene-abc",
      payload: { camera: { fov: 75 } },
    });
  });

  it("drop silencieux les frames si la WS n'est pas OPEN", () => {
    const ec = new EditorWebSocket({
      ...OPTS_BASE,
      onEvent: () => {},
    });
    // readyState = CONNECTING (0) → send ne devrait rien envoyer.
    ec.subscribe("scene-xyz");
    expect(MockWebSocket.instances[0].sent).toEqual([]);
  });
});

describe("EditorWebSocket — heartbeat (server → client ping)", () => {
  it("répond automatiquement pong quand le serveur envoie ping", () => {
    const ec = new EditorWebSocket({
      ...OPTS_BASE,
      onEvent: () => {},
    });
    const ws = MockWebSocket.instances[0];
    ws.triggerOpen();
    // Simulate server heartbeat ping
    ws.triggerMessage({ type: "ping", t: 42 });
    const frames = ws.sent.map((s) => JSON.parse(s));
    expect(frames).toEqual([{ type: "pong" }]);
  });

  it("notifie quand même le consumer via onEvent pour le ping reçu", () => {
    const events: EditorServerEvent[] = [];
    const ec = new EditorWebSocket({
      ...OPTS_BASE,
      onEvent: (e) => events.push(e),
    });
    const ws = MockWebSocket.instances[0];
    ws.triggerOpen();
    ws.triggerMessage({ type: "ping", t: 100 });
    // Le consumer voit le ping (utile pour logging / latency)
    expect(events.some((e) => e.type === "ping")).toBe(true);
  });
});

describe("EditorWebSocket — reconnect", () => {
  it("reconnecte après un close non-manuel (backoff 500ms initial)", async () => {
    const ec = new EditorWebSocket({
      ...OPTS_BASE,
      onEvent: () => {},
    });
    expect(MockWebSocket.instances).toHaveLength(1);
    const ws1 = MockWebSocket.instances[0];
    ws1.triggerOpen();
    ws1.triggerClose(); // simule drop
    // Avance le temps — 500ms → doit scheduler un nouveau ctor
    vi.advanceTimersByTime(500);
    expect(MockWebSocket.instances).toHaveLength(2);
    expect(MockWebSocket.instances[1].url).toBe(OPTS_BASE.url);
    ec.close(); // cleanup
  });

  it("close() manuel ne déclenche PAS de reconnect", async () => {
    const ec = new EditorWebSocket({
      ...OPTS_BASE,
      onEvent: () => {},
    });
    const ws1 = MockWebSocket.instances[0];
    ws1.triggerOpen();
    ec.close();
    // Même après 10s de wait, pas de nouvelle instance.
    vi.advanceTimersByTime(10000);
    expect(MockWebSocket.instances).toHaveLength(1);
  });

  it("double le délai à chaque tentative (500 → 1000 → ...)", async () => {
    const ec = new EditorWebSocket({
      ...OPTS_BASE,
      onEvent: () => {},
    });
    // Tentative 1 : instance 0 (directe au new)
    MockWebSocket.instances[0].triggerClose();
    vi.advanceTimersByTime(499);
    expect(MockWebSocket.instances).toHaveLength(1); // pas encore
    vi.advanceTimersByTime(1);
    expect(MockWebSocket.instances).toHaveLength(2); // 500ms atteint

    // Tentative 2 : instance 1 close sans jamais s'ouvrir → next delay = 1000ms
    MockWebSocket.instances[1].triggerClose();
    vi.advanceTimersByTime(999);
    expect(MockWebSocket.instances).toHaveLength(2);
    vi.advanceTimersByTime(1);
    expect(MockWebSocket.instances).toHaveLength(3);
    ec.close();
  });
});
