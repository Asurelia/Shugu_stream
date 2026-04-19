/**
 * Sub Goal card — port direct du mockup Stitch (coin bas-gauche).
 *
 *   ┌─ + ──────────────── + ─┐
 *   │ SUB GOAL    1,452/1,500│
 *   │ Horror Game Unlocked   │
 *   │ ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓░░  │   ← gradient purple→pink, glow
 *   └────────────────────────┘
 */

type Props = {
  eyebrow?: string;
  title?: string;
  current?: number;
  target?: number;
};

export function SubGoalBar({
  eyebrow = "Sub Goal",
  title = "Horror Game Stream Unlocked",
  current = 1452,
  target = 1500,
}: Props) {
  const pct = Math.min(100, Math.max(0, (current / target) * 100));

  return (
    <div className="hidden md:block fixed left-8 bottom-12 z-20">
      <div className="glass-panel p-6 w-80">
        <div className="flex justify-between items-end mb-3">
          <div className="min-w-0 pr-3">
            <p className="text-[10px] uppercase tracking-widest text-gray-400 font-bold">
              {eyebrow}
            </p>
            <p className="text-sm font-semibold text-white truncate">
              {title}
            </p>
          </div>
          <p className="text-xs text-celestial-purple font-bold shrink-0">
            {current.toLocaleString("en-US")} / {target.toLocaleString("en-US")}
          </p>
        </div>
        <div className="w-full bg-white/10 h-2.5 rounded-full overflow-hidden">
          <div
            className="bg-gradient-to-r from-celestial-purple to-celestial-pink h-full rounded-full"
            style={{
              width: `${pct}%`,
              boxShadow: "0 0 10px rgba(181, 133, 255, 0.5)",
            }}
          />
        </div>
      </div>
    </div>
  );
}
