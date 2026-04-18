import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState } from "react";

/**
 * Floating emoji pop-ups layered over the VRM canvas.
 *
 * Exposes an imperative `push(name)` via the ref — the page-level WS handler
 * calls it whenever a `[emote=...]` tag arrives, bypassing React state churn
 * in the parent. Particles self-expire after 2.2s.
 */

export type EmoteName = "heart" | "sparkle" | "sweat" | "question" | "laugh" | "fire";

export type EmoteOverlayHandle = {
  push: (name: string) => void;
};

const EMOJI: Record<string, string> = {
  heart: "♡",
  sparkle: "✨",
  sweat: "💦",
  question: "❓",
  laugh: "😆",
  fire: "🔥",
};

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
    const emoji = EMOJI[name.toLowerCase()];
    if (!emoji) return;
    const id = ++idRef.current;
    const leftPct = 30 + Math.random() * 40;
    const topPct = 35 + Math.random() * 25;
    const drift = (Math.random() - 0.5) * 40;
    const hue = name === "heart"
      ? "#FF6B8A"
      : name === "fire"
      ? "#FF8A3D"
      : name === "sparkle"
      ? "#FFF2A8"
      : "#FFD1DC";
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
