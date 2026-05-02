/**
 * Tests unit — `editorPopout` helper (Phase G).
 *
 * Approche : on remplace le `BroadcastChannel` global par une implémentation
 * mock qui capture tous les `postMessage` et permet de déclencher des
 * `message` events à la main. Après chaque test on reset le singleton
 * interne du helper pour éviter la fuite entre suites.
 *
 * Coverage :
 *  - publishPopout : debounce `state-sync` (collapse N appels → 1 message)
 *  - publishPopout : signaux ponctuels envoyés immédiatement (pas de debounce)
 *  - publishPopout : injection automatique de `ts`, `senderOrigin`, `senderNonce`
 *  - subscribePopout : dispatch seulement si panelKey match
 *  - subscribePopout : rejet si senderOrigin mismatch (sécurité tab-scope)
 *  - subscribePopout : rejet si senderNonce mismatch (sécurité cross-tab — H2)
 *  - subscribePopout : rejet si forme invalide (missing fields)
 *  - subscribePopout : cleanup retire le listener (pas de double-dispatch)
 *  - openPanelWindow : appelle window.open avec l'URL + nonce + features attendus
 *  - openPanelWindow : retourne null si BroadcastChannel indisponible
 *  - flushPopout : flush le dernier state-sync queued
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/* ────────── MOCK BROADCASTCHANNEL ────────── */

/**
 * Mock qui réplique exactement l'API navigateur et fanout les postMessage
 * à toutes les instances actives sur le même `name`. Nécessaire pour que
 * les tests multi-instance (parent ↔ popout) fonctionnent même si on ne
 * crée qu'un singleton côté helper.
 */
type MockListener = (ev: MessageEvent) => void;

class MockBroadcastChannel {
  static instancesByName = new Map<string, MockBroadcastChannel[]>();

  public name: string;
  public closed = false;
  private listeners = new Set<MockListener>();
  public posted: unknown[] = [];

  constructor(name: string) {
    this.name = name;
    const arr = MockBroadcastChannel.instancesByName.get(name) ?? [];
    arr.push(this);
    MockBroadcastChannel.instancesByName.set(name, arr);
  }

  postMessage(data: unknown): void {
    if (this.closed) {
      throw new DOMException("Channel closed", "InvalidStateError");
    }
    this.posted.push(data);
    const peers = MockBroadcastChannel.instancesByName.get(this.name) ?? [];
    // Conform to spec : le canal émetteur NE reçoit PAS ses propres messages.
    for (const peer of peers) {
      if (peer === this || peer.closed) continue;
      const ev = new MessageEvent("message", { data });
      peer.listeners.forEach((l) => l(ev));
    }
  }

  addEventListener(type: string, listener: MockListener): void {
    if (type !== "message" || !listener) return;
    this.listeners.add(listener);
  }

  removeEventListener(type: string, listener: MockListener): void {
    if (type !== "message" || !listener) return;
    this.listeners.delete(listener);
  }

  close(): void {
    this.closed = true;
    this.listeners.clear();
    const arr = MockBroadcastChannel.instancesByName.get(this.name) ?? [];
    const filtered = arr.filter((c) => c !== this);
    if (filtered.length === 0) {
      MockBroadcastChannel.instancesByName.delete(this.name);
    } else {
      MockBroadcastChannel.instancesByName.set(this.name, filtered);
    }
  }

  /** Helper test : dispatch un message arbitraire comme si reçu du canal. */
  triggerMessage(data: unknown): void {
    const ev = new MessageEvent("message", { data });
    this.listeners.forEach((l) => l(ev));
  }

  dispatchEvent(_ev: Event): boolean {
    return true;
  }

  static reset(): void {
    MockBroadcastChannel.instancesByName.clear();
  }
}

/* ────────── TEST FIXTURE ────────── */

/**
 * Nonce fixture déterministe utilisé par tous les tests. On le pose côté
 * helper via `setPopoutNonce` AVANT toute opération publish/subscribe
 * (sinon le helper lazy-init un nonce aléatoire qui ne matchera pas avec
 * nos messages forgés).
 */
const TEST_NONCE = "test-nonce-fixture-uuid-0000";

