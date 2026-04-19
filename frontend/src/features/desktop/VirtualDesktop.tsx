// VirtualDesktop — the glass surface where Hermes's windows live.
//
// Positioned as an overlay on the right half of the screen (asymmetric,
// Celestial-Veil-style). Only renders when there's at least one thing to show,
// so it stays out of the way of an empty stream.

import { useEffect } from "react";
import { DesktopWindow } from "./DesktopWindow";
import { HermesStateWindow } from "./HermesStateWindow";
import { useDesktopState } from "./desktopState";

export function VirtualDesktop() {
  const { state, dispatch } = useDesktopState();
  const hasWindows = Object.keys(state.windows).length > 0;
  const hasImage = state.image !== null;
  const hasHud = state.hermesHud.open;

  const visible = hasWindows || hasImage || hasHud;
  if (!visible) return null;

  return (
    <div className="pointer-events-none fixed inset-0 z-10">
      {/* Asymmetric glass surface anchored to the right-center of the viewport.
          Width 44vw on desktop, full-bleed beneath on mobile. */}
      <div
        className="pointer-events-auto absolute top-24 right-0 md:right-[340px] bottom-24 w-[min(520px,44vw)] hidden md:block"
        aria-label="bureau virtuel"
      >
        {/* Windows */}
        {state.order.map((name) => {
          const win = state.windows[name];
          if (!win) return null;
          return <DesktopWindow key={name} win={win} />;
        })}

        {hasHud && <HermesStateWindow />}

        {/* Fullscreen image overlay (below windows, above background) */}
        {hasImage && state.image && (
          <div
            onClick={() => dispatch({ type: "image.clear" })}
            className="absolute inset-0 rounded-xl overflow-hidden bg-black/50 backdrop-blur-md flex items-center justify-center animate-fade-up"
            style={{ zIndex: 50 }}
          >
            <img
              src={state.image.url}
              alt={state.image.caption || "image"}
              className="max-w-full max-h-full"
              style={{ objectFit: state.image.fit === "cover" ? "cover" : "contain" }}
            />
            {state.image.caption && (
              <div className="absolute bottom-3 left-3 right-3 text-shugu-cream text-xs px-3 py-1.5 rounded-full text-center"
                style={{ background: "rgba(26,10,32,0.75)" }}
              >
                {state.image.caption}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * Minimize-all auto-apply when the layout switches to minimize_all — this is
 * idempotent because the reducer flips the `minimized` flag on every window.
 * Lives outside the main component so it can subscribe without re-rendering
 * the whole desktop on every state tick.
 */
export function useDesktopLayoutSync() {
  const { state, dispatch } = useDesktopState();
  useEffect(() => {
    if (state.layout === "minimize_all") {
      // Already applied in reducer; nothing more to do — hook exists to add
      // focus/tile_right transitions later without refactoring index.tsx.
    }
  }, [state.layout, dispatch]);
}
