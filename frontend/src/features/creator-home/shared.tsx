/**
 * Creator Home — hooks et composants partagés (port du bundle Claude Design).
 * Tous les tokens CSS viennent de `celestial-veil-tokens.css` chargé au shell.
 */
import {
  useState, useEffect, useRef, useMemo, useCallback,
  type CSSProperties, type ReactNode, type FormEvent,
} from "react";

// ─── TYPES ────────────────────────────────────────────────────────────────

export type Tone = "professional" | "playful";
export type RankKey = "mod" | "sub1" | "sub2" | "sub3" | "vip" | "viewer";
export type AccentKey = "primary" | "secondary" | "tertiary";

export type Message = {
  id: number;
  user: string;
  rank: RankKey;
  color: string;
  text: string;
  time: string;
  self?: boolean;
};

// ─── COPY TONE ─────────────────────────────────────────────────────────────

export const COPY: Record<Tone, Record<string, string>> = {
  professional: {
    appName: "Shugu",
    goLive: "Go Live", endStream: "End Stream",
    subscribe: "Subscribe", follow: "Follow",
    subGoalLabel: "Subscriber Goal",
    chatPlaceholder: "Send a message",
    liveTag: "LIVE", viewersLabel: "Viewers", uptime: "Uptime",
    latestSub: "Latest Subscriber", latestTip: "Latest Tip",
    thankyouTitle: "Thank you", newFollowerTitle: "New Follower",
    nowPlaying: "Now Playing", recentlyJoined: "Recently Joined",
    communityNote: "Community",
    modTools: "Moderator Tools", slowMode: "Slow Mode",
    subsOnly: "Subscribers Only", clearChat: "Clear Chat",
    reactLabel: "React", aboutStreamer: "About",
    streamTitle: "Live from the studio — quiet work session",
    tagline: "A livestream by Shugu",
    category: "Just Chatting",
    statusIdle: "Calibrating capture pipeline",
  },
  playful: {
    appName: "shugu",
    goLive: "send it ✦", endStream: "wrap up",
    subscribe: "join the veil", follow: "lurk+",
    subGoalLabel: "sub goal ✧",
    chatPlaceholder: "say something nice :3",
    liveTag: "LIVE!!", viewersLabel: "goobers", uptime: "been vibing",
    latestSub: "newest friend", latestTip: "latest snack",
    thankyouTitle: "ty so much !", newFollowerTitle: "new friend!! ♡",
    nowPlaying: "on blast", recentlyJoined: "just arrived ♡",
    communityNote: "the homies",
    modTools: "mod stuff", slowMode: "slow chat",
    subsOnly: "subs only", clearChat: "nuke it",
    reactLabel: "react ♡", aboutStreamer: "about me",
    streamTitle: "gaming n glowing <3",
    tagline: "streaming into the abyss",
    category: "just yapping",
    statusIdle: "setting up the vibes",
  },
};

// ─── DATA ──────────────────────────────────────────────────────────────────

export const INITIAL_MESSAGES: Message[] = [
  { id: 1, user: "CyberMod_Alpha", rank: "mod",    color: "secondary",  text: "welcome everyone! please be respectful in the veil ✨", time: "20:41" },
  { id: 2, user: "Lunar_Glow",     rank: "sub3",   color: "tertiary",   text: "the model looks absolutely insane today!! lighting is unreal 💜", time: "20:42" },
  { id: 3, user: "Void_King",      rank: "sub1",   color: "tertiary",   text: "new sub goal lets goooo, ready for the gaming segment", time: "20:43" },
  { id: 4, user: "Starflight00",   rank: "viewer", color: "on-surface", text: "just got here! what did i miss", time: "20:43" },
  { id: 5, user: "PixelPioneer",   rank: "vip",    color: "primary",    text: "pog", time: "20:44" },
  { id: 6, user: "NebulaWalker",   rank: "viewer", color: "on-surface", text: "the BGM is so good tonight", time: "20:44" },
];

