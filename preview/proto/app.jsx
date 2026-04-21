const { useState, useEffect, useRef, useMemo, useCallback } = React;

/* ══════════════════════ DATA ══════════════════════ */

// rank: guest | sub | vip | mod | king | admin | assistant
const VISITORS = [
  { name: 'CyberMod_Alpha', rank: 'mod',    glyph: '✦' },
  { name: 'Lunar_Glow',     rank: 'sub',    glyph: '★' },
  { name: 'StarlitFox',     rank: 'guest',  glyph: ''  },
  { name: 'nebula_dev',     rank: 'guest',  glyph: ''  },
  { name: 'VeilKing42',     rank: 'king',   glyph: '👑' },
  { name: 'RiftWalker',     rank: 'vip',    glyph: '◆' },
  { name: 'hex_plum',       rank: 'guest',  glyph: ''  },
  { name: 'auroraTea',      rank: 'mod',    glyph: '✦' },
  { name: 'Petrichor',      rank: 'guest',  glyph: ''  },
  { name: 'Solenne',        rank: 'vip',    glyph: '◆' },
  { name: 'glasshaze',      rank: 'sub',    glyph: '★' },
];

const SCRIPT = [
  { kind: 'system', text: 'Stream started · Celestial Veil' },
  { kind: 'visitor', who: 'CyberMod_Alpha', text: 'bienvenue à toutes et tous ✨' },
  { kind: 'visitor', who: 'Lunar_Glow', text: 'le VRM rend dingue ce soir' },
  { kind: 'visitor', who: 'StarlitFox', text: 'premier stream ici, c\'est beau' },
  { kind: 'assistant', who: 'Shugu', text: 'Hey Starlit — merci de passer, sers-toi un thé ☕ on reste posés ce soir.' },
  { kind: 'visitor', who: 'nebula_dev', text: '!dance' },
  { kind: 'visitor', who: 'hex_plum', text: 'l\'ambiance musicale est parfaite' },
  { kind: 'assistant', who: 'Shugu', text: 'Playlist du jour : "lofi for velvet void" — je la mets en description dans 2 min.' },
  { kind: 'visitor', who: 'VeilKing42', text: 'Raid incoming from auroraTea 🌸' },
  { kind: 'system', text: 'auroraTea raid · 42 viewers' },
  { kind: 'visitor', who: 'auroraTea', text: 'salut les veilers, on débarque !' },
  { kind: 'visitor', who: 'RiftWalker', text: 'welcome party 🎉' },
  { kind: 'assistant', who: 'Shugu', text: 'Aurora 💜 merci pour le raid — install toi, c\'est chill tonight.' },
  { kind: 'visitor', who: 'Solenne', text: 'tes cheveux font vraiment lumière ambiante' },
  { kind: 'visitor', who: 'Petrichor', text: 'le chat reste sublime' },
  { kind: 'assistant', who: 'Shugu', text: 'Refonte Liquid Glass — on teste, dis-moi ce qui te parle ou pas.' },
  { kind: 'visitor', who: 'glasshaze', text: 'pseudo approprié 🔮' },
];

const FIRST_BATCH = 9;
const STEP_MS = 2800;

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

function SystemMsg({ text }) {
  return <div className="msg msg-system">{text}</div>;
}

function Bubble({ rank, who, text, glyph, time, stream = false, hermes = false }) {
  const [shown, setShown] = useState(stream ? '' : text);
  const [streaming, setStreaming] = useState(stream);

  useEffect(() => {
    if (!stream) { setShown(text); setStreaming(false); return; }
    setShown(''); setStreaming(true);
    let i = 0;
    const tick = () => {
      i += Math.max(1, Math.round(text.length / 60));
      if (i >= text.length) { setShown(text); setStreaming(false); return; }
      setShown(text.slice(0, i));
      timer = setTimeout(tick, 34);
    };
    let timer = setTimeout(tick, 120);
    return () => clearTimeout(timer);
  }, [text, stream]);

  const cls = `bubble rank-${rank} ${hermes ? 'hermes' : ''}`.trim();

  return (
    <div className={`msg rank-${rank}`}>
      <div className="who">
        {glyph && <span className="glyph">{glyph}</span>}
        <span className="name">{who}</span>
        {time && <span className="time">{time}</span>}
      </div>
      <div className={cls}>
        <LiquidLayers />
        <div className={`bubble-text ${streaming ? 'streaming' : ''}`}>{shown}</div>
      </div>
    </div>
  );
}

