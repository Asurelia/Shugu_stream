import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { Message } from "@/features/messages/messages";
import { useMediaQuery } from "@/hooks/useMediaQuery";

/**
 * Rail chat droit — port direct du mockup Stitch `vtuber_immersive_room_overlay`.
 *
 *   ┌─ + ─────── LIVE COMMUNITY ───── + ─┐
 *   │  ✦ CyberMod_Alpha                  │   glyph + pseudo coloré par rang
 *   │  Welcome to the stream everyone…   │
 *   │  ★ Lunar_Glow                      │
 *   │  The character model looks…        │
 *   │  ─────────────────────────────     │
 *   │  ( Send a message…              )  │   input rounded-full
 *   └────────────────────────────────────┘
 *
 * Glyphes par rang (copiés du HTML fourni) :
 *  - ✦ rose-400  → MOD
 *  - ★ blue-400  → SUB / VIP
 *  - 👑 yellow-500 → King / top-donator
 *  - aucun glyph, gray-400 → simple viewer
 *
 * `showAssistant` : les visiteurs ne voient pas les messages de Shugu.
 */

type VoiceProps = {
  supported: boolean;
  listening: boolean;
  interim: string;
  start: () => void;
  stop: () => void;
};

type Props = {
  messages: Message[];
  showAssistant?: boolean;
  viewerCount?: number;
  inputValue: string;
  onInputChange: (v: string) => void;
  onSubmit: (e: FormEvent) => void;
  inputDisabled: boolean;
  voice?: VoiceProps;
  /**
   * "default" → comportement historique (aside fixed right-8 top-24 bottom-12
   * w-80 avec handle retractable gradient rose).
   * "viewer-rail" → rend uniquement le corps chat (glass-panel intérieur) en
   *   mode plus translucide (classe `chat-rail-translucent`). Le parent
   *   s'occupe du positionnement/toggle/width. Fallback mobile identique au
   *   mode default (overlay plein écran).
   */
  variant?: "default" | "viewer-rail";
};

const DESKTOP_QUERY = "(min-width: 768px)";

// Palette de rangs — chaque entrée = glyph + couleur username.
// Ajouter un rang : new row ici, zéro JSX à toucher.
const ROLE_STYLES = {
  assistant: { label: "Shugu",   glyph: "✦", glyphClass: "text-celestial-pink",   nameClass: "text-celestial-pink" },
  user:      { label: "viewer",  glyph: "",  glyphClass: "",                      nameClass: "text-gray-400"       },
} as const;

