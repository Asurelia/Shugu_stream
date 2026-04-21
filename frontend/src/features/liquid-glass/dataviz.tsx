/**
 * Sub-composants data-viz utilitaires pour les pages admin.
 * Zero dépendance — juste du SVG inline pour rester léger.
 */

import React from "react";

/* ─────────────── Sparkline ─────────────── */

export function Sparkline({
  data, width = 160, height = 40, color = "#e08efe", fill = true, strokeWidth = 1.75,
}: {
  data: number[]; width?: number; height?: number; color?: string;
  fill?: boolean; strokeWidth?: number;
}) {
  if (data.length < 2) return null;
  const min = Math.min(...data), max = Math.max(...data);
  const range = max - min || 1;
  const stepX = width / (data.length - 1);
  const pts = data.map((v, i) => [i * stepX, height - ((v - min) / range) * (height - 4) - 2] as [number, number]);
  const linePath = pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1)).join(" ");
  const fillPath = `${linePath} L ${width} ${height} L 0 ${height} Z`;
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden>
      <defs>
        <linearGradient id={`sp-${color.replace("#", "")}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%"  stopColor={color} stopOpacity="0.35" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      {fill && <path d={fillPath} fill={`url(#sp-${color.replace("#", "")})`} />}
      <path d={linePath} fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

/* ─────────────── Horizontal bars ─────────────── */

export function BarList({
  rows, color = "#e08efe", unit = "",
}: {
  rows: { label: string; value: number; sub?: string }[];
  color?: string;
  unit?: string;
}) {
  const max = Math.max(...rows.map((r) => r.value)) || 1;
  return (
    <div className="flex flex-col gap-2.5">
      {rows.map((r) => {
        const pct = (r.value / max) * 100;
        return (
          <div key={r.label} className="flex items-center gap-3">
            <div className="text-[12px] text-shugu-cream w-24 shrink-0 truncate">{r.label}</div>
            <div
              className="flex-1 h-2 rounded-full overflow-hidden"
              style={{ background: "rgba(255,255,255,0.05)" }}
            >
              <div
                style={{
                  width: pct + "%",
                  height: "100%",
                  background: `linear-gradient(90deg, ${color}, ${color}cc)`,
                  boxShadow: `0 0 10px -2px ${color}90`,
                  borderRadius: 999,
                }}
              />
            </div>
            <div className="font-mono text-[11px] text-shugu-cream-dim w-16 text-right tabular-nums">
              {r.value.toLocaleString("fr-FR")}{unit}
            </div>
          </div>
        );
      })}
    </div>
  );
}

/* ─────────────── Heatmap (grille activité 24×7) ─────────────── */

export function Heatmap({ data, color = "#e08efe" }: { data: number[][]; color?: string }) {
  // data[day][hour] — 7 × 24
  const max = Math.max(...data.flat()) || 1;
  return (
    <div className="overflow-x-auto">
      <table className="border-separate" style={{ borderSpacing: 3 }}>
        <tbody>
          {data.map((row, d) => (
            <tr key={d}>
              <td className="pr-2 text-[10px] text-shugu-cream-dim font-mono">
                {["L", "M", "M", "J", "V", "S", "D"][d]}
              </td>
              {row.map((v, h) => {
                const a = (v / max) * 0.9 + 0.05;
                return (
                  <td
                    key={h}
                    title={`${v} évts`}
                    style={{
                      width: 14, height: 14, borderRadius: 3,
                      background: v === 0
                        ? "rgba(255,255,255,0.03)"
                        : `${color}${Math.floor(a * 255).toString(16).padStart(2, "0")}`,
                      boxShadow: v > max * 0.7 ? `0 0 6px -1px ${color}` : "none",
                    }}
                  />
                );
              })}
            </tr>
          ))}
          <tr>
            <td />
            {Array.from({ length: 24 }, (_, h) => (
              <td key={h} className="text-[8px] text-shugu-cream-dim font-mono text-center">
                {h % 6 === 0 ? h : ""}
              </td>
            ))}
          </tr>
        </tbody>
      </table>
    </div>
  );
}

/* ─────────────── Metric tile ─────────────── */

export function MetricTile({
  label, value, delta, spark, color = "#e08efe",
}: {
  label: string; value: string; delta?: string;
  spark?: number[]; color?: string;
}) {
  const positive = delta && !delta.startsWith("-");
  return (
    <div className="lg lg-card">
      <span className="lg-specular" /><span className="lg-edge" />
      <div className="lg-content p-4">
        <div className="font-mono text-[10px] text-shugu-cream-dim uppercase tracking-[0.16em]">
          {label}
        </div>
        <div className="flex items-end justify-between mt-1">
          <div className="font-comfortaa font-bold text-xl" style={{ color }}>
            {value}
          </div>
          {delta && (
            <div
              className="font-mono text-[11px]"
              style={{ color: positive ? "#81ecff" : "#ff9fb0" }}
            >
              {positive ? "▲" : "▼"} {delta}
            </div>
          )}
        </div>
        {spark && <div className="mt-2"><Sparkline data={spark} color={color} width={220} height={36} /></div>}
      </div>
    </div>
  );
}
