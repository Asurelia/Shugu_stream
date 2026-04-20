import Link from "next/link";
import { Logo, LiveDot } from "@/features/creator-home/shared";

type ConnStatus = "connecting" | "open" | "closed" | "error";

type Props = {
  connStatus: ConnStatus;
  viewerCount: number;
  uptime: string;
  operatorUsername?: string;
  /** Retire les CTA du rail chat quand ouvert pour éviter le chevauchement. */
  chatOpen: boolean;
};

/**
 * HUD top V3 Immersive — Logo à gauche, capsule LIVE/viewers/uptime au centre,
 * CTA Follow/Subscribe (ou Dashboard pour operator) à droite.
 */
export function HudTopBar({ connStatus, viewerCount, uptime, operatorUsername, chatOpen }: Props) {
  const liveLabel =
    connStatus === "open" ? "LIVE"
    : connStatus === "connecting" ? "…"
    : "OFFLINE";
  return (
    <div
      className="fixed top-0 left-0 flex items-center justify-between"
      style={{
        right: chatOpen ? 392 : 0,
        padding: "1.25rem 1.5rem", zIndex: 3, gap: 12,
        transition: "right 0.45s cubic-bezier(0.5, 1.5, 0.5, 1)",
      }}
    >
      <Logo tone="professional" size={22} />
      <div
        className="glass"
        style={{
          display: "flex", alignItems: "center", gap: 14,
          padding: "0.5rem 0.85rem", borderRadius: "var(--r-full)",
          boxShadow: "inset 0 0 0 1px rgba(253,108,156,0.3)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <LiveDot size={7} />
          <span
            className="font-mono"
            style={{ fontSize: "0.7rem", letterSpacing: "0.14em", color: "var(--secondary)" }}
          >
            {liveLabel}
          </span>
        </div>
        <span style={{ width: 1, height: 12, background: "rgba(224,142,254,0.25)" }} />
        <span className="font-mono" style={{ fontSize: "0.72rem" }}>
          {viewerCount.toLocaleString("en-US")}
        </span>
        <span style={{ width: 1, height: 12, background: "rgba(224,142,254,0.25)" }} />
        <span
          className="font-mono"
          style={{ fontSize: "0.72rem", color: "var(--on-surface-variant)" }}
        >
          {uptime}
        </span>
      </div>
      <div className="hidden sm:flex items-center" style={{ gap: 10 }}>
        {operatorUsername ? (
          <Link
            href={`/${encodeURIComponent(operatorUsername)}/admin`}
            className="btn-ghost"
            style={{ fontSize: "0.78rem", textDecoration: "none", display: "inline-flex", alignItems: "center" }}
            title={`dashboard — ${operatorUsername}`}
          >
            Dashboard
          </Link>
        ) : (
          <button
            className="btn-ghost"
            style={{ fontSize: "0.78rem" }}
            type="button"
            title="bientôt disponible"
          >
            Follow
          </button>
        )}
        <button
          className="btn-primary"
          style={{ fontSize: "0.78rem" }}
          type="button"
          title="bientôt disponible"
        >
          Subscribe
        </button>
      </div>
    </div>
  );
}
