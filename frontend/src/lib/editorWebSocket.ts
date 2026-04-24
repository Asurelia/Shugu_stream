/**
 * Scene Editor WebSocket client — Phase D.
 *
 * Client typé pour `/ws/editor` (cf. `backend/shugu/routes/editor_ws.py`).
 * Responsabilités :
 *  - ouvrir la WS et maintenir la connexion (reconnect exponentiel, 500ms → 8s,
 *    pattern identique à `services/shuguClient.ts`) ;
 *  - expose une API typée pour `subscribe`, `draft.update`, `preview.push`, `ping` ;
 *  - répond automatiquement aux `ping` server-initiated par des `pong` (le
 *    serveur coupe la connexion après 40s sans pong) ;
 *  - notifie un callback `onEvent` pour chaque event server (discriminated
 *    union `EditorServerEvent`) — le consumer (le hook React `useEditorWebSocket`)
 *    décide quoi faire.
 *
 * Déliberément **pas** de logique métier ici (peers, remote deltas, store
 * Zustand wiring) — on garde cette classe pure pour qu'elle soit testable
 * sans monter un composant React + Zustand. Le wiring vit dans
 * `useEditorWebSocket` (hook React dédié Phase D).
 */

/* ─────────────────────────── TYPES ─────────────────────────── */

/** Ce que le client peut envoyer au serveur. */
export type EditorClientMessage =
  | { type: "subscribe"; scene_id: string }
  | { type: "unsubscribe" }
  | {
      type: "draft.update";
      scene_id: string;
      delta: Record<string, unknown>;
      nonce: string;
    }
  | {
      type: "preview.push";
      scene_id: string;
      payload: Record<string, unknown>;
    }
  | { type: "ping"; nonce: string }
  | { type: "pong"; nonce?: string };

/** Code d'erreur discriminant retourné par le server. */
export type EditorErrorCode =
  | "invalid_payload"
  | "not_subscribed"
  | "unauthorized";

/** Ce que le client reçoit du serveur. */
export type EditorServerEvent =
  | { type: "hello"; operator: string; protocol_version: number }
  | { type: "subscribed"; scene_id: string; peers: string[] }
  | { type: "unsubscribed" }
  | { type: "peer.joined"; scene_id: string; operator: string }
  | { type: "peer.left"; scene_id: string; operator: string }
  | {
      type: "draft.update";
      scene_id: string;
      delta: Record<string, unknown>;
      origin: string;
      nonce?: string;
    }
  | {
      type: "preview.push";
      scene_id: string;
      payload: Record<string, unknown>;
      origin: string;
    }
  | { type: "ping"; t?: number }
  | { type: "pong"; nonce?: string }
  | { type: "error"; code: EditorErrorCode; message: string };

/* ─────────────────────────── OPTIONS ─────────────────────────── */

export type EditorWebSocketStatus =
  | "connecting"
  | "open"
  | "closed"
  | "error";

export type EditorWebSocketOptions = {
  /**
   * URL complète à utiliser. Facultatif : par défaut on déduit `ws(s)://<host>/ws/editor`
   * depuis `window.location`. Pratique pour injecter une URL mock en tests.
   */
  url?: string;

  /** Appelé pour chaque event server reçu. Obligatoire. */
  onEvent: (event: EditorServerEvent) => void;

  /** Appelé quand la WS passe OPEN (y compris après un reconnect). */
  onOpen?: () => void;

  /** Appelé quand la WS passe CLOSED (avant le scheduling d'un reconnect). */
  onClose?: () => void;

  /** Appelé sur erreur réseau / WS error event. */
  onError?: (error: Event) => void;

  /** Appelé à chaque changement de statut (utile pour un indicateur UI). */
  onStatus?: (status: EditorWebSocketStatus) => void;

  /**
   * Constructeur WebSocket à utiliser. Par défaut `globalThis.WebSocket`.
   * Utile pour injecter un mock en tests Vitest sans polluer le global
   * (meilleur que `vi.stubGlobal` qui fuit entre tests si pas clean).
   */
  WebSocketCtor?: typeof WebSocket;
};

/* ─────────────────────────── CLIENT ─────────────────────────── */

const INITIAL_RECONNECT_DELAY_MS = 500;
const MAX_RECONNECT_DELAY_MS = 8000;

/**
 * Construit l'URL par défaut à partir de `window.location`. Renvoie `null`
 * côté SSR (pas de window) — le client ne devrait jamais être instancié dans
 * ce contexte, mais on échoue gracieusement quand même.
 */