const INCOMING_POOL: Omit<Message, "id" | "time">[] = [
  { user: "NeonNinja",    rank: "sub2",   color: "tertiary",   text: "cant wait for the reveal !" },
  { user: "Aurora_Q",     rank: "viewer", color: "on-surface", text: "hey chat, first time here :)" },
  { user: "CometChaser",  rank: "sub1",   color: "tertiary",   text: "screen looks clean af" },
  { user: "LumiFan1",     rank: "vip",    color: "primary",    text: "raid inbound soon!! 💕" },
  { user: "SilentObs",    rank: "viewer", color: "on-surface", text: "lurking hard tonight" },
  { user: "GalaxyBrain",  rank: "sub3",   color: "tertiary",   text: "this nebula hits different" },
  { user: "ModPrime",     rank: "mod",    color: "secondary",  text: "slow mode lifted, chat away" },
  { user: "PogChampion",  rank: "viewer", color: "on-surface", text: "POGGGG" },
];

export const RANK_META: Record<RankKey, { label: string; icon: string; color: string }> = {
  mod:    { label: "MOD", icon: "⬢", color: "var(--secondary)" },
  sub1:   { label: "SUB", icon: "★", color: "var(--tertiary)" },
  sub2:   { label: "2Y",  icon: "★", color: "var(--tertiary)" },
  sub3:   { label: "3Y",  icon: "★", color: "var(--tertiary)" },
  vip:    { label: "VIP", icon: "♦", color: "var(--primary)" },
  viewer: { label: "",    icon: "",  color: "var(--on-surface-variant)" },
};

export const STREAMER = {
  handle: "shugu",
  displayName: "Shugu",
  category: "Just Chatting",
  title: "quiet evening stream — catching up with chat",
  followers: 48293,
  subs: 1842,
};

// ─── HOOKS ─────────────────────────────────────────────────────────────────

export function useNow() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);
  return now;
}

export function useUptime(startOffsetSec = 3 * 3600 + 45 * 60) {
  const [t0] = useState(() => Date.now() - startOffsetSec * 1000);
  const [s, setS] = useState(startOffsetSec);
  useEffect(() => {
    const id = setInterval(() => setS(Math.floor((Date.now() - t0) / 1000)), 1000);
    return () => clearInterval(id);
  }, [t0]);
  const h = String(Math.floor(s / 3600)).padStart(2, "0");
  const m = String(Math.floor((s % 3600) / 60)).padStart(2, "0");
  const sec = String(s % 60).padStart(2, "0");
  return `${h}:${m}:${sec}`;
}

export function useViewers(initial = 12405) {
  const [v, setV] = useState(initial);
  useEffect(() => {
    const id = setInterval(() => {
      setV((prev) => Math.max(8000, prev + Math.floor(Math.random() * 40) - 18));
    }, 2500);
    return () => clearInterval(id);
  }, []);
  return v;
}

export function useLiveChat() {
  const [messages, setMessages] = useState<Message[]>(INITIAL_MESSAGES);
  const idRef = useRef(100);

  useEffect(() => {
    let tid: ReturnType<typeof setTimeout>;
    const schedule = (): ReturnType<typeof setTimeout> => {
      const delay = 2800 + Math.random() * 3500;
      return setTimeout(() => {
        const pick = INCOMING_POOL[Math.floor(Math.random() * INCOMING_POOL.length)];
        const now = new Date();
        const tstr = `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}`;
        setMessages((prev) =>
          [...prev, { ...pick, id: idRef.current++, time: tstr }].slice(-40),
        );
        tid = schedule();
      }, delay);
    };
    tid = schedule();
    return () => clearTimeout(tid);
  }, []);

  const sendUser = useCallback((text: string) => {
    if (!text.trim()) return;
    const now = new Date();
    const tstr = `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}`;
    setMessages((prev) =>
      [...prev, {
        id: idRef.current++, user: "you", rank: "vip" as RankKey,
        color: "primary", text, time: tstr, self: true,
      }].slice(-40),
    );
  }, []);

  const deleteMsg = useCallback((id: number) => {
    setMessages((prev) => prev.filter((m) => m.id !== id));
  }, []);

  return { messages, sendUser, deleteMsg };
}

