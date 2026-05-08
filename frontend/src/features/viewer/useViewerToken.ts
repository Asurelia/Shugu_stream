/**
 * useViewerToken — hook React mutualisé fetch + refresh proactif T-60s
 * (Sprint D PR D-8).
 *
 * Pourquoi un hook plutôt que deux providers fetch leur token chacun :
 *   - Réduit la charge serveur : 2 endpoints `/api/voice/token` au mount, 2
 *     refresh timers en parallèle, 2 logs `viewer.token_issued` par session.
 *   - Aligne `session_id` : un seul claim signé partagé entre LiveKit et WS,
 *     ce qui évite le drift lors du refresh (cf spec §6.3).
 *   - Centralise le warn de l'erreur 401 silencieux mid-session > 5min.
 *
 * Important — ce hook NE force PAS la reconnexion des consumers actifs :
 *   - LiveKit Room n'est pas torn-down à chaque refresh (4min cycle silen-
 *     cierait l'audio régulièrement). Le SDK livekit-client gère son propre
 *     reconnect via tokens internes, on lui passe un token frais à la NEXT
 *     instantiation (transient drop, remount React).
 *   - Idem ViewerEventsClient : le subprotocol WS est négocié au handshake
 *     et fixé pour la durée de la session — on rejoue la WS uniquement sur
 *     close transient.
 *   - Conséquence : le refresh garde un `token` frais en cache pour le
 *     prochain (re)connect, sans toucher aux connexions actives.
 *
 * Référence spec : docs/specs/2026-05-08-voice-body-pipeline-design.md §6.3.
 */

"use client";

import { useEffect, useRef, useState } from "react";
import { buildUrl } from "@/utils/buildUrl";

// ─── Constantes ─────────────────────────────────────────────────────────────

/** Endpoint de bootstrap initial. */
export const VIEWER_TOKEN_ENDPOINT = "/api/voice/token";

/** Endpoint de refresh — accepte Bearer du token courant. */
export const VIEWER_TOKEN_REFRESH_ENDPOINT = "/api/voice/token/refresh";

/** Marge avant `expires_at` pour fire le refresh (cf spec §6.3). */
const REFRESH_LEAD_MS = 60_000;

// ─── Types ──────────────────────────────────────────────────────────────────

/**
 * Réponse du backend `POST /api/voice/token`.
 * Backend (`backend/shugu/routes/viewer.py:VoiceTokenResponse`) expose
 * `livekit_url`. On accepte aussi `url` (legacy LiveKitProvider D-6) via
 * un compat shim pour ne pas casser les tests existants.
 */
interface BackendTokenResponse {
  token?: string;
  expires_at?: number; // epoch seconds
  livekit_url?: string;
  /** Compat shim D-6 — synonym for `livekit_url`. */
  url?: string;
  /** Legacy — pas exposé par le hook. */
  room?: string;
}

/**
 * Réponse du backend `POST /api/voice/token/refresh`.
 * Cf `backend/shugu/routes/viewer.py:VoiceTokenRefreshResponse`.
 */
interface BackendRefreshResponse {
  token?: string;
  expires_at?: number;
}

/** Surface exposée aux consumers du hook. */
export interface ViewerTokenState {
  /** JWT viewer-token courant (TTL 5min). `null` tant que fetch initial pending. */
  token: string | null;
  /** URL WSS LiveKit (`livekit_url` backend ou `url` legacy). */
  livekitUrl: string | null;
  /** Epoch seconds — utile pour debug / UI countdown. */
  expiresAt: number | null;
  /** True pendant le fetch initial OU un refresh en cours. */
  isLoading: boolean;
  /** Error remontée si fetch initial échoue (refresh fail garde l'ancien token). */
  error: Error | null;
}

/** Options du hook. `enabled` permet de mounter le hook en arbre sans
 *  déclencher un fetch tant qu'une condition externe n'est pas remplie
 *  (typiquement `!!operator`). Au flip false→true, le bootstrap fetch fire ;
 *  au flip true→false, le timer de refresh est cancel + état reset. */
export interface UseViewerTokenOptions {
  enabled?: boolean;
}

// ─── Implémentation ─────────────────────────────────────────────────────────

/**
 * Hook qui fetch + refresh un viewer-token.
 *
 * Lifecycle :
 *   1. Mount : POST `/api/voice/token` → `{token, livekitUrl, expiresAt}`.
 *   2. Schedule un setTimeout pour fire à `expires_at - 60s` (clamp >= 0).
 *   3. À l'échéance : POST `/api/voice/token/refresh` Bearer-auth → nouveau
 *      token. Re-schedule le prochain refresh.
 *   4. Si refresh échoue : log warn, garde l'ancien token, ne re-schedule pas
 *      (au prochain remount le hook refera un fetch initial — TTL 5min couvre
 *      la fenêtre).
 *   5. Unmount : clearTimeout du refresh pending.
 */
