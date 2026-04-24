/**
 * Scene Editor — hooks partagés : hotkeys globaux + toast éphémère.
 *
 * Les hotkeys suivent la convention DCC (Unity, Blender) : W/E/R changent
 * l'outil actif, F focus sur la sélection, A frame all, Space joue/pause,
 * Delete retire la sélection, ⌘Z/⇧⌘Z pour undo/redo, ⌘D duplique, ⌘S save,
 * chiffres 1-8 basculent les panneaux.
 *
 * Les entrées texte (input/textarea/contenteditable) court-circuitent
 * tous les raccourcis pour ne pas voler leur frappe.
 */

import { useCallback, useEffect, useRef, useState } from "react";

export type Tool = "move" | "rotate" | "scale";

export type HotkeyActions = {
  setTool: (t: Tool) => void;
  undo: () => void;
  redo: () => void;
  duplicate: () => void;
  save: () => void;
  deleteSelected: () => void;
  frameAll: () => void;
  focusSelected: () => void;
  togglePlay: () => void;
  selectPanel: (idx: number) => void;
  toast: (msg: string) => void;
};

const isTextInput = (el: EventTarget | null): boolean => {
  if (!(el instanceof HTMLElement)) return false;
  const tag = el.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
  if (el.isContentEditable) return true;
  return false;
};

export function useHotkeys(actions: HotkeyActions) {
  const actionsRef = useRef(actions);
  useEffect(() => {
    actionsRef.current = actions;
  }, [actions]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (isTextInput(e.target)) return;
      const a = actionsRef.current;
      const cmd = e.metaKey || e.ctrlKey;
      const k = e.key.toLowerCase();

      // Tool hotkeys (no modifier)
      if (!cmd && !e.altKey && !e.shiftKey) {
        if (k === "w") { e.preventDefault(); a.setTool("move");   a.toast("Tool · Move"); return; }
        if (k === "e") { e.preventDefault(); a.setTool("rotate"); a.toast("Tool · Rotate"); return; }
        if (k === "r") { e.preventDefault(); a.setTool("scale");  a.toast("Tool · Scale"); return; }
        if (k === "f") { e.preventDefault(); a.focusSelected(); a.toast("Focus selected"); return; }
        if (k === "a") { e.preventDefault(); a.frameAll();     a.toast("Frame all"); return; }
        if (k === " ") { e.preventDefault(); a.togglePlay();   return; }
        if (k === "delete" || k === "backspace") {
          e.preventDefault();
          a.deleteSelected();
          a.toast("Delete selection");
          return;
        }
        // Panel switching 1-8
        if (/^[1-8]$/.test(e.key)) {
          e.preventDefault();
          a.selectPanel(parseInt(e.key, 10));
          return;
        }
      }

      // Cmd/Ctrl combos
      if (cmd) {
        if (k === "z" && !e.shiftKey) { e.preventDefault(); a.undo(); a.toast("Undo"); return; }
        if (k === "z" &&  e.shiftKey) { e.preventDefault(); a.redo(); a.toast("Redo"); return; }
        if (k === "d") { e.preventDefault(); a.duplicate(); a.toast("Duplicate"); return; }
        if (k === "s") { e.preventDefault(); a.save(); a.toast("Scene saved"); return; }
      }
    };

    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
}

/* ───────────────────────────── Toast ───────────────────────────── */

export function useToast() {
  const [msg, setMsg] = useState<string | null>(null);
  const timerRef = useRef<number | null>(null);

  const show = useCallback((m: string) => {
    setMsg(m);
    if (timerRef.current) window.clearTimeout(timerRef.current);
    timerRef.current = window.setTimeout(() => setMsg(null), 1200);
  }, []);

  useEffect(() => () => {
    if (timerRef.current) window.clearTimeout(timerRef.current);
  }, []);

  return { msg, show };
}

export function HotkeyToast({ msg }: { msg: string | null }) {
  if (!msg) return null;
  return (
    <div className="ide-toast">
      <span className="dot" />
      {msg}
    </div>
  );
}
