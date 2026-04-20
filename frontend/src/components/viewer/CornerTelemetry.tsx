type ConnStatus = "connecting" | "open" | "closed" | "error";

type Props = { connStatus: ConnStatus };

/**
 * Corner telemetry mono small-caps — remplace les `.tech-label` hardcodés.
 * Positionné en top-left sous le HUD top (z:3). Purement décoratif.
 */
export function CornerTelemetry({ connStatus }: Props) {
  const signal = connStatus === "open" ? "LOCKED" : connStatus.toUpperCase();
  return (
    <div
      className="hidden md:block fixed pointer-events-none"
      style={{ top: 90, left: 24, zIndex: 3 }}
    >
      <span
        className="font-mono"
        style={{ fontSize: "0.62rem", color: "var(--on-surface-muted)", letterSpacing: "0.14em" }}
      >
        NODE 07 · SIGNAL {signal}
      </span>
      <div style={{ marginTop: 4, display: "flex", gap: 10 }}>
        <span className="font-mono" style={{ fontSize: "0.6rem", color: "var(--on-surface-muted)" }}>X: 184.5</span>
        <span className="font-mono" style={{ fontSize: "0.6rem", color: "var(--on-surface-muted)" }}>Y: 220.1</span>
        <span className="font-mono" style={{ fontSize: "0.6rem", color: "var(--on-surface-muted)" }}>Z: 60.8</span>
      </div>
    </div>
  );
}
