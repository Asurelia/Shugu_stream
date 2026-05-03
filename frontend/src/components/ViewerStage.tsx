import { useEffect, useRef, useState, type ReactNode } from "react";

/* ══════════════════════════════════════════════════════════════════════════
   ViewerStage — port TSX littéral de `preview/proto/app.jsx` (Claude Design).
   Structure JSX / class names / animations / timings IDENTIQUES au proto.
   Seules les données scriptées (SCRIPT, VISITORS, session demo) sont remplacées
   par des props connectées au vrai state (WebSocket / auth / voice).
   Tout est scopé sous `<div className="viewer-proto-root">`.
   ══════════════════════════════════════════════════════════════════════════ */

export type Rank = "guest" | "sub" | "vip" | "mod" | "king" | "admin" | "assistant";
export type Tier = "user" | "vip" | "admin";

export type ChatMsg =
  | { kind: "system"; text: string }
  | { kind: "visitor"; who: string; text: string; rank?: Rank; glyph?: string }
  | { kind: "assistant"; who: string; text: string; stream?: boolean };

export type Session = { name: string; tier: Tier } | null;

export type VoiceProps = {
  supported: boolean;
  listening: boolean;
  interim: string;
  start: () => void;
  stop: () => void;
};

type Props = {
  messages: ChatMsg[];
  session: Session;
  viewerCount: number;
  uptimeLabel: string;     // ex. "LIVE · 2h 14m"
  connStatus: "connecting" | "open" | "closed" | "error";
  inputValue: string;
  onInputChange: (v: string) => void;
  onSend: (text: string) => void;
  inputDisabled: boolean;
  reactionSeed: number;
  /** Handlers brand-menu (proto HudTop). */
  onLogin?: () => void;
  onSignup?: () => void;
  onAccount?: () => void;
  onLogout?: () => void;
  onAdmin?: () => void;
  voice?: VoiceProps;
  /** Stage 3D — le VRM viewer passe par ici pour occuper le fond. */
  stageSlot?: ReactNode;
};

/* ══════════════════════ LIQUID GLASS LAYERS ══════════════════════ */
const LiquidLayers = () => (
  <>
    <div className="lg-backdrop" />
    <div className="lg-tint" />
    <div className="lg-specular" />
    <div className="lg-edge" />
  </>
);

/* ══════════════════════ MESSAGES ══════════════════════ */
function SystemMsg({ text }: { text: string }) {
  return <div className="msg msg-system">{text}</div>;
}

type BubbleProps = {
  rank: Rank;
  who: string;
  text: string;
  glyph?: string;
  time?: string;
  stream?: boolean;
};

function Bubble({ rank, who, text, glyph, time, stream = false }: BubbleProps) {
  const [shown, setShown] = useState<string>(stream ? "" : text);
  const [streaming, setStreaming] = useState<boolean>(stream);

  // FIXME P3: streaming-text pattern — setShown/setStreaming driven by stream+text change.
  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    if (!stream) { setShown(text); setStreaming(false); return; }
    setShown(""); setStreaming(true);
    let i = 0;
    let timer: number;
    const tick = () => {
      i += Math.max(1, Math.round(text.length / 60));
      if (i >= text.length) { setShown(text); setStreaming(false); return; }
      setShown(text.slice(0, i));
      timer = window.setTimeout(tick, 34);
    };
    timer = window.setTimeout(tick, 120);
    return () => window.clearTimeout(timer);
  }, [text, stream]);
  /* eslint-enable react-hooks/set-state-in-effect */

  const cls = `bubble rank-${rank}`;

  return (
    <div className={`msg rank-${rank}`}>
      <div className="who">
        {glyph && <span className="glyph">{glyph}</span>}
        <span className="name">{who}</span>
        {time && <span className="time">{time}</span>}
      </div>
      <div className={cls}>
        <LiquidLayers />
        <div className={`bubble-text ${streaming ? "streaming" : ""}`}>{shown}</div>
      </div>
    </div>
  );
}