function defaultUrl(): string | null {
  if (typeof window === "undefined" || !window.location) return null;
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}/ws/editor`;
}

/**
 * Client WebSocket typé pour le Scene Editor.
 *
 * Usage :
 *   const ws = new EditorWebSocket({
 *     onEvent: (e) => console.log(e),
 *   });
 *   ws.subscribe("scene-uuid");
 *   ws.sendDraftUpdate("scene-uuid", { camera: { fov: 60 } });
 *   ws.close();
 */
export class EditorWebSocket {
  private readonly url: string;
  private readonly onEvent: (e: EditorServerEvent) => void;
  private readonly onOpen?: () => void;
  private readonly onClose?: () => void;
  private readonly onError?: (err: Event) => void;
  private readonly onStatus?: (s: EditorWebSocketStatus) => void;
  private readonly WebSocketCtor: typeof WebSocket;

  private ws: WebSocket | null = null;
  private reconnectDelay = INITIAL_RECONNECT_DELAY_MS;
  /** Set à true quand `.close()` est appelé manuellement → pas de reconnect. */
  private stopped = false;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  constructor(opts: EditorWebSocketOptions) {
    const resolvedUrl = opts.url ?? defaultUrl();
    if (!resolvedUrl) {
      throw new Error(
        "EditorWebSocket: no url and no window.location — explicit url required in SSR.",
      );
    }
    this.url = resolvedUrl;
    this.onEvent = opts.onEvent;
    this.onOpen = opts.onOpen;
    this.onClose = opts.onClose;
    this.onError = opts.onError;
    this.onStatus = opts.onStatus;
    // On accepte un ctor injecté (tests), sinon globalThis.WebSocket.
    this.WebSocketCtor = opts.WebSocketCtor ?? globalThis.WebSocket;
    if (!this.WebSocketCtor) {
      throw new Error(
        "EditorWebSocket: no WebSocket constructor available (SSR? provide WebSocketCtor option).",
      );
    }
    this.connect();
  }

  /* ─── Public API ─── */

  /** S'abonne à une scène. Remplace la subscription courante si existe. */
  subscribe(sceneId: string): void {
    this.send({ type: "subscribe", scene_id: sceneId });
  }

  /** Libère la subscription courante (optionnel ; close() suffit en général). */
  unsubscribe(): void {
    this.send({ type: "unsubscribe" });
  }

  /**
   * Envoie un delta d'édition en cours. Broadcast-only : ne persiste rien
   * serveur-side ; les peers operators reçoivent pour refléter l'UI live.
   */
  sendDraftUpdate(
    sceneId: string,
    delta: Record<string, unknown>,
    nonce?: string,
  ): void {
    this.send({
      type: "draft.update",
      scene_id: sceneId,
      delta,
      nonce: nonce ?? this.makeNonce(),
    });
  }

  /**
   * Envoie un snapshot de preview scène (camera + avatar + fov...). Fanout
   * vers les operators subscribed à la scène + relay sur le topic `stage`
   * pour les visiteurs (via le backend).
   */
  sendPreviewPush(
    sceneId: string,
    payload: Record<string, unknown>,
  ): void {
    this.send({ type: "preview.push", scene_id: sceneId, payload });
  }

  /** Ping applicatif (optionnel ; le server heartbeat est déjà géré). */
  ping(nonce?: string): void {
    this.send({ type: "ping", nonce: nonce ?? this.makeNonce() });
  }

  /** Ferme la connexion définitivement. Pas de reconnect après ça. */
  close(): void {
    this.stopped = true;
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.ws) {
      try {
        this.ws.close();
      } catch {
        /* ignore — socket peut-être déjà fermé */
      }
      this.ws = null;
    }
  }

  /** True si la WS est actuellement OPEN. Utile aux tests. */
  isOpen(): boolean {
    return this.ws !== null && this.ws.readyState === WebSocket.OPEN;
  }

  /* ─── Internals ─── */

  private connect(): void {
    if (this.stopped) return;
    this.onStatus?.("connecting");
    try {
      this.ws = new this.WebSocketCtor(this.url);
    } catch (err) {
      this.onStatus?.("error");
      this.scheduleReconnect();
      return;
    }

    this.ws.onopen = () => {
      // Reset du backoff : si on survit ≥ 1 onopen, la prochaine chute retry
      // immédiatement (500ms), pas 8s.
      this.reconnectDelay = INITIAL_RECONNECT_DELAY_MS;
      this.onStatus?.("open");
      this.onOpen?.();
    };

    this.ws.onmessage = (msg: MessageEvent) => {
      this.handleMessage(msg);
    };

    this.ws.onerror = (err: Event) => {
      this.onStatus?.("error");
      this.onError?.(err);
    };

    this.ws.onclose = () => {
      this.onStatus?.("closed");
      this.onClose?.();
      this.ws = null;
      if (!this.stopped) this.scheduleReconnect();
    };
  }

  private scheduleReconnect(): void {
    if (this.stopped) return;
    const delay = this.reconnectDelay;
    this.reconnectDelay = Math.min(delay * 2, MAX_RECONNECT_DELAY_MS);
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, delay);
  }

  private handleMessage(msg: MessageEvent): void {
    let parsed: unknown;
    try {
      parsed = JSON.parse(typeof msg.data === "string" ? msg.data : String(msg.data));
    } catch {
      // Message malformed côté server (ne devrait jamais arriver) : on
      // n'essaie pas de fix l'impossible.
      return;
    }
    if (!parsed || typeof parsed !== "object" || !("type" in parsed)) return;

    const event = parsed as EditorServerEvent;
    // Auto-pong au heartbeat server sans déranger le consumer — le consumer
    // peut quand même observer `onEvent` pour le logging.
    if (event.type === "ping") {
      this.send({ type: "pong" });
    }
    // On notifie TOUJOURS le consumer, même après auto-pong — certains tests
    // et panels peuvent vouloir observer le ping pour un indicateur de latence.
    this.onEvent(event);
  }

  private send(msg: EditorClientMessage): void {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      // Drop silencieux : la plupart des gestes UI sont éphémères, un reconnect
      // en cours ne doit pas faire crasher l'app. Les appels critiques (save)
      // utilisent HTTP, pas la WS.
      return;
    }
    try {
      this.ws.send(JSON.stringify(msg));
    } catch {
      /* ignore — socket probablement en train de mourir */
    }
  }

  private makeNonce(): string {
    // Simple nonce opaque — suffisant pour ACKs applicatifs (les tests
    // peuvent injecter un nonce explicite pour déterminisme).
    return `e-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
  }
}
