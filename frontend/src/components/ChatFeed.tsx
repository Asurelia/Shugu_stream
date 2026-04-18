import { useEffect, useMemo, useRef, useState } from "react";
import { Message } from "@/features/messages/messages";
import { useMediaQuery } from "@/hooks/useMediaQuery";

/**
 * Twitch-style chat panel.
 *
 * Desktop (≥768px): persistent 320px sidebar on the right. A pill toggle FAB on
 *   the panel's left edge slides it in/out.
 * Mobile  (<768px): hidden by default. A floating bubble FAB in the bottom-right
 *   opens a full-height drawer (85vw).
 */

type Props = {
  messages: Message[];
};

const DESKTOP_QUERY = "(min-width: 768px)";

export function ChatFeed({ messages }: Props) {
  const isDesktop = useMediaQuery(DESKTOP_QUERY, true);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const prevLenRef = useRef<number>(messages.length);
  const [autoFollow, setAutoFollow] = useState(true);
  const [open, setOpen] = useState(true);
  const [unread, setUnread] = useState(0);

  useEffect(() => {
    setOpen(isDesktop);
  }, [isDesktop]);

  useEffect(() => {
    if (open) {
      setUnread(0);
      if (autoFollow) {
        const el = scrollRef.current;
        if (el) el.scrollTop = el.scrollHeight;
      }
    } else if (messages.length > prevLenRef.current) {
      setUnread((n) => Math.min(99, n + (messages.length - prevLenRef.current)));
    }
    prevLenRef.current = messages.length;
  }, [messages.length, open, autoFollow]);

  const onScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
    setAutoFollow(nearBottom);
  };

  const scrollToBottom = () => {
    const el = scrollRef.current;
    if (!el) return;
    setAutoFollow(true);
    el.scrollTop = el.scrollHeight;
  };

  const content = (
    <>
      <header className="px-4 py-2.5 flex items-center justify-between border-b border-shugu-pink-soft/15 shrink-0">
        <span className="text-xs font-bold text-shugu-pink-soft tracking-wide">
          ♡ CHAT
        </span>
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-shugu-cream-dim">
            {messages.length > 0 ? `${messages.length} msg` : "—"}
          </span>
          {!isDesktop && (
            <button
              onClick={() => setOpen(false)}
              aria-label="fermer le chat"
              className="w-7 h-7 rounded-full bg-shugu-ink-soft/80 hover:bg-shugu-ink-soft text-shugu-cream-dim hover:text-shugu-cream flex items-center justify-center text-sm"
            >
              ×
            </button>
          )}
        </div>
      </header>

      <div
        ref={scrollRef}
        onScroll={onScroll}
        className="flex-1 min-h-0 overflow-y-auto px-3 py-2 space-y-1.5 scroll-hidden"
      >
        {messages.length === 0 && (
          <div className="text-shugu-cream-dim text-xs text-center py-8 italic leading-relaxed">
            Aucun message pour l&apos;instant.<br />
            Dis bonjour à Shugu ♡
          </div>
        )}
        {messages.map((m, i) => (
          <ChatLine key={i} message={m} />
        ))}
      </div>

      {!autoFollow && messages.length > 0 && (
        <button
          onClick={scrollToBottom}
          className="mx-3 mb-2 px-3 py-1.5 bg-shugu-pink hover:bg-shugu-pink-glow text-white text-xs font-bold rounded-full shadow-lg shrink-0"
        >
          ↓ nouveaux messages
        </button>
      )}
    </>
  );

  const panelBgStyle = {
    background: "linear-gradient(180deg, rgba(26,10,32,0.72) 0%, rgba(26,10,32,0.95) 35%)",
    borderLeft: "1px solid rgba(255,168,185,0.2)",
  };

  if (isDesktop) {
    return (
      <>
        <aside
          className={[
            "fixed top-20 right-0 z-30 font-quicksand flex flex-col",
            "w-[320px] h-[calc(100vh-5rem)]",
            "transition-transform duration-300 ease-out",
            open ? "translate-x-0" : "translate-x-full",
          ].join(" ")}
          style={panelBgStyle}
        >
          {content}
        </aside>

        <button
          onClick={() => setOpen((v) => !v)}
          aria-label={open ? "masquer le chat" : "afficher le chat"}
          title={open ? "masquer le chat" : "afficher le chat"}
          className={[
            "fixed z-40",
            "h-20 w-9 flex flex-col items-center justify-center gap-1",
            "bg-shugu-pink hover:bg-shugu-pink-glow text-white",
            "rounded-l-xl font-bold",
            "transition-[right,background-color] duration-300 ease-out",
            "shadow-[0_4px_18px_rgba(255,97,127,0.55)]",
          ].join(" ")}
          style={{
            right: open ? "320px" : "0px",
            top: "calc(50vh - 2.5rem)",
          }}
        >
          <span className="text-base leading-none">💬</span>
          <span className="text-sm leading-none font-black">{open ? "›" : "‹"}</span>
          {!open && unread > 0 && (
            <span className="absolute -top-1 -left-1 min-w-[18px] h-[18px] px-1 rounded-full bg-shugu-live text-white text-[9px] font-bold flex items-center justify-center shadow-md">
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
          className="fixed inset-0 z-30 bg-black/45 backdrop-blur-sm animate-fade-up"
          onClick={() => setOpen(false)}
        />
      )}

      <aside
        className={[
          "fixed top-0 right-0 z-40 font-quicksand flex flex-col",
          "w-[85vw] max-w-[360px] h-full",
          "transition-transform duration-300 ease-out",
          open ? "translate-x-0" : "translate-x-full",
        ].join(" ")}
        style={panelBgStyle}
      >
        {content}
      </aside>

      <button
        onClick={() => setOpen(true)}
        aria-label="afficher le chat"
        className={[
          "fixed z-30",
          "w-14 h-14 rounded-full",
          "bg-shugu-pink hover:bg-shugu-pink-glow text-white text-2xl",
          "flex items-center justify-center",
          "shadow-[0_6px_22px_rgba(255,97,127,0.55)]",
          "transition-all duration-300",
          open ? "opacity-0 pointer-events-none scale-75" : "opacity-100 scale-100",
        ].join(" ")}
        style={{
          right: "1rem",
          bottom: "calc(5rem + env(safe-area-inset-bottom, 0px))",
        }}
      >
        <span>💬</span>
        {unread > 0 && (
          <span className="absolute -top-1 -right-1 min-w-[20px] h-5 px-1.5 rounded-full bg-shugu-live text-white text-[10px] font-bold flex items-center justify-center shadow-md">
            {unread > 99 ? "99+" : unread}
          </span>
        )}
      </button>
    </>
  );
}

function ChatLine({ message }: { message: Message }) {
  const isShugu = message.role === "assistant";
  return (
    <div className="animate-fade-up">
      <div className="flex items-baseline gap-1.5 flex-wrap">
        <span
          className={`text-[11px] font-bold shrink-0 ${
            isShugu ? "text-shugu-pink-glow" : "text-shugu-blue"
          }`}
        >
          {isShugu ? "Shugu ♡" : "visiteur"}
        </span>
        <span className="text-shugu-cream text-[13px] leading-snug break-words">
          {message.content}
        </span>
      </div>
    </div>
  );
}