function nowClock() {
  const d = new Date();
  return `${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`;
}

/* ══════════════════════ CHAT CARD (collapsible) ══════════════════════ */

function ChatCard({ messages, collapsed, onToggleCollapse, unread, input, setInput, onSend,
                    listening, onMicToggle, hermesMode, isAdmin, target, setTarget }) {
  const scrollRef = useRef(null);
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

  const submit = (e) => {
    e.preventDefault();
    if (!input.trim()) return;
    onSend(input);
    setInput('');
  };

  return (
    <aside
      className={`chat-shell ${collapsed ? 'collapsed' : ''}`}
      onClick={collapsed ? onToggleCollapse : undefined}
      role={collapsed ? 'button' : undefined}
      aria-label={collapsed ? 'ouvrir le chat' : undefined}
    >
      <div className="chat-card lg">
        <LiquidLayers />

        {/* Bubble FAB (visible only when collapsed) */}
        <div className="bubble-fab">
          <span className="fab-ripple" />
          <span className="fab-glyph">✦</span>
          {unread > 0 && <span className="fab-badge">{unread > 99 ? '99+' : unread}</span>}
        </div>

        {/* Expanded chat */}
        <div className="lg-content">
          <div className="chat-header">
            <div className="chat-title">
              <span className="live-dot" />
              <span className="chat-label">Live Chat</span>
            </div>
            <button className="chip-btn" onClick={(e) => { e.stopPropagation(); onToggleCollapse(); }}
                    aria-label="réduire le chat" title="réduire">−</button>
          </div>

          <div className="chat-body">
            <div className="chat-messages" ref={scrollRef} onScroll={onScroll}>
              {messages.map((m, i) => {
                if (m.kind === 'system') return <SystemMsg key={i} text={m.text} />;
                if (m.kind === 'assistant') {
                  return <Bubble key={i}
                    rank="assistant"
                    who={m.who}
                    text={m.text}
                    glyph={hermesMode && m.who === 'Hermes' ? '⚡' : '✦'}
                    time={nowClock()}
                    stream={m.stream}
                    hermes={hermesMode && m.who === 'Hermes'}
                  />;
                }
                // visitor
                const v = VISITORS.find(v => v.name === m.who)
                       || { rank: m.rank || 'guest', glyph: m.glyph || '' };
                return <Bubble key={i}
                  rank={v.rank}
                  who={m.who}
                  text={m.text}
                  glyph={v.glyph}
                />;
              })}
            </div>

            <div className="chat-input-wrap">
              {isAdmin && <TargetSelector target={target} setTarget={setTarget} />}
              <form className={`chat-input lg-pill ${listening ? 'listening' : ''}`} onSubmit={submit}>
                <LiquidLayers />
                <input
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  placeholder={listening ? '✦ écoute…' : (hermesMode ? '⚡ commande Hermes…' : 'Send a message…')}
                  disabled={listening}
                  aria-label="message"
                />
                <button type="button" className="btn-mic"
                        onClick={(e) => { e.stopPropagation(); onMicToggle(); }}
                        title={listening ? 'stop' : 'parler'}>
                  {listening ? '●' : '◉'}
                </button>
                <button type="submit" className="btn-send"
                        disabled={!input.trim() || listening}
                        aria-label="envoyer">
                  {hermesMode ? '⚡' : '→'}
                </button>
              </form>
            </div>
          </div>
        </div>
      </div>
    </aside>
  );
}

/* ══════════════════════ HUD ══════════════════════ */

