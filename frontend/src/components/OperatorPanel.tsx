import { useEffect, useRef, useState } from "react";
import { logout } from "../services/shuguClient";
import { AdminModal } from "./AdminModal";

export type Mode = "shugu" | "hermes";

type Props = {
  username: string;
  mode: Mode;
  onModeChange: (m: Mode) => void;
  pendingHermesTask?: boolean;
  debugCaptions?: boolean;
  onDebugCaptionsChange?: (v: boolean) => void;
};

/**
 * Operator HUD — top-right under the LIVE badge. Collapses to just a chip on
 * hover-out 4 s. Segmented control replaces the two-buttons toggle from v1.
 *
 * The `debugCaptions` toggle reveals Shugu's own messages in the ChatFeed — by
 * default visitors (and operator) see none, since her voice is the only carrier
 * in public. Useful during dev to verify what the brain produced.
 */
export function OperatorPanel({
  username,
  mode,
  onModeChange,
  pendingHermesTask,
  debugCaptions = false,
  onDebugCaptionsChange,
}: Props) {
  const [adminOpen, setAdminOpen] = useState(false);
  const [expanded, setExpanded] = useState(true);
  const idleTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const markActive = () => {
    setExpanded(true);
    if (idleTimer.current) clearTimeout(idleTimer.current);
    idleTimer.current = setTimeout(() => setExpanded(false), 4000);
  };

  useEffect(() => {
    // FIXME: false positive — markActive → setExpanded is intentional (P3 idle timer init).
    // eslint-disable-next-line react-hooks/set-state-in-effect
    markActive();
    return () => { if (idleTimer.current) clearTimeout(idleTimer.current); };
  }, []);

  const handleLogout = async () => { await logout(); window.location.reload(); };

  const collapsed = !expanded;

  return (
    <>
      <div
        onMouseEnter={markActive}
        onFocus={markActive}
        className={`fixed right-4 md:right-[340px] z-20 font-quicksand transition-all duration-200 ${
          collapsed ? "top-14 sm:top-16" : "top-14 sm:top-16"
        }`}
      >
        {collapsed ? (
          <button
            onClick={markActive}
            className="veil-glass text-veil-on-surface veil-body text-xs px-3 py-1.5 rounded-full hover:scale-105 transition-transform"
          >
            ◈ {username}
          </button>
        ) : (
          <div className="veil-glass-bright text-veil-on-surface rounded-2xl px-3 py-2.5 min-w-[220px]">
            <div className="flex items-center justify-between mb-2 text-xs">
              <div className="flex items-center gap-1.5">
                <span className="text-veil-primary">◈</span>
                <span className="veil-headline text-veil-on-surface">{username}</span>
              </div>
              <div className="flex items-center gap-1">
                <button
                  onClick={() => setAdminOpen(true)}
                  title="dashboard admin"
                  className="w-7 h-7 rounded-full flex items-center justify-center text-shugu-pink-soft hover:text-shugu-pink-glow hover:bg-white/10"
                >
                  ⚙
                </button>
                <button
                  onClick={handleLogout}
                  title="se déconnecter"
                  className="w-7 h-7 rounded-full flex items-center justify-center text-shugu-cream-dim hover:text-shugu-cream hover:bg-white/10"
                >
                  ⏻
                </button>
              </div>
            </div>

            {/* Segmented control — tonal layering, no 1px border */}
            <div
              className="relative flex items-center rounded-full p-0.5"
              style={{ background: "rgba(13,13,24,0.65)" }}
            >
              <div
                className={`absolute top-0.5 bottom-0.5 w-[calc(50%-2px)] rounded-full transition-all duration-300 ${
                  mode === "shugu"
                    ? "left-0.5 veil-gradient-primary veil-halo-pink"
                    : "left-[calc(50%+1px)] veil-gradient-secondary veil-halo-pink"
                }`}
              />
              <button
                onClick={() => onModeChange("shugu")}
                className={`relative z-10 flex-1 py-1.5 text-xs font-bold rounded-full transition-colors ${
                  mode === "shugu" ? "text-white" : "text-veil-on-surface-variant"
                }`}
              >
                ✦ Shugu
              </button>
              <button
                onClick={() => onModeChange("hermes")}
                className={`relative z-10 flex-1 py-1.5 text-xs font-bold rounded-full transition-colors ${
                  mode === "hermes" ? "text-white" : "text-veil-on-surface-variant"
                }`}
              >
                ◇ Hermes
              </button>
            </div>

            {mode === "hermes" && (
              <div className="mt-2 veil-body text-[10px] text-veil-primary leading-tight">
                outils réels • résumé filtré diffusé
              </div>
            )}
            {pendingHermesTask && (
              <div className="mt-2 veil-body text-[11px] text-veil-tertiary flex items-center gap-1.5">
                <span className="w-1.5 h-1.5 rounded-full bg-veil-tertiary animate-pulse" />
                Hermes travaille…
              </div>
            )}

            {onDebugCaptionsChange && (
              <label className="mt-2.5 flex items-center justify-between veil-body text-[10px] text-veil-on-surface-variant cursor-pointer select-none hover:text-veil-on-surface">
                <span>captions debug</span>
                <input
                  type="checkbox"
                  checked={debugCaptions}
                  onChange={(e) => onDebugCaptionsChange(e.target.checked)}
                  className="accent-veil-primary w-3.5 h-3.5"
                />
              </label>
            )}
          </div>
        )}
      </div>

      <AdminModal open={adminOpen} onClose={() => setAdminOpen(false)} />
    </>
  );
}
