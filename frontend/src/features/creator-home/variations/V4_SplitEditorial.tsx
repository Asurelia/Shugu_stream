/**
 * V4 — Split Editorial. Left page = magazine editorial ; right = stream + chat.
 */
import {
  COPY, Logo, LiveDot, AvatarFrame, ReactionLayer, ReactionBar,
  ChatPanel, SubGoalCard,
  useLiveChat, useSubGoal, useViewers, useUptime, useReactions,
  type Tone,
} from "../shared";

export default function V4_SplitEditorial({ tone }: { tone: Tone }) {
  const t = COPY[tone];
  const { messages, sendUser, deleteMsg } = useLiveChat();
  const { current, target } = useSubGoal();
  const viewers = useViewers();
  const uptime = useUptime();
  const { items: reactions, add: addReaction } = useReactions();

  const upcoming = [
    { day: "TUE", title: "zine making live", time: "20:00 EST" },
    { day: "THU", title: "horror co-op w/ nova", time: "21:00 EST" },
    { day: "SAT", title: "karaoke night ♡", time: "22:00 EST" },
  ];

  return (
    <div style={{
      position: "relative", width: "100%", height: "100%",
      display: "grid", gridTemplateColumns: "360px 1fr", zIndex: 1,
    }}>
      <div style={{
        position: "relative",
        padding: "1.25rem 1.5rem",
        display: "flex", flexDirection: "column",
        overflow: "auto",
        background: "linear-gradient(180deg, rgba(18,18,30,0.35), rgba(9,9,18,0.5))",
        backdropFilter: "blur(8px)",
        boxShadow: "inset -1px 0 0 rgba(224,142,254,0.1)",
      }}>
        <Logo tone={tone} size={22} />

        <div style={{ marginTop: 24, display: "flex", alignItems: "center", gap: 10 }}>
          <LiveDot />
          <span className="font-mono" style={{ fontSize: "0.72rem", letterSpacing: "0.14em", color: "var(--secondary)" }}>{t.liveTag}</span>
          <span style={{ color: "var(--on-surface-muted)", fontSize: "0.72rem" }}>·</span>
          <span className="font-mono" style={{ fontSize: "0.72rem", color: "var(--on-surface-variant)" }}>EP 042</span>
        </div>

        <div className="label" style={{ marginTop: 28, color: "var(--primary)" }}>{t.category}</div>
        <h1 className="font-display" style={{
          margin: "10px 0 0",
          fontSize: "clamp(2.2rem, 4vw, 3.2rem)",
          fontWeight: 700, lineHeight: 1.02,
          letterSpacing: "-0.035em", textWrap: "balance",
        }}>
          <span style={{ color: "var(--on-surface)" }}>{t.streamTitle.split(" ").slice(0, 3).join(" ")}</span>{" "}
          <span className="grad-text-warm">{t.streamTitle.split(" ").slice(3).join(" ")}</span>
        </h1>

        <p style={{
          marginTop: 18, color: "var(--on-surface-variant)",
          fontSize: "0.95rem", lineHeight: 1.65,
          fontFamily: "var(--font-display)", fontWeight: 400,
          maxWidth: "32ch", textWrap: "pretty",
        }}>
          {tone === "playful"
            ? "come hang out while i doodle & chat. no pressure, just vibes & soft synths."
            : "A quiet evening with music, illustrations, and conversation with the community."}
        </p>

        <div style={{ marginTop: 26, display: "flex", gap: 32 }}>
          <div>
            <div className="label">{t.viewersLabel}</div>
            <div className="font-display" style={{ fontSize: "1.5rem", fontWeight: 700, letterSpacing: "-0.02em", marginTop: 2 }}>
              {viewers.toLocaleString()}
            </div>
          </div>
          <div>
            <div className="label">{t.uptime}</div>
            <div className="font-mono" style={{ fontSize: "1.1rem", fontWeight: 600, color: "var(--tertiary)", marginTop: 2 }}>
              {uptime}
            </div>
          </div>
          <div>
            <div className="label">followers</div>
            <div className="font-display" style={{ fontSize: "1.5rem", fontWeight: 700, letterSpacing: "-0.02em", marginTop: 2 }}>
              48.2K
            </div>
          </div>
        </div>

        <div className="hairline" style={{ margin: "28px 0 20px" }} />

        <div>
          <div className="label" style={{ marginBottom: 10 }}>upcoming · the veil</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {upcoming.map((u) => (
              <div key={u.title} style={{ display: "flex", alignItems: "center", gap: 14 }}>
                <div style={{
                  width: 44, textAlign: "center",
                  fontFamily: "var(--font-mono)", fontSize: "0.72rem",
                  color: "var(--primary)", letterSpacing: "0.1em",
                }}>{u.day}</div>
                <div style={{
                  width: 4, height: 4, borderRadius: "50%",
                  background: "var(--primary)", boxShadow: "0 0 8px var(--primary)",
                }} />
                <div style={{ flex: 1 }}>
                  <div className="font-display" style={{ fontSize: "0.9rem", fontWeight: 600 }}>{u.title}</div>
                  <div className="font-mono" style={{ fontSize: "0.68rem", color: "var(--on-surface-muted)" }}>{u.time}</div>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div style={{ flex: 1 }} />

        <div style={{ display: "flex", gap: 10, marginTop: 20 }}>
          <button className="btn-primary" style={{ fontSize: "0.82rem", flex: 1 }}>{t.subscribe}</button>
          <button className="btn-ghost" style={{ fontSize: "0.82rem", flex: 1 }}>{t.follow}</button>
        </div>
      </div>

      <div style={{
        position: "relative",
        padding: "1.25rem 1.5rem",
        display: "grid", gridTemplateRows: "1fr auto",
        gap: 12, minHeight: 0,
      }}>
        <div style={{ position: "relative", minHeight: 0 }}>
          <div style={{
            position: "absolute", inset: 0,
            borderRadius: "var(--r-2xl)", overflow: "hidden",
          }}>
            <AvatarFrame aspectRatio="auto" style={{ height: "100%" }} label="VTUBER FEED" />
            <ReactionLayer items={reactions} />
          </div>
          <div style={{
            position: "absolute", right: 16, top: 16, bottom: 16,
            width: 300, display: "flex", flexDirection: "column",
          }}>
            <div className="glass-strong" style={{
              flex: 1, borderRadius: "var(--r-xl)",
              display: "flex", flexDirection: "column",
              boxShadow: "inset 0 0 0 1px rgba(224,142,254,0.18), 0 30px 60px -30px rgba(0,0,0,0.8)",
              overflow: "hidden",
            }}>
              <ChatPanel tone={tone} messages={messages} onSend={sendUser} onDelete={deleteMsg} compact />
            </div>
          </div>
          <div style={{ position: "absolute", left: 16, bottom: 16, display: "flex", gap: 8 }}>
            <span className="chip glass" style={{ boxShadow: "inset 0 0 0 1px rgba(253,108,156,0.4)", color: "var(--secondary)" }}>
              <LiveDot size={6} /> {t.liveTag}
            </span>
            <span className="chip glass" style={{ color: "var(--on-surface)" }}>{viewers.toLocaleString()}</span>
          </div>
          <div style={{ position: "absolute", right: 332, top: 16 }}>
            <ReactionBar onReact={(e) => addReaction(e, 10 + Math.random() * 30)} />
          </div>
        </div>
        <SubGoalCard tone={tone} current={current} target={target} variant="horror" />
      </div>
    </div>
  );
}
