/**
 * ViewerEventsClient — wrapper WebSocket pour `/ws/viewer/events`
 * (Sprint D PR D-7, voice-body pipeline).
 *
 * Consomme les events Director publiés par le backend D-3 :
 *   - `scene.apply`    : émotion / face / anim / vfx / camera / outfit
 *   - `voice.interrupt`: barge-in (VAD détecte parole user)
 *   - `hello`          : frame de bienvenue après accept (cf viewer.py:343)
 *
 * Auth : JWT viewer-token transmis via `Sec-WebSocket-Protocol` header,
 * conforme à la décision de review D-3 — la query-string `?token=` reste
 * supportée par le backend mais elle est loggée par uvicorn/nginx, donc
 * réservée au dev/test. Côté browser, le 2e argument du constructeur
 * `WebSocket(url, protocols)` correspond exactement à ce header.
 *
 * Resilience :
 *   - Reconnect exponentiel 200 → 500 → 1000 → 2000ms cap (spec §3.2).
 *   - Backoff reset sur reconnect réussi (réception du `hello`).
 *   - Pas de reconnect sur close terminal (1000 normal, 1008 policy,
 *     4xxx range custom backend pour auth/quota — RFC 6455 §7.4.2).
 *   - Validation Zod du payload AVANT dispatch — un payload mal formé
 *     est ignoré + log warn, sans crash ni callback.
 *
 * Référence spec : docs/specs/2026-05-08-voice-body-pipeline-design.md §3.2 + §6.2.
 */

import { z } from "zod";

// ─── Schémas Zod ─────────────────────────────────────────────────────────────
//
// On valide STRICTEMENT le shape des events avant dispatch. Si le backend
// introduit un nouveau type d'event sans que le frontend soit mis à jour,
// `safeParse` échoue → on l'ignore silencieusement (pas de crash).

const ViewerSceneApplySchema = z.object({
  type: z.literal("scene.apply"),
  kind: z.enum([
    "say_emotion",
    "face",
    "anim",
    "vfx",
    "camera",
    "outfit",
  ]),
  id: z.string().min(1),
  ts: z.string(), // ISO 8601 — backend `datetime.now().isoformat()`
  audio_at_ms: z.number().optional(),
  session_id: z.string().optional(),
});

const ViewerInterruptSchema = z.object({
  type: z.literal("voice.interrupt"),
  session_id: z.string().optional(),
  reason: z.enum(["vad_detected", "manual", "shutdown"]),
  ts: z.string(),
});

const HelloSchema = z.object({
  type: z.literal("hello"),
  session_id: z.string(),
  expires_at: z.number(),
});

// ─── Types exposés ──────────────────────────────────────────────────────────

/**
 * Event `scene.apply` (kind+id, optionnel `audio_at_ms`/`session_id`).
 * Cf spec §4.1.
 */
export type ViewerSceneApply = z.infer<typeof ViewerSceneApplySchema>;

/**
 * Event `voice.interrupt` (barge-in). Cf spec §4.2.
 */
export type ViewerInterrupt = z.infer<typeof ViewerInterruptSchema>;

/**
 * Event `hello` envoyé par le backend après accept (auth confirmée).
 * Cf `backend/shugu/routes/viewer.py:343-347`.
 */
export type ViewerHello = z.infer<typeof HelloSchema>;

/** Union des events (utile pour les API consumers qui veulent un type strict). */
export type ViewerEvent = ViewerSceneApply | ViewerInterrupt | ViewerHello;

/** Options de configuration du client. */
export interface ViewerEventsClientOptions {
  /** URL WS, ex `ws://localhost:8000/ws/viewer/events` (sans `?token=...`). */
  url: string;
  /** JWT viewer-token (issu de `POST /api/voice/token`, TTL 5min). */
  token: string;
  /** Callback fire-and-forget sur réception d'un `scene.apply` valide. */
  onSceneApply?: (event: ViewerSceneApply) => void;
  /** Callback fire-and-forget sur réception d'un `voice.interrupt` valide. */
  onInterrupt?: (event: ViewerInterrupt) => void;
  /** Callback fire-and-forget sur réception du `hello` (auth confirmée). */
  onConnected?: (hello: ViewerHello) => void;
  /** Callback fire-and-forget sur close (terminal ou transient). */
  onDisconnected?: (code: number, reason: string) => void;
}

// ─── Constantes de reconnect ────────────────────────────────────────────────