export function useSubGoal(target = 1500, startAt = 1452) {
  const [current, setCurrent] = useState(startAt);
  const bump = useCallback(() => setCurrent((c) => Math.min(target, c + 1)), [target]);
  return { current, target, bump, pct: (current / target) * 100 };
}

export function useReactions() {
  const [items, setItems] = useState<{ id: number; emoji: string; x: number; r: string }[]>([]);
  const idRef = useRef(0);
  const add = useCallback((emoji: string, x = 50) => {
    const id = idRef.current++;
    const r = Math.random() * 30 - 15 + "deg";
    setItems((prev) => [...prev, { id, emoji, x, r }]);
    setTimeout(() => setItems((prev) => prev.filter((i) => i.id !== id)), 2400);
  }, []);
  return { items, add };
}

// ─── COMPONENTS ────────────────────────────────────────────────────────────

export function LiveDot({ size = 8 }: { size?: number }) {
  return (
    <span className="live-dot" style={{
      display: "inline-block", width: size, height: size,
      background: "var(--secondary)", borderRadius: "50%",
      boxShadow: "0 0 10px var(--secondary)",
    }} />
  );
}

export function Logo({ size = 22, tone = "professional" }: { size?: number; tone?: Tone }) {
  const label = COPY[tone].appName;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
      <svg width={size} height={size} viewBox="0 0 32 32" style={{ filter: "drop-shadow(0 0 8px rgba(224,142,254,0.4))" }}>
        <defs>
          <linearGradient id="lg1" x1="0" x2="1" y1="0" y2="1">
            <stop offset="0%" stopColor="#e08efe" />
            <stop offset="60%" stopColor="#fd6c9c" />
            <stop offset="100%" stopColor="#81ecff" />
          </linearGradient>
        </defs>
        <circle cx="16" cy="16" r="6" fill="url(#lg1)" />
        <circle cx="16" cy="16" r="12" fill="none" stroke="url(#lg1)" strokeWidth="1.2" opacity="0.6" />
        <circle cx="28" cy="8" r="1.5" fill="#e08efe" />
        <circle cx="4" cy="22" r="1" fill="#81ecff" />
      </svg>
      <span className="font-display" style={{ fontWeight: 800, fontSize: size * 0.85, letterSpacing: "-0.02em" }}>
        <span className="grad-text-warm">{label}</span>
      </span>
    </div>
  );
}

export function RankBadge({ rank }: { rank: RankKey }) {
  const meta = RANK_META[rank];
  if (!meta || !meta.label) return null;
  const bg = rank === "mod" ? "rgba(253, 108, 156, 0.12)"
    : rank === "vip" ? "rgba(224, 142, 254, 0.14)"
    : "rgba(129, 236, 255, 0.12)";
  return (
    <span className="chip" style={{
      background: bg, color: meta.color,
      boxShadow: `inset 0 0 0 1px ${meta.color}40, 0 0 8px ${meta.color}22`,
      padding: "0.15rem 0.45rem", fontSize: "0.62rem",
    }}>
      <span style={{ fontSize: "0.7rem" }}>{meta.icon}</span>
      {meta.label}
    </span>
  );
}

export function Avatar({
  size = 40, seed = "a", label, ring = false,
}: { size?: number; seed?: string; label?: string; ring?: boolean }) {
  const hash = Array.from(String(seed)).reduce((a, c) => a + c.charCodeAt(0), 0);
  const h1 = (hash * 37) % 360;
  const h2 = (hash * 73) % 360;
  return (
    <div style={{
      width: size, height: size, borderRadius: "50%",
      background: `linear-gradient(135deg, hsl(${h1} 70% 55%), hsl(${h2} 70% 45%))`,
      display: "flex", alignItems: "center", justifyContent: "center",
      color: "#fff", fontFamily: "var(--font-display)", fontWeight: 700,
      fontSize: size * 0.4, flexShrink: 0,
      boxShadow: ring ? "0 0 0 2px rgba(224,142,254,0.6), 0 0 16px rgba(224,142,254,0.4)" : "none",
    }}>
      {(label || String(seed)).slice(0, 2).toUpperCase()}
    </div>
  );
}

