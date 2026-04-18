type ConnStatus = "connecting" | "open" | "closed" | "error";

type Props = {
  connStatus: ConnStatus;
  viewerCount: number;
  speaking: boolean;
};

/**
 * Compact status chip — LIVE badge + viewer count only. Positioned top-center
 * on desktop so it doesn't collide with the Brand (left) or Operator HUD / login
 * button (right). On mobile, shifts to top-right but stays very small.
 */
export function LiveHUD({ connStatus, viewerCount, speaking }: Props) {
  const live = connStatus === "open";

  return (
    <div className="fixed top-4 left-1/2 -translate-x-1/2 z-20 flex items-center gap-2 font-quicksand">
      <div
        className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full font-bold text-[11px] sm:text-xs tracking-wide ${
          live
            ? "bg-shugu-live text-white"
            : "bg-shugu-ink-soft text-shugu-cream-dim"
        }`}
        style={live ? { boxShadow: "0 0 14px rgba(255, 59, 92, 0.55)" } : undefined}
      >
        <span
          className={`w-1.5 h-1.5 rounded-full ${
            live ? "bg-white animate-live-pulse" : connStatus === "connecting" ? "bg-yellow-300 animate-pulse" : "bg-gray-400"
          }`}
        />
        <span>{live ? "LIVE" : connStatus === "connecting" ? "…" : "OFF"}</span>
        {speaking && live && <span className="hidden sm:inline opacity-90">✨</span>}
      </div>

      <div className="flex items-center gap-1 px-2.5 py-1 rounded-full bg-shugu-ink-soft/85 text-shugu-cream text-[11px] sm:text-xs font-semibold">
        <span className="text-shugu-pink-soft">♡</span>
        <span>{viewerCount}</span>
      </div>
    </div>
  );
}
