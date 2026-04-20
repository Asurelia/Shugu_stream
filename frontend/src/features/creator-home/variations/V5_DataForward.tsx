/**
 * V5 — Data-Forward Studio. Metric tiles, live viewer pulse, dashboard-like.
 */
import { useEffect, useMemo, useState } from "react";
import {
  COPY, Logo, LiveDot, AvatarFrame, ReactionLayer, ReactionBar,
  ChatPanel, SubGoalCard,
  useLiveChat, useSubGoal, useViewers, useUptime, useReactions,
  type Tone, type AccentKey,
} from "../shared";

export default function V5_DataForward({ tone }: { tone: Tone }) {
  const t = COPY[tone];
  const { messages, sendUser, deleteMsg } = useLiveChat();
  const { current, target } = useSubGoal();
  const viewers = useViewers();
  const uptime = useUptime();
  const { items: reactions, add: addReaction } = useReactions();

  const points = useMemo(() => {
    const arr: number[] = [];
    let v = 0.5;
    for (let i = 0; i < 60; i++) {
      v += (Math.random() - 0.5) * 0.08;
      v = Math.max(0.25, Math.min(0.95, v));
      arr.push(v);
    }
    return arr;
  }, []);
  const [pulse, setPulse] = useState<number[]>(points);
  useEffect(() => {
    const id = setInterval(() => {
      setPulse((prev) => {
        const next = prev[prev.length - 1] + (Math.random() - 0.5) * 0.08;
        return [...prev.slice(1), Math.max(0.25, Math.min(0.95, next))];
      });
    }, 1500);
    return () => clearInterval(id);
  }, []);

  const w = 100, h = 34;
  const pathD = pulse.map((p, i) => `${i === 0 ? "M" : "L"} ${(i / (pulse.length - 1)) * w},${h - p * h}`).join(" ");
  const areaD = pathD + ` L ${w},${h} L 0,${h} Z`;

  return (
    <div style={{
      position: "relative", width: "100%", height: "100%",
      padding: "1.25rem 1.5rem",
      display: "grid",
      gridTemplateColumns: "1fr 340px",
      gridTemplateRows: "auto 1fr",
      gap: "1.25rem", zIndex: 1,
    }}>
      <div style={{ gridColumn: "1 / -1", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 20 }}>
          <Logo tone={tone} size={22} />
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <LiveDot />
            <span className="font-mono" style={{ fontSize: "0.72rem", letterSpacing: "0.14em" }}>{t.liveTag}</span>
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <button className="btn-ghost" style={{ fontSize: "0.78rem" }}>{t.follow}</button>
          <button className="btn-primary" style={{ fontSize: "0.78rem" }}>{t.subscribe}</button>
        </div>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 14, minWidth: 0 }}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12 }}>
          <MetricTile label={t.viewersLabel} value={viewers.toLocaleString()} trend="+4.8%" accent="primary" />
          <MetricTile label="chat / min" value="47" trend="+12%" accent="tertiary" />
          <MetricTile label={t.uptime} value={uptime} mono accent="secondary" />
          <MetricTile label="bitrate" value="8500" unit="kbps" accent="primary" />
        </div>

        <div style={{ position: "relative", flex: 1, borderRadius: "var(--r-2xl)", overflow: "hidden", minHeight: 0 }}>
          <AvatarFrame aspectRatio="auto" style={{ height: "100%" }} label="VTUBER FEED" />
          <div style={{
            position: "absolute", left: 0, right: 0, bottom: 0,
            background: "linear-gradient(180deg, transparent, rgba(8,8,16,0.7) 40%, rgba(8,8,16,0.92))",
            padding: "3rem 1.5rem 1.25rem",
          }}>
            <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", gap: 20 }}>
              <div style={{ flex: 1 }}>
                <div className="label" style={{ color: "var(--primary)" }}>● {t.category}</div>
                <h2 className="font-display" style={{
                  margin: "4px 0 0",
                  fontSize: "clamp(1.3rem, 2.4vw, 2rem)",
                  fontWeight: 700, lineHeight: 1.1,
                  letterSpacing: "-0.025em", maxWidth: "22ch",
                }}>{t.streamTitle}</h2>
              </div>
              <div style={{ width: 260 }}>
                <div className="label" style={{ fontSize: "0.62rem", marginBottom: 4 }}>viewer pulse · 60s</div>
                <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" style={{ width: "100%", height: 44, display: "block" }}>
                  <defs>
                    <linearGradient id="v5grad" x1="0" x2="0" y1="0" y2="1">
                      <stop offset="0%" stopColor="#e08efe" stopOpacity="0.35" />
                      <stop offset="100%" stopColor="#e08efe" stopOpacity="0" />
                    </linearGradient>
                    <linearGradient id="v5stroke" x1="0" x2="1" y1="0" y2="0">
                      <stop offset="0%" stopColor="#fd6c9c" />
                      <stop offset="100%" stopColor="#81ecff" />
                    </linearGradient>
                  </defs>
                  <path d={areaD} fill="url(#v5grad)" />
                  <path d={pathD} fill="none" stroke="url(#v5stroke)" strokeWidth="1.2" />
                </svg>
              </div>
            </div>
          </div>
          <ReactionLayer items={reactions} />
          <div style={{ position: "absolute", right: 16, top: 16 }}>
            <ReactionBar onReact={(e) => addReaction(e, 60 + Math.random() * 30)} />
          </div>
        </div>

        <SubGoalCard tone={tone} current={current} target={target} />
      </div>

      <aside className="glass" style={{
        borderRadius: "var(--r-xl)", overflow: "hidden",
        display: "flex", flexDirection: "column",
        boxShadow: "inset 0 0 0 1px rgba(71,71,84,0.18)",
        minHeight: 0,
      }}>
        <ChatPanel tone={tone} messages={messages} onSend={sendUser} onDelete={deleteMsg} compact />
      </aside>
    </div>
  );
}

function MetricTile({
  label, value, trend, unit, accent = "primary", mono,
}: { label: string; value: string; trend?: string; unit?: string; accent?: AccentKey; mono?: boolean }) {
  const color = `var(--${accent})`;
  return (
    <div className="glass" style={{
      padding: "0.85rem 1rem", borderRadius: "var(--r-lg)",
      boxShadow: `inset 0 0 0 1px ${color}22`,
      display: "flex", flexDirection: "column", gap: 4,
    }}>
      <div className="label" style={{ fontSize: "0.62rem" }}>{label}</div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
        <span style={{
          fontFamily: mono ? "var(--font-mono)" : "var(--font-display)",
          fontSize: "1.3rem", fontWeight: 700, letterSpacing: "-0.02em", color,
        }}>{value}</span>
        {unit && (
          <span className="font-mono" style={{ fontSize: "0.7rem", color: "var(--on-surface-muted)" }}>{unit}</span>
        )}
      </div>
      {trend && <div className="font-mono" style={{ fontSize: "0.65rem", color: "var(--success)" }}>{trend}</div>}
    </div>
  );
}
