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

// ─── TriggerSpec — discriminated union TS (miroir Pydantic v2) ───────────────

/**
 * Trigger manuel — déclenchement explicite via POST `/scenes/{id}/play`.
 *
 * Aucun champ requis hors `kind` ; correspond à `ManualTrigger` Pydantic.
 */
export interface ManualTriggerSpec {
  kind: "manual";
}

/**
 * Trigger AFK — déclenché quand le compteur viewers passe sous `threshold`.
 *
 * Wiring runtime en Phase E5.4. Bornes backend : `0 <= threshold <= 100_000`.
 */
export interface ViewerCountBelowTriggerSpec {
  kind: "viewer_count_below";
  /** Seuil viewer count (entier, 0..100000). */
  threshold: number;
}

/**
 * Trigger silence — déclenché après `seconds` secondes sans chat.
 *
 * Bornes backend : `5 <= seconds <= 3600`. Le nom du champ est `seconds`
 * côté Pydantic (et NON `duration_s`) — cf. SilenceForTrigger ligne 98.
 */
export interface SilenceForTriggerSpec {
  kind: "silence_for";
  /** Durée silence en secondes (entier, 5..3600). */
  seconds: number;
}

/**
 * Trigger cron — déclenché à des moments fixes via expression cron.
 *
 * Le champ s'appelle `expr` côté Pydantic (et NON `cron_expr`) — cf.
 * ScheduleCronTrigger ligne 109. La validation cron est déférée au scheduler
 * Phase E5.4 (un cron mal formé désactive juste le trigger avec warning).
 */
export interface ScheduleCronTriggerSpec {
  kind: "schedule_cron";
  /** Expression cron 5-field (ex: `"*\/15 * * * *"`). 1..80 caractères. */
  expr: string;
}

/**
 * Trigger event stream — déclenché sur event Twitch / OBS.
 *
 * Le set d'events supportés est figé côté backend (Literal Pydantic). Tout
 * event inconnu fait partir le payload en 422.
 */
export interface StreamEventTriggerSpec {
  kind: "stream_event";
  /** Type d'event stream supporté (Literal côté backend). */
  event: "intro" | "outro" | "raid" | "follow" | "subscribe";
}

/**
 * `TriggerSpec` — discriminated union miroir backend Pydantic v2.
 *
 * Chaque `kind` impose SES propres champs requis ; TypeScript narrow le type
 * via le tag `kind`, ce qui permet au compilateur de rejeter des payloads
 * mal formés AVANT le 422 backend.
 *
 * @example
 * ```ts
 * const t: TriggerSpec = { kind: "viewer_count_below", threshold: 5 };
 * if (t.kind === "viewer_count_below") {
 *   t.threshold; // typé number ici
 * }
 *
 * // ❌ Erreur TS : `threshold` manquant
 * const bad: TriggerSpec = { kind: "viewer_count_below" };
 * ```
 *
 * Synchronisé avec `backend/shugu/domain/scene_composer_schemas.py` —
 * `ManualTrigger`, `ViewerCountBelowTrigger`, `SilenceForTrigger`,
 * `ScheduleCronTrigger`, `StreamEventTrigger`.
 */
export type TriggerSpec =
  | ManualTriggerSpec
  | ViewerCountBelowTriggerSpec
  | SilenceForTriggerSpec
  | ScheduleCronTriggerSpec
  | StreamEventTriggerSpec;

/**
 * Forme **réponse** d'un trigger persisté.
 *
 * Backend retourne `list[dict[str, Any]]` (cf. `AuthoredSceneOut.triggers`
 * Pydantic ligne 348) pour rester forward-compat : un trigger persisté
 * avec un `kind` futur inconnu du serveur ne crash pas le GET.
 *
 * Côté client on garde un type laxiste pour les réponses (on peut narrow
 * via `kind` à l'usage), mais on impose la discriminated union stricte
 * en INPUT (création/update) — cf. `AuthoredSceneCreate.triggers`.
 */
export type TriggerSpecPersisted = { kind: string } & Record<string, unknown>;

export interface AuthoredSceneOut {
  id: string;
  name: string;
  description: string | null;
  type: SceneType;
  /**
   * Triggers persistés (forme laxiste — backend renvoie list[dict[str, Any]]).
   * Pour narrow vers la discriminated union, faire un `if (t.kind === ...)`.
   */
  triggers: TriggerSpecPersisted[];
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
  /**
   * Triggers à persister (input strict — discriminated union TriggerSpec).
   *
   * TypeScript rejette les payloads mal formés à la compilation
   * (ex: `{ kind: "viewer_count_below" }` sans `threshold`).
   */
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
