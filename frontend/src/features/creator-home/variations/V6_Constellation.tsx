/**
 * V6 — Constellation Break. Avatar qui déborde + constellations de modules.
 */
import { useState, useEffect, useRef, type FormEvent } from "react";
import {
  COPY, Logo, LiveDot, AvatarFrame, ReactionLayer, ReactionBar,
  SubGoalCard, ChatInput, RANK_META,
  useLiveChat, useSubGoal, useViewers, useUptime, useReactions,
  type Tone, type Message, type AccentKey,
} from "../shared";

export default function V6_Constellation({ tone }: { tone: Tone }) {
  const t = COPY[tone];
  const { messages, sendUser } = useLiveChat();
  const { current, target } = useSubGoal();
  const viewers = useViewers();
  const uptime = useUptime();
  const { items: reactions, add: addReaction } = useReactions();
  const [chatExpanded, setChatExpanded] = useState(false);

  return (
    <div style={{ position: "relative", width: "100%", height: "100%", zIndex: 1, overflow: "hidden" }}>
      <svg style={{ position: "absolute", inset: 0, width: "100%", height: "100%", pointerEvents: "none", opacity: 0.3 }}>
        <defs>
          <linearGradient id="linegrad" x1="0" x2="1" y1="0" y2="0">
            <stop offset="0%" stopColor="#e08efe" stopOpacity="0" />
            <stop offset="50%" stopColor="#e08efe" stopOpacity="0.4" />
            <stop offset="100%" stopColor="#81ecff" stopOpacity="0" />
          </linearGradient>
        </defs>
        <line x1="12%" y1="22%" x2="42%" y2="38%" stroke="url(#linegrad)" strokeWidth="1" />
        <line x1="42%" y1="38%" x2="78%" y2="24%" stroke="url(#linegrad)" strokeWidth="1" />
        <line x1="78%" y1="24%" x2="88%" y2="62%" stroke="url(#linegrad)" strokeWidth="1" />
        <line x1="88%" y1="62%" x2="58%" y2="74%" stroke="url(#linegrad)" strokeWidth="1" />
        <line x1="58%" y1="74%" x2="18%" y2="68%" stroke="url(#linegrad)" strokeWidth="1" />
        <line x1="18%" y1="68%" x2="12%" y2="22%" stroke="url(#linegrad)" strokeWidth="1" />
      </svg>

      <header style={{
        position: "absolute", top: 0, left: 0, right: 0, zIndex: 3,
        padding: "1.5rem 2rem",
        display: "flex", alignItems: "center", justifyContent: "space-between",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 28 }}>
          <Logo tone={tone} size={24} />
          <div className="font-mono" style={{ fontSize: "0.68rem", letterSpacing: "0.2em", color: "var(--on-surface-muted)" }}>
            EPISODE 042 · NODE 07
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
          <span className="chip glass" style={{ color: "var(--secondary)", boxShadow: "inset 0 0 0 1px rgba(253,108,156,0.35)" }}>
            <LiveDot size={6} /> {t.liveTag}
          </span>
          <span className="font-mono" style={{ fontSize: "0.72rem", color: "var(--on-surface-variant)" }}>
            {viewers.toLocaleString()} · {uptime}
          </span>
          <button className="btn-primary" style={{ fontSize: "0.78rem" }}>{t.subscribe}</button>
        </div>
      </header>

      <div style={{
        position: "absolute",
        left: "50%", top: "50%", transform: "translate(-50%, -46%)",
        width: "min(52vw, 660px)", height: "min(74vh, 760px)",
        zIndex: 2,
      }}>
        <div style={{
          position: "absolute", inset: "-60px",
          background: "radial-gradient(ellipse at center, rgba(224,142,254,0.18) 0%, rgba(253,108,156,0.08) 40%, transparent 70%)",
          filter: "blur(20px)",
          pointerEvents: "none",
        }} />
        <div style={{
          position: "absolute", inset: 0,
          borderRadius: "var(--r-2xl) var(--r-2xl) 0 0",
          overflow: "hidden",
          boxShadow: "0 40px 100px -30px rgba(224,142,254,0.35), inset 0 0 0 1px rgba(224,142,254,0.15)",
        }}>
          <AvatarFrame aspectRatio="auto" style={{ height: "100%", borderRadius: 0 }} label={"VTUBER AVATAR\n(transparent capture)"} />
        </div>
        <ReactionLayer items={reactions} />
      </div>

      <div style={{
        position: "absolute", left: "2.5rem", top: "18%",
        zIndex: 3, maxWidth: 360,
      }}>
        <div className="label" style={{ color: "var(--primary)" }}>● {t.category}</div>
        <h1 className="font-display fade-in-up" style={{
          margin: "12px 0 0",
          fontSize: "clamp(2.2rem, 4.2vw, 3.4rem)",
          fontWeight: 700, lineHeight: 0.98,
          letterSpacing: "-0.04em", textWrap: "balance",
        }}>
          <span className="grad-text">{t.streamTitle.split(" ")[0]}</span>
          <br />
          {t.streamTitle.split(" ").slice(1).join(" ")}
        </h1>
        <p style={{
          marginTop: 20, fontFamily: "var(--font-display)",
          fontSize: "0.92rem", color: "var(--on-surface-variant)",
          lineHeight: 1.6, textWrap: "pretty", maxWidth: "28ch",
        }}>
          {tone === "playful"
            ? "soft music, sketchbook, and warm drinks. pull up a seat in the veil ♡"
            : "A slow evening of illustration, conversation, and ambient soundscapes."}
        </p>
      </div>

      <div style={{
        position: "absolute", right: "2.5rem", top: "17%", zIndex: 3,
        display: "flex", flexDirection: "column", gap: 14, alignItems: "flex-end",
      }}>
        <ConstellationCard icon="+" title="Nebula_Walker_99" subtitle={t.latestSub} accent="primary" offset={0} />
        <ConstellationCard icon="$" title="$50.00" subtitle={t.latestTip} accent="tertiary" offset={-24} />
        <ConstellationCard icon="♡" title="412 likes" subtitle="this scene" accent="secondary" offset={-8} />
      </div>

      <div style={{
        position: "absolute", left: "2.5rem", bottom: "2rem",
        zIndex: 3, width: 320,
      }}>
        <SubGoalCard tone={tone} current={current} target={target} variant="horror" />
      </div>

      <div style={{
        position: "absolute",
        left: "50%", bottom: chatExpanded ? 360 : "2rem",
        transform: "translateX(-50%)",
        zIndex: 4, transition: "bottom 0.4s cubic-bezier(0.2, 0.8, 0.2, 1)",
      }}>
        <ReactionBar onReact={(e) => addReaction(e, 40 + Math.random() * 20)} />
      </div>

      <div style={{
        position: "absolute", right: 0, bottom: 0,
        width: "min(420px, 95%)",
        height: chatExpanded ? 360 : 120,
        transition: "height 0.4s cubic-bezier(0.2, 0.8, 0.2, 1)",
        zIndex: 4,
      }}>
        <div className="glass-strong" style={{
          margin: "0 1rem 1rem 0",
          height: "100%",
          borderRadius: "var(--r-xl)",
          display: "flex", flexDirection: "column",
          boxShadow: "inset 0 0 0 1px rgba(224,142,254,0.22), 0 30px 60px -20px rgba(0,0,0,0.6)",
          overflow: "hidden",
        }}>
          <button
            onClick={() => setChatExpanded((x) => !x)}
            style={{
              display: "flex", alignItems: "center", justifyContent: "space-between",
              padding: "0.85rem 1.1rem", background: "transparent", border: "none",
              cursor: "pointer", color: "var(--on-surface)",
              borderBottom: chatExpanded ? "1px solid rgba(71,71,84,0.2)" : "none",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <LiveDot size={6} />
              <span className="label" style={{ color: "var(--on-surface)" }}>{t.communityNote}</span>
              <span className="font-mono" style={{ fontSize: "0.7rem", color: "var(--on-surface-muted)" }}>· {messages.length}</span>
            </div>
            <span style={{ color: "var(--on-surface-variant)", fontSize: "0.9rem" }}>
              {chatExpanded ? "⌄" : "⌃"}
            </span>
          </button>
          {chatExpanded ? (
            <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
              <ChatPanelBody tone={tone} messages={messages} onSend={sendUser} />
            </div>
          ) : (
            <div style={{ padding: "0 1.1rem 0.9rem", display: "flex", flexDirection: "column", gap: 6, overflow: "hidden" }}>
              {messages.slice(-2).map((m) => {
                const meta = RANK_META[m.rank] || RANK_META.viewer;
                return (
                  <div key={m.id} className="chat-msg" style={{
                    display: "flex", gap: 8, alignItems: "baseline", fontSize: "0.82rem",
                  }}>
                    <span className="font-display" style={{ color: meta.color, fontWeight: 700, flexShrink: 0 }}>{m.user}</span>
                    <span style={{
                      color: "var(--on-surface-variant)",
                      textOverflow: "ellipsis", overflow: "hidden", whiteSpace: "nowrap",
                    }}>{m.text}</span>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function ChatPanelBody({ tone, messages, onSend }: { tone: Tone; messages: Message[]; onSend: (t: string) => void }) {
  const [input, setInput] = useState("");
  const ref = useRef<HTMLDivElement | null>(null);
  useEffect(() => { if (ref.current) ref.current.scrollTop = ref.current.scrollHeight; }, [messages]);
  const onSubmit = (e: FormEvent) => { e.preventDefault(); onSend(input); setInput(""); };
  return (
    <>
      <div ref={ref} className="scroll-inner" style={{
        flex: 1, minHeight: 0, padding: "0.7rem 1.1rem",
        display: "flex", flexDirection: "column", gap: 10,
      }}>
        {messages.slice(-15).map((m) => {
          const meta = RANK_META[m.rank] || RANK_META.viewer;
          return (
            <div key={m.id} className="chat-msg" style={{ display: "flex", flexDirection: "column", gap: 2 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <span className="font-display" style={{ color: meta.color, fontWeight: 700, fontSize: "0.82rem" }}>{m.user}</span>
                <span className="font-mono" style={{
                  marginLeft: "auto", color: "var(--on-surface-muted)", fontSize: "0.62rem",
                }}>{m.time}</span>
              </div>
              <div style={{ fontSize: "0.84rem", color: "var(--on-surface)", lineHeight: 1.45 }}>{m.text}</div>
            </div>
          );
        })}
      </div>
      <form onSubmit={onSubmit} style={{ padding: "0.7rem 1.1rem", borderTop: "1px solid rgba(71,71,84,0.2)" }}>
        <ChatInput tone={tone} value={input} onChange={setInput} />
      </form>
    </>
  );
}

function ConstellationCard({
  icon, title, subtitle, accent = "primary", offset = 0,
}: { icon: string; title: string; subtitle: string; accent?: AccentKey; offset?: number }) {
  const color = `var(--${accent})`;
  return (
    <div className="glass float-y" style={{
      padding: "0.75rem 0.95rem",
      borderRadius: "var(--r-lg)",
      display: "flex", alignItems: "center", gap: 10,
      transform: `translateX(${offset}px)`,
      boxShadow: `inset 0 0 0 1px ${color}2e, 0 20px 40px -20px ${color}40`,
      minWidth: 220,
    }}>
      <div style={{
        width: 32, height: 32, borderRadius: "50%",
        background: `linear-gradient(135deg, ${color}, ${color}80)`,
        display: "flex", alignItems: "center", justifyContent: "center",
        color: "#1a0a24", fontWeight: 800, fontSize: 15,
        boxShadow: `0 0 16px ${color}66`,
      }}>{icon}</div>
      <div>
        <div className="font-display" style={{ fontSize: "0.88rem", fontWeight: 700, letterSpacing: "-0.01em" }}>{title}</div>
        <div className="label" style={{ fontSize: "0.6rem" }}>{subtitle}</div>
      </div>
    </div>
  );
}
