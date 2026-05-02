// HermesStateWindow — renders ~/.hermes/ consciousness data in Celestial Veil style.
//
// Fetches from GET /api/hermes/state (overview) and GET /api/hermes/state/{tab}
// when the user switches tab. Polls every 3s while open to keep the display
// fresh — cheap because the backend cache is 5s so a burst of clients costs
// one disk read per 5s window.

import { useCallback, useEffect, useRef, useState } from "react";
import { useDesktopState } from "./desktopState";

type TabKey =
  | "overview"
  | "memory"
  | "skills"
  | "tools"
  | "projects"
  | "health"
  | "growth"
  | "corrections"
  | "cron";

const TABS: { key: TabKey; label: string }[] = [
  { key: "overview",    label: "Overview" },
  { key: "memory",      label: "Memory" },
  { key: "skills",      label: "Skills" },
  { key: "tools",       label: "Tools" },
  { key: "projects",    label: "Projects" },
  { key: "health",      label: "Health" },
  { key: "growth",      label: "Growth" },
  { key: "corrections", label: "Corrections" },
  { key: "cron",        label: "Cron" },
];

const POLL_MS = 3000;

export function HermesStateWindow() {
  const { state, dispatch } = useDesktopState();
  const [activeTab, setActiveTab] = useState<TabKey>(
    (state.hermesHud.tab as TabKey) || "overview",
  );
  const [data, setData] = useState<any>(null);
  const [available, setAvailable] = useState(true);
  const [loading, setLoading] = useState(true);
  const timerRef = useRef<number | null>(null);

  // When the backend broadcasts `hermes_state.window_open` with a different
  // tab, keep the local view in sync.
  /* eslint-disable react-hooks/exhaustive-deps, react-hooks/set-state-in-effect -- FIXME P3: sync state from external signal, activeTab omitted intentionally to avoid loop */
  useEffect(() => {
    if (state.hermesHud.tab && state.hermesHud.tab !== activeTab) {
      setActiveTab(state.hermesHud.tab as TabKey);
    }
  }, [state.hermesHud.tab]);
  /* eslint-enable react-hooks/exhaustive-deps, react-hooks/set-state-in-effect */

  const fetchTab = useCallback(async (tab: TabKey) => {
    try {
      const url = tab === "overview" ? "/api/hermes/state" : `/api/hermes/state/${tab}`;
      const r = await fetch(url, { credentials: "include" });
      if (!r.ok) {
        setAvailable(false);
        setLoading(false);
        return;
      }
      const body = await r.json();
      if (tab === "overview") {
        setAvailable(body.available !== false);
        setData(body);
      } else {
        setAvailable(body.available !== false);
        setData(body.data ?? {});
      }
      setLoading(false);
    } catch (err) {
      console.warn("[hermes_state] fetch failed", err);
      setAvailable(false);
      setLoading(false);
    }
  }, []);

  /* eslint-disable react-hooks/set-state-in-effect -- FIXME P6: setLoading in mount effect, timer-derived state — refactor to useReducer when adopting data lib */
  useEffect(() => {
    setLoading(true);
    void fetchTab(activeTab);
    if (timerRef.current) window.clearInterval(timerRef.current);
    timerRef.current = window.setInterval(() => {
      void fetchTab(activeTab);
    }, POLL_MS);
    return () => {
      if (timerRef.current) window.clearInterval(timerRef.current);
    };
  }, [activeTab, fetchTab]);
  /* eslint-enable react-hooks/set-state-in-effect */

  return (
    <div
      className="absolute top-4 left-4 right-4 rounded-2xl overflow-hidden shadow-[0_20px_60px_rgba(129,236,255,0.15)] flex flex-col animate-fade-up"
      style={{
        height: 360,
        zIndex: 90,
        background: "linear-gradient(180deg, rgba(30,30,45,0.88), rgba(18,18,30,0.94))",
        backdropFilter: "blur(18px)",
        border: "1px solid rgba(129,236,255,0.22)",
      }}
    >
      <header className="px-4 py-2 flex items-center justify-between shrink-0 text-xs"
        style={{ background: "linear-gradient(90deg, rgba(129,236,255,0.12), rgba(224,142,254,0.06))" }}
      >
        <span className="font-bold text-shugu-cream">
          ◈ Hermes HUD
          {!available && <span className="ml-2 text-shugu-cream-dim">(~/.hermes not found)</span>}
        </span>
        <button
          onClick={() => dispatch({ type: "hermesHud.close" })}
          className="w-6 h-6 rounded-full bg-shugu-live/60 hover:bg-shugu-live text-white text-[11px] font-bold"
        >
          ×
        </button>
      </header>

      {/* Tabs */}
      <nav className="px-3 py-1.5 flex flex-wrap gap-1 shrink-0 border-b border-white/5">
        {TABS.map((t) => {
          const active = t.key === activeTab;
          return (
            <button
              key={t.key}
              onClick={() => setActiveTab(t.key)}
              className={[
                "text-[10px] px-2.5 py-1 rounded-full font-semibold transition-all",
                active
                  ? "bg-gradient-to-r from-shugu-pink-glow to-shugu-pink text-white shadow-[0_0_10px_rgba(255,97,127,0.5)]"
                  : "text-shugu-cream-dim hover:text-shugu-cream hover:bg-white/5",
              ].join(" ")}
            >
              {t.label}
            </button>
          );
        })}
      </nav>

      <div className="flex-1 min-h-0 overflow-auto px-4 py-3 scroll-hidden">
        {loading && <LoadingShimmer />}
        {!loading && !available && <Unavailable />}
        {!loading && available && <TabBody tab={activeTab} data={data} />}
      </div>
    </div>
  );
}

