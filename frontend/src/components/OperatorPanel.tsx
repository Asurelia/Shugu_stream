import { useEffect, useRef, useState } from "react";
import { logout } from "../services/shuguClient";
import { AdminModal } from "./AdminModal";

export type Mode = "shugu" | "hermes";

type Props = {
  username: string;
  mode: Mode;
  onModeChange: (m: Mode) => void;
  pendingHermesTask?: boolean;
};

/**
 * Operator HUD — top-right under the LIVE badge. Collapses to just a chip on
 * hover-out 4 s. Segmented control replaces the two-buttons toggle from v1.
 */
export function OperatorPanel({ username, mode, onModeChange, pendingHermesTask }: Props) {
  const [adminOpen, setAdminOpen] = useState(false);
  const [expanded, setExpanded] = useState(true);
  const idleTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const markActive = () => {
    setExpanded(true);
    if (idleTimer.current) clearTimeout(idleTimer.current);
    idleTimer.current = setTimeout(() => setExpanded(false), 4000);
  };

  useEffect(() => {
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
            className="glass-pink text-shugu-cream text-xs px-3 py-1.5 rounded-full hover:scale-105 transition-transform"
          >
            ⚙ {username}
          </button>
        ) : (
          <div className="glass-pink text-shugu-cream rounded-2xl px-3 py-2.5 min-w-[220px] shadow-xl">
            <div className="flex items-center justify-between mb-2 text-xs">
              <div className="flex items-center gap-1.5">
                <span className="text-shugu-pink-glow">♡</span>
                <span className="font-bold">{username}</span>
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

            {/* Segmented control */}
            <div
              className="relative flex items-center bg-shugu-ink/80 rounded-full p-0.5"
              style={{ border: "1px solid rgba(255,168,185,0.15)" }}
            >
              <div
                className={`absolute top-0.5 bottom-0.5 w-[calc(50%-2px)] rounded-full transition-all duration-300 ${
                  mode === "shugu"
                    ? "left-0.5 bg-shugu-pink shadow-[0_0_12px_rgba(255,97,127,0.6)]"
                    : "left-[calc(50%+1px)] bg-shugu-live shadow-[0_0_12px_rgba(255,59,92,0.7)]"
                }`}
              />
              <button
                onClick={() => onModeChange("shugu")}
                className={`relative z-10 flex-1 py-1.5 text-xs font-bold rounded-full transition-colors ${
                  mode === "shugu" ? "text-white" : "text-shugu-cream-dim"
                }`}
              >
                ♡ Shugu
              </button>
              <button
                onClick={() => onModeChange("hermes")}
                className={`relative z-10 flex-1 py-1.5 text-xs font-bold rounded-full transition-colors ${
                  mode === "hermes" ? "text-white" : "text-shugu-cream-dim"
                }`}
              >
                ⚡ Hermes
              </button>
            </div>

            {mode === "hermes" && (
              <div className="mt-2 text-[10px] text-shugu-pink-glow leading-tight">
                outils réels • résumé filtré diffusé
              </div>
            )}
            {pendingHermesTask && (
              <div className="mt-2 text-[11px] text-shugu-blue flex items-center gap-1.5">
                <span className="w-1.5 h-1.5 rounded-full bg-shugu-blue animate-pulse" />
                Hermes travaille…
              </div>
            )}
          </div>
        )}
      </div>

      <AdminModal open={adminOpen} onClose={() => setAdminOpen(false)} />
    </>
  );
}
