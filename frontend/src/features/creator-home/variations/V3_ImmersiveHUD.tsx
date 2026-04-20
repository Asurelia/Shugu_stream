/**
 * V3 — Immersive HUD. Fullscreen avatar + HUD flottant. Chat rail rétractable.
 */
import { useState } from "react";
import {
  COPY, Logo, LiveDot, AvatarFrame, EventCard, ReactionLayer, ReactionBar,
  ChatPanel,
  useLiveChat, useSubGoal, useViewers, useUptime, useReactions,
  type Tone,
} from "../shared";

export default function V3_ImmersiveHUD({ tone }: { tone: Tone }) {
  const t = COPY[tone];
  const { messages, sendUser, deleteMsg } = useLiveChat();
  const { current, target, pct } = useSubGoal();
  const viewers = useViewers();
  const uptime = useUptime();
  const { items: reactions, add: addReaction } = useReactions();
  const [chatOpen, setChatOpen] = useState(true);

  return (
    <div style={{ position: "relative", width: "100%", height: "100%", zIndex: 1, overflow: "hidden" }}>
      <div style={{ position: "absolute", inset: 0 }}>
        <AvatarFrame
          aspectRatio="auto"
          style={{ height: "100%", borderRadius: 0 }}
          label={"FULLSCREEN VTUBER\n(alpha-keyed capture)"}
        />
        <div style={{
          position: "absolute", inset: 0,
          background: "linear-gradient(180deg, rgba(8,8,16,0.6) 0%, transparent 30%, transparent 60%, rgba(8,8,16,0.85) 100%)",
        }} />
        <div style={{
          position: "absolute", inset: 0,
          background: "linear-gradient(90deg, rgba(8,8,16,0.4) 0%, transparent 30%, transparent 70%, rgba(8,8,16,0.5) 100%)",
        }} />
      </div>

      <div style={{
        position: "absolute", top: 0, left: 0, right: 0,
        padding: "1.25rem 1.5rem",
        display: "flex", alignItems: "center", justifyContent: "space-between",
        zIndex: 3,
      }}>
        <Logo tone={tone} size={22} />
        <div className="glass" style={{
          display: "flex", alignItems: "center", gap: 14,
          padding: "0.5rem 0.85rem", borderRadius: "var(--r-full)",
          boxShadow: "inset 0 0 0 1px rgba(253,108,156,0.3)",
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <LiveDot size={7} />
            <span className="font-mono" style={{ fontSize: "0.7rem", letterSpacing: "0.14em", color: "var(--secondary)" }}>
              {t.liveTag}
            </span>
          </div>
          <span style={{ width: 1, height: 12, background: "rgba(224,142,254,0.25)" }} />
          <span className="font-mono" style={{ fontSize: "0.72rem" }}>{viewers.toLocaleString()}</span>
          <span style={{ width: 1, height: 12, background: "rgba(224,142,254,0.25)" }} />
          <span className="font-mono" style={{ fontSize: "0.72rem", color: "var(--on-surface-variant)" }}>{uptime}</span>
        </div>
        <div style={{ display: "flex", gap: 10 }}>
          <button className="btn-ghost" style={{ fontSize: "0.78rem" }}>{t.follow}</button>
          <button className="btn-primary" style={{ fontSize: "0.78rem" }}>{t.subscribe}</button>
        </div>
      </div>

      <div style={{ position: "absolute", top: 90, left: 24, zIndex: 3 }}>
        <span className="font-mono" style={{ fontSize: "0.62rem", color: "var(--on-surface-muted)", letterSpacing: "0.14em" }}>
          NODE 07 · SIGNAL LOCKED
        </span>
        <div style={{ marginTop: 4, display: "flex", gap: 10 }}>
          <span className="font-mono" style={{ fontSize: "0.6rem", color: "var(--on-surface-muted)" }}>X: 184.5</span>
          <span className="font-mono" style={{ fontSize: "0.6rem", color: "var(--on-surface-muted)" }}>Y: 220.1</span>
          <span className="font-mono" style={{ fontSize: "0.6rem", color: "var(--on-surface-muted)" }}>Z: 60.8</span>
        </div>
      </div>

      <div style={{
        position: "absolute", left: 24, top: 140,
        display: "flex", flexDirection: "column", gap: 10,
        zIndex: 3, maxWidth: 240,
      }}>
        <EventCard icon="+" label={t.latestSub} value="Nebula_Walker_99" accent="primary" style={{ minWidth: 220 }} />
        <EventCard icon="$" label={t.latestTip} value="$50.00 — Anon" accent="tertiary" style={{ minWidth: 220 }} />
      </div>

      <div style={{
        position: "absolute", bottom: 56, left: 0,
        right: chatOpen ? 380 : 24,
        padding: "1rem 1.75rem", zIndex: 3,
      }}>
        <div className="label" style={{ color: "var(--primary)" }}>● {t.category}</div>
        <h1 className="font-display" style={{
          margin: "6px 0 0",
          fontSize: "clamp(1.2rem, 2.2vw, 1.9rem)",
          fontWeight: 700, letterSpacing: "-0.025em", lineHeight: 1.1,
          textWrap: "balance", maxWidth: "24ch",
          textShadow: "0 2px 20px rgba(0,0,0,0.6)",
        }}>{t.streamTitle}</h1>
        <div style={{ marginTop: 16, display: "flex", alignItems: "center", gap: 16 }}>
          <div style={{ flex: 1, maxWidth: 420 }}>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
              <span className="label" style={{ fontSize: "0.65rem" }}>{t.subGoalLabel}</span>
              <span className="font-mono" style={{ fontSize: "0.7rem" }}>
                {current.toLocaleString()} / {target.toLocaleString()}
              </span>
            </div>
            <div className="progress-track" style={{ height: 4 }}>
              <div className="progress-fill" style={{ width: `${pct}%` }} />
            </div>
          </div>
          <ReactionBar onReact={(e) => addReaction(e, 30 + Math.random() * 30)} />
        </div>
      </div>

      <div style={{
        position: "absolute", right: 0, top: 0, bottom: 0,
        width: chatOpen ? 360 : 0,
        transition: "width 0.4s cubic-bezier(0.2, 0.8, 0.2, 1)",
        zIndex: 4, overflow: "hidden",
      }}>
        <div className="glass-strong" style={{
          width: 360, height: "100%",
          display: "flex", flexDirection: "column",
          boxShadow: "inset 1px 0 0 rgba(224,142,254,0.18)",
          paddingTop: 72,
        }}>
          <ChatPanel tone={tone} messages={messages} onSend={sendUser} onDelete={deleteMsg} compact />
        </div>
        <ReactionLayer items={reactions} />
      </div>

      <button
        onClick={() => setChatOpen((o) => !o)}
        style={{
          position: "absolute",
          right: chatOpen ? 372 : 12,
          top: 80, zIndex: 5,
          background: "rgba(18,18,30,0.7)",
          backdropFilter: "blur(16px)", border: "none",
          width: 32, height: 32, borderRadius: "50%",
          cursor: "pointer", color: "var(--on-surface)",
          boxShadow: "inset 0 0 0 1px rgba(224,142,254,0.25)",
          transition: "right 0.4s cubic-bezier(0.2, 0.8, 0.2, 1)",
          display: "flex", alignItems: "center", justifyContent: "center",
        }}
      >
        {chatOpen ? "›" : "‹"}
      </button>
    </div>
  );
}
