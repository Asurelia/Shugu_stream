/**
 * httpClient — helper HTTP partagé pour les API clients du Scene Composer.
 *
 * Responsabilité unique : centraliser la mécanique fetch (credentials, parse
 * JSON, gestion erreur, redirect 401) pour que `scenesClient.ts` et
 * `catalogClient.ts` (et tout futur client Phase E5.x) ne duplique plus la
 * même logique.
 *
 * ## Pourquoi un module dédié ?
 *
 * Avant : chaque client avait son propre `request<T>` + sa propre classe
 * d'erreur (`ScenesClientError`, `CatalogClientError`), et AUCUN ne gérait
 * le 401 mid-session. Un cookie expiré pendant l'usage du Composer
 * affichait juste "Erreur 401" sans rediriger l'opérateur — qui restait
 * bloqué sur une UI morte.
 *
 * Après : un seul `request<T>` qui :
 *   - injecte `credentials: "include"` (cookies httpOnly)
 *   - sur 401 → `window.location.replace("/login")` AVANT de throw
 *     (redirect dur — la session SPA est cassée, rester en mémoire avec
 *     un état partiel mène à des bugs plus subtils que le coût d'un reload)
 *   - parse `{ detail }` Pydantic v2 et expose un `HttpError` unique
 *   - gère 204 No Content sans tenter de parser un body vide
 *
 * ## Discipline modulaire
 *
 * 1 module = 1 responsabilité. `httpClient` ne sait RIEN du Scene Composer
 * métier — il est réutilisable par tout futur client REST de la feature.
 *
 * @module api/httpClient
 */

// ─── Erreur unifiée ───────────────────────────────────────────────────────────

/**
 * Erreur HTTP levée par `request()` sur tout statut non-OK.
 *
 * Remplace `ScenesClientError` + `CatalogClientError` (anciens duplicats —
 * 1 module = 1 responsabilité). Les call-sites peuvent typer le `catch`
 * avec `instanceof HttpError` et accéder à `status` / `detail` / `raw`.
 *
 * @example
 * ```ts
 * try {
 *   await listScenes();
 * } catch (err) {
 *   if (err instanceof HttpError && err.status === 404) {
 *     // ...
 *   }
 * }
 * ```
 */
export class HttpError extends Error {
  constructor(
    /** Code HTTP retourné par le serveur (ex: 404, 500). */
    public readonly status: number,
    /** Message lisible — `payload.detail` si présent, sinon `statusText`. */
    public readonly detail: string,
    /** Payload brut décodé (peut être `null` si parse JSON échoue). */
    public readonly raw: unknown,
  ) {
    super(`[${status}] ${detail}`);
    this.name = "HttpError";
  }
}

// ─── Hook redirect 401 (testable) ────────────────────────────────────────────

/**
 * Effectue la redirection vers `/login` en cas de 401.
 *
 * Extrait dans une fonction dédiée pour être mockable en test (sinon il
 * faut stub `window.location` complet, ce qui est lourd et fragile).
 *
 * Stratégie : `window.location.replace(...)` plutôt que `router.push(...)`.
 *  - `replace` ne pollue pas l'historique (un user qui cliquait "back"
 *    reviendrait sur la page protégée et boucle).
 *  - On évite la dépendance à `next/router` ici → ce module reste agnostique
 *    du framework de routing (testable sans monter un Next.js).
 *  - Reload dur recharge le `_app.tsx` → l'état SPA bancal (stores Zustand
 *    pleins de données obsolètes) est purgé proprement.
 */
export function redirectToLogin(): void {
  if (typeof window !== "undefined") {
    window.location.replace("/login");
  }
}

// ─── Helper request<T> ────────────────────────────────────────────────────────

/**
 * Effectue un fetch authentifié et parse la réponse JSON.
 *
 * Comportement :
 *   - `credentials: "include"` toujours (cookies httpOnly).
 *   - Header `Content-Type: application/json` mergé avec ceux de l'appelant.
 *   - 401 → `redirectToLogin()` puis throw `HttpError(401)` pour déclencher
 *     les `.catch()` côté appelant (rejette les promesses encore en vol).
 *   - !ok → parse `{ detail }` Pydantic v2 et throw `HttpError(status, ...)`.
 *   - 204 No Content → résolve `null as T`.
 *   - 2xx → résolve le JSON parsé typé `T`.
 *
 * @template T - Type de la réponse JSON attendue.
 * @param url   - Path absolu (ex: `/api/scene-composer/scenes`).
 * @param init  - Options fetch standard (method, body, headers...).
 * @throws HttpError - Sur 401 (après redirect) ou tout autre statut !ok.
 */
export async function request<T>(
  url: string,
  init: RequestInit = {},
): Promise<T> {
  const resp = await fetch(url, {
    credentials: "include",
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init.headers ?? {}),
    },
  });

  // 401 mid-session : cookie expiré. Redirect dur AVANT de throw pour purger
  // l'état SPA (les stores Zustand pleins de données obsolètes seraient un
  // gouffre à bugs si on restait en mémoire).
  if (resp.status === 401) {
    redirectToLogin();
    throw new HttpError(401, "Session expirée, redirection en cours.", null);
  }

  // 204 No Content : rien à parser. Cast `null as T` accepté (le call-site
  // typique appelle `request<void>(...)`).
  if (resp.status === 204) {
    return null as T;
  }

  // Parse JSON best-effort. Un body vide ou non-JSON → `raw=null`,
  // detail tombe sur `statusText`.
  let raw: unknown = null;
  let detail: string = resp.statusText || `HTTP ${resp.status}`;
  const text = await resp.text();
  if (text) {
    try {
      raw = JSON.parse(text);
      if (
        typeof raw === "object" &&
        raw !== null &&
        "detail" in raw &&
        typeof (raw as Record<string, unknown>).detail === "string"
      ) {
        detail = (raw as Record<string, unknown>).detail as string;
      }
    } catch {
      // Body non-JSON : on garde le texte brut comme detail.
      raw = { rawText: text };
      detail = text;
    }
  }

  if (!resp.ok) {
    throw new HttpError(resp.status, detail, raw);
  }

  return raw as T;
}