type ChatPanelProps = {
  tone: Tone;
  messages: Message[];
  onSend: (text: string) => void;
  onDelete?: (id: number) => void;
  modMode?: boolean;
  compact?: boolean;
  emphasis?: string;
};

export function ChatPanel({ tone, messages, onSend, onDelete, modMode, compact = false, emphasis = "default" }: ChatPanelProps) {
  const t = COPY[tone];
  const [input, setInput] = useState("");
  const scrollRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [messages]);

  const onSubmit = (e: FormEvent) => { e.preventDefault(); onSend(input); setInput(""); };

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", minHeight: 0 }}>
      <div style={{
        padding: compact ? "0.7rem 1rem" : "1rem 1.25rem",
        display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <LiveDot size={6} />
          <span className="label" style={{ color: "var(--on-surface)" }}>{t.communityNote}</span>
        </div>
        <span className="font-mono" style={{ fontSize: "0.7rem", color: "var(--on-surface-muted)" }}>
          {messages.length} msgs
        </span>
      </div>
      <div ref={scrollRef} className="scroll-inner" style={{
        flex: 1, minHeight: 0,
        padding: compact ? "0 1rem 0.5rem" : "0 1.25rem 0.5rem",
        display: "flex", flexDirection: "column", gap: compact ? 10 : 14,
      }}>
        {messages.map((m) => (
          <ChatMessage key={m.id} m={m} modMode={modMode} onDelete={onDelete} compact={compact} emphasis={emphasis} />
        ))}
      </div>
      <form onSubmit={onSubmit} style={{
        padding: compact ? "0.7rem 1rem" : "1rem 1.25rem",
        borderTop: "1px solid rgba(71,71,84,0.15)",
      }}>
        <ChatInput tone={tone} value={input} onChange={setInput} />
      </form>
    </div>
  );
}

function ChatMessage({
  m, modMode, onDelete, compact, emphasis: _emphasis,
}: { m: Message; modMode?: boolean; onDelete?: (id: number) => void; compact?: boolean; emphasis?: string }) {
  const meta = RANK_META[m.rank] || RANK_META.viewer;
  const isEmphasis = m.rank === "mod" || m.rank === "vip";
  return (
    <div className="chat-msg" style={{
      display: "flex", flexDirection: "column", gap: 3,
      padding: isEmphasis ? "0.5rem 0.6rem" : "0.15rem 0",
      borderRadius: isEmphasis ? "var(--r-md)" : 0,
      background: isEmphasis ? "rgba(36,36,52,0.55)" : "transparent",
      boxShadow: isEmphasis ? `inset 0 0 0 1px ${meta.color}33, 0 0 16px ${meta.color}14` : "none",
      position: "relative",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        {meta.label && <RankBadge rank={m.rank} />}
        <span className="font-display" style={{
          fontWeight: 700, fontSize: compact ? "0.82rem" : "0.88rem",
          color: meta.color, letterSpacing: "-0.01em",
        }}>{m.user}</span>
        <span className="font-mono" style={{
          marginLeft: "auto", color: "var(--on-surface-muted)", fontSize: "0.65rem",
        }}>{m.time}</span>
        {modMode && !m.self && (
          <button onClick={() => onDelete?.(m.id)} style={{
            background: "transparent", border: "none", cursor: "pointer",
            color: "var(--on-surface-muted)", padding: "2px 4px", fontSize: "0.7rem",
          }} title="delete">✕</button>
        )}
      </div>
      <div style={{
        color: "var(--on-surface)", fontSize: compact ? "0.82rem" : "0.9rem", lineHeight: 1.5,
      }}>
        {m.text}
      </div>
    </div>
  );
}

export function ChatInput({ tone, value, onChange }: { tone: Tone; value: string; onChange: (v: string) => void }) {
  const t = COPY[tone];
  const [focused, setFocused] = useState(false);
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 8,
      padding: "0.5rem 0.75rem 0.5rem 1rem",
      borderRadius: "var(--r-full)",
      background: focused ? "rgba(36,36,52,0.7)" : "rgba(9,9,18,0.6)",
      boxShadow: focused
        ? "inset 0 0 0 1px rgba(129,236,255,0.5), 0 0 20px rgba(129,236,255,0.15)"
        : "inset 0 0 0 1px rgba(71,71,84,0.3)",
      transition: "all 0.25s ease",
    }}>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
        placeholder={t.chatPlaceholder}
        style={{
          flex: 1, background: "transparent", border: "none", outline: "none",
          color: "var(--on-surface)", fontSize: "0.88rem",
          fontFamily: "var(--font-body)", padding: "0.3rem 0",
        }}
      />
      <button type="submit" style={{
        background: value.trim() ? "linear-gradient(135deg, var(--primary), var(--primary-container))" : "transparent",
        border: "none", cursor: "pointer",
        width: 30, height: 30, borderRadius: "50%",
        color: value.trim() ? "#1a0a24" : "var(--on-surface-muted)",
        display: "flex", alignItems: "center", justifyContent: "center",
        transition: "all 0.2s ease",
      }}>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M22 2L11 13" /><path d="M22 2l-7 20-4-9-9-4 20-7z" /></svg>
      </button>
    </div>
  );
}

