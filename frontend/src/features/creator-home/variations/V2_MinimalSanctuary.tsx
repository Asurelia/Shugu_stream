/**
 * V2 — Minimal Sanctuary. Airy, éditorial. Avatar centre, whisper-chat droite.
 */
import { useState, useEffect, useRef, type FormEvent } from "react";
import {
  COPY, STREAMER, Logo, LiveDot, AvatarFrame, ReactionLayer, ReactionBar,
  ChatInput, RANK_META,
  useLiveChat, useSubGoal, useViewers, useUptime, useReactions,
  type Tone, type Message,
} from "../shared";

export default function V2_MinimalSanctuary({ tone }: { tone: Tone }) {
  const t = COPY[tone];
  const { messages, sendUser } = useLiveChat();
  const { current, target, pct } = useSubGoal();
  const viewers = useViewers();
  const uptime = useUptime();
  const { items: reactions, add: addReaction } = useReactions();

  return (
    <div style={{
      position: "relative", width: "100%", height: "100%",
      padding: "2rem 3rem",
      display: "flex", flexDirection: "column",
      zIndex: 1,
    }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          <Logo tone={tone} size={22} />
          <span style={{ width: 1, height: 16, background: "rgba(224,142,254,0.3)" }} />
          <span className="font-display" style={{ fontSize: "0.85rem", color: "var(--on-surface-variant)", letterSpacing: "-0.01em" }}>
            {STREAMER.displayName}
          </span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 20 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <LiveDot />
            <span className="font-mono" style={{ fontSize: "0.72rem", letterSpacing: "0.14em" }}>
              {t.liveTag} · {viewers.toLocaleString()}
            </span>
          </div>
          <button className="btn-ghost" style={{ fontSize: "0.78rem" }}>{t.follow}</button>
          <button className="btn-primary" style={{ fontSize: "0.78rem" }}>{t.subscribe}</button>
        </div>
      </div>

      <div style={{ flex: 1, display: "grid", gridTemplateColumns: "1fr 320px", gap: 48, marginTop: 32, minHeight: 0 }}>
        <div style={{ display: "flex", flexDirection: "column", justifyContent: "center", minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 12, marginBottom: 16 }}>
            <div className="label" style={{ color: "var(--primary)" }}>● {t.category}</div>
            <div className="font-mono" style={{ fontSize: "0.72rem", color: "var(--on-surface-muted)", letterSpacing: "0.1em" }}>
              UPTIME · {uptime}
            </div>
          </div>
          <h1 className="font-display" style={{
            margin: 0,
            fontSize: "clamp(1.8rem, 3.4vw, 3rem)",
            fontWeight: 700, letterSpacing: "-0.03em", lineHeight: 1.05,
            textWrap: "balance", maxWidth: "14ch", marginBottom: 24,
          }}>
            {t.streamTitle}
          </h1>
          <div style={{ position: "relative", flex: 1, maxHeight: 560, minHeight: 300, borderRadius: "var(--r-2xl)", overflow: "hidden" }}>
            <AvatarFrame aspectRatio="auto" style={{ height: "100%" }} label="VTUBER FEED" />
            <ReactionLayer items={reactions} />
            <div style={{ position: "absolute", left: 20, right: 20, bottom: 20, display: "flex", alignItems: "center", gap: 16 }}>
              <div style={{ flex: 1 }}>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
                  <span className="label" style={{ color: "#fff" }}>{t.subGoalLabel}</span>
                  <span className="font-mono" style={{ fontSize: "0.72rem", color: "#fff" }}>
                    {current.toLocaleString()} / {target.toLocaleString()}
                  </span>
                </div>
                <div className="progress-track" style={{ height: 4, background: "rgba(255,255,255,0.12)" }}>
                  <div className="progress-fill" style={{ width: `${pct}%` }} />
                </div>
              </div>
              <ReactionBar onReact={(e) => addReaction(e, 40 + Math.random() * 30)} />
            </div>
          </div>
        </div>

        <aside style={{ display: "flex", flexDirection: "column", gap: 18, minHeight: 0 }}>
          <div style={{ position: "relative", flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
            <div className="label" style={{ marginBottom: 12 }}>{t.communityNote} · {messages.length}</div>
            <div className="hairline" style={{ marginBottom: 14 }} />
            <WhisperChat tone={tone} messages={messages} onSend={sendUser} />
          </div>
        </aside>
      </div>
    </div>
  );
}

function WhisperChat({ tone, messages, onSend }: { tone: Tone; messages: Message[]; onSend: (t: string) => void }) {
  const [input, setInput] = useState("");
  const ref = useRef<HTMLDivElement | null>(null);
  useEffect(() => { if (ref.current) ref.current.scrollTop = ref.current.scrollHeight; }, [messages]);
  const onSubmit = (e: FormEvent) => { e.preventDefault(); onSend(input); setInput(""); };
  return (
    <>
      <div ref={ref} className="scroll-inner" style={{
        flex: 1, minHeight: 0, display: "flex", flexDirection: "column",
        gap: 16, paddingRight: 6,
      }}>
        {messages.slice(-20).map((m) => {
          const meta = RANK_META[m.rank] || RANK_META.viewer;
          return (
            <div key={m.id} className="chat-msg" style={{ display: "flex", flexDirection: "column", gap: 3 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span className="font-display" style={{
                  fontWeight: 700, fontSize: "0.85rem",
                  color: meta.color, letterSpacing: "-0.01em",
                }}>{m.user}</span>
                {meta.label && (
                  <span style={{
                    fontSize: "0.6rem", color: meta.color,
                    letterSpacing: "0.1em", fontFamily: "var(--font-mono)",
                  }}>{meta.label}</span>
                )}
                <span className="font-mono" style={{ marginLeft: "auto", color: "var(--on-surface-muted)", fontSize: "0.62rem" }}>{m.time}</span>
              </div>
              <div style={{ color: "var(--on-surface)", fontSize: "0.86rem", lineHeight: 1.5 }}>{m.text}</div>
            </div>
          );
        })}
      </div>
      <form onSubmit={onSubmit} style={{ marginTop: 12 }}>
        <ChatInput tone={tone} value={input} onChange={setInput} />
      </form>
    </>
  );
}