/** Backoff exponentiel des reconnect (ms). Cf spec §3.2. */
const BACKOFF_LADDER_MS = [200, 500, 1000, 2000] as const;

/**
 * Codes WebSocket considérés comme TERMINAUX — pas de reconnect.
 * - 1000 : Normal Closure (RFC 6455 §7.4.1)
 * - 1008 : Policy Violation (backend `WS_CLOSE_TOO_MANY` ou rejet auth)
 * - 4000-4999 : range applicatif custom (backend D-3 utilise 4001 token expired,
 *   4002 session_id mismatch — convention interne, à étendre côté backend
 *   au besoin).
 *
 * Source : spec §6.2 (review advisor D-7) + backend `WS_CLOSE_TOO_MANY` dans
 * `backend/shugu/routes/viewer.py:303-322`.
 */
function isTerminalCloseCode(code: number): boolean {
  if (code === 1000) return true;
  if (code === 1008) return true;
  if (code >= 4000 && code <= 4999) return true;
  return false;
}

// ─── Implémentation ─────────────────────────────────────────────────────────

/**
 * Wrapper WebSocket lifecycle pour `/ws/viewer/events`.
 *
 * Lifecycle :
 *   1. `new ViewerEventsClient(opts)` — capture des callbacks, pas de connexion.
 *   2. `await client.connect()` — ouvre la WS avec token comme subprotocol.
 *   3. À réception du `hello` du backend, `onConnected` fire (auth confirmée).
 *   4. Les events `scene.apply` / `voice.interrupt` arrivent → callbacks.
 *   5. Si la WS drop avec un code transient, on reconnect avec backoff
 *      exponentiel. Si le code est terminal, on s'arrête + `onDisconnected`.
 *   6. `client.disconnect()` — close la WS et annule tout reconnect en attente.
 */
export class ViewerEventsClient {
  private readonly _options: ViewerEventsClientOptions;
  private _ws: WebSocket | null = null;
  private _reconnectAttempt: number = 0;
  private _reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  /** True si `disconnect()` a été appelé — empêche tout reconnect. */
  private _disposed: boolean = false;

  public constructor(options: ViewerEventsClientOptions) {
    this._options = options;
  }

  /**
   * Ouvre la WebSocket. Idempotent : si une socket existe déjà (CONNECTING
   * ou OPEN), retourne immédiatement.
   *
   * Le `await` ne bloque PAS jusqu'à OPEN — la résolution est synchrone après
   * l'instanciation. C'est cohérent avec le comportement browser : la
   * connexion s'ouvre en arrière-plan, les callbacks (`onopen`, `onmessage`)
   * fournissent l'asynchronicité réelle.
   */
  public async connect(): Promise<void> {
    if (this._disposed) {
      // Réutilisation après disconnect() : on accepte de relancer un cycle.
      this._disposed = false;
    }
    if (this._ws && this._ws.readyState !== WebSocket.CLOSED) {
      // Déjà CONNECTING ou OPEN — no-op.
      return;
    }
    this._open();
    return Promise.resolve();
  }

  /**
   * Ferme la WebSocket et annule tout reconnect armé. No-op si jamais connect().
   * Après `disconnect()`, le client peut être réutilisé via `connect()`.
   */
  public disconnect(): void {
    this._disposed = true;
    if (this._reconnectTimer) {
      clearTimeout(this._reconnectTimer);
      this._reconnectTimer = null;
    }
    if (this._ws) {
      try {
        this._ws.close(1000, "client disconnect");
      } catch {
        // close() peut throw si la socket est déjà CLOSED — on ignore.
      }
      this._ws = null;
    }
  }

  /** True si la socket est en état OPEN. False sinon (incl. CONNECTING). */
  public isConnected(): boolean {
    return this._ws?.readyState === WebSocket.OPEN;
  }

  // ─── Internal ──────────────────────────────────────────────────────────