export function AvatarFrame({
  aspectRatio = "3/4", label = "VTUBER AVATAR\n(drop in live feed)",
  style = {}, overlayChildren,
}: { aspectRatio?: string; label?: string; style?: CSSProperties; overlayChildren?: ReactNode }) {
  return (
    <div style={{
      position: "relative", width: "100%", aspectRatio,
      borderRadius: "var(--r-xl)", overflow: "hidden", ...style,
    }}>
      <div className="avatar-placeholder" style={{
        position: "absolute", inset: 0, whiteSpace: "pre-line",
      }}>
        <div style={{ opacity: 0.6 }}>{label}</div>
      </div>
      <div style={{
        position: "absolute", inset: 0,
        background: "radial-gradient(ellipse at 50% 100%, rgba(224,142,254,0.08), transparent 60%)",
        pointerEvents: "none",
      }} />
      {overlayChildren}
    </div>
  );
}

export function ReactionLayer({ items }: { items: { id: number; emoji: string; x: number; r: string }[] }) {
  return (
    <div style={{ position: "absolute", inset: 0, pointerEvents: "none", overflow: "hidden" }}>
      {items.map((i) => (
        <div key={i.id} className="reaction-float" style={{
          left: `${i.x}%`, bottom: 30,
          ["--r" as string]: i.r,
        } as CSSProperties}>{i.emoji}</div>
      ))}
    </div>
  );
}

export function SubGoalCard({
  tone, current, target, style = {}, variant = "default",
}: { tone: Tone; current: number; target: number; style?: CSSProperties; variant?: "default" | "horror" }) {
  const t = COPY[tone];
  const pct = (current / target) * 100;
  return (
    <div className="glass" style={{
      padding: "1rem 1.1rem", borderRadius: "var(--r-lg)",
      boxShadow: "inset 0 0 0 1px rgba(71,71,84,0.15), var(--glow-secondary)",
      ...style,
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 8 }}>
        <span className="label">{t.subGoalLabel}</span>
        <span className="font-mono" style={{ fontSize: "0.75rem", color: "var(--on-surface)" }}>
          {current.toLocaleString()} <span style={{ color: "var(--on-surface-muted)" }}>/ {target.toLocaleString()}</span>
        </span>
      </div>
      <div style={{
        fontFamily: "var(--font-display)", fontSize: "1rem", fontWeight: 600,
        color: "var(--on-surface)", marginBottom: 12, letterSpacing: "-0.01em",
      }}>
        {variant === "horror" ? "Horror Game Unlocked" : "Late-night sketch session"}
      </div>
      <div className="progress-track" style={{ height: 6 }}>
        <div className="progress-fill" style={{ width: `${pct}%` }} />
      </div>
      <div style={{ marginTop: 6, textAlign: "right" }}>
        <span className="font-mono" style={{ fontSize: "0.7rem", color: "var(--primary)" }}>
          {pct.toFixed(0)}%
        </span>
      </div>
    </div>
  );
}

