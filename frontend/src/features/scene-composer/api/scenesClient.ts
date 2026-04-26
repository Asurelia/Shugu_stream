/**
 * scenesClient — CRUD typed pour les AuthoredScenes (backend Phase C/E5.1).
 *
 * Endpoints consommés :
 *   GET    /api/scene-composer/scenes          → AuthoredSceneOut[]
 *   GET    /api/scene-composer/scenes/:id      → AuthoredSceneOut
 *   POST   /api/scene-composer/scenes          → AuthoredSceneOut
 *   PUT    /api/scene-composer/scenes/:id      → AuthoredSceneOut
 *   DELETE /api/scene-composer/scenes/:id      → void (204)
 *   POST   /api/scene-composer/scenes/:id/play → { ok: true }
 *
 * Pattern : `request<T>` helper local avec `credentials: "include"` (cookies
 * httpOnly) — identique à `services/accountClient.ts`.
 *
 * @module api/scenesClient
 */

// ─── Types Pydantic miroirs ───────────────────────────────────────────────────
// (miroirs de `backend/shugu/domain/scene_composer_schemas.py`)

export type SceneType = "static" | "timeline" | "loop";

export interface TriggerSpec {
  kind:
    | "manual"
    | "viewer_count_below"
    | "silence_for"
    | "schedule_cron"
    | "stream_event";
  [key: string]: unknown;
}

export interface AuthoredSceneOut {
  id: string;
  name: string;
  description: string | null;
  type: SceneType;
  triggers: TriggerSpec[];
  static_state: Record<string, unknown> | null;
  timeline_keyframes: Record<string, unknown>[] | null;
  loop_config: Record<string, unknown> | null;
  owner_username: string;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface AuthoredSceneCreate {
  name: string;
  description?: string | null;
  type: SceneType;
  triggers?: TriggerSpec[];
  static_state?: Record<string, unknown> | null;
  timeline_keyframes?: Record<string, unknown>[] | null;
  loop_config?: Record<string, unknown> | null;
  enabled?: boolean;
}

/** Tous les champs sont optionnels sauf `type` (immutable backend). */
export type AuthoredSceneUpdate = Partial<
  Omit<AuthoredSceneCreate, "type">
>;

// ─── Erreur client ────────────────────────────────────────────────────────────

export class ScenesClientError extends Error {
  constructor(
    public status: number,
    public detail: string,
  ) {
    super(`[${status}] ${detail}`);
    this.name = "ScenesClientError";
  }
}

// ─── Helper fetch ─────────────────────────────────────────────────────────────

async function request<T>(path: string, opts: RequestInit = {}): Promise<T> {
  const resp = await fetch(path, {
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(opts.headers ?? {}),
    },
    ...opts,
  });

  if (resp.status === 204) {
    return undefined as unknown as T;
  }

  const text = await resp.text();
  const payload = text
    ? (() => {
        try {
          return JSON.parse(text);
        } catch {
          return { detail: text };
        }
      })()
    : {};

  if (!resp.ok) {
    const detail =
      (payload as { detail?: string })?.detail ?? `HTTP ${resp.status}`;
    throw new ScenesClientError(resp.status, String(detail));
  }

  return payload as T;
}

// ─── API ────────────────────────────────────────────────────────────────────

const BASE = "/api/scene-composer/scenes";

/**
 * Liste toutes les scènes authoriées de l'opérateur connecté.
 */
export async function listScenes(): Promise<AuthoredSceneOut[]> {
  return request<AuthoredSceneOut[]>(BASE);
}

/**
 * Récupère une scène par ID.
 */
export async function getScene(id: string): Promise<AuthoredSceneOut> {
  return request<AuthoredSceneOut>(`${BASE}/${encodeURIComponent(id)}`);
}

/**
 * Crée une nouvelle scène authoriée.
 */
export async function createScene(
  body: AuthoredSceneCreate,
): Promise<AuthoredSceneOut> {
  return request<AuthoredSceneOut>(BASE, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/**
 * Met à jour une scène existante.
 */
export async function updateScene(
  id: string,
  body: AuthoredSceneUpdate,
): Promise<AuthoredSceneOut> {
  return request<AuthoredSceneOut>(`${BASE}/${encodeURIComponent(id)}`, {
    method: "PUT",
    body: JSON.stringify(body),
  });
}

/**
 * Supprime une scène. Retourne `undefined` (204 No Content).
 */
export async function deleteScene(id: string): Promise<void> {
  return request<void>(`${BASE}/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
}

/**
 * Déclenche le play d'une scène authoriée (envoi au director).
 */
export async function playScene(id: string): Promise<{ ok: boolean }> {
  return request<{ ok: boolean }>(
    `${BASE}/${encodeURIComponent(id)}/play`,
    { method: "POST" },
  );
}