function LoadingShimmer() {
  return (
    <div className="space-y-2">
      {[0, 1, 2, 3].map((i) => (
        <div
          key={i}
          className="h-8 rounded-md animate-pulse"
          style={{ background: "rgba(255,255,255,0.04)" }}
        />
      ))}
    </div>
  );
}

function Unavailable() {
  return (
    <div className="text-shugu-cream-dim text-xs italic leading-relaxed text-center py-8">
      <p>~/.hermes/ n&apos;est pas accessible sur ce serveur.</p>
      <p className="mt-2">
        Définir <code className="text-shugu-pink-glow">HERMES_HOME</code> ou installer
        <a
          href="https://github.com/joeynyc/hermes-hud"
          target="_blank"
          rel="noreferrer"
          className="ml-1 text-shugu-pink hover:text-shugu-pink-glow underline"
        >
          hermes-hud
        </a>
        .
      </p>
    </div>
  );
}

function TabBody({ tab, data }: { tab: TabKey; data: any }) {
  if (!data) return <Unavailable />;
  switch (tab) {
    case "overview":
      return <OverviewPanel data={data} />;
    case "memory":
      return <MemoryPanel data={data} />;
    case "skills":
      return <SkillsPanel data={data} />;
    case "tools":
      return <ToolsPanel data={data} />;
    case "projects":
      return <ProjectsPanel data={data} />;
    case "health":
      return <HealthPanel data={data} />;
    case "growth":
      return <GrowthPanel data={data} />;
    case "corrections":
      return <CorrectionsPanel data={data} />;
    case "cron":
      return <CronPanel data={data} />;
  }
}

function StatCard({ label, value }: { label: string; value: string | number }) {
  return (
    <div
      className="rounded-xl px-3 py-2.5"
      style={{
        background: "rgba(36,36,52,0.6)",
        border: "1px solid rgba(255,255,255,0.04)",
      }}
    >
      <div className="text-[9px] uppercase tracking-wide text-shugu-cream-dim">{label}</div>
      <div className="text-base font-bold text-shugu-cream mt-0.5">{value}</div>
    </div>
  );
}

function OverviewPanel({ data }: { data: any }) {
  return (
    <div className="grid grid-cols-2 gap-2">
      <StatCard label="memory" value={data.memory?.count ?? data.memory_files ?? 0} />
      <StatCard label="skills" value={data.skills?.count ?? data.skills_count ?? 0} />
      <StatCard label="projects" value={data.projects?.count ?? data.projects_count ?? 0} />
      <StatCard label="tool uses" value={data.tools?.counts ? sum(data.tools.counts) : (data.tools_usage_entries ?? 0)} />
      <StatCard label="corrections" value={data.corrections_entries ?? 0} />
      <StatCard label="health" value={data.has_health ? "known" : "—"} />
      <div className="col-span-2 text-[9px] text-shugu-cream-dim/60 mt-1 truncate">
        root: {data.root}
      </div>
    </div>
  );
}

function MemoryPanel({ data }: { data: any }) {
  const recent = data.recent || [];
  const sessions = data.sessions || [];
  return (
    <div className="space-y-3">
      <Section title={`Recent (${recent.length})`}>
        {recent.slice(0, 10).map((m: any, i: number) => (
          <Row key={i} primary={m.summary || m.text || JSON.stringify(m).slice(0, 120)} />
        ))}
      </Section>
      <Section title={`Sessions (${sessions.length})`}>
        {sessions.slice(0, 10).map((s: string) => (
          <Row key={s} primary={s} mono />
        ))}
      </Section>
    </div>
  );
}

