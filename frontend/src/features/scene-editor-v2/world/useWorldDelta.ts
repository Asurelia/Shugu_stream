/**
 * useWorldDelta — React hook that subscribes to /ws/world WebSocket events
 * and applies each world.delta to the useWorldStateStore.
 *
 * Usage: call once at the root of the 3D Workspace component (single instance
 * per app). The hook is intentionally side-effect only (returns void).
 *
 * Reconnection: exponential backoff from 1s up to 16s maximum, capped per
 * the ShuguClient pattern. Backoff resets to 1s on each successful open.
 * Cancelled on unmount — no reconnect attempt after component is destroyed.
 *
 * Protocol: the backend pushes JSON dicts matching WorldDelta (partial
 * WorldState). Any invalid JSON is silently discarded with a console.warn.
 *
 * Auth: the backend expects the shugu_access httpOnly cookie (operator JWT).
 * No explicit token is passed in the URL — the browser sends the cookie
 * automatically on the WS upgrade request (same-origin).
 *
 * @module world/useWorldDelta
 */

import { useEffect, useRef } from "react";
import { useWorldStateStore } from "./useWorldStateStore";

const INITIAL_BACKOFF_MS = 1000;
const MAX_BACKOFF_MS = 16000;

/** Resolves the WebSocket base URL from the current window location. */
function getWsBaseUrl(): string {
  const wsProto =
    typeof window !== "undefined" && window.location.protocol === "https:"
      ? "wss:"
      : "ws:";
  const host = typeof window !== "undefined" ? window.location.host : "";
  return `${wsProto}//${host}`;
}

/**
 * Opens a WebSocket to /ws/world and applies each received world.delta
 * to the global useWorldStateStore.
 *
 * The hook reconnects automatically on disconnect using exponential backoff
 * (1s → 2s → 4s → … → 16s, then capped).
 *
 * @example
 * // In the root of the 3D Workspace:
 * function WorldWorkspace() {
 *   useWorldDelta(); // single call — subscribes for this app instance
 *   return <Canvas />;
 * }
 */
export function useWorldDelta(): void {
  const applyDelta = useWorldStateStore((s) => s.applyDelta);
  const wsRef = useRef<WebSocket | null>(null);
  const backoffRef = useRef(INITIAL_BACKOFF_MS);

  useEffect(() => {
    let cancelled = false;

    const connect = (): void => {
      if (cancelled) return;

      const url = `${getWsBaseUrl()}/ws/world`;
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = (): void => {
        backoffRef.current = INITIAL_BACKOFF_MS; // reset backoff on success
      };

      ws.onmessage = (ev: MessageEvent): void => {
        try {
          const delta = JSON.parse(ev.data as string);
          applyDelta(delta);
        } catch (err) {
          console.warn("useWorldDelta: invalid delta payload", err);
        }
      };

      ws.onclose = (): void => {
        if (cancelled) return;
        const delay = backoffRef.current;
        backoffRef.current = Math.min(delay * 2, MAX_BACKOFF_MS);
        setTimeout(connect, delay);
      };

      ws.onerror = (err: Event): void => {
        // onclose will fire after onerror — reconnect handled there.
        console.warn("useWorldDelta: WebSocket error", err);
      };
    };

    connect();

    return (): void => {
      cancelled = true;
      wsRef.current?.close();
    };
  }, [applyDelta]);
}
