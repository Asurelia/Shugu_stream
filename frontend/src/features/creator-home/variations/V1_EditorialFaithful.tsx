/**
 * V1 — Editorial Faithful.
 * 3-colonnes (events / avatar / chat) + sub-goal bottom. Port du v1.jsx.
 */
import { useState, useEffect } from "react";
import {
  COPY, STREAMER, Logo, LiveDot, EventCard, AvatarFrame, ReactionLayer,
  ReactionBar, ChatPanel, SubGoalCard,
  useLiveChat, useSubGoal, useViewers, useUptime, useReactions,
  type Tone,
} from "../shared";

export default function V1_EditorialFaithful({ tone }: { tone: Tone }) {
  const t = COPY[tone];
  const { messages, sendUser, deleteMsg } = useLiveChat();
  const { current, target, bump, pct } = useSubGoal();
  const viewers = useViewers();
  const uptime = useUptime();
  const { items: reactions, add: addReaction } = useReactions();
  const [modMode, setModMode] = useState(false);

  useEffect(() => {
    const id = setInterval(() => { if (Math.random() > 0.6) bump(); }, 6000);
    return () => clearInterval(id);
  }, [bump]);

  return (
    <div style={{
      position: "relative", width: "100%", height: "100%",
      padding: "1rem 1.25rem", minWidth: 0,
      display: "grid",
      gridTemplateColumns: "220px 1fr 300px",
      gridTemplateRows: "auto 1fr auto",
      gap: "1rem", zIndex: 1,
    }}>
      <div style={{ gridColumn: "1 / -1", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 24 }}>
          <Logo tone={tone} size={24} />
          <nav style={{ display: "flex", gap: 18 }}>
            {["home", "about", "schedule", "vods"].map((n, i) => (
              <a key={n} style={{
                fontFamily: "var(--font-display)", fontSize: "0.8rem",
                color: i === 0 ? "var(--primary)" : "var(--on-surface-variant)",
                textDecoration: "none", letterSpacing: "0.04em",
                textTransform: "uppercase", fontWeight: 600,
                borderBottom: i === 0 ? "1px solid var(--primary)" : "none",
                paddingBottom: 2,
              }}>{n}</a>
            ))}
          </nav>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <LiveDot /> <span className="font-mono" style={{ fontSize: "0.7rem", letterSpacing: "0.12em" }}>{t.liveTag}</span>
          </div>
          <span className="font-mono" style={{ fontSize: "0.75rem", color: "var(--on-surface-variant)" }}>
            {viewers.toLocaleString()} {t.viewersLabel}
          </span>
          <span className="font-mono" style={{ fontSize: "0.75rem", color: "var(--on-surface-variant)" }}>{uptime}</span>
          <button className="btn-primary" style={{ fontSize: "0.8rem" }}>{t.subscribe}</button>
        </div>
      </div>

      <aside style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <EventCard icon="+" label={t.latestSub} value="Nebula_Walker_99" accent="primary" />
        <EventCard icon="$" label={t.latestTip} value="$50.00 — Anonymous" accent="tertiary" />
        <div className="glass" style={{
          padding: "1rem 1.1rem", borderRadius: "var(--r-lg)",
          boxShadow: "inset 0 0 0 1px rgba(71,71,84,0.15)",
        }}>
          <div className="label">{t.nowPlaying}</div>
          <div className="font-display" style={{ fontWeight: 700, fontSize: "0.95rem", marginTop: 6 }}>
            midnight hum <span style={{ color: "var(--on-surface-variant)", fontWeight: 500 }}>— loscil</span>
          </div>
          <style>{`
            @keyframes v1-bar-bounce {
              0%, 100% { transform: scaleY(0.3); }
              50%       { transform: scaleY(1); }
            }
          `}</style>
          <div style={{ marginTop: 10, display: "flex", alignItems: "center", gap: 8 }}>
            {[...Array(24)].map((_, i) => (
              <div key={i} style={{
                width: 2,
                height: 18,
                background: "linear-gradient(180deg, var(--primary), var(--secondary))",
                borderRadius: 2, opacity: 0.7,
                transformOrigin: "bottom",
                animation: `v1-bar-bounce ${0.8 + (i % 5) * 0.15}s ease-in-out ${i * 80}ms infinite`,
              }} />
            ))}
          </div>
        </div>
        <div style={{ flex: 1 }} />
        <div className="glass" style={{ padding: "0.9rem 1rem", borderRadius: "var(--r-lg)" }}>
          <div className="label">{t.aboutStreamer}</div>
          <div style={{
            fontFamily: "var(--font-display)", fontSize: "1.1rem", fontWeight: 700,
            letterSpacing: "-0.02em", marginTop: 6,
          }}>{STREAMER.displayName}</div>
          <div style={{ fontSize: "0.78rem", color: "var(--on-surface-variant)", lineHeight: 1.5, marginTop: 4 }}>
            {tone === "playful" ? "sleepy celestial demon playing video games <3" : "Illustrator & variety streamer. Quiet studio vibes."}
          </div>
        </div>
      </aside>

      <main style={{ display: "flex", flexDirection: "column", gap: 12, minWidth: 0 }}>
        <div style={{ position: "relative", flex: 1, borderRadius: "var(--r-2xl)", overflow: "hidden" }}>
          <AvatarFrame aspectRatio="auto" style={{ height: "100%" }} label={"VTUBER LIVE FEED\n\n1920 × 1080\ndrop OBS capture here"} />
          <div style={{ position: "absolute", top: 12, left: 12, display: "flex", gap: 6, flexWrap: "wrap" }}>
            <span className="chip glass" style={{ boxShadow: "inset 0 0 0 1px rgba(253,108,156,0.5)", color: "var(--secondary)" }}>
              <LiveDot size={6} /> {t.liveTag}
            </span>
            <span className="chip glass" style={{ color: "var(--on-surface)" }}>{viewers.toLocaleString()}</span>
            <span className="chip glass font-mono" style={{ color: "var(--on-surface)" }}>{uptime}</span>
          </div>
          <div style={{ position: "absolute", top: 12, right: 12 }}>
            <span className="font-mono" style={{ fontSize: "0.6rem", color: "var(--on-surface-muted)", letterSpacing: "0.1em" }}>NODE 07</span>
          </div>
          <div style={{ position: "absolute", left: 16, right: 16, bottom: 16, display: "flex", gap: 10, alignItems: "flex-end", justifyContent: "space-between" }}>
            <div style={{ maxWidth: "60%", minWidth: 0 }}>
              <div className="label" style={{ fontSize: "0.6rem" }}>{t.category}</div>
              <div className="font-display" style={{
                fontSize: "clamp(0.95rem, 1.6vw, 1.4rem)", fontWeight: 700,
                lineHeight: 1.15, letterSpacing: "-0.02em",
                textWrap: "balance", marginTop: 4,
                textShadow: "0 2px 20px rgba(0,0,0,0.6)",
              }}>{t.streamTitle}</div>
            </div>
            <ReactionBar onReact={(e) => addReaction(e, 50 + Math.random() * 40 - 20)} />
          </div>
          <ReactionLayer items={reactions} />
        </div>
        <SubGoalCard tone={tone} current={current} target={target} variant="horror" />
      </main>

      <aside className="glass" style={{
        borderRadius: "var(--r-xl)", overflow: "hidden",
        display: "flex", flexDirection: "column",
        boxShadow: "inset 0 0 0 1px rgba(71,71,84,0.2)",
      }}>
        <ChatPanel tone={tone} messages={messages} onSend={sendUser} onDelete={deleteMsg} modMode={modMode} />
        <div style={{ padding: "0.4rem 1rem 0.9rem", display: "flex", gap: 8, borderTop: "1px solid rgba(71,71,84,0.15)" }}>
          <button onClick={() => setModMode((m) => !m)} style={{
            background: modMode ? "rgba(253,108,156,0.18)" : "transparent",
            border: "none", cursor: "pointer",
            padding: "0.35rem 0.7rem", borderRadius: "var(--r-full)",
            color: modMode ? "var(--secondary)" : "var(--on-surface-variant)",
            fontFamily: "var(--font-display)", fontSize: "0.7rem", fontWeight: 600,
            boxShadow: modMode
              ? "inset 0 0 0 1px rgba(253,108,156,0.4)"
              : "inset 0 0 0 1px rgba(71,71,84,0.25)",
            letterSpacing: "0.06em", textTransform: "uppercase",
          }}>
            {modMode ? "◉ mod on" : "○ mod tools"}
          </button>
        </div>
      </aside>
    </div>
  );
}