export function EventCard({
  icon, label, value, accent = "primary", style = {},
}: { icon: string; label: string; value: string; accent?: AccentKey; style?: CSSProperties }) {
  const color = `var(--${accent})`;
  return (
    <div className="glass float-y" style={{
      padding: "0.85rem 1rem", borderRadius: "var(--r-lg)",
      boxShadow: `inset 0 0 0 1px ${color}26, 0 20px 40px -20px ${color}40`,
      display: "flex", alignItems: "center", gap: 12, minWidth: 220,
      ...style,
    }}>
      <div style={{
        width: 36, height: 36, borderRadius: "var(--r-md)",
        background: `linear-gradient(135deg, ${color}, ${color}90)`,
        display: "flex", alignItems: "center", justifyContent: "center",
        color: "#1a0a24", fontSize: 18, fontWeight: 800,
      }}>{icon}</div>
      <div>
        <div className="label" style={{ color: "var(--on-surface-muted)" }}>{label}</div>
        <div className="font-display" style={{ fontWeight: 700, fontSize: "0.95rem", letterSpacing: "-0.01em" }}>{value}</div>
      </div>
    </div>
  );
}

export function ReactionBar({ onReact, style = {} }: { onReact: (emoji: string) => void; style?: CSSProperties }) {
  const emojis = ["♡", "✦", "✧", "◆", "☾"];
  return (
    <div style={{
      display: "inline-flex", gap: 6,
      padding: "6px 8px", borderRadius: "var(--r-full)",
      background: "rgba(18,18,30,0.7)", backdropFilter: "blur(20px)",
      boxShadow: "inset 0 0 0 1px rgba(224,142,254,0.25)",
      ...style,
    }}>
      {emojis.map((e) => (
        <button
          key={e}
          onClick={() => onReact(e)}
          style={{
            background: "transparent", border: "none", cursor: "pointer",
            width: 30, height: 30, borderRadius: "50%",
            color: "var(--on-surface)", fontSize: 16,
            transition: "all 0.2s ease",
            display: "flex", alignItems: "center", justifyContent: "center",
          }}
          onMouseEnter={(ev) => {
            ev.currentTarget.style.background = "rgba(224,142,254,0.18)";
            ev.currentTarget.style.transform = "scale(1.15)";
          }}
          onMouseLeave={(ev) => {
            ev.currentTarget.style.background = "transparent";
            ev.currentTarget.style.transform = "scale(1)";
          }}
        >{e}</button>
      ))}
    </div>
  );
}

export function TopBar({ tone, children, style = {} }: { tone: Tone; children?: ReactNode; style?: CSSProperties }) {
  return (
    <header style={{
      display: "flex", alignItems: "center", justifyContent: "space-between",
      padding: "1rem 1.5rem", position: "relative", zIndex: 2,
      ...style,
    }}>
      <Logo tone={tone} size={22} />
      {children}
    </header>
  );
}

export function Stat({ label, value, icon }: { label: string; value: string; icon?: ReactNode }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      {icon && <div style={{ color: "var(--on-surface-variant)" }}>{icon}</div>}
      <div>
        <div className="label" style={{ fontSize: "0.6rem" }}>{label}</div>
        <div className="font-mono" style={{ fontSize: "0.9rem", fontWeight: 600 }}>{value}</div>
      </div>
    </div>
  );
}

// Re-export `useMemo` pour V5 (graph).
export { useMemo };