  /**
   * Instancie la WebSocket avec auth subprotocol et wire les handlers.
   * Appelé par `connect()` et par le scheduler de reconnect.
   */
  private _open(): void {
    if (this._disposed) return;

    // Le 2ème argument du constructeur WebSocket browser correspond à
    // `Sec-WebSocket-Protocol`. Le backend D-3 echo le subprotocol reçu via
    // `ws.accept(subprotocol=...)` — sans cet echo, Chrome/Firefox rejettent
    // la connexion (RFC 6455 §4.2.2).
    const ws = new WebSocket(this._options.url, this._options.token);
    this._ws = ws;

    ws.onopen = (): void => {
      // Pas de callback ici — on attend le `hello` pour confirmer l'auth.
      // L'`open` côté SDK signifie juste que la handshake TCP/TLS a réussi.
    };

    ws.onmessage = (ev: MessageEvent): void => {
      this._handleMessage(ev.data);
    };

    ws.onerror = (): void => {
      // L'event `error` n'a pas de détail exploitable côté browser (sécurité).
      // On laisse `onclose` gérer la suite (toujours fire après error).
    };

    ws.onclose = (ev: CloseEvent): void => {
      this._handleClose(ev.code, ev.reason);
    };
  }

  /**
   * Parse + dispatch un message reçu. Ignore silencieusement tout payload
   * mal formé (warn pour debug).
   */
  private _handleMessage(rawData: unknown): void {
    if (typeof rawData !== "string") {
      console.warn(
        "[ViewerEventsClient] non-string message ignored:",
        typeof rawData,
      );
      return;
    }

    let parsed: unknown;
    try {
      parsed = JSON.parse(rawData);
    } catch (jsonErr) {
      console.warn(
        "[ViewerEventsClient] invalid JSON ignored:",
        jsonErr instanceof Error ? jsonErr.message : String(jsonErr),
      );
      return;
    }

    if (!parsed || typeof parsed !== "object" || !("type" in parsed)) {
      console.warn(
        "[ViewerEventsClient] payload missing `type` field — ignored.",
      );
      return;
    }

    const type = (parsed as { type: unknown }).type;

    // Hello = première frame après accept ; on l'ignore pour les callbacks
    // event mais on s'en sert pour confirmer l'auth + reset le backoff.
    if (type === "hello") {
      const helloResult = HelloSchema.safeParse(parsed);
      if (!helloResult.success) {
        // Rare — le backend D-3 produit toujours un hello bien formé. Si on
        // est ici, c'est probablement un drift de schéma → warn pour debug.
        console.warn(
          "[ViewerEventsClient] malformed hello frame ignored:",
          helloResult.error.message,
        );
        return;
      }
      // Auth confirmée : on reset le backoff. Évite que des dropouts
      // successifs accumulent des délais artificiels (cf advisor D-7).
      this._reconnectAttempt = 0;
      this._options.onConnected?.(helloResult.data);
      return;
    }

    if (type === "scene.apply") {
      const result = ViewerSceneApplySchema.safeParse(parsed);
      if (!result.success) {
        console.warn(
          "[ViewerEventsClient] malformed scene.apply ignored:",
          result.error.message,
        );
        return;
      }
      this._options.onSceneApply?.(result.data);
      return;
    }

    if (type === "voice.interrupt") {
      const result = ViewerInterruptSchema.safeParse(parsed);
      if (!result.success) {
        console.warn(
          "[ViewerEventsClient] malformed voice.interrupt ignored:",
          result.error.message,
        );
        return;
      }
      this._options.onInterrupt?.(result.data);
      return;
    }

    // Forward-compat : type inconnu → silently ignored. On log à debug pour
    // ne pas spammer les consoles si le backend introduit du `tts.chunk_started`
    // (cf spec §4.3) ou autre.
    console.debug(
      "[ViewerEventsClient] unknown event type ignored:",
      type,
    );
  }

  /**
   * Gère le close — décide si on reconnect ou non.
   */
  private _handleClose(code: number, reason: string): void {
    this._ws = null;
    this._options.onDisconnected?.(code, reason);

    if (this._disposed) {
      return; // disconnect() explicite : pas de reconnect.
    }

    if (isTerminalCloseCode(code)) {
      console.warn(
        `[ViewerEventsClient] terminal close ${code} (${reason}) — no reconnect.`,
      );
      return;
    }

    // Schedule reconnect avec backoff exponentiel (capé à 2000ms).
    const delay =
      BACKOFF_LADDER_MS[
        Math.min(this._reconnectAttempt, BACKOFF_LADDER_MS.length - 1)
      ];
    this._reconnectAttempt += 1;
    console.info(
      `[ViewerEventsClient] transient close ${code} — reconnect in ${delay}ms (attempt ${this._reconnectAttempt}).`,
    );
    this._reconnectTimer = setTimeout(() => {
      this._reconnectTimer = null;
      this._open();
    }, delay);
  }
}