export function ChatFeed({
  messages, showAssistant = false, viewerCount,
  inputValue, onInputChange, onSubmit, inputDisabled, voice,
  variant = "default",
}: Props) {
  const isDesktop = useMediaQuery(DESKTOP_QUERY, true);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const visibleMessages = useMemo(
    () => (showAssistant ? messages : messages.filter((m) => m.role !== "assistant")),
    [messages, showAssistant],
  );
  const prevLenRef = useRef<number>(visibleMessages.length);
  const [autoFollow, setAutoFollow] = useState(true);
  const [open, setOpen] = useState(true);
  const [unread, setUnread] = useState(0);

  // FIXME(react-hooks/set-state-in-effect): pattern P3 — sync open with isDesktop prop;
  // preserves user-toggle agency so can't be a simple derivation.
  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => { setOpen(isDesktop); }, [isDesktop]);

  // FIXME(react-hooks/set-state-in-effect): pattern P3 — unread counter driven by two
  // independent state sources (messages length + open); not derivable without useSyncExternalStore.
  useEffect(() => {
    if (open) {
      setUnread(0);
      if (autoFollow) {
        const el = scrollRef.current;
        if (el) el.scrollTop = el.scrollHeight;
      }
    } else if (visibleMessages.length > prevLenRef.current) {
      setUnread((n) => Math.min(99, n + (visibleMessages.length - prevLenRef.current)));
    }
    prevLenRef.current = visibleMessages.length;
  }, [visibleMessages.length, open, autoFollow]);
  /* eslint-enable react-hooks/set-state-in-effect */

  const onScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
    setAutoFollow(nearBottom);
  };

  const placeholder = voice?.listening
    ? (voice.interim ? `✦ « ${voice.interim} »` : "✦ écoute…")
    : "Send a message…";

  const inputEl = (
    <form onSubmit={onSubmit} className="p-4">
      <div className="relative flex items-center">
        <input
          type="text"
          value={voice?.listening ? voice.interim : inputValue}
          onChange={(e) => onInputChange(e.target.value)}
          placeholder={placeholder}
          maxLength={500}
          disabled={inputDisabled || !!voice?.listening}
          aria-label="message"
          className="w-full bg-white/5 border border-white/10 rounded-full py-3 pl-6 pr-12 text-sm focus:outline-none focus:ring-1 focus:ring-celestial-purple placeholder:text-gray-500 text-white veil-body"
        />
        <div className="absolute right-1.5 top-1/2 -translate-y-1/2 flex items-center gap-1">
          {voice?.supported && (
            <button
              type="button"
              onClick={voice.listening ? voice.stop : voice.start}
              disabled={inputDisabled}
              title={voice.listening ? "arrêter" : "parler"}
              className={[
                "w-7 h-7 rounded-full flex items-center justify-center text-xs transition-all",
                voice.listening
                  ? "bg-gradient-to-r from-[#b585ff] to-[#e879f9] text-black animate-pulse"
                  : "text-gray-400 hover:text-celestial-pink hover:bg-white/5",
              ].join(" ")}
            >
              {voice.listening ? "●" : "◉"}
            </button>
          )}
          <button
            type="submit"
            disabled={!inputValue.trim() || inputDisabled || !!voice?.listening}
            aria-label="envoyer"
            className="w-7 h-7 rounded-full flex items-center justify-center text-sm font-bold bg-gradient-to-r from-[#b585ff] to-[#e879f9] text-black hover:scale-105 transition-transform disabled:opacity-30 disabled:cursor-not-allowed disabled:hover:scale-100"
          >
            {"→"}
          </button>
        </div>
      </div>
    </form>
  );

  const chatBody = (
    <div
      className={[
        "glass-panel flex-grow flex flex-col overflow-hidden",
        variant === "viewer-rail" ? "chat-rail-translucent" : "",
      ].filter(Boolean).join(" ")}
    >
      {/* Header chat */}
      <div className="p-4 border-b border-white/10 flex items-center justify-between">
        <div className="flex items-center space-x-2.5">
          <span className="w-1.5 h-1.5 rounded-full bg-celestial-pink animate-live-pulse" />
          <h2 className="text-xs uppercase tracking-[0.2em] font-bold text-gray-300">
            Live Community
          </h2>
        </div>
        {typeof viewerCount === "number" && viewerCount > 0 && (
          <span className="tech-label">
            {viewerCount.toLocaleString("fr-FR")} viewers
          </span>
        )}
        {!isDesktop && (
          <button
            onClick={() => setOpen(false)}
            aria-label="fermer le chat"
            className="w-7 h-7 rounded-full text-gray-400 hover:text-white flex items-center justify-center text-sm"
          >
            ×
          </button>
        )}
      </div>

      {/* Messages */}
      <div
        ref={scrollRef}
        onScroll={onScroll}
        className="flex-grow min-h-0 p-4 space-y-5 overflow-y-auto custom-scrollbar"
      >
        {visibleMessages.length === 0 && (
          <div className="text-gray-500 text-xs text-center py-10 italic leading-relaxed">
            Aucun message pour l&apos;instant.<br />
            Dis bonjour à Shugu ✦
          </div>
        )}
        {visibleMessages.map((m, i) => (
          <ChatMessage key={i} message={m} />
        ))}
      </div>

      {!autoFollow && visibleMessages.length > 0 && (
        <button
          onClick={() => {
            const el = scrollRef.current;
            if (!el) return;
            setAutoFollow(true);
            el.scrollTop = el.scrollHeight;
          }}
          className="mx-4 mb-1 px-4 py-1.5 bg-gradient-to-r from-[#b585ff] to-[#e879f9] text-black text-[11px] font-bold rounded-full shrink-0 hover:scale-[1.02] transition-transform"
        >
          ↓ nouveaux messages
        </button>
      )}

      {inputEl}
    </div>
  );

  if (isDesktop) {
    // Variante viewer-rail : le parent (page viewer V3 Immersive HUD)
    // s'occupe de `position: fixed`, de la largeur du rail et du toggle.
    // ChatFeed ne rend alors que son corps, avec la classe translucide.
    if (variant === "viewer-rail") {
      return <>{chatBody}</>;
    }
    return (
      <>
        <aside
          className={[
            "fixed right-8 top-24 bottom-12 w-80 flex flex-col z-20",
            "transition-transform duration-300 ease-out",
            open ? "translate-x-0" : "translate-x-[calc(100%+2rem)]",
          ].join(" ")}
        >
          {chatBody}
        </aside>

        {/* Handle rétractable — ancré au bord droit du viewport (right:0 quand
            fermé, aligné sur le bord gauche du rail quand ouvert). On fige
            `top` à 50vh - 3rem (hauteur/2) au lieu d'utiliser translate, pour
            que `hover:brightness` ne casse pas le positioning. Transition
            limitée à `right` → pas d'effet de bord sur le hover. */}
        <button
          onClick={() => setOpen((v) => !v)}
          aria-label={open ? "masquer le chat" : "afficher le chat"}
          title={open ? "masquer le chat" : "afficher le chat"}
          className={[
            "fixed z-40 flex flex-col items-center justify-center gap-1",
            "w-10 h-24 rounded-l-xl",
            "bg-gradient-to-b from-[#b585ff] to-[#e879f9] text-black",
            "hover:brightness-110",
            "shadow-[0_8px_24px_rgba(181,133,255,0.45)]",
          ].join(" ")}
          style={{
            right: open ? "352px" : "0px",
            top: "calc(50vh - 3rem)",
            transition: "right 300ms ease-out, filter 150ms",
          }}
        >
          <span className="text-base font-bold leading-none">{open ? "›" : "‹"}</span>
          <span
            className="text-[10px] leading-none font-bold tracking-[0.3em]"
            style={{ writingMode: "vertical-rl" }}
          >
            CHAT
          </span>
          {!open && unread > 0 && (
            <span className="absolute -top-1.5 -left-1.5 min-w-[18px] h-[18px] px-1 rounded-full bg-celestial-pink text-white text-[9px] font-bold flex items-center justify-center shadow-md">
              {unread > 99 ? "99+" : unread}
            </span>
          )}
        </button>
      </>
    );
  }

  return (
    <>
      {open && (
        <div
          className="fixed inset-0 z-30 bg-black/55 backdrop-blur-sm animate-fade-up"
          onClick={() => setOpen(false)}
        />
      )}
      <aside
        className={[
          "fixed top-20 right-4 bottom-4 z-40 flex flex-col",
          "w-[86vw] max-w-[360px]",
          "transition-transform duration-300 ease-out",
          open ? "translate-x-0" : "translate-x-full",
        ].join(" ")}
      >
        {chatBody}
      </aside>

      <button
        onClick={() => setOpen(true)}
        aria-label="afficher le chat"
        className={[
          "fixed z-30 w-14 h-14 rounded-full",
          "bg-gradient-to-r from-[#b585ff] to-[#e879f9] text-black text-2xl",
          "flex items-center justify-center shadow-lg",
          "transition-all duration-300",
          open ? "opacity-0 pointer-events-none scale-75" : "opacity-100 scale-100",
        ].join(" ")}
        style={{
          right: "1rem",
          bottom: "calc(1.25rem + env(safe-area-inset-bottom, 0px))",
        }}
      >
        <span>✦</span>
        {unread > 0 && (
          <span className="absolute -top-1 -right-1 min-w-[20px] h-5 px-1.5 rounded-full bg-celestial-pink text-black text-[10px] font-bold flex items-center justify-center shadow-md">
            {unread > 99 ? "99+" : unread}
          </span>
        )}
      </button>
    </>
  );
}

/**
 * Message : glyph coloré + username bold ligne 1, puis texte sur ligne 2.
 * (Aucun conteneur de bulle, aucun avatar — aligné avec le HTML Stitch.)
 */
function ChatMessage({ message }: { message: Message }) {
  const role = message.role === "assistant" ? "assistant" : "user";
  const style = ROLE_STYLES[role];
  return (
    <div className="group animate-fade-up">
      <div className="flex items-center space-x-2 mb-1">
        {style.glyph && (
          <span className={`text-[10px] font-bold ${style.glyphClass}`}>
            {style.glyph}
          </span>
        )}
        <span className={`text-xs font-bold ${style.nameClass}`}>
          {style.label}
        </span>
      </div>
      <p className="text-sm text-gray-200 leading-relaxed break-words m-0">
        {message.content}
      </p>
    </div>
  );
}
