/**
 * LiveKitProvider — Context React qui gère la session LiveKit côté viewer.
 *
 * Sprint D PR D-6 (voice-body pipeline) : ce Provider est monté dans le
 * viewer page React une fois le VRM chargé.
 *
 * Sprint D PR D-8 (refactor) : le fetch + refresh proactif du token est
 * désormais délégué au hook `useViewerToken()` mutualisé avec
 * `ViewerEventsProvider`. Le Provider ne fetche plus directement — il consomme
 * `{ token, livekitUrl }` depuis le hook et instancie LiveKitClient une seule
 * fois (pas de re-instantiation sur refresh, sinon l'audio serait silencié
 * toutes les ~4 minutes).
 *
 * Workflow au mount :
 *   1. `useViewerToken()` fetch `/api/voice/token` (mutualisé entre Providers).
 *   2. Une fois `token` + `livekitUrl` dispo, instancie un `LiveKitClient`.
 *   3. Quand le client signale un audio track (callback `onAudioTrack`), il
 *      branche le `HTMLAudioElement` sur l'analyser lipSync du viewer via
 *      `viewer.model.attachStreamingAudio(audio)`.
 *   4. Si l'AudioContext est suspendu (Chrome autoplay policy), il affiche
 *      un overlay "Click to start audio" qui appelle `audioContext.resume()`.
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
import { useViewerToken } from "@/features/viewer/useViewerToken";

/** Endpoint historique exposé pour compat — le fetch concret est désormais
 *  encapsulé dans `useViewerToken`. Conservé pour les imports externes
 *  (ne pas supprimer sans audit). */
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
   * Active ou désactive le pipeline voice. Quand `false`, le Provider rend
   * uniquement les children sans fetcher de token ni instancier de LiveKit
   * client. Permet de wrap toujours l'arbre par les Providers (évite un
   * remount du `<VrmViewer />` quand l'user log in mid-session) tout en
   * gardant le voice pipeline gated derrière l'auth. Défaut : true.
   */
  enabled?: boolean;
}

/**
 * Provider — monter au-dessus de `<VrmViewer />` dans la hiérarchie React.
 *
 * Architecture isolation : ce Provider ne lit `viewer.model` qu'au moment où
 * un audio track arrive. À ce point-là, idéalement le VRM est déjà chargé,
 * mais il existe une race documentée : token-fetch peut compléter avant que
 * le VRM (28 MB) finisse de se charger en cold-cache. `RoomEvent.TrackSubscribed`
 * ne fire qu'UNE fois par session — sans gestion explicite, l'audio serait
 * perdu pour toute la session avec zéro signal user. On poll donc 100ms x 300
 * (30s cap) jusqu'à ce que le model soit ready, puis on flush l'audio en attente.
 *
 * IMPORTANT D-8 : `useViewerToken()` peut update son `state.token` à T-60s avant
 * exp (refresh proactif). Le Provider ne re-instancie PAS LiveKitClient sur ce
 * change — sinon l'audio serait silencé toutes les ~4 minutes. Le client conserve
 * son token initial pour la durée de la session active ; le refresh sert à
 * fournir un token frais pour le PROCHAIN connect (transient drop, remount).
 * Cf spec §6.3 + design notes useViewerToken.
 */
