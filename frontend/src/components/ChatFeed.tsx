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
 *
 * `showAssistant` (default false): visitors never see Shugu's own messages —
 * her voice carries them. The operator can flip the debug-captions toggle in
 * OperatorPanel to render them for developer visibility.
 */

type Props = {
  messages: Message[];
  showAssistant?: boolean;
};

const DESKTOP_QUERY = "(min-width: 768px)";

export function ChatFeed({ messages, showAssistant = false }: Props) {
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
    } else if (visibleMessages.length > prevLenRef.current) {
      setUnread((n) => Math.min(99, n + (visibleMessages.length - prevLenRef.current)));
    }
    prevLenRef.current = visibleMessages.length;
  }, [visibleMessages.length, open, autoFollow]);

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
      <header
        className="px-4 py-2.5 flex items-center justify-between shrink-0"
        style={{ background: "linear-gradient(90deg, rgba(224,142,254,0.10) 0%, rgba(129,236,255,0.05) 100%)" }}
      >
        <span className="veil-headline text-xs text-veil-primary tracking-[0.12em] uppercase">
          ✦ Chat
        </span>
        <div className="flex items-center gap-2">
          <span className="veil-body text-[10px] text-veil-on-surface-variant">
            {visibleMessages.length > 0 ? `${visibleMessages.length} msg` : "—"}
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
        {visibleMessages.length === 0 && (
          <div className="text-shugu-cream-dim text-xs text-center py-8 italic leading-relaxed">
            Aucun message pour l&apos;instant.<br />
            Dis bonjour à Shugu ♡
          </div>
        )}
        {visibleMessages.map((m, i) => (
          <ChatLine key={i} message={m} />
        ))}
      </div>

      {!autoFollow && visibleMessages.length > 0 && (
        <button
          onClick={scrollToBottom}
          className="mx-3 mb-2 px-4 py-1.5 veil-gradient-primary text-white text-xs font-bold rounded-full veil-halo-pink shrink-0 hover:scale-[1.02] transition-transform"
        >
          ↓ nouveaux messages
        </button>
      )}
    </>
  );

  // Celestial Veil: no 1px solid border — separation via surface gradient +
  // backdrop blur. The thin inset shadow acts as a "ghost border" at 15% opacity.
  const panelBgStyle = {
    background: "linear-gradient(180deg, rgba(18,18,30,0.78) 0%, rgba(13,13,24,0.95) 35%)",
    backdropFilter: "blur(20px)",
    WebkitBackdropFilter: "blur(20px)",
    boxShadow:
      "inset 1px 0 0 0 rgba(224,142,254,0.12), -14px 0 40px rgba(224,142,254,0.10)",
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
            "veil-gradient-primary text-white",
            "rounded-l-xl font-bold",
            "transition-[right] duration-300 ease-out",
            "veil-halo-pink hover:scale-[1.03]",
          ].join(" ")}
          style={{
            right: open ? "320px" : "0px",
            top: "calc(50vh - 2.5rem)",
          }}
        >
          <span className="text-base leading-none">✦</span>
          <span className="text-sm leading-none font-black">{open ? "›" : "‹"}</span>
          {!open && unread > 0 && (
            <span className="absolute -top-1 -left-1 min-w-[18px] h-[18px] px-1 rounded-full veil-gradient-secondary text-white text-[9px] font-bold flex items-center justify-center shadow-md">
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
          "veil-gradient-primary text-white text-2xl",
          "flex items-center justify-center",
          "veil-halo-pink",
          "transition-all duration-300",
          open ? "opacity-0 pointer-events-none scale-75" : "opacity-100 scale-100",
        ].join(" ")}
        style={{
          right: "1rem",
          bottom: "calc(5rem + env(safe-area-inset-bottom, 0px))",
        }}
      >
        <span>✦</span>
        {unread > 0 && (
          <span className="absolute -top-1 -right-1 min-w-[20px] h-5 px-1.5 rounded-full veil-gradient-secondary text-white text-[10px] font-bold flex items-center justify-center shadow-md">
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
    <div className="animate-fade-up rounded-lg px-2 py-1"
      style={{ background: isShugu ? "rgba(224,142,254,0.06)" : "rgba(129,236,255,0.04)" }}
    >
      <div className="flex items-baseline gap-1.5 flex-wrap">
        <span
          className={`veil-headline text-[10px] uppercase tracking-wider shrink-0 ${
            isShugu ? "text-veil-primary" : "text-veil-tertiary"
          }`}
        >
          {isShugu ? "Shugu" : "visiteur"}
        </span>
        <span className="veil-body text-veil-on-surface text-[13px] leading-snug break-words">
          {message.content}
        </span>
      </div>
    </div>
  );
}