beforeEach(() => {
  // Swap global BroadcastChannel pour notre mock. jsdom en ship un stub no-op
  // via vitest.setup.ts — on l'écrase pour obtenir un vrai fanout.
  (globalThis as Record<string, unknown>).BroadcastChannel =
    MockBroadcastChannel as unknown as typeof BroadcastChannel;
  // Fixe l'origin pour que publishPopout embarque une valeur déterministe.
  // jsdom expose par défaut `http://localhost` ou équivalent ; on s'assure.
  if (typeof window !== "undefined") {
    Object.defineProperty(window, "location", {
      value: { ...window.location, origin: "http://localhost:3005" },
      writable: true,
    });
    // Clean sessionStorage pour que chaque test reparte sur un nonce frais
    // (pas de fuite via la clé POPOUT_NONCE_STORAGE_KEY persistée par un
    // test précédent).
    if (window.sessionStorage) {
      try {
        window.sessionStorage.clear();
      } catch {
        /* certains envs jsdom restreignent l'accès */
      }
    }
  }
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  MockBroadcastChannel.reset();
});

// Import APRÈS le setup pour que le helper voie le mock dès son init.
// On re-importe fraîchement à chaque test via vi.resetModules() pour purger
// le singleton interne. On installe le nonce de test juste après l'import
// pour figer la valeur — sinon le lazy-init du helper génèrerait un UUID
// random qui ne matcherait pas nos fixtures.
async function loadHelper() {
  vi.resetModules();
  const helper = await import("../editorPopout");
  helper.setPopoutNonce(TEST_NONCE);
  return helper;
}

/* ────────── TESTS ────────── */

describe("editorPopout — publishPopout debounce", () => {
  it("collapse 3 appels state-sync rapprochés en un seul message", async () => {
    const helper = await loadHelper();
    // Un subscriber sur le même canal pour observer ce qui arrive.
    const receiver = new MockBroadcastChannel("scene-editor");
    const received: unknown[] = [];
    receiver.addEventListener("message", (ev) => received.push(ev.data));

    helper.publishPopout({
      type: "state-sync",
      panelKey: "inspector",
      origin: "parent",
      payload: { foo: 1 },
    });
    helper.publishPopout({
      type: "state-sync",
      panelKey: "inspector",
      origin: "parent",
      payload: { foo: 2 },
    });
    helper.publishPopout({
      type: "state-sync",
      panelKey: "inspector",
      origin: "parent",
      payload: { foo: 3 },
    });

    // Rien tant que le timer n'a pas expiré.
    expect(received).toHaveLength(0);
    // Avance du temps du debounce (50ms).
    vi.advanceTimersByTime(helper.POPOUT_PUBLISH_DEBOUNCE_MS);

    expect(received).toHaveLength(1);
    const msg = received[0] as {
      type: string;
      payload: { foo: number };
      senderOrigin: string;
      senderNonce: string;
    };
    expect(msg.type).toBe("state-sync");
    // Seul le dernier payload survit — c'est tout l'intérêt du debounce.
    expect(msg.payload).toEqual({ foo: 3 });
    expect(msg.senderOrigin).toBe("http://localhost:3005");
    // Le nonce est injecté automatiquement par publishPopout.
    expect(msg.senderNonce).toBe(TEST_NONCE);
  });

  it("envoie immédiatement les signaux ponctuels (popout-ready, etc.)", async () => {
    const helper = await loadHelper();
    const receiver = new MockBroadcastChannel("scene-editor");
    const received: unknown[] = [];
    receiver.addEventListener("message", (ev) => received.push(ev.data));

    helper.publishPopout({
      type: "popout-ready",
      panelKey: "inspector",
      origin: "popout",
    });
    // Pas de timer avancé — le message doit déjà être là.
    expect(received).toHaveLength(1);
    const msg = received[0] as { type: string; panelKey: string };
    expect(msg.type).toBe("popout-ready");
    expect(msg.panelKey).toBe("inspector");
  });

  it("ne mélange pas les debounces de panelKeys différents", async () => {
    const helper = await loadHelper();
    const receiver = new MockBroadcastChannel("scene-editor");
    const received: unknown[] = [];
    receiver.addEventListener("message", (ev) => received.push(ev.data));

    helper.publishPopout({
      type: "state-sync",
      panelKey: "inspector",
      origin: "parent",
      payload: { fov: 60 },
    });
    helper.publishPopout({
      type: "state-sync",
      panelKey: "scene",
      origin: "parent",
      payload: { cam: "A" },
    });
    vi.advanceTimersByTime(helper.POPOUT_PUBLISH_DEBOUNCE_MS);

    // Les deux panels ont leur propre debounce key → 2 messages distincts.
    expect(received).toHaveLength(2);
    const panels = (received as Array<{ panelKey: string }>).map((m) => m.panelKey);
    expect(panels.sort()).toEqual(["inspector", "scene"]);
  });
});

