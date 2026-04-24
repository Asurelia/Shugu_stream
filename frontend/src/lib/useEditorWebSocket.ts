/**
 * React hook — `useEditorWebSocket(sceneId)` — Phase D.
 *
 * Pilote un `EditorWebSocket` sur tout le cycle de vie d'un composant React
 * et route les events reçus vers les actions du Zustand store
 * (`useSceneEditorStore`). Le hook est délibérément unidirectionnel côté
 * Phase D :
 *  - IN  : server → store (peer.joined → addPeer, draft.update → applyRemoteDraftUpdate, etc.)
 *  - OUT : rien. Les gestes "live-sync" (drag avatar, slider FOV) ne sont
 *          pas encore wired au `sendDraftUpdate` — ce sera fait en Phase F
 *          quand les panels auront une surface explicite pour émettre.
 *
 * Pourquoi ne PAS envoyer depuis le hook en Phase D :
 *  - sans savoir quel champ du store est "dirty par l'user" vs "reçu du WS",
 *    on créerait des boucles infinies (send → recv → applyRemoteDraftUpdate
 *    → store change → hook resend...).
 *  - Phase B explicite que `currentScene` / `layoutPreset` sont les seuls
 *    champs undoable ; Phase F enrichira le scope et fixera les règles de
 *    provenance avec un flag `isRemote: boolean` par action.
 *
 * Si `sceneId` est `null`, aucune WS n'est ouverte (utile pendant le chargement
 * initial, ou quand l'utilisateur n'a pas encore sélectionné de scène).
 * Un changement de `sceneId` déclenche un `subscribe()` — la WS est
 * réutilisée, pas recréée, pour minimiser les handshakes.
 */

import { useEffect, useRef } from "react";
import { EditorWebSocket, type EditorServerEvent } from "./editorWebSocket";
import { useSceneEditorStore } from "@/stores/useSceneEditorStore";

export type UseEditorWebSocketOptions = {
  /**
   * URL WS optionnelle (utile pour les tests Playwright qui redirigent vers
   * un backend local custom). Par défaut `wss?://<host>/ws/editor`.
   */
  url?: string;
  /**
   * Si false, le hook n'ouvre aucune WS — pratique pour désactiver la
   * collab live (mode "offline editing"). Défaut : true.
   */
  enabled?: boolean;
};

/**
 * Branche une WS `/ws/editor` au store Zustand pendant la vie du composant.
 *
 * Retourne une réf stable vers le client pour que le code appelant puisse
 * émettre lui-même des `sendDraftUpdate` ou `sendPreviewPush` (Phase F).
 */
export function useEditorWebSocket(
  sceneId: string | null,
  options: UseEditorWebSocketOptions = {},
): { clientRef: React.MutableRefObject<EditorWebSocket | null> } {
  const { url, enabled = true } = options;
  const clientRef = useRef<EditorWebSocket | null>(null);

  // Les actions Zustand sont stables (Zustand garantit l'identité tant que
  // le store n'est pas recréé) → on peut les accéder via getState() sans
  // impacter les deps du useEffect.
  useEffect(() => {
    if (!enabled) return;
    // SSR guard : no WebSocket constructor → le ref reste null.
    if (typeof window === "undefined" || typeof window.WebSocket !== "function") {
      return;
    }

    const onEvent = (event: EditorServerEvent) => {
      // Dispatcher typé par discriminant. On récupère les actions du store
      // à chaque event (getState() est O(1)) pour éviter les stale closures
      // si jamais le store est swap en dev avec HMR.
      const store = useSceneEditorStore.getState();
      switch (event.type) {
        case "subscribed":
          store.setPeers(event.peers);
          break;
        case "peer.joined":
          store.addPeer(event.operator);
          break;
        case "peer.left":
          store.removePeer(event.operator);
          break;
        case "draft.update":
          // delta est un Record<string, unknown> — shallow-merge dans l'état.
          store.applyRemoteDraftUpdate(event.delta);
          break;
        case "preview.push":
          // Phase D : preview côté operator = no-op (on reçoit le payload
          // mais aucune surface opérator n'a besoin de l'afficher ; les
          // visiteurs l'ont déjà via le `stage` topic existant).
          break;
        case "unsubscribed":
          // Reset la liste de peers quand on quitte la scène. `peers`
          // concerne uniquement la scène courante.
          store.setPeers([]);
          break;
        case "error":
          // Log uniquement — Phase D ne surfaces pas d'UI d'erreur WS.
          // eslint-disable-next-line no-console
          console.warn("[editor_ws] error:", event.code, event.message);
          break;
        // hello, ping, pong : no-op (gérés par EditorWebSocket directement
        // ou utilisés seulement pour le tracking de connexion).
        case "hello":
        case "ping":
        case "pong":
          break;
      }
    };

    const ws = new EditorWebSocket({ url, onEvent });
    clientRef.current = ws;

    return () => {
      ws.close();
      clientRef.current = null;
      // Cleanup state WS — on quitte l'éditeur, les peers du moment ne
      // sont plus pertinents.
      useSceneEditorStore.getState().setPeers([]);
    };
    // `enabled` et `url` changent rarement ; on re-crée la WS si ça arrive.
  }, [enabled, url]);

  // Subscribe quand sceneId change (sans reconstruire la WS). On attend que
  // la WS soit OPEN pour envoyer, sinon c'est dropé silencieusement par
  // EditorWebSocket — Phase D accepte la perte d'un premier subscribe en
  // race avec le handshake (l'UI se recalera au prochain subscribe ou au
  // prochain gesture).
  useEffect(() => {
    if (!enabled) return;
    if (!sceneId) return;
    const client = clientRef.current;
    if (!client) return;
    // Petite pollette : si ce n'est pas encore ouvert, on retry rapidement.
    if (client.isOpen()) {
      client.subscribe(sceneId);
    } else {
      const poll = setInterval(() => {
        if (client.isOpen()) {
          client.subscribe(sceneId);
          clearInterval(poll);
        }
      }, 100);
      // Safety timeout : on arrête d'essayer après 5s (la reconnect logic
      // d'EditorWebSocket prendra le relais si le backend est down).
      const safety = setTimeout(() => clearInterval(poll), 5000);
      return () => {
        clearInterval(poll);
        clearTimeout(safety);
      };
    }
  }, [sceneId, enabled]);

  return { clientRef };
}