function SkillsPanel({ data }: { data: any }) {
  const skills = data.skills || [];
  return (
    <div className="space-y-1.5">
      {skills.length === 0 && <Empty label="no skills yet" />}
      {skills.map((sk: any) => (
        <div
          key={sk.name}
          className="rounded-lg px-3 py-2 flex items-baseline gap-2"
          style={{ background: "rgba(224,142,254,0.06)" }}
        >
          <span className="text-[10px] font-bold text-shugu-pink-glow">⚙</span>
          <span className="font-semibold text-shugu-cream text-xs">{sk.name}</span>
          <span className="text-[10px] text-shugu-cream-dim truncate flex-1">{sk.summary}</span>
        </div>
      ))}
    </div>
  );
}

function ToolsPanel({ data }: { data: any }) {
  const counts = data.counts || {};
  const recent = data.recent || [];
  const entries = Object.entries(counts) as [string, number][];
  entries.sort((a, b) => b[1] - a[1]);
  return (
    <div className="space-y-3">
      <Section title="Usage counts (last 30)">
        {entries.slice(0, 10).map(([name, count]) => (
          <div key={name} className="flex items-center justify-between text-xs">
            <span className="text-shugu-cream font-mono text-[11px]">{name}</span>
            <span className="text-shugu-pink-glow font-bold">{count}</span>
          </div>
        ))}
        {entries.length === 0 && <Empty label="no tool usage yet" />}
      </Section>
      <Section title={`Recent entries (${recent.length})`}>
        {recent.slice(0, 8).map((e: any, i: number) => (
          <Row key={i} primary={`${e.tool || e.name || "?"}`} secondary={e.summary || e.status || ""} mono />
        ))}
      </Section>
    </div>
  );
}

function ProjectsPanel({ data }: { data: any }) {
  const projects = data.projects || [];
  return (
    <div className="space-y-1.5">
      {projects.length === 0 && <Empty label="no projects tracked" />}
      {projects.map((p: any) => (
        <Row key={p.name} primary={p.name} secondary={p.type} />
      ))}
    </div>
  );
}

function HealthPanel({ data }: { data: any }) {
  if (!data.known) return <Empty label="no health snapshot" />;
  return (
    <div className="space-y-2">
      {Object.entries(data).filter(([k]) => k !== "known").map(([k, v]) => (
        <Row key={k} primary={k} secondary={JSON.stringify(v)} mono />
      ))}
    </div>
  );
}

function GrowthPanel({ data }: { data: any }) {
  const snaps = data.snapshots || [];
  return (
    <div className="space-y-1.5">
      {snaps.length === 0 && <Empty label="no growth snapshots yet" />}
      {snaps.map((s: any) => (
        <Row
          key={s.name}
          primary={s.name}
          secondary={`${Math.round(s.size / 1024)} KB`}
          mono
        />
      ))}
    </div>
  );
}

function CorrectionsPanel({ data }: { data: any }) {
  const entries = data.entries || [];
  return (
    <div className="space-y-1">
      {entries.length === 0 && <Empty label="no corrections logged" />}
      {entries.map((e: string, i: number) => (
        <div
          key={i}
          className="text-[11px] font-mono text-shugu-cream-dim px-2 py-1 rounded"
          style={{ background: "rgba(255,97,127,0.04)" }}
        >
          {e}
        </div>
      ))}
    </div>
  );
}

function CronPanel({ data }: { data: any }) {
  const jobs = data.jobs || [];
  return (
    <div className="space-y-1.5">
      {jobs.length === 0 && <Empty label="no cron jobs" />}
      {jobs.map((j: any, i: number) => (
        <Row
          key={i}
          primary={j.name || j.id || `job ${i}`}
          secondary={j.schedule || j.cron || ""}
          mono
        />
      ))}
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-[9px] uppercase tracking-wider text-shugu-cream-dim mb-1.5">{title}</div>
      <div className="space-y-1">{children}</div>
    </div>
  );
}

function Row({ primary, secondary, mono }: { primary: string; secondary?: string; mono?: boolean }) {
  return (
    <div className="flex items-center justify-between gap-2 text-xs">
      <span className={`truncate text-shugu-cream ${mono ? "font-mono text-[11px]" : ""}`}>{primary}</span>
      {secondary && (
        <span className="shrink-0 text-shugu-cream-dim text-[10px]">{secondary}</span>
      )}
    </div>
  );
}

function Empty({ label }: { label: string }) {
  return (
    <div className="text-shugu-cream-dim text-[11px] italic text-center py-3">{label}</div>
  );
}

function sum(obj: Record<string, number>): number {
  return Object.values(obj).reduce((a, b) => a + b, 0);
}
