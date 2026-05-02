/**
 * Creator Home Shell — port de `Shugu Creator Home.html`.
 *
 * Orchestre les 6 variations, le switcher, le tweaks panel et les raccourcis
 * clavier. Le fond nébuleux `.nebula` vient de `celestial-veil-tokens.css`.
 *
 * État persisté dans `localStorage` (key `shugu-creator-home`).
 */
import { useEffect, useState } from "react";
import type { Tone } from "./shared";
import V1 from "./variations/V1_EditorialFaithful";
import V2 from "./variations/V2_MinimalSanctuary";
import V3 from "./variations/V3_ImmersiveHUD";
import V4 from "./variations/V4_SplitEditorial";
import V5 from "./variations/V5_DataForward";
import V6 from "./variations/V6_Constellation";

const VARIATIONS = [
  { n: 1, name: "Editorial Faithful",   Comp: V1 },
  { n: 2, name: "Minimal Sanctuary",    Comp: V2 },
  { n: 3, name: "Immersive HUD",        Comp: V3 },
  { n: 4, name: "Split Editorial",      Comp: V4 },
  { n: 5, name: "Data-Forward Studio",  Comp: V5 },
  { n: 6, name: "Constellation Break",  Comp: V6 },
] as const;

const DEFAULTS = { variation: 3, tone: "playful" as Tone };

type Persisted = { variation?: number; tone?: Tone };

