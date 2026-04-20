import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState } from "react";
import { getItems } from "@/features/registry/registryClient";

/**
 * Floating emoji pop-ups layered over the VRM canvas.
 *
 * Exposes an imperative `push(name)` via the ref — the page-level WS handler
 * calls it whenever a `[emote=...]` tag arrives, bypassing React state churn
 * in the parent. Particles self-expire after 2.2s.
 *
 * Phase 1 — data-fication : la map `EMOJI` commence avec le fallback statique
 * et est enrichie au boot par fetch `/api/registry/emote`. Ajouter un emote
 * via l'admin UI le rend disponible sans redéploiement.
 */

export type EmoteName = string;

export type EmoteOverlayHandle = {
  push: (name: string) => void;
};

// Fallback statique — conservé pour zéro régression si le registry est
// injoignable. Enrichi au boot depuis `/api/registry/emote`.
const FALLBACK_EMOJI: Record<string, string> = {
  heart: "♡",
  sparkle: "✨",
  sweat: "💦",
  question: "❓",
  laugh: "😆",
  fire: "🔥",
};

const FALLBACK_HUE: Record<string, string> = {
  heart: "#FF6B8A",
  fire: "#FF8A3D",
  sparkle: "#FFF2A8",
};

const EMOJI: Record<string, string> = { ...FALLBACK_EMOJI };
const HUE: Record<string, string> = { ...FALLBACK_HUE };

/** À appeler au boot (et à chaque WS `registry.invalidated`). */
export async function refreshEmotes(): Promise<void> {
  const items = await getItems("emote");
  for (const k of Object.keys(EMOJI)) delete EMOJI[k];
  for (const k of Object.keys(HUE)) delete HUE[k];
  Object.assign(EMOJI, FALLBACK_EMOJI);
  Object.assign(HUE, FALLBACK_HUE);
  for (const item of items) {
    if (!item.is_active) continue;
    const payload = item.payload as { emoji?: string; hue?: string };
    if (typeof payload.emoji === "string") EMOJI[item.slug] = payload.emoji;
    if (typeof payload.hue === "string") HUE[item.slug] = payload.hue;
  }
}

type Particle = {
  id: number;
  emoji: string;
  leftPct: number;
  topPct: number;
  drift: number;
  hue: string;
  createdAt: number;
};

const MAX_PARTICLES = 5;
const LIFESPAN_MS = 2200;

export const EmoteOverlay = forwardRef<EmoteOverlayHandle>((_, ref) => {
  const [particles, setParticles] = useState<Particle[]>([]);
  const idRef = useRef(0);

  const push = useCallback((name: string) => {
    const slug = name.toLowerCase();
    const emoji = EMOJI[slug];
    if (!emoji) return;
    const id = ++idRef.current;
    const leftPct = 30 + Math.random() * 40;
    const topPct = 35 + Math.random() * 25;
    const drift = (Math.random() - 0.5) * 40;
    const hue = HUE[slug] ?? "#FFD1DC";
    setParticles((prev) => {
      const next = [...prev, { id, emoji, leftPct, topPct, drift, hue, createdAt: performance.now() }];
      return next.slice(-MAX_PARTICLES);
    });
    window.setTimeout(() => {
      setParticles((prev) => prev.filter((p) => p.id !== id));
    }, LIFESPAN_MS);
  }, []);

  useImperativeHandle(ref, () => ({ push }), [push]);

  // Safety: clear stuck particles if tab was backgrounded for long.
  useEffect(() => {
    const handle = window.setInterval(() => {
      const now = performance.now();
      setParticles((prev) => prev.filter((p) => now - p.createdAt < LIFESPAN_MS + 500));
    }, 3000);
    return () => window.clearInterval(handle);
  }, []);

  return (
    <div className="fixed inset-0 z-10 pointer-events-none overflow-hidden">
      {particles.map((p) => (
        <span
          key={p.id}
          className="absolute select-none emote-pop"
          style={{
            left: `${p.leftPct}%`,
            top: `${p.topPct}%`,
            color: p.hue,
            // @ts-ignore — custom property forwarded to the keyframe
            "--emote-drift": `${p.drift}px`,
            textShadow: `0 0 18px ${p.hue}`,
            fontSize: "2.75rem",
            lineHeight: 1,
          }}
        >
          {p.emoji}
        </span>
      ))}
    </div>
  );
});

EmoteOverlay.displayName = "EmoteOverlay";
