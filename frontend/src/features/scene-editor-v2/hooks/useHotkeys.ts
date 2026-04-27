/**
 * Hook hotkeys global pour Scene Editor v2.
 *
 * - Bindings classiques : touches simples (1, 2, 3, Escape) ignorées si focus
 *   est dans un INPUT, TEXTAREA, SELECT, contenteditable.
 * - Bindings avec modifier (Mod = Ctrl sur Win/Linux, Cmd sur macOS) : TOUJOURS
 *   actifs, même quand un input est focused (Mod+K command palette doit marcher
 *   partout, Escape doit pouvoir fermer un overlay même depuis un input).
 * - Cleanup au unmount via useEffect return.
 */

import { useEffect } from "react";

export type Binding = {
  key: string;
  mod?: boolean;
  shift?: boolean;
  alt?: boolean;
  handler: (event: KeyboardEvent) => void;
  preventDefault?: boolean;
};

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
  if (target.isContentEditable) return true;
  return false;
}

function modifierActive(event: KeyboardEvent): boolean {
  return event.ctrlKey || event.metaKey;
}

function matches(binding: Binding, event: KeyboardEvent): boolean {
  if (event.key !== binding.key && event.key.toLowerCase() !== binding.key.toLowerCase()) {
    return false;
  }
  if (Boolean(binding.mod) !== modifierActive(event)) return false;
  if (Boolean(binding.shift) !== event.shiftKey) return false;
  if (Boolean(binding.alt) !== event.altKey) return false;
  return true;
}

export function useHotkeys(bindings: Binding[]): void {
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      const editable = isEditableTarget(event.target);
      for (const b of bindings) {
        if (!matches(b, event)) continue;
        // Plain keys (no modifier, not Escape) are blocked while editing.
        const isPlain = !b.mod && !b.shift && !b.alt && b.key !== "Escape";
        if (isPlain && editable) continue;
        if (b.preventDefault) event.preventDefault();
        b.handler(event);
        break;
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [bindings]);
}
