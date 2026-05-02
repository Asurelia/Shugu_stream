// A single window on the virtual desktop — read-only from the user's POV.
// Hermes is the only actor that opens/edits/closes; the user can click to
// focus (raise z-index) and minimize, nothing else.
//
// Char-by-char type animation: when a `pendingAppend` lands (from a
// desktop.edit_file append), the window pushes those chars one at a time
// into a local `revealed` buffer so the audience sees Hermes "typing".

import { useEffect, useState } from "react";
import { DesktopWindow as WindowState, useDesktopState } from "./desktopState";

const TYPE_CHARS_PER_SEC = 45;   // roughly matches natural human typing

type Props = {
  win: WindowState;
};

export function DesktopWindow({ win }: Props) {
  const { dispatch } = useDesktopState();
  const [revealedSuffix, setRevealedSuffix] = useState("");

  useEffect(() => {
    if (!win.pendingAppend) {
      return;
    }
    // Animate the append char-by-char, then clear pendingAppend.
    const chars = win.pendingAppend;
    let i = 0;
    const intervalMs = Math.max(10, 1000 / TYPE_CHARS_PER_SEC);
    const handle = window.setInterval(() => {
      i += 1;
      setRevealedSuffix(chars.slice(0, i));
      if (i >= chars.length) {
        window.clearInterval(handle);
        dispatch({ type: "window.clearAppend", fileName: win.fileName });
      }
    }, intervalMs);
    return () => window.clearInterval(handle);
  }, [win.pendingAppend, win.fileName, dispatch]);

  const bodyText = win.pendingAppend
    ? win.content.slice(0, win.content.length - win.pendingAppend.length) + revealedSuffix
    : win.content;

  const isCode = win.kind === "code";
  const isImage = win.kind === "image";
  const isMinimized = !!win.minimized;

  return (
    <div
      onClick={() => dispatch({ type: "window.focus", fileName: win.fileName })}
      className="absolute rounded-xl overflow-hidden shadow-[0_14px_40px_rgba(255,97,127,0.18)] flex flex-col animate-fade-up"
      style={{
        left: win.position.x,
        top: win.position.y,
        width: isMinimized ? 180 : 360,
        height: isMinimized ? 40 : 280,
        zIndex: win.zIndex,
        background: "linear-gradient(180deg, rgba(30,30,45,0.86), rgba(18,18,30,0.92))",
        backdropFilter: "blur(14px)",
        border: "1px solid rgba(224,142,254,0.18)",
      }}
    >
      <header className="px-3 py-1.5 flex items-center justify-between shrink-0 text-xs text-shugu-cream"
        style={{ background: "linear-gradient(90deg, rgba(224,142,254,0.18), rgba(129,236,255,0.08))" }}
      >
        <span className="font-bold truncate max-w-[200px]">
          {iconFor(win.kind)} {win.fileName}
        </span>
        <div className="flex items-center gap-1">
          <button
            onClick={(e) => {
              e.stopPropagation();
              dispatch({
                type: "window.focus",
                fileName: win.fileName,
              });
            }}
            title="focus"
            className="w-5 h-5 rounded-full bg-white/10 hover:bg-white/20 text-[10px]"
          >
            ↑
          </button>
          <button
            onClick={(e) => {
              e.stopPropagation();
              dispatch({ type: "window.close", fileName: win.fileName });
            }}
            title="close"
            className="w-5 h-5 rounded-full bg-shugu-live/60 hover:bg-shugu-live text-white text-[10px] font-bold"
          >
            ×
          </button>
        </div>
      </header>
      {!isMinimized && (
        <div className="flex-1 min-h-0 overflow-auto scroll-hidden">
          {isImage ? (
            // kind=image uses window.content as the src URL
            (<img
              src={win.content}
              alt={win.fileName}
              className="w-full h-full object-contain"
            />)
          ) : (
            <pre
              className={`p-3 text-[11px] leading-snug whitespace-pre-wrap break-words ${
                isCode
                  ? "font-mono text-shugu-cream-dim"
                  : "text-shugu-cream"
              }`}
            >
              {bodyText}
              {win.pendingAppend && (
                <span className="inline-block w-[2px] h-[12px] bg-shugu-pink-glow align-middle ml-[1px] animate-pulse" />
              )}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}

function iconFor(kind: WindowState["kind"]): string {
  switch (kind) {
    case "code":
      return "⌘";
    case "markdown":
      return "✎";
    case "image":
      return "▭";
    case "note":
      return "✦";
    default:
      return "◦";
  }
}
