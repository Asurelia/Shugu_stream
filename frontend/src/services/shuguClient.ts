// Shugu WS client — routes to /ws/visitor or /ws/operator depending on auth.

import { nanoid } from "./nanoid";

export type PerformanceTags = {
  scene?: string;
  action?: string;
  emote?: string;
  shot?: string;
  /** Storyboard audio source (relative URL under frontend/public/) — when
   *  present the client fetches audio from this path instead of decoding
   *  `audio_b64` (which will be empty for storyboards). */
  audio_src?: string;
};

export type TimedCue = {
  offset_ms: number;
  tags: PerformanceTags;
};

export type MoodName = "cheerful" | "focused" | "sleepy" | "playful" | "bored";

export type ShuguEvent =
  | { type: "performance.start"; performance_id: string; start_at_server_ts: number; author: string; original_text_truncated: string | null }
  | { type: "performance.audio"; performance_id: string; audio_b64: string; mime: string; duration_ms: number; screenplay: { emotion: string; talk_style: string }; text: string; tags?: PerformanceTags; timed_cues?: TimedCue[] }
  | { type: "performance.audio_begin"; performance_id: string; mime: string; duration_estimate_ms: number; screenplay: { emotion: string; talk_style: string }; text: string; tags?: PerformanceTags; timed_cues?: TimedCue[] }
  | { type: "performance.audio_chunk"; performance_id: string; seq: number; audio_b64: string; mime: string; final: boolean }
  | { type: "performance.truncate"; performance_id: string; reason?: string }
  | { type: "performance.end"; performance_id: string }
  | { type: "viewer.count"; n: number }
  | { type: "mood.change"; from: MoodName; to: MoodName }
  | { type: "scene.change"; scene: string }
  | { type: "look.hint"; ndc: { x: number; y: number }; hold_ms?: number }
  | { type: "expression.set"; expression: string; duration_ms?: number }
  | { type: "shot.change"; shot: string }
  | { type: "error.moderation"; nonce?: string; reason: string; detector: string }
  | { type: "queue.rejected"; nonce?: string; reason: string }
  | { type: "registry.invalidated"; reason?: string }
  | {
      type: "scene.preview"; slug: string;
      config: {
        camera: { x: number; y: number; z: number };
        look_at: { x: number; y: number; z: number };
        fov: number;
        background: string;
        idle_animation: string;
        avatar_position: { x: number; y: number; z: number };
        avatar_rotation_y: number;
      };
    }
  | { type: "pong"; t?: number }
  | { type: "error"; nonce?: string; reason: string };

export type ShuguClientOptions = {
  operator?: boolean;
  url?: string;
  onEvent: (ev: ShuguEvent) => void;
  onStatus?: (status: "connecting" | "open" | "closed" | "error") => void;
};

export class ShuguClient {
  private ws: WebSocket | null = null;
  private url: string;
  private onEvent: (ev: ShuguEvent) => void;
  private onStatus?: (status: "connecting" | "open" | "closed" | "error") => void;
  private reconnectDelay = 500;
  private maxReconnectDelay = 8000;
  private stopped = false;

  constructor(opts: ShuguClientOptions) {
    const wsProto = typeof window !== "undefined" && window.location.protocol === "https:" ? "wss:" : "ws:";
    const host = typeof window !== "undefined" ? window.location.host : "";
    const endpoint = opts.operator ? "/ws/operator" : "/ws/visitor";
    this.url = opts.url || `${wsProto}//${host}${endpoint}`;
    this.onEvent = opts.onEvent;
    this.onStatus = opts.onStatus;
  }

  connect() {
    if (this.stopped) return;
    this.onStatus?.("connecting");
    try {
      this.ws = new WebSocket(this.url);
    } catch (err) {
      this.onStatus?.("error");
      this.scheduleReconnect();
      return;
    }
    this.ws.onopen = () => {
      this.reconnectDelay = 500;
      this.onStatus?.("open");
    };
    this.ws.onmessage = (msg) => {
      try {
        const ev = JSON.parse(msg.data) as ShuguEvent;
        this.onEvent(ev);
      } catch (_) { /* ignore */ }
    };
    this.ws.onerror = () => { this.onStatus?.("error"); };
    this.ws.onclose = () => {
      this.onStatus?.("closed");
      if (!this.stopped) this.scheduleReconnect();
    };
  }

  private scheduleReconnect() {
    setTimeout(() => this.connect(), this.reconnectDelay);
    this.reconnectDelay = Math.min(this.reconnectDelay * 2, this.maxReconnectDelay);
  }

  sendChat(text: string): boolean {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return false;
    const msg: Record<string, unknown> = { type: "chat.send", text, nonce: nanoid() };
    this.ws.send(JSON.stringify(msg));
    return true;
  }

  close() {
    this.stopped = true;
    this.ws?.close();
  }
}

export function base64ToArrayBuffer(b64: string): ArrayBuffer {
  const bin = atob(b64);
  const buf = new ArrayBuffer(bin.length);
  const view = new Uint8Array(buf);
  for (let i = 0; i < bin.length; i++) view[i] = bin.charCodeAt(i);
  return buf;
}

// ─── Auth helpers (cookies are httpOnly, so we probe GET /auth/me) ────────────

/** AUTH-1: unified auth response type — same shape from POST /auth/login and GET /auth/me. */
export type AuthResponse = {
  username: string;
  role: string;
  is_operator: boolean;
};

export async function fetchAuthStatus(): Promise<AuthResponse | null> {
  try {
    const r = await fetch("/auth/me", { credentials: "include" });
    if (!r.ok) return null;
    return (await r.json()) as AuthResponse;
  } catch (_) { return null; }
}

/**
 * Unified login — calls POST /auth/login.
 *
 * On success (2xx): returns { data: AuthResponse, error: null }.
 *   - is_operator=true: sets shugu_access + shugu_user_access cookies (dual)
 *   - is_operator=false: sets shugu_user_access cookie only
 * On failure: returns { data: null, error: string }.
 */
export async function login(
  username: string,
  password: string,
): Promise<{ data: AuthResponse | null; error: string | null }> {
  const r = await fetch("/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ username, password }),
  });
  if (!r.ok) {
    let msg: string;
    try { msg = (await r.json()).detail || `HTTP ${r.status}`; } catch { msg = `HTTP ${r.status}`; }
    return { data: null, error: msg };
  }
  const data = (await r.json()) as AuthResponse;
  return { data, error: null };
}

export async function logout(): Promise<void> {
  try { await fetch("/auth/logout", { method: "POST", credentials: "include" }); } catch {}
}