function nowClock(): string {
  const d = new Date();
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

/* ══════════════════════ CHAT CARD (collapsible) ══════════════════════ */
type ChatCardProps = {
  messages: ChatMsg[];
  collapsed: boolean;
  onToggleCollapse: () => void;
  unread: number;
  input: string;
  setInput: (v: string) => void;
  onSend: (text: string) => void;
  listening: boolean;
  onMicToggle: () => void;
  inputDisabled: boolean;
  voiceSupported: boolean;
};

function ChatCard({
  messages, collapsed, onToggleCollapse, unread,
  input, setInput, onSend,
  listening, onMicToggle,
  inputDisabled, voiceSupported,
}: ChatCardProps) {
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const [autoFollow, setAutoFollow] = useState(true);

  useEffect(() => {
    if (collapsed) return;
    const el = scrollRef.current;
    if (el && autoFollow) el.scrollTop = el.scrollHeight;
  }, [messages.length, collapsed, autoFollow]);

  const onScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
    setAutoFollow(nearBottom);
  };

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim()) return;
    onSend(input);
    setInput("");
  };

  return (
    <aside
      className={`chat-shell ${collapsed ? "collapsed" : ""}`}
      onClick={collapsed ? onToggleCollapse : undefined}
      role={collapsed ? "button" : undefined}
      aria-label={collapsed ? "ouvrir le chat" : undefined}
    >
      <div className="chat-card lg">
        <LiquidLayers />

        {/* Bubble FAB — visible only when collapsed */}
        <div className="bubble-fab">
          <span className="fab-ripple" />
          <span className="fab-glyph">✦</span>
          {unread > 0 && <span className="fab-badge">{unread > 99 ? "99+" : unread}</span>}
        </div>

        {/* Expanded chat */}
        <div className="lg-content">
          <div className="chat-header">
            <div className="chat-title">
              <span className="live-dot" />
              <span className="chat-label">Live Chat</span>
            </div>
            <button
              className="chip-btn"
              onClick={(e) => { e.stopPropagation(); onToggleCollapse(); }}
              aria-label="réduire le chat"
              title="réduire"
            >
              −
            </button>
          </div>

          <div className="chat-body">
            <div className="chat-messages" ref={scrollRef} onScroll={onScroll}>
              {messages.map((m, i) => {
                if (m.kind === "system") return <SystemMsg key={i} text={m.text} />;
                if (m.kind === "assistant") {
                  return (
                    <Bubble
                      key={i}
                      rank="assistant"
                      who={m.who}
                      text={m.text}
                      glyph="✦"
                      time={nowClock()}
                      stream={m.stream}
                    />
                  );
                }
                const rank = m.rank || "guest";
                return (
                  <Bubble
                    key={i}
                    rank={rank}
                    who={m.who}
                    text={m.text}
                    glyph={m.glyph || ""}
                  />
                );
              })}
            </div>

            <div className="chat-input-wrap">
              <form
                className={`chat-input lg-pill ${listening ? "listening" : ""}`}
                onSubmit={submit}
              >
                <LiquidLayers />
                <input
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  placeholder={
                    listening ? "✦ écoute…" : "Send a message…"
                  }
                  disabled={listening || inputDisabled}
                  aria-label="message"
                />
                {voiceSupported && (
                  <button
                    type="button"
                    className="btn-mic"
                    onClick={(e) => { e.stopPropagation(); onMicToggle(); }}
                    title={listening ? "stop" : "parler"}
                  >
                    {listening ? "●" : "◉"}
                  </button>
                )}
                <button
                  type="submit"
                  className="btn-send"
                  disabled={!input.trim() || listening || inputDisabled}
                  aria-label="envoyer"
                >
                  {"→"}
                </button>
              </form>
            </div>
          </div>
        </div>
      </div>
    </aside>
  );
}

/* ══════════════════════ HUD TOP ══════════════════════ */
type HudTopProps = {
  session: Session;
  viewerCount: number;
  uptimeLabel: string;
  connStatus: "connecting" | "open" | "closed" | "error";
  onLogin?: () => void;
  onSignup?: () => void;
  onAccount?: () => void;
  onLogout?: () => void;
  onAdmin?: () => void;
};