describe("editorPopout — subscribePopout dispatch", () => {
  it("appelle le callback pour un message valide et même panelKey", async () => {
    const helper = await loadHelper();
    const received: Array<{ payload: unknown }> = [];
    const unsubscribe = helper.subscribePopout("inspector", (msg) => {
      received.push({ payload: msg.payload });
    });

    // Envoie depuis une seconde instance mock (sinon pas de fanout : le canal
    // émetteur ne reçoit pas ses propres messages).
    const sender = new MockBroadcastChannel("scene-editor");
    sender.postMessage({
      type: "state-sync",
      origin: "popout",
      panelKey: "inspector",
      ts: Date.now(),
      senderOrigin: "http://localhost:3005",
      senderNonce: TEST_NONCE,
      payload: { hello: "world" },
    });

    expect(received).toEqual([{ payload: { hello: "world" } }]);
    unsubscribe();
  });

  it("NE dispatche PAS un message dont panelKey ne match pas", async () => {
    const helper = await loadHelper();
    const received: unknown[] = [];
    helper.subscribePopout("inspector", (msg) => received.push(msg));

    const sender = new MockBroadcastChannel("scene-editor");
    sender.postMessage({
      type: "state-sync",
      origin: "popout",
      panelKey: "scene", // ≠ inspector
      ts: Date.now(),
      senderOrigin: "http://localhost:3005",
      senderNonce: TEST_NONCE,
      payload: { x: 1 },
    });

    expect(received).toHaveLength(0);
  });

  it("rejette un message dont senderOrigin ne matche pas window.location.origin (sécurité)", async () => {
    const helper = await loadHelper();
    const received: unknown[] = [];
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

    helper.subscribePopout("inspector", (msg) => received.push(msg));

    const sender = new MockBroadcastChannel("scene-editor");
    sender.postMessage({
      type: "state-sync",
      origin: "popout",
      panelKey: "inspector",
      ts: Date.now(),
      senderOrigin: "http://evil.attacker.example", // forgerie
      senderNonce: TEST_NONCE,
      payload: { evil: true },
    });

    expect(received).toHaveLength(0);
    // Le helper log un warning pour tracer l'éviction.
    expect(warnSpy).toHaveBeenCalled();
    const warnCall = warnSpy.mock.calls[0];
    expect(String(warnCall[0])).toContain("mismatched origin");
    warnSpy.mockRestore();
  });

  it("rejette un message dont senderNonce ne matche pas le nonce courant (H2 cross-tab forgery)", async () => {
    // Scénario : un onglet "frère" same-origin (ex: XSS sur autre route)
    // tente de publier un message avec un senderOrigin valide (puisque
    // forcément same-origin par spec BroadcastChannel) mais sans connaître
    // le nonce de notre tab. Doit être droppé + warn.
    const helper = await loadHelper();
    const received: unknown[] = [];
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

    helper.subscribePopout("inspector", (msg) => received.push(msg));

    const sender = new MockBroadcastChannel("scene-editor");
    sender.postMessage({
      type: "state-sync",
      origin: "popout",
      panelKey: "inspector",
      ts: Date.now(),
      senderOrigin: "http://localhost:3005", // origin valide
      senderNonce: "wrong-nonce-from-other-tab", // mais nonce inconnu
      payload: { evil: true },
    });

    expect(received).toHaveLength(0);
    // Warn dédié — on vérifie qu'on a bien le message "mismatched nonce"
    // (différent du "mismatched origin" du test précédent).
    expect(warnSpy).toHaveBeenCalled();
    const warnTexts = warnSpy.mock.calls.map((c) => String(c[0]));
    expect(warnTexts.some((t) => t.includes("mismatched nonce"))).toBe(true);
    warnSpy.mockRestore();
  });

  it("ignore silencieusement un message malformé (missing fields)", async () => {
    const helper = await loadHelper();
    const received: unknown[] = [];
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

    helper.subscribePopout("inspector", (msg) => received.push(msg));

    const sender = new MockBroadcastChannel("scene-editor");
    sender.postMessage({ hello: "not a real message" });
    sender.postMessage({ type: "state-sync" }); // manque origin + panelKey etc.
    sender.postMessage(null);
    sender.postMessage(42);
    // Cas spécifique H2 : un message presque-bien-formé mais sans
    // senderNonce → considéré malformé par isValidMessage (drop silencieux).
    sender.postMessage({
      type: "state-sync",
      origin: "popout",
      panelKey: "inspector",
      ts: Date.now(),
      senderOrigin: "http://localhost:3005",
      // senderNonce manquant — invariant violé
      payload: { a: 1 },
    });

    expect(received).toHaveLength(0);
    // Malformé = drop silencieux (PAS de warn ; les warn sont réservés
    // aux mismatch origin/nonce, qui supposent un message bien-formé).
    expect(warnSpy).not.toHaveBeenCalled();
    warnSpy.mockRestore();
  });

  it("unsubscribe() stoppe les dispatch futurs", async () => {
    const helper = await loadHelper();
    const received: unknown[] = [];
    const unsubscribe = helper.subscribePopout("inspector", (msg) =>
      received.push(msg),
    );

    const sender = new MockBroadcastChannel("scene-editor");
    sender.postMessage({
      type: "state-sync",
      origin: "popout",
      panelKey: "inspector",
      ts: Date.now(),
      senderOrigin: "http://localhost:3005",
      senderNonce: TEST_NONCE,
      payload: { a: 1 },
    });
    expect(received).toHaveLength(1);

    unsubscribe();

    sender.postMessage({
      type: "state-sync",
      origin: "popout",
      panelKey: "inspector",
      ts: Date.now(),
      senderOrigin: "http://localhost:3005",
      senderNonce: TEST_NONCE,
      payload: { a: 2 },
    });
    // Toujours 1 — le unsubscribe a bien remove le listener.
    expect(received).toHaveLength(1);
  });
});

