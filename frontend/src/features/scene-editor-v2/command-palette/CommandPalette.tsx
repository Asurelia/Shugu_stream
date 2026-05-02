/**
 * Command Palette (Mod+K) — recherche fuzzy + clavier-first.
 *
 * Pattern :
 * - <dialog> aria-modal centré (CSS GlassModal-like via .lg-modal class).
 * - Input combobox avec autocomplete listbox en dessous.
 * - Arrow up/down change l'index actif.
 * - Enter exécute la commande active. Click aussi.
 * - Escape ferme.
 *
 * Liaison : ouvre/ferme via store.paletteOpen, build commandes via buildCommands(store).
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { useSceneEditorStore } from "../store/useSceneEditorStore";
import { buildCommands, filterCommands, type Command } from "./commands";

export function CommandPalette() {
  const open = useSceneEditorStore((s) => s.paletteOpen);
  const close = useSceneEditorStore((s) => s.closePalette);
  const storeApi = useSceneEditorStore;

  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement | null>(null);

  // Reset on open / close.
  // FIXME(react-hooks/set-state-in-effect): pattern P3 — reset query/activeIndex when
  // open changes. Could use key={open} on parent; left as-is to avoid parent refactor.
  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    if (open) {
      setQuery("");
      setActiveIndex(0);
      // autofocus input on open (after paint)
      const t = window.setTimeout(() => inputRef.current?.focus(), 0);
      return () => window.clearTimeout(t);
    }
    return undefined;
  }, [open]);
  /* eslint-enable react-hooks/set-state-in-effect */

  const commands = useMemo(() => buildCommands(storeApi.getState()), [storeApi]);
  const filtered = useMemo(() => filterCommands(commands, query), [commands, query]);

  // FIXME(react-hooks/set-state-in-effect): pattern P3 — reset activeIndex on query change.
  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    setActiveIndex(0);
  }, [query]);
  /* eslint-enable react-hooks/set-state-in-effect */

  if (!open) return null;

  const runCommand = (cmd: Command) => {
    cmd.run();
    close();
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Escape") {
      e.preventDefault();
      close();
      return;
    }
    if (e.key === "Enter") {
      e.preventDefault();
      const cmd = filtered[activeIndex];
      if (cmd) runCommand(cmd);
      return;
    }
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIndex((i) => Math.min(filtered.length - 1, i + 1));
      return;
    }
    if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIndex((i) => Math.max(0, i - 1));
      return;
    }
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Command palette"
      className="sev2-palette-scrim"
      onClick={(e) => {
        if (e.target === e.currentTarget) close();
      }}
    >
      <div className="lg lg-modal sev2-palette" role="document">
        <input
          ref={inputRef}
          role="combobox"
          aria-expanded="true"
          aria-controls="sev2-palette-list"
          aria-autocomplete="list"
          aria-activedescendant={filtered[activeIndex] ? `cmd-${filtered[activeIndex].id}` : undefined}
          className="lgi sev2-palette-input"
          placeholder="Search commands…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={onKeyDown}
          spellCheck={false}
          autoComplete="off"
        />
        <ul
          id="sev2-palette-list"
          role="listbox"
          aria-label="Commands"
          className="sev2-palette-list"
        >
          {filtered.length === 0 ? (
            <li className="sev2-palette-empty" role="presentation">
              No command matches &quot;{query}&quot;.
            </li>
          ) : (
            filtered.map((cmd, i) => (
              <li
                key={cmd.id}
                id={`cmd-${cmd.id}`}
                role="option"
                aria-selected={i === activeIndex}
                className={`sev2-palette-row ${i === activeIndex ? "sev2-palette-row--active" : ""}`}
                onMouseEnter={() => setActiveIndex(i)}
                onClick={() => runCommand(cmd)}
              >
                <span className="sev2-palette-cat">{cmd.category}</span>
                <span className="sev2-palette-label">{cmd.label}</span>
                {cmd.hint && <kbd className="sev2-palette-kbd">{cmd.hint}</kbd>}
              </li>
            ))
          )}
        </ul>
      </div>
    </div>
  );
}