const HudTop = ({ session, onLogin, onSignup, onAccount, onLogout, onAdmin }) => {
  const [open, setOpen] = useState(false);
  const tier = session?.tier;
  const subLabel = {
    user: 'member',
    vip: 'vip · patron',
    admin: 'administrator',
  }[tier] || 'celestial veil';
  return (
  <div className="hud-top">
    <div className={`hud-brand lg lg-pill ${open ? 'open' : 'closed'}`}>
      <LiquidLayers />
      <button
        type="button"
        className="brand-trigger"
        onClick={() => setOpen(o => !o)}
        aria-expanded={open}
        aria-label={open ? 'fermer le menu compte' : 'ouvrir le menu compte'}
      >
        <div className="brand-mark">S</div>
        <div className="brand-text">
          <span className="brand-name">SHUGU</span>
          {session ? (
            <span className={`brand-sub brand-user tier-${tier}`} title={session.name}>
              {tier === 'vip' && <span className="tier-crown" aria-hidden>♛</span>}
              {tier === 'admin' && <span className="tier-crown admin" aria-hidden>♚</span>}
              @{session.name}
              <span className="tier-label"> · {subLabel}</span>
            </span>
          ) : (
            <span className="brand-sub">celestial veil</span>
          )}
        </div>
        <span className={`brand-caret ${open ? 'up' : 'down'}`} aria-hidden>▾</span>
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
            {tier === 'admin' && (
              <button className="hud-btn admin" onClick={onAdmin} title="Admin panel">
                <span className="hud-btn-glyph">♚</span> Admin
              </button>
            )}
            <button
              className={`hud-btn account-btn ${tier === 'vip' ? 'vip' : ''} ${tier === 'admin' ? 'admin' : ''}`}
              onClick={onAccount}
            >
              {tier === 'vip'   && <span className="crown vip"   aria-hidden>♛</span>}
              {tier === 'admin' && <span className="crown admin" aria-hidden>♚</span>}
              Account
              {(tier === 'vip' || tier === 'admin') && (
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
        <div style={{ position:'relative', zIndex:1, display:'flex', alignItems:'center', gap:8 }}>
          <span className="chip-dot" /><span>LIVE · 2h 14m</span>
        </div>
      </div>
      <div className="hud-chip lg lg-pill">
        <div style={{ position:'relative', zIndex:1, display:'flex', alignItems:'center', gap:8 }}>
          <span className="chip-dot" /><span>2 184 viewers</span>
        </div>
      </div>
    </div>
  </div>
  );
};

const HudBottom = () => (
  <div className="hud-bottom">
    <div className="title-card lg">
      <LiquidLayers />
      <div style={{ position:'relative', zIndex:1 }}>
        <div className="title">✦ Hermes ⇢ velvet void — lofi & quiet talk</div>
        <div className="tags">
          <span>Virtual · VRM</span><span>FR</span><span>SFW</span><span>chill</span>
        </div>
      </div>
    </div>
  </div>
);

/* ══════════════════════ REACTIONS ══════════════════════ */

const EMOJI = ['✦','💜','🔮','⭐','🌙','💫','✨'];

function Reactions({ seed }) {
  const [items, setItems] = useState([]);
  useEffect(() => {
    if (seed === 0) return;
    const count = 3 + Math.floor(Math.random() * 3);
    const batch = Array.from({ length: count }, (_, i) => ({
      id: `${seed}-${i}`,
      emoji: EMOJI[Math.floor(Math.random() * EMOJI.length)],
      x: Math.random() * 40 - 20,
      r: (Math.random() * 30 - 15) + 'deg',
      delay: i * 180,
    }));
    setItems(prev => [...prev, ...batch]);
    const t = setTimeout(() => {
      setItems(prev => prev.filter(p => !batch.find(b => b.id === p.id)));
    }, 4000);
    return () => clearTimeout(t);
  }, [seed]);

  return (
    <div className="reactions">
      {items.map(it => (
        <span key={it.id} className="reaction-float"
              style={{ left: `${it.x}px`, animationDelay: `${it.delay}ms`, '--r': it.r }}>
          {it.emoji}
        </span>
      ))}
    </div>
  );
}

/* ══════════════════════ TARGET SELECTOR (admin only) ══════════════════════ */
/* Inline pill above the chat input — lets the admin/streamer pick which brain
   the next prompt hits. Hidden for everyone else. In production: derive from
   session/JWT. For preview, a hidden keystroke (Alt+A) flips admin on/off. */

function TargetSelector({ target, setTarget }) {
  return (
    <div className="target-selector lg lg-pill">
      <LiquidLayers />
      <span className="ts-label">target</span>
      <div className="ts-seg">
        <button
          className={`shugu ${target === 'shugu' ? 'active' : ''}`}
          onClick={() => setTarget('shugu')}
          aria-pressed={target === 'shugu'}
        >
          <span className="ts-glyph">✦</span> Shugu
        </button>
        <button
          className={`hermes ${target === 'hermes' ? 'active' : ''}`}
          onClick={() => setTarget('hermes')}
          aria-pressed={target === 'hermes'}
        >
          <span className="ts-glyph">⚡</span> Hermes
        </button>
      </div>
    </div>
  );
}

/* ══════════════════════ APP ══════════════════════ */

function App() {
  const [messages, setMessages] = useState(() => SCRIPT.slice(0, FIRST_BATCH));
  const [cursor, setCursor] = useState(FIRST_BATCH);
  const [collapsed, setCollapsed] = useState(false);
  const [unread, setUnread] = useState(0);
  const [input, setInput] = useState('');
  const [listening, setListening] = useState(false);
  const [reactionSeed, setReactionSeed] = useState(0);

  // Session demo: null = anon, {name, tier} where tier = 'user' | 'vip' | 'admin'.
  // Alt+A cycles between states for preview.
  const [session, setSession] = useState({ name: 'asurelia', tier: 'admin' });
  const [target, setTarget] = useState('shugu'); // shugu | hermes

  useEffect(() => {
    const h = (e) => {
      if (e.altKey && (e.key === 'a' || e.key === 'A')) {
        e.preventDefault();
        setSession(s => {
          if (!s) return { name: 'veil_guest', tier: 'user' };
          if (s.tier === 'user') return { name: 'lunar_glow', tier: 'vip' };
          if (s.tier === 'vip') return { name: 'asurelia', tier: 'admin' };
          return null;
        });
      }
    };
    window.addEventListener('keydown', h);
    return () => window.removeEventListener('keydown', h);
  }, []);

  const isAdmin = !!(session && session.tier === 'admin');

  // scripted stream
  useEffect(() => {
    if (cursor >= SCRIPT.length) return;
    const t = setTimeout(() => {
      const nextMsg = SCRIPT[cursor];
      const enriched = nextMsg.kind === 'assistant' ? { ...nextMsg, stream: true } : nextMsg;
      setMessages(prev => [...prev, enriched]);
      setCursor(c => c + 1);
      if (collapsed) setUnread(u => Math.min(99, u + 1));
      if (nextMsg.kind === 'assistant') setReactionSeed(s => s + 1);
    }, STEP_MS + Math.random() * 800);
    return () => clearTimeout(t);
  }, [cursor, collapsed]);

  useEffect(() => { if (!collapsed) setUnread(0); }, [collapsed]);

  const send = (text) => {
    setMessages(prev => [...prev, {
      kind: 'visitor',
      who: 'you',
      text,
      rank: isAdmin ? 'admin' : 'guest',
      glyph: isAdmin ? '♚' : '',
    }]);
    setTimeout(() => {
      const useHermes = isAdmin && target === 'hermes';
      const who = useHermes ? 'Hermes' : 'Shugu';
      const replyText = useHermes
        ? 'Reçu. Je décompose ta requête en tool_calls.'
        : 'Hey ! j\'entends ça. on en parle.';
      setMessages(prev => [...prev, { kind: 'assistant', who, text: replyText, stream: true }]);
      setReactionSeed(s => s + 1);
    }, 900);
  };

  const hermesMode = isAdmin && target === 'hermes';

  return (
    <>
      <div className="stage">
        <div className="nebula stars" />
        <div className="avatar-stage"><div className="avatar-silhouette" /></div>
        <div className="avatar-halo" />
      </div>

      <HudTop
        session={session}
        onLogin={() => setSession({ name: 'veil_guest', tier: 'user' })}
        onSignup={() => setSession({ name: 'veil_guest', tier: 'user' })}
        onAccount={() => {}}
        onLogout={() => setSession(null)}
        onAdmin={() => {}}
      />
      <HudBottom />
      <Reactions seed={reactionSeed} />

      <ChatCard
        messages={messages}
        collapsed={collapsed}
        onToggleCollapse={() => setCollapsed(v => !v)}
        unread={unread}
        input={input} setInput={setInput}
        onSend={send}
        listening={listening}
        onMicToggle={() => setListening(v => !v)}
        hermesMode={hermesMode}
        isAdmin={isAdmin}
        target={target}
        setTarget={setTarget}
      />
    </>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App />);