describe("editorPopout — openPanelWindow", () => {
  it("appelle window.open avec l'URL relative + nonce et un nom par panel", async () => {
    const helper = await loadHelper();
    const openSpy = vi
      .spyOn(window, "open")
      .mockImplementation(() => ({ closed: false }) as unknown as Window);

    const win = helper.openPanelWindow("inspector");
    expect(win).not.toBeNull();
    expect(openSpy).toHaveBeenCalledTimes(1);
    const [url, name, features] = openSpy.mock.calls[0];
    // Format attendu : `?panel=inspector&nonce=<TEST_NONCE>`. Le nonce est
    // url-encoded — comme TEST_NONCE ne contient pas de caractères spéciaux,
    // l'encodage est identité.
    expect(url).toBe(
      `/shugu/admin/scene-editor-popout?panel=inspector&` +
        `${helper.POPOUT_NONCE_QUERY_PARAM}=${encodeURIComponent(TEST_NONCE)}`,
    );
    expect(name).toBe("shugu-scene-editor-popout-inspector");
    expect(String(features)).toContain("width=800");
    expect(String(features)).toContain("height=600");
    openSpy.mockRestore();
  });

  it("retourne null si BroadcastChannel est indisponible (fallback gracieux)", async () => {
    // Retire BroadcastChannel global AVANT de loader le helper.
    // eslint-disable-next-line
    const saved = (globalThis as any).BroadcastChannel;
    // eslint-disable-next-line
    (globalThis as any).BroadcastChannel = undefined;

    try {
      const helper = await loadHelper();
      const openSpy = vi.spyOn(window, "open");
      const win = helper.openPanelWindow("inspector");
      expect(win).toBeNull();
      // Aucune fenêtre ouverte non plus — on ne veut pas laisser une popup
      // orpheline qui ne pourrait jamais sync avec le parent.
      expect(openSpy).not.toHaveBeenCalled();
      openSpy.mockRestore();
    } finally {
      // eslint-disable-next-line
      (globalThis as any).BroadcastChannel = saved;
    }
  });
});

describe("editorPopout — flushPopout", () => {
  it("flush le dernier state-sync queued avant son debounce naturel", async () => {
    const helper = await loadHelper();
    const receiver = new MockBroadcastChannel("scene-editor");
    const received: unknown[] = [];
    receiver.addEventListener("message", (ev) => received.push(ev.data));

    helper.publishPopout({
      type: "state-sync",
      panelKey: "inspector",
      origin: "parent",
      payload: { last: true },
    });
    // Sans flush, le timer de 50ms n'a pas encore expiré → 0 message.
    expect(received).toHaveLength(0);

    helper.flushPopout();
    expect(received).toHaveLength(1);
    const msg = received[0] as { payload: { last: boolean } };
    expect(msg.payload).toEqual({ last: true });
  });
});
