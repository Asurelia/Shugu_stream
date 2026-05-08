/**
 * ViewerEventsProvider — runtime wiring D-3 → D-7 → D-8 (Sprint D PR D-8).
 *
 * Composant React qui matérialise la chaîne complète :
 *
 *   useViewerToken → ViewerEventsClient → sceneApplyMapper →
 *     SceneScheduler → emoteController.applyDirectorAction
 *
 * Monter ce Provider à côté de `LiveKitProvider` dans le viewer page (les deux
 * partagent le hook `useViewerToken` mutualisé). Le Provider :
 *
 *   1. Récupère le token viewer + URL LiveKit via `useViewerToken()`.
 *   2. Construit l'URL WebSocket vers `/ws/viewer/events` avec auto-upgrade
 *      du protocole (HTTPS page → WSS, HTTP local-dev page → plain WS) et
 *      préfixe `NEXT_PUBLIC_BASE_PATH` éventuel.
 *   3. Instancie un `ViewerEventsClient` + `SceneScheduler`.
 *   4. `onSceneApply` → `mapSceneApply(event)` → `scheduler.schedule(event, action)`.
 *      Le scheduler décide rAF/setTimeout selon `audio_at_ms`. À l'échéance,
 *      il appelle `emoteController.applyDirectorAction(action)`.
 *   5. `onInterrupt` → `scheduler.flush()` (drop pending events).
 *      L'application d'une expression neutre arrivera en D-9.
 *
 * Architecture isolation : la chaîne est PUREMENT pilotée côté frontend par
 * les events backend — pas d'état React partagé avec LiveKitProvider hormis
 * via le viewer-context (lecture du `model.emoteController` quand un event
 * arrive). Si le viewer.model n'est pas encore loaded, on log warn et on
 * skip — pas de queue côté frontend (le backend re-broadcast au reconnect).
 *
 * Référence spec : docs/specs/2026-05-08-voice-body-pipeline-design.md §3.2 + §6.2.
 */

"use client";

import {
  useContext,
  useEffect,
  useRef,
  type ReactNode,
} from "react";
import { ViewerContext } from "@/features/vrmViewer/viewerContext";
import { useViewerToken } from "./useViewerToken";
import { ViewerEventsClient } from "./ViewerEventsClient";
import { mapSceneApply } from "./sceneApplyMapper";
import { SceneScheduler } from "./sceneScheduler";

// ─── Constantes ─────────────────────────────────────────────────────────────

/** Path WS exposé par le backend (`backend/shugu/routes/viewer.py`). */
const WS_VIEWER_EVENTS_PATH = "/ws/viewer/events";

// ─── Helpers ────────────────────────────────────────────────────────────────

/**
 * Construit l'URL WebSocket depuis `window.location` (browser SSR-safe via
 * lazy evaluation dans useEffect). Auto-upgrade : si la page est servie en
 * HTTPS, on utilise WebSocket Secure (`wss:`). Le fallback `ws:` n'est
 * possible que si la page elle-même est servie en HTTP (local-dev) — la
 * production est forcément en HTTPS, donc forcément en WSS.
 *
 * Sécurité : pas de risque de cleartext-leak en prod tant que le hosting
 * sert l'app en HTTPS (cf spec §6.3 + headers Strict-Transport-Security).
 *
 * Exposée pour les tests — accepte un `windowLocation` factice optionnel.
 */
export function buildViewerEventsUrl(
  windowLocation?: { protocol: string; host: string },
): string {
  const loc = windowLocation ?? window.location;
  // Si la page est en HTTPS, on impose WSS. Sinon (local dev en plain HTTP),
  // on accepte le protocole non-secure miroir.
  const wsProto = loc.protocol === "https:" ? "wss:" : "ws:";
  const basePath = process.env.NEXT_PUBLIC_BASE_PATH ?? "";
  return `${wsProto}//${loc.host}${basePath}${WS_VIEWER_EVENTS_PATH}`;
}

// ─── Composant ──────────────────────────────────────────────────────────────

