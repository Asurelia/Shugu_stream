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
    <div className="fixed top-4 left-1/2 -translate-x-1/2 z-20 flex items-center gap-2 veil-body">
      <div
        className={`flex items-center gap-1.5 px-3 py-1 rounded-full font-bold text-[11px] sm:text-xs tracking-wide transition-all ${
          live
            ? "veil-gradient-secondary text-white veil-halo-pink"
            : "veil-glass text-veil-on-surface-variant"
        }`}
      >
        <span
          className={`w-1.5 h-1.5 rounded-full ${
            live
              ? "bg-white animate-live-pulse"
              : connStatus === "connecting"
                ? "bg-veil-tertiary animate-pulse"
                : "bg-veil-outline"
          }`}
        />
        <span>{live ? "LIVE" : connStatus === "connecting" ? "…" : "OFF"}</span>
        {speaking && live && <span className="hidden sm:inline opacity-90">✦</span>}
      </div>

      <div className="flex items-center gap-1.5 px-3 py-1 rounded-full veil-glass text-veil-on-surface text-[11px] sm:text-xs font-semibold">
        <span className="text-veil-tertiary">◇</span>
        <span className="veil-headline tracking-tight">{viewerCount}</span>
      </div>
    </div>
  );
}