function HudTop({
  session, viewerCount, uptimeLabel, connStatus,
  onLogin, onSignup, onAccount, onLogout, onAdmin,
}: HudTopProps) {
  const [open, setOpen] = useState(false);
  const tier: Tier | undefined = session?.tier;
  const subLabel =
    tier === "user"  ? "member"
    : tier === "vip"   ? "vip · patron"
    : tier === "admin" ? "administrator"
    : "celestial veil";

  return (
    <div className="hud-top">
      <div className={`hud-brand lg lg-pill ${open ? "open" : "closed"}`}>
        <LiquidLayers />
        <button
          type="button"
          className="brand-trigger"
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          aria-label={open ? "fermer le menu compte" : "ouvrir le menu compte"}
        >
          <div className="brand-mark">S</div>
          <div className="brand-text">
            <span className="brand-name">SHUGU</span>
            {session ? (
              <span className={`brand-sub brand-user tier-${tier}`} title={session.name}>
                {tier === "vip" && <span className="tier-crown" aria-hidden>♛</span>}
                {tier === "admin" && <span className="tier-crown admin" aria-hidden>♚</span>}
                @{session.name}
                <span className="tier-label"> · {subLabel}</span>
              </span>
            ) : (
              <span className="brand-sub">celestial veil</span>
            )}
          </div>
          <span className={`brand-caret ${open ? "up" : "down"}`} aria-hidden>▾</span>
        </button>
        <div className="brand-actions" aria-hidden={!open}>
          {!session && (
            <>
              <button className="hud-btn ghost" onClick={onLogin}>Log in</button>
              <button className="hud-btn primary" onClick={onSignup}>Sign up</button>
            </>
          )}
          {session && (
            <>
              {tier === "admin" && (
                <button className="hud-btn admin" onClick={onAdmin} title="Admin panel">
                  <span className="hud-btn-glyph">♚</span> Admin
                </button>
              )}
              <button
                className={`hud-btn account-btn ${tier === "vip" ? "vip" : ""} ${tier === "admin" ? "admin" : ""}`}
                onClick={onAccount}
              >
                {tier === "vip"   && <span className="crown vip"   aria-hidden>♛</span>}
                {tier === "admin" && <span className="crown admin" aria-hidden>♚</span>}
                Account
                {(tier === "vip" || tier === "admin") && (
                  <span className="sparkle-layer" aria-hidden>
                    <span className="sparkle s1">✦</span>
                    <span className="sparkle s2">✧</span>
                    <span className="sparkle s3">✦</span>
                  </span>
                )}
              </button>
              <button className="hud-btn subtle" onClick={onLogout}>Log out</button>
            </>
          )}
        </div>
      </div>
      <div className="hud-chips">
        <div className="hud-chip lg lg-pill live">
          <div style={{ position: "relative", zIndex: 1, display: "flex", alignItems: "center", gap: 8 }}>
            <span className="chip-dot" />
            <span>{connStatus === "open" ? uptimeLabel : connStatus === "connecting" ? "CONNECTING" : "OFFLINE"}</span>
          </div>
        </div>
        <div className="hud-chip lg lg-pill">
          <div style={{ position: "relative", zIndex: 1, display: "flex", alignItems: "center", gap: 8 }}>
            <span className="chip-dot" />
            <span>{viewerCount.toLocaleString("en-US")} viewers</span>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ══════════════════════ HUD BOTTOM ══════════════════════ */
function HudBottom() {
  return (
    <div className="hud-bottom">
      <div className="title-card lg">
        <LiquidLayers />
        <div style={{ position: "relative", zIndex: 1 }}>
          <div className="title">✦ Shugu ⇢ velvet void — session live</div>
          <div className="tags">
            <span>Virtual · VRM</span><span>FR</span><span>SFW</span><span>chill</span>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ══════════════════════ REACTIONS ══════════════════════ */
const EMOJI = ["✦", "💜", "🔮", "⭐", "🌙", "💫", "✨"];

type ReactionItem = { id: string; emoji: string; x: number; r: string; delay: number };

function Reactions({ seed }: { seed: number }) {
  const [items, setItems] = useState<ReactionItem[]>([]);
  useEffect(() => {
    // FIXME P3: trigger-by-increment pattern — setItems driven by seed increment (emoji burst on performance.audio).
    if (seed === 0) return;
    const count = 3 + Math.floor(Math.random() * 3);
    const batch: ReactionItem[] = Array.from({ length: count }, (_, i) => ({
      id: `${seed}-${i}`,
      emoji: EMOJI[Math.floor(Math.random() * EMOJI.length)],
      x: Math.random() * 40 - 20,
      r: (Math.random() * 30 - 15) + "deg",
      delay: i * 180,
    }));
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setItems((prev) => [...prev, ...batch]);
    const batchIds = new Set(batch.map((b) => b.id));
    const t = window.setTimeout(() => {
      setItems((prev) => prev.filter((p) => !batchIds.has(p.id)));
    }, 4000);
    return () => window.clearTimeout(t);
  }, [seed]);

  return (
    <div className="reactions">
      {items.map((it) => (
        <span
          key={it.id}
          className="reaction-float"
          style={{
            left: `${it.x}px`,
            animationDelay: `${it.delay}ms`,
            ["--r" as string]: it.r,
          } as React.CSSProperties}
        >
          {it.emoji}
        </span>
      ))}
    </div>
  );
}

/* ══════════════════════ STAGE ══════════════════════ */
/* Proto rend `.stage > .nebula + .avatar-stage/silhouette + .avatar-halo`.
   En production le VRM viewer (canvas 3D plein écran) occupe cette zone —
   on conserve la classe `.stage` pour le z-index/isolate mais son contenu
   vient du parent via `stageSlot`. */
function Stage({ slot }: { slot?: ReactNode }) {
  return (
    <div className="stage">
      {slot ?? (
        <>
          <div className="nebula stars" />
          <div className="avatar-stage"><div className="avatar-silhouette" /></div>
          <div className="avatar-halo" />
        </>
      )}
    </div>
  );
}

/* ══════════════════════ VIEWER STAGE (APP) ══════════════════════ */
/**
 * Port de `App` du proto (preview/proto/app.jsx:380-484) — logique de collapse,
 * unread, reactions, dispatch send. Données scriptées remplacées par props.
 * Le parent gère le WebSocket → `messages` / `session` / `onSend`.
 */
export function ViewerStage({
  messages,
  session,
  viewerCount,
  uptimeLabel,
  connStatus,
  inputValue,
  onInputChange,
  onSend,
  inputDisabled,
  reactionSeed,
  onLogin,
  onSignup,
  onAccount,
  onLogout,
  onAdmin,
  voice,
  stageSlot,
}: Props) {
  const [collapsed, setCollapsed] = useState(false);
  const [unread, setUnread] = useState(0);
  const prevCountRef = useRef(messages.length);

  /* eslint-disable react-hooks/set-state-in-effect */
  // Track new messages → incrémente unread si collapsed.
  // FIXME(react-hooks/set-state-in-effect): pattern P3 — unread driven by two independent
  // sources (messages.length + collapsed); not derivable without useSyncExternalStore.
  useEffect(() => {
    if (collapsed && messages.length > prevCountRef.current) {
      setUnread((u) => Math.min(99, u + (messages.length - prevCountRef.current)));
    }
    prevCountRef.current = messages.length;
  }, [messages.length, collapsed]);

  // Reset unread à chaque ouverture.
  useEffect(() => { if (!collapsed) setUnread(0); }, [collapsed]);
  /* eslint-enable react-hooks/set-state-in-effect */

  return (
    <div className="viewer-proto-root">
      {/* SVG filter for .lg-backdrop displacement */}
      <svg width={0} height={0} style={{ position: "absolute" }} aria-hidden>
        <defs>
          <filter id="liquid-glass-displacement" x="0%" y="0%" width="100%" height="100%">
            <feTurbulence type="fractalNoise" baseFrequency="0.012 0.018" numOctaves={2} seed={7} result="noise" />
            <feDisplacementMap in="SourceGraphic" in2="noise" scale={6} xChannelSelector="R" yChannelSelector="G" />
          </filter>
        </defs>
      </svg>

      <Stage slot={stageSlot} />

      <HudTop
        session={session}
        viewerCount={viewerCount}
        uptimeLabel={uptimeLabel}
        connStatus={connStatus}
        onLogin={onLogin}
        onSignup={onSignup}
        onAccount={onAccount}
        onLogout={onLogout}
        onAdmin={onAdmin}
      />
      <HudBottom />
      <Reactions seed={reactionSeed} />

      <ChatCard
        messages={messages}
        collapsed={collapsed}
        onToggleCollapse={() => setCollapsed((v) => !v)}
        unread={unread}
        input={inputValue}
        setInput={onInputChange}
        onSend={onSend}
        listening={!!voice?.listening}
        onMicToggle={() => {
          if (!voice) return;
          voice.listening ? voice.stop() : voice.start();
        }}
        inputDisabled={inputDisabled}
        voiceSupported={!!voice?.supported}
      />
    </div>
  );
}