export function useViewerToken(
  options: UseViewerTokenOptions = {},
): ViewerTokenState {
  const { enabled = true } = options;
  const [state, setState] = useState<ViewerTokenState>({
    token: null,
    livekitUrl: null,
    expiresAt: null,
    isLoading: enabled,
    error: null,
  });

  /** Ref pour persister la valeur courante du token sans triggerer
   *  des effects (consumers du token initial ne re-render pas sur refresh). */
  const tokenRef = useRef<string | null>(null);
  /** Timer du prochain refresh — clearTimeout au unmount ou re-schedule. */
  const refreshTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  /** Compteur de refresh consécutifs avec délai 0 — détecte une boucle si
   *  le backend retourne en chaîne des tokens déjà expirés (clock skew). */
  const consecutiveImmediateRefreshRef = useRef<number>(0);

  useEffect(() => {
    if (!enabled) {
      // Skip bootstrap : le hook reste inerte jusqu'à un flip enabled=true.
      // On retire la ref token pour éviter un refresh résiduel, mais on ne
      // touche PAS au state — la dérivation `displayedState` ci-dessous
      // exposera un snapshot "vide" tant que `enabled` est false sans déclen-
      // cher de cascading render.
      tokenRef.current = null;
      return;
    }

    let cancelled = false;

    const clearRefreshTimer = (): void => {
      if (refreshTimerRef.current) {
        clearTimeout(refreshTimerRef.current);
        refreshTimerRef.current = null;
      }
    };

    /**
     * Schedule le prochain refresh à `expiresAtS - 60s`. Clamp à 0 si déjà
     * passé (fire immédiat — token presque expiré).
     *
     * Garde-fou anti-boucle : si on enchaîne >3 refresh successifs avec délai
     * <1s (= backend retourne des tokens déjà expirés en chaîne), on stoppe
     * le scheduling pour éviter un infinite loop. Le user verra l'auth
     * invalidée au prochain WS / Room.connect.
     */
    const scheduleRefresh = (expiresAtS: number): void => {
      clearRefreshTimer();
      const refreshAtMs = expiresAtS * 1000 - REFRESH_LEAD_MS;
      const delayMs = Math.max(0, refreshAtMs - Date.now());

      if (delayMs < 1000) {
        consecutiveImmediateRefreshRef.current += 1;
        if (consecutiveImmediateRefreshRef.current > 3) {
          console.error(
            "[useViewerToken] >3 consecutive stale-token refreshes — stopping " +
              "to avoid infinite loop. Backend clock skew likely.",
          );
          return;
        }
      } else {
        consecutiveImmediateRefreshRef.current = 0;
      }

      refreshTimerRef.current = setTimeout(() => {
        if (cancelled) return;
        void doRefresh();
      }, delayMs);
    };

    /**
     * POST /api/voice/token/refresh avec Bearer du token courant.
     * En cas d'erreur, garde l'ancien token + warn (pas de crash).
     */
    const doRefresh = async (): Promise<void> => {
      const currentToken = tokenRef.current;
      if (!currentToken) {
        // Pas de token initial → le bootstrap a échoué. Pas de refresh à faire.
        return;
      }
      try {
        const resp = await fetch(buildUrl(VIEWER_TOKEN_REFRESH_ENDPOINT), {
          method: "POST",
          credentials: "include",
          headers: {
            Authorization: `Bearer ${currentToken}`,
            "Content-Type": "application/json",
          },
        });
        if (cancelled) return;
        if (!resp.ok) {
          throw new Error(`refresh failed: HTTP ${resp.status}`);
        }
        const data = (await resp.json()) as BackendRefreshResponse;
        if (cancelled) return;

        if (!data.token || typeof data.expires_at !== "number") {
          throw new Error(
            "refresh response missing token or expires_at",
          );
        }
        tokenRef.current = data.token;
        setState((prev) => ({
          ...prev,
          token: data.token!,
          expiresAt: data.expires_at!,
        }));
        scheduleRefresh(data.expires_at);
      } catch (err) {
        // Pas critique — l'ancien token reste valide jusqu'à `expires_at`.
        // Le prochain remount du hook refera un bootstrap si besoin.
        console.warn(
          "[useViewerToken] proactive refresh failed — keeping current token:",
          err,
        );
      }
    };

    /**
     * Bootstrap initial — POST /api/voice/token.
     */
    const bootstrap = async (): Promise<void> => {
      try {
        const resp = await fetch(buildUrl(VIEWER_TOKEN_ENDPOINT), {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
        });
        if (cancelled) return;
        if (!resp.ok) {
          let detail = `HTTP ${resp.status}`;
          try {
            const payload = await resp.json();
            if (payload && typeof payload.detail === "string") {
              detail = payload.detail;
            }
          } catch {
            // body non-JSON → on garde le détail HTTP.
          }
          throw new Error(`voice-token fetch failed: ${detail}`);
        }
        const data = (await resp.json()) as BackendTokenResponse;
        if (cancelled) return;

        // Compat : le backend expose `livekit_url`, le LiveKitProvider D-6
        // initial attendait `url`. On accepte les deux pour la migration.
        const livekitUrl = data.livekit_url ?? data.url ?? null;
        const token = data.token ?? null;
        const expiresAt = data.expires_at ?? null;

        if (!token || expiresAt === null || livekitUrl === null) {
          throw new Error(
            "voice-token response missing required fields (token, expires_at, livekit_url|url)",
          );
        }

        tokenRef.current = token;
        setState({
          token,
          livekitUrl,
          expiresAt,
          isLoading: false,
          error: null,
        });
        scheduleRefresh(expiresAt);
      } catch (err) {
        if (cancelled) return;
        const error = err instanceof Error ? err : new Error(String(err));
        console.error("[useViewerToken] bootstrap failed:", error);
        setState((prev) => ({
          ...prev,
          isLoading: false,
          error,
        }));
      }
    };

    void bootstrap();

    return () => {
      cancelled = true;
      clearRefreshTimer();
    };
  }, [enabled]);

  // Quand disabled, on expose un snapshot inerte sans toucher au state interne.
  // Pas d'effet de bord → pas de cascading render au toggle.
  if (!enabled) {
    return {
      token: null,
      livekitUrl: null,
      expiresAt: null,
      isLoading: false,
      error: null,
    };
  }
  return state;
}
