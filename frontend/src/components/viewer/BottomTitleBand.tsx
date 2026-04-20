type Props = {
  /** Retire la bande du rail chat quand ouvert. */
  chatOpen: boolean;
  category?: string;
  title?: string;
  subGoalCurrent?: number;
  subGoalTarget?: number;
};

/**
 * Bande du bas — category eyebrow + title éditorial + sub goal progress.
 * Remplace SubGoalBar avec un layout plus éditorial façon V3.
 */
export function BottomTitleBand({
  chatOpen,
  category = "Just Chatting",
  title = "Shugu est en ligne — séance chill",
  subGoalCurrent = 1452,
  subGoalTarget = 1500,
}: Props) {
  const pct = Math.min(100, Math.max(0, (subGoalCurrent / subGoalTarget) * 100));
  return (
    <div
      className="hidden md:block fixed pointer-events-none"
      style={{
        bottom: 56, left: 0,
        right: chatOpen ? 392 : 24,
        padding: "1rem 1.75rem", zIndex: 3,
        transition: "right 0.45s cubic-bezier(0.5, 1.5, 0.5, 1)",
      }}
    >
      <div className="pointer-events-auto">
        <div className="label" style={{ color: "var(--primary)" }}>● {category}</div>
        <h1
          className="font-display"
          style={{
            margin: "6px 0 0",
            fontSize: "clamp(1.2rem, 2.2vw, 1.9rem)",
            fontWeight: 700, letterSpacing: "-0.025em", lineHeight: 1.1,
            maxWidth: "24ch",
            textShadow: "0 2px 20px rgba(0,0,0,0.6)",
          }}
        >
          {title}
        </h1>
        <div style={{ marginTop: 16 }}>
          <div style={{ maxWidth: 420 }}>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
              <span className="label" style={{ fontSize: "0.65rem" }}>Subscriber Goal</span>
              <span className="font-mono" style={{ fontSize: "0.7rem" }}>
                {subGoalCurrent.toLocaleString("en-US")} / {subGoalTarget.toLocaleString("en-US")}
              </span>
            </div>
            <div className="progress-track" style={{ height: 4 }}>
              <div className="progress-fill" style={{ width: `${pct}%` }} />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
