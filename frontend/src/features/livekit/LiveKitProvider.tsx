/**
 * LiveKitProvider — Context React qui gère la session LiveKit côté viewer.
 *
 * Sprint D PR D-6 (voice-body pipeline) : ce Provider est monté dans le
 * viewer page React une fois le VRM chargé. Au mount, il :
 *
 *   1. Fetch un JWT viewer-token via `POST /api/voice/token`.
 *   2. Instancie un `LiveKitClient` avec le token + l'URL retournés.
 *   3. Quand le client signale un audio track (callback `onAudioTrack`), il
 *      branche le `HTMLAudioElement` sur l'analyser lipSync du viewer via
 *      `viewer.model.attachStreamingAudio(audio)`. Conséquence : les
 *      blendshapes mouth de l'avatar bougent en synchro avec la TTS.
 *   4. Si l'AudioContext est suspendu (Chrome autoplay policy), il affiche
 *      un overlay "Click to start audio" qui appelle `audioContext.resume()`
 *      sur l'AudioContext exposé par le viewer (PAS un nouveau context, sinon
 *      les deux graphs deviendraient désynchronisés).
 *   5. Au unmount, il appelle `client.disconnect()` pour libérer la Room.
 *
 * Les valeurs exposées via le Context :
 *   - `isConnected`            : Room.state === "connected"
 *   - `isReconnecting`         : Room en RoomEvent.Reconnecting
 *   - `needsUserGesture`       : AudioContext suspendu, overlay actif
 *   - `resume()`               : appel manuel pour resume l'audio context
 *   - `error`                  : Error remontée si fetch token / connect KO
 *
 * Référence spec : docs/specs/2026-05-08-voice-body-pipeline-design.md §3.2 + §6.2.
 */

"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { ViewerContext } from "@/features/vrmViewer/viewerContext";
import { LiveKitClient } from "./LiveKitClient";
import { buildUrl } from "@/utils/buildUrl";

/** Réponse attendue de `POST /api/voice/token`. Aligné sur le pattern existant
 *  `mintVIPToken` (services/livekitClient.ts) : `{ token, url, room }`. */
interface VoiceTokenResponse {
  token: string;
  url: string;
  room?: string;
}

/** Endpoint pour récupérer un viewer-token TTL court (5 min, cf spec §6.3).
 *  `buildUrl` préfixe le `NEXT_PUBLIC_BASE_PATH` éventuel. */
export const VOICE_TOKEN_ENDPOINT = "/api/voice/token";

/** Surface du Context React exposée aux consumers via `useLiveKit()`. */
export interface LiveKitContextValue {
  isConnected: boolean;
  isReconnecting: boolean;
  needsUserGesture: boolean;
  /** Appelle `audioContext.resume()` sur l'AudioContext du viewer.
   *  Idempotent — peut être invoqué plusieurs fois sans effet de bord. */
  resume: () => Promise<void>;
  error: Error | null;
}

const DEFAULT_VALUE: LiveKitContextValue = {
  isConnected: false,
  isReconnecting: false,
  needsUserGesture: false,
  resume: async () => {
    /* no-op fallback when used outside Provider */
  },
  error: null,
};

export const LiveKitContext = createContext<LiveKitContextValue>(DEFAULT_VALUE);

/** Hook utilitaire pour accéder au context. */
export function useLiveKit(): LiveKitContextValue {
  return useContext(LiveKitContext);
}

interface LiveKitProviderProps {
  children: ReactNode;
  /**
   * Override l'endpoint de fetch du token (utile pour tests / déploiements
   * derrière un reverse-proxy avec préfixe non-standard).
   */
  tokenEndpoint?: string;
}

/**
 * Provider — monter au-dessus de `<VrmViewer />` dans la hiérarchie React.
 *
 * Architecture isolation : ce Provider ne lit `viewer.model` qu'au moment où
 * un audio track arrive. À ce point-là, le VRM est forcément chargé (sinon le
 * backend n'aurait pas commencé à publier). Si jamais le model est encore
 * undefined (race), on log et on retry au prochain track ; pas de crash.
 */