export function LiveKitProvider({
  children,
  enabled = true,
}: LiveKitProviderProps): JSX.Element {
  const { viewer } = useContext(ViewerContext);
  const { token, livekitUrl, error: tokenError } = useViewerToken({ enabled });

  const [isConnected, setIsConnected] = useState(false);
  const [isReconnecting, setIsReconnecting] = useState(false);
  const [needsUserGesture, setNeedsUserGesture] = useState(false);
  const [connectError, setConnectError] = useState<Error | null>(null);

  // L'erreur affichée à l'user est la première qui survient : token (priorité
  // haute, bloque tout) sinon la connect error (Room.connect KO mais token OK).
  // Dérivation pure → pas d'effect de synchro qui forcerait un re-render.
  const error: Error | null = tokenError ?? connectError;

  // On garde une ref vers le client pour le cleanup au unmount sans
  // re-render inutile.
  const clientRef = useRef<LiveKitClient | null>(null);

  // Race fix — gestion de l'audio reçu avant que viewer.model soit ready.
  // `pendingAudioRef` retient le HTMLAudioElement en attente.
  // `pollIntervalRef` track le setInterval pour cleanup propre au unmount.
  const pendingAudioRef = useRef<HTMLAudioElement | null>(null);
  const pollIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

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

    if (!enabled) {
      // Voice gated derrière l'auth. Le hook ne fetch même pas dans cet état.
      return;
    }
    // Garde anti-reinstantiation : si un client existe déjà, on ne re-rentre
    // PAS dans bootstrap quand `token` change (refresh proactif T-60s).
    if (clientRef.current) {
      return;
    }
    // Attend que le hook ait délivré le token + l'URL.
    if (!token || !livekitUrl) {
      return;
    }

    /**
     * Bootstrap pipeline :
     *   instancie LiveKitClient → connect →
     *   onAudioTrack câble lipSync.attachStreamingAudio.
     */
    const bootstrap = async (): Promise<void> => {
      try {
        const client = new LiveKitClient({
          url: livekitUrl,
          token,
          onAudioTrack: (_track, audio) => {
            // Tente l'attach maintenant. Retourne true si succès (model était
            // ready), false si on doit poll en attendant que le VRM finisse
            // de charger.
            const tryAttach = (): boolean => {
              const model = viewer.model;
              if (!model) return false;
              model.attachStreamingAudio(audio);
              // Vérifier la policy autoplay : si le context du browser refuse
              // de jouer l'audio sans user gesture, on lève le flag pour que
              // l'overlay s'affiche.
              const ctx = model.audioContext;
              if (ctx && ctx.state === "suspended") {
                setNeedsUserGesture(true);
              }
              return true;
            };

            if (tryAttach()) return;

            // Race condition fix — TrackSubscribed fire UNE seule fois par
            // session (le backend D-1 publie une track persistante, pas une
            // par chunk). Si on droppait ici sans retry, l'audio serait perdu
            // pour TOUTE la session sans signal user. On poll 100ms x 300
            // (30s cap) jusqu'à ce que viewer.model soit ready.
            console.warn(
              "[LiveKit] Audio track received before viewer.model ready — polling 100ms × 300 (30s cap).",
            );
            pendingAudioRef.current = audio;
            // Cleanup tout poll précédent (paranoïa : si un onAudioTrack
            // précédent avait laissé un poll actif, on l'écrase ici).
            if (pollIntervalRef.current) {
              clearInterval(pollIntervalRef.current);
            }
            let attempts = 0;
            pollIntervalRef.current = setInterval(() => {
              attempts++;
              if (cancelled) {
                // Provider unmonté pendant le poll — cleanup et stop.
                if (pollIntervalRef.current) {
                  clearInterval(pollIntervalRef.current);
                  pollIntervalRef.current = null;
                }
                return;
              }
              if (tryAttach()) {
                if (pollIntervalRef.current) {
                  clearInterval(pollIntervalRef.current);
                  pollIntervalRef.current = null;
                }
                pendingAudioRef.current = null;
                console.info(
                  `[LiveKit] viewer.model ready after ${attempts * 100}ms — audio attached.`,
                );
              } else if (attempts >= 300) {
                // 30s : éviter l'interval-leak et signaler clairement.
                if (pollIntervalRef.current) {
                  clearInterval(pollIntervalRef.current);
                  pollIntervalRef.current = null;
                }
                pendingAudioRef.current = null;
                console.error(
                  "[LiveKit] viewer.model never became ready after 30s — audio dropped, session degraded.",
                );
                setConnectError(
                  new Error("VRM model never loaded — audio attach failed"),
                );
              }
            }, 100);
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
        setConnectError(err instanceof Error ? err : new Error(String(err)));
      }
    };

    void bootstrap();

    return () => {
      cancelled = true;
      // Cleanup poll race-fix avant disconnect, sinon l'interval pourrait
      // appeler attachStreamingAudio sur un model en cours d'unmount.
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
        pollIntervalRef.current = null;
      }
      pendingAudioRef.current = null;
      clientRef.current?.disconnect();
      clientRef.current = null;
    };
    // viewer is a context-singleton (see viewerContext.ts) — stable across
    // renders. token + livekitUrl viennent du hook useViewerToken : on
    // ne re-rentre dans bootstrap() qu'au mount initial (guarded ci-dessus).
    // `enabled` flip false→true ré-arme le bootstrap.
  }, [viewer, token, livekitUrl, enabled]);

  // Token refresh proactif T-60s : géré par `useViewerToken` (D-8).

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
