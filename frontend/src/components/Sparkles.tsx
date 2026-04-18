import { useMemo } from "react";

const SPARKS = [
  { x: 6, y: 18, size: 14, delay: 0, dur: 7 },
  { x: 14, y: 62, size: 10, delay: 2.4, dur: 9 },
  { x: 22, y: 30, size: 18, delay: 4.8, dur: 8 },
  { x: 82, y: 22, size: 12, delay: 1.2, dur: 10 },
  { x: 90, y: 60, size: 16, delay: 3.6, dur: 7 },
  { x: 74, y: 80, size: 11, delay: 5.4, dur: 9 },
  { x: 34, y: 88, size: 13, delay: 0.8, dur: 8 },
  { x: 58, y: 12, size: 12, delay: 6.0, dur: 11 },
];

export function Sparkles() {
  const stars = useMemo(() => SPARKS, []);
  return (
    <div className="pointer-events-none fixed inset-0 overflow-hidden" style={{ zIndex: -5 }}>
      {stars.map((s, i) => (
        <span
          key={i}
          className="absolute text-shugu-pink-glow opacity-60 animate-sparkle-float"
          style={{
            left: `${s.x}%`,
            top: `${s.y}%`,
            fontSize: `${s.size}px`,
            animationDelay: `-${s.delay}s`,
            animationDuration: `${s.dur}s`,
            textShadow: "0 0 8px rgba(255, 143, 165, 0.6)",
          }}
        >
          ✦
        </span>
      ))}
    </div>
  );
}