export function LiveKitProvider({
  children,
  tokenEndpoint = VOICE_TOKEN_ENDPOINT,
}: LiveKitProviderProps): JSX.Element {
  const { viewer } = useContext(ViewerContext);

  const [isConnected, setIsConnected] = useState(false);
  const [isReconnecting, setIsReconnecting] = useState(false);
  const [needsUserGesture, setNeedsUserGesture] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  // On garde une ref vers le client pour le cleanup au unmount sans
  // re-render inutile.
  const clientRef = useRef<LiveKitClient | null>(null);

  // Resume = appelle audioContext.resume() sur l'AudioContext du viewer.
  const resume = useCallback(async (): Promise<void> => {
    const ctx = viewer.model?.audioContext;
    if (!ctx) return;
    // Early return si déjà "running" — pas de raison de retoucher l'overlay.
    if (ctx.state === "running") {
      setNeedsUserGesture(false);
      return;
    }
    try {
      await ctx.resume();
      // Re-lire `state` après l'await : TS narrow le type via la branche du
      // early-return ci-dessus, mais l'await change cet état runtime. On cast
      // explicitement vers le type complet pour comparer "running" librement.
      const newState = ctx.state as AudioContextState;
      if (newState === "running") {
        setNeedsUserGesture(false);
      }
    } catch (resumeErr) {
      // Si resume() échoue (très rare hors quotas), on log mais on garde
      // l'overlay actif pour donner une chance au user de re-cliquer.
      console.warn("[LiveKit] AudioContext.resume() failed:", resumeErr);
    }
  }, [viewer]);

  useEffect(() => {
    let cancelled = false;

    /**
     * Bootstrap pipeline :
     *   fetch token → instancie LiveKitClient → connect →
     *   onAudioTrack câble lipSync.attachStreamingAudio.
     */
    const bootstrap = async (): Promise<void> => {
      try {
        const resp = await fetch(buildUrl(tokenEndpoint), {
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
            // body non-JSON → on garde le détail HTTP générique
          }
          throw new Error(`voice-token fetch failed: ${detail}`);
        }

        const data = (await resp.json()) as VoiceTokenResponse;
        if (cancelled) return;

        if (!data?.token || !data?.url) {
          throw new Error(
            "voice-token response missing required fields (token, url)",
          );
        }

        const client = new LiveKitClient({
          url: data.url,
          token: data.token,
          onAudioTrack: (_track, audio) => {
            const model = viewer.model;
            if (!model) {
              console.warn(
                "[LiveKit] Audio track received but viewer.model is not ready — skipping lipSync attach (will be retried on next track).",
              );
              return;
            }
            model.attachStreamingAudio(audio);

            // Vérifier la policy autoplay : si le context du browser refuse
            // de jouer l'audio sans user gesture, on lève le flag pour que
            // l'overlay s'affiche.
            const ctx = model.audioContext;
            if (ctx && ctx.state === "suspended") {
              setNeedsUserGesture(true);
            }
          },
          onConnected: () => {
            if (cancelled) return;
            setIsConnected(true);
            setIsReconnecting(false);
          },
          onReconnecting: () => {
            if (cancelled) return;
            setIsReconnecting(true);
          },
          onReconnected: () => {
            if (cancelled) return;
            setIsReconnecting(false);
            setIsConnected(true);
          },
          onDisconnected: () => {
            if (cancelled) return;
            setIsConnected(false);
            setIsReconnecting(false);
          },
        });

        clientRef.current = client;
        await client.connect();
      } catch (err) {
        if (cancelled) return;
        console.error("[LiveKit] bootstrap failed:", err);
        setError(err instanceof Error ? err : new Error(String(err)));
      }
    };

    void bootstrap();

    return () => {
      cancelled = true;
      clientRef.current?.disconnect();
      clientRef.current = null;
    };
    // viewer is a context-singleton (see viewerContext.ts) — stable across
    // renders. tokenEndpoint is a prop, on re-fetch si parent en change.
  }, [viewer, tokenEndpoint]);

  const value: LiveKitContextValue = {
    isConnected,
    isReconnecting,
    needsUserGesture,
    resume,
    error,
  };

  return (
    <LiveKitContext.Provider value={value}>
      {children}
      {needsUserGesture && (
        <NeedsUserGestureOverlay onClick={() => void resume()} />
      )}
      {error && (
        <div
          data-testid="livekit-error"
          role="alert"
          className="fixed bottom-4 right-4 z-50 max-w-md rounded-md bg-red-600/95 px-4 py-3 text-sm text-white shadow-lg"
        >
          <strong className="block mb-1">Voice connection error</strong>
          <span className="opacity-90">{error.message}</span>
        </div>
      )}
    </LiveKitContext.Provider>
  );
}

/** Overlay click-to-start affiché quand l'AudioContext est suspendu.
 *  Pattern standard pour contourner Chrome/Safari autoplay policy. */
function NeedsUserGestureOverlay({
  onClick,
}: {
  onClick: () => void;
}): JSX.Element {
  return (
    <div
      data-testid="livekit-user-gesture-overlay"
      className="fixed inset-0 z-40 flex items-center justify-center bg-black/40 backdrop-blur-sm"
    >
      <button
        type="button"
        onClick={onClick}
        className="rounded-md bg-white px-6 py-3 text-base font-medium text-slate-900 shadow-lg hover:bg-slate-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
      >
        Click to start audio
      </button>
    </div>
  );
}