export default function CreatorHomeShell() {
  const [variation, setVariation] = useState<number>(DEFAULTS.variation);
  const [tone, setTone] = useState<Tone>(DEFAULTS.tone);
  const [tweaksOpen, setTweaksOpen] = useState(false);
  const [hydrated, setHydrated] = useState(false);

  // Hydrate depuis localStorage au mount (client-only).
  // FIXME(react-hooks/set-state-in-effect): SSR-safe hydration pattern — lazy useState
  // is unsafe here (localStorage unavailable on server → hydration mismatch). Keep as-is.
  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    try {
      const raw = localStorage.getItem("shugu-creator-home");
      if (raw) {
        const p = JSON.parse(raw) as Persisted;
        if (p.variation && p.variation >= 1 && p.variation <= 6) setVariation(p.variation);
        if (p.tone === "professional" || p.tone === "playful") setTone(p.tone);
      }
    } catch { /* ignore */ }
    setHydrated(true);
  }, []);
  /* eslint-enable react-hooks/set-state-in-effect */

  // Persiste à chaque changement (après hydratation pour éviter d'écraser).
  useEffect(() => {
    if (!hydrated) return;
    try {
      localStorage.setItem("shugu-creator-home", JSON.stringify({ variation, tone }));
    } catch { /* ignore */ }
  }, [variation, tone, hydrated]);

  // Raccourcis clavier : 1-6 switch variation, ← → step, T toggle tone.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tgt = e.target as HTMLElement | null;
      if (tgt && (tgt.tagName === "INPUT" || tgt.tagName === "TEXTAREA")) return;
      const n = parseInt(e.key, 10);
      if (n >= 1 && n <= 6) setVariation(n);
      if (e.key === "ArrowRight") setVariation((v) => Math.min(6, v + 1));
      if (e.key === "ArrowLeft") setVariation((v) => Math.max(1, v - 1));
      if (e.key === "t" || e.key === "T") {
        setTone((t) => (t === "professional" ? "playful" : "professional"));
      }
      if (e.key === "Escape") setTweaksOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const current = VARIATIONS.find((v) => v.n === variation) ?? VARIATIONS[2];
  const ActiveVariation = current.Comp;

  return (
    <div className="creator-home-shell">
      {/* Fond nébuleux partagé */}
      <div className="nebula" />

      {/* Scène — une variation plein écran à la fois */}
      <div
        className="variation-stage"
        key={variation}
        style={{ position: "absolute", inset: "0 0 56px 0", display: "flex", flexDirection: "column" }}
      >
        <ActiveVariation tone={tone} />
      </div>

      {/* Switcher bas-centre */}
      <div className="switcher-pill">
        {VARIATIONS.map((v) => (
          <button
            key={v.n}
            className={v.n === variation ? "active" : ""}
            onClick={() => setVariation(v.n)}
            type="button"
          >
            {v.n}
            <span className="tooltip">{v.name}</span>
          </button>
        ))}
        <div className="switcher-sep" />
        <button
          className="tweaks-toggle"
          onClick={() => setTweaksOpen((o) => !o)}
          type="button"
          title="Tweaks · T"
        >
          ✦
        </button>
      </div>

      {/* Tweaks panel haut-droite */}
      {tweaksOpen && (
        <div className="tweaks open">
          <h3>
            Tweaks
            <button
              onClick={() => setTweaksOpen(false)}
              style={{
                background: "transparent", border: "none", cursor: "pointer",
                color: "var(--on-surface-muted)", padding: 0, fontSize: "0.9rem",
              }}
              type="button"
            >✕</button>
          </h3>

          <div className="tweak-row">
            <label>Copy tone</label>
            <div className="seg">
              <button
                className={tone === "professional" ? "active" : ""}
                onClick={() => setTone("professional")}
                type="button"
              >professional</button>
              <button
                className={tone === "playful" ? "active" : ""}
                onClick={() => setTone("playful")}
                type="button"
              >playful</button>
            </div>
          </div>

          <div className="tweak-row">
            <label>Variation · {current.name}</label>
            <div className="seg" style={{ flexWrap: "wrap" }}>
              {VARIATIONS.map((v) => (
                <button
                  key={v.n}
                  className={v.n === variation ? "active" : ""}
                  onClick={() => setVariation(v.n)}
                  style={{ flex: "0 0 auto", padding: "6px 10px" }}
                  type="button"
                >{v.n}</button>
              ))}
            </div>
          </div>

          <div style={{
            fontSize: "0.68rem", color: "var(--on-surface-muted)",
            lineHeight: 1.5, marginTop: 12,
            fontFamily: "var(--font-mono)", textAlign: "right",
          }}>
            ← → arrows · 1–6 · T to toggle tone
          </div>
        </div>
      )}

      {/* Aide bas-droite */}
      <div className="help-hint">
        {current.n.toString().padStart(2, "0")} · {current.name} ·{" "}
        <kbd>1</kbd>–<kbd>6</kbd> · <kbd>T</kbd>
      </div>

      {/* Styles locaux au shell — scope évite d'affecter les autres pages. */}
      <style jsx>{`
        .creator-home-shell {
          position: relative;
          width: 100%;
          height: 100vh;
          overflow: hidden;
          background: var(--surface-dim);
          color: var(--on-surface);
          font-family: var(--font-body);
        }
        .switcher-pill {
          position: fixed;
          bottom: 16px;
          left: 50%;
          transform: translateX(-50%);
          z-index: 100;
          display: flex;
          flex-direction: row;
          gap: 8px;
          padding: 8px 10px;
          background: rgba(18, 18, 30, 0.75);
          backdrop-filter: blur(20px);
          -webkit-backdrop-filter: blur(20px);
          border-radius: 999px;
          box-shadow:
            inset 0 0 0 1px rgba(224, 142, 254, 0.22),
            0 20px 40px -20px rgba(0, 0, 0, 0.6);
        }
        .switcher-pill button {
          width: 32px;
          height: 32px;
          border-radius: 50%;
          background: transparent;
          border: none;
          cursor: pointer;
          color: var(--on-surface-variant);
          font-family: var(--font-mono);
          font-size: 0.72rem;
          font-weight: 600;
          transition: all 0.2s ease;
          display: flex;
          align-items: center;
          justify-content: center;
          position: relative;
        }
        .switcher-pill button.active {
          background: linear-gradient(135deg, var(--primary), var(--primary-container));
          color: #1a0a24;
          box-shadow: 0 0 16px rgba(224, 142, 254, 0.6);
        }
        .switcher-pill button:hover:not(.active) {
          background: rgba(224, 142, 254, 0.15);
          color: var(--on-surface);
        }
        .switcher-pill .switcher-sep {
          width: 1px;
          align-self: stretch;
          background: rgba(224, 142, 254, 0.2);
          margin: 4px 2px;
        }
        .switcher-pill button .tooltip {
          position: absolute;
          bottom: calc(100% + 10px);
          left: 50%;
          transform: translateX(-50%);
          background: rgba(36, 36, 52, 0.92);
          backdrop-filter: blur(20px);
          padding: 6px 12px;
          border-radius: 6px;
          white-space: nowrap;
          font-family: var(--font-display);
          font-size: 0.72rem;
          color: var(--on-surface);
          letter-spacing: -0.01em;
          box-shadow: inset 0 0 0 1px rgba(224, 142, 254, 0.25);
          opacity: 0;
          pointer-events: none;
          transition: opacity 0.2s ease;
        }
        .switcher-pill button:hover .tooltip {
          opacity: 1;
        }
        .tweaks {
          position: fixed;
          top: 18px;
          right: 18px;
          z-index: 100;
          width: 280px;
          padding: 14px 16px 16px;
          background: rgba(18, 18, 30, 0.82);
          backdrop-filter: blur(24px);
          -webkit-backdrop-filter: blur(24px);
          border-radius: 14px;
          box-shadow:
            inset 0 0 0 1px rgba(224, 142, 254, 0.28),
            0 30px 60px -20px rgba(0, 0, 0, 0.7);
          animation: soft-scale 0.25s ease-out;
        }
        .tweaks h3 {
          margin: 0 0 10px;
          font-family: var(--font-display);
          font-size: 0.72rem;
          letter-spacing: 0.14em;
          text-transform: uppercase;
          color: var(--on-surface-variant);
          font-weight: 600;
          display: flex;
          justify-content: space-between;
          align-items: center;
        }
        .tweaks :global(.tweak-row) { margin-bottom: 14px; }
        .tweaks :global(.tweak-row:last-child) { margin-bottom: 0; }
        .tweaks :global(.tweak-row) > label {
          display: block;
          font-family: var(--font-display);
          font-size: 0.68rem;
          letter-spacing: 0.08em;
          text-transform: uppercase;
          color: var(--on-surface-muted);
          margin-bottom: 6px;
        }
        .tweaks :global(.seg) {
          display: flex;
          gap: 4px;
          padding: 3px;
          background: rgba(9, 9, 18, 0.6);
          border-radius: 999px;
          box-shadow: inset 0 0 0 1px rgba(71, 71, 84, 0.25);
        }
        .tweaks :global(.seg button) {
          flex: 1;
          padding: 6px 10px;
          background: transparent;
          border: none;
          cursor: pointer;
          color: var(--on-surface-variant);
          font-family: var(--font-display);
          font-size: 0.75rem;
          font-weight: 600;
          border-radius: 999px;
          transition: all 0.2s ease;
        }
        .tweaks :global(.seg button.active) {
          background: linear-gradient(135deg, var(--primary), var(--primary-container));
          color: #1a0a24;
        }
        .help-hint {
          position: fixed;
          bottom: 14px;
          right: 20px;
          z-index: 99;
          font-family: var(--font-mono);
          font-size: 0.66rem;
          color: var(--on-surface-muted);
          letter-spacing: 0.1em;
          pointer-events: none;
        }
        .help-hint :global(kbd) {
          display: inline-block;
          padding: 1px 5px;
          background: rgba(36, 36, 52, 0.7);
          border-radius: 4px;
          font-family: var(--font-mono);
          font-size: 0.66rem;
          color: var(--on-surface);
          box-shadow: inset 0 0 0 1px rgba(71, 71, 84, 0.4);
        }
      `}</style>
    </div>
  );
}