interface ViewerEventsProviderProps {
  children: ReactNode;
  /** Override de l'URL WS (utilisé en tests pour pointer vers un mock). */
  url?: string;
  /**
   * Active ou désactive l'écoute des events. Quand `false`, le Provider rend
   * uniquement les children sans fetcher de token ni ouvrir de WebSocket.
   * Mêmes raisons que `LiveKitProvider.enabled` : permet un wrap inconditionnel
   * pour éviter le remount du sous-arbre VRM. Défaut : true.
   */
  enabled?: boolean;
}

/**
 * Provider qui orchestre `ViewerEventsClient` + `SceneScheduler` et applique
 * les actions au `emoteController` du viewer en cours.
 *
 * Lifecycle :
 *   1. Mount + token reçu → instancie scheduler + client + connect().
 *   2. Sur scene.apply → schedule via mapper.
 *   3. Sur voice.interrupt → flush pending.
 *   4. Unmount → client.disconnect() + scheduler.flush() (cleanup propre,
 *      empêche un setTimeout en flight de fire après unmount).
 */
export function ViewerEventsProvider({
  children,
  url,
  enabled = true,
}: ViewerEventsProviderProps): JSX.Element {
  const { viewer } = useContext(ViewerContext);
  const { token } = useViewerToken({ enabled });

  // Refs stables — évitent re-instantiation sur re-render du parent.
  const clientRef = useRef<ViewerEventsClient | null>(null);
  const schedulerRef = useRef<SceneScheduler | null>(null);
  /** Capture du moment où la chunk audio courante a commencé à jouer
   *  côté frontend. Mis à jour par LiveKitProvider via `audio.onplaying`
   *  (wiring D-9). En MVP D-8, reste null → scheduler apply immédiat
   *  (acceptable au démarrage, cf spec §6.2). */
  const chunkStartedAtRef = useRef<number | null>(null);

  useEffect(() => {
    // Garde anti-double-instantiation : si on a déjà un client, on ne
    // re-bootstrap pas sur re-render. Le hook `useViewerToken` peut update
    // le `token` à T-60s (refresh proactif) — on ne veut PAS rejouer la
    // connexion WS, le client existant garde son token initial pour la
    // session active. Cf design notes useViewerToken.
    if (!enabled) {
      return;
    }
    if (clientRef.current) {
      return;
    }
    if (!token) {
      return;
    }
    if (typeof window === "undefined") {
      // SSR safety : pas de window → on attend l'hydratation client.
      return;
    }

    // Construction du scheduler en premier — il sera capturé par les closures
    // onSceneApply / onInterrupt.
    const scheduler = new SceneScheduler({
      getAudioContext: () => viewer.model?.audioContext,
      getChunkStartedAtPerfNow: () => chunkStartedAtRef.current,
      onApply: (action) => {
        const ctrl = viewer.model?.emoteController;
        if (!ctrl) {
          // VRM pas encore loaded : pas de queue côté frontend (le backend
          // continue de broadcast l'état courant via /api/viewer/state).
          // On log debug, pas warn — c'est un transient nominal au boot.
          console.debug(
            "[ViewerEventsProvider] emoteController not ready — skip action.",
          );
          return;
        }
        ctrl.applyDirectorAction(action);
      },
    });
    schedulerRef.current = scheduler;

    const wsUrl = url ?? buildViewerEventsUrl();
    const client = new ViewerEventsClient({
      url: wsUrl,
      token,
      onSceneApply: (event) => {
        const action = mapSceneApply(event);
        scheduler.schedule(event, action);
      },
      onInterrupt: () => {
        scheduler.flush();
        // D-9 : appliquer une expression neutre + ramp-down audio. Stub.
      },
    });
    clientRef.current = client;
    void client.connect();

    return () => {
      // Cleanup ordre important : flush() AVANT disconnect() pour annuler
      // tout setTimeout pending — sinon une callback fired après unmount
      // accéderait au viewer.model qui peut être en cours de teardown.
      schedulerRef.current?.flush();
      schedulerRef.current = null;
      clientRef.current?.disconnect();
      clientRef.current = null;
    };
    // viewer est un singleton de contexte (stable). token vient du hook —
    // re-rentrée dans l'effect serait un bug (cf garde ci-dessus).
    // enabled flip false→true ré-arme le pipeline (cleanup propre via cancel).
  }, [viewer, token, url, enabled]);

  return <>{children}</>;
}
