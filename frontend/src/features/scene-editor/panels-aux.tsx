/**
 * Scene Editor — panneaux auxiliaires (Assets, Timeline, Patterns, Mixer, FX,
 * Stream, Perf).
 *
 * Tous consomment les mocks de `./mock-data` et les primitives de
 * `./primitives`. Ils sont autonomes : chaque panneau gère son propre petit
 * état local (sélection, filtres, valeurs de knobs), aucun store global.
 */

// Note Phase A : le design bundle Claude Design avait oublié les imports
// `DragEvent` (type React) et `useDragDrop` dans ce fichier bien qu'ils soient
// utilisés dans `AssetsPanel`. Ajoutés pour que le port compile sans modifier
// la sémantique. Même pattern que `panels-main.tsx`.
import { useEffect, useRef, useState, type DragEvent } from "react";
import { useDragDrop } from "./dnd-context";
import {
  ColorPicker,
  Icon,
  Panel,
  PropRow,
  PropSection,
  Select,
  Slider,
  Switch,
  TBBtn,
  type IconName,
} from "./primitives";
import { type AssetKind, type AudioChannel, type AssetItem } from "./mock-data";
// Phase B : chaque panel lit sa slice depuis le store. Les fixtures MOCK_*
// restent dans `mock-data.ts` en tant qu'initial state du store, ce qui
// permet aux tests Playwright Phase A de continuer à valider le contenu
// par défaut sans toucher au store.
import {
  useSceneEditorStore,
  selectAssets,
  selectAudioChannels,
  selectPatterns,
  selectTimeline,
} from "@/stores/useSceneEditorStore";

/* ═══════════════════════════════ ASSETS ═══════════════════════════════ */

const ASSET_FILTERS: { id: AssetKind | "ALL"; label: string }[] = [
  { id: "ALL",  label: "All" },
  { id: "VRM",  label: "Avatars" },
  { id: "BG",   label: "Backgrounds" },
  { id: "PROP", label: "Props" },
  { id: "OVL",  label: "Overlays" },
  { id: "SFX",  label: "SFX" },
  { id: "BGM",  label: "Music" },
  { id: "FX",   label: "Effects" },
];

export function AssetsPanel({ onPopout }: { onPopout?: () => void }) {
  const [filter, setFilter] = useState<AssetKind | "ALL">("ALL");
  const [query, setQuery] = useState("");
  const { setPayload, toast } = useDragDrop();
  // Phase B : assets tirés du store. L'AssetItem typé est réexporté de
  // mock-data, donc l'ancienne `(typeof MOCK_ASSETS)[number]` devient
  // simplement `AssetItem`.
  const assets = useSceneEditorStore(selectAssets);

  const onAssetDragStart = (asset: AssetItem) => (e: DragEvent<HTMLDivElement>) => {
    setPayload({ kind: "asset", asset });
    e.dataTransfer.effectAllowed = "copy";
    e.dataTransfer.setData("text/plain", `shugu-asset:${asset.id}`);
    (e.currentTarget as HTMLElement).classList.add("dragging");
    toast(`Drag · ${asset.label}`);
  };
  const onAssetDragEnd = (e: DragEvent<HTMLDivElement>) => {
    setPayload(null);
    (e.currentTarget as HTMLElement).classList.remove("dragging");
  };

  const items = assets.filter(
    (a) =>
      (filter === "ALL" || a.kind === filter) &&
      (query === "" || a.label.toLowerCase().includes(query.toLowerCase())),
  );

  return (
    <Panel
      title="Assets"
      icon="folder"
      onPopout={onPopout}
      actions={
        <>
          <button className="ide-panel-btn" title="Import">
            <Icon name="plus" size={11} />
          </button>
          <button className="ide-panel-btn" title="New folder">
            <Icon name="folder" size={11} />
          </button>
        </>
      }
    >
      <div style={{ padding: "8px 10px", borderBottom: "1px solid var(--ide-divider)" }}>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            background: "rgba(0,0,0,0.35)",
            border: "1px solid var(--ide-divider)",
            borderRadius: 5,
            padding: "0 8px",
            height: 26,
          }}
        >
          <Icon name="search" size={11} />
          <input
            type="text"
            placeholder="Search assets…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            style={{
              flex: 1,
              background: "transparent",
              border: 0,
              color: "var(--ide-text)",
              fontSize: 11,
              fontFamily: "var(--ide-font-ui)",
              outline: "none",
            }}
          />
        </div>
        <div style={{ display: "flex", gap: 4, marginTop: 8, flexWrap: "wrap" }}>
          {ASSET_FILTERS.map((f) => (
            <button
              key={f.id}
              className="ide-chip"
              style={
                filter === f.id
                  ? {
                      background: "rgba(253,108,156,0.15)",
                      borderColor: "var(--ide-pink)",
                      color: "var(--ide-text)",
                    }
                  : undefined
              }
              onClick={() => setFilter(f.id)}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>
      <div className="ide-asset-grid">
        {items.map((a) => (
          <div
            key={a.id}
            className="ide-asset-card"
            draggable
            onDragStart={onAssetDragStart(a)}
            onDragEnd={onAssetDragEnd}
          >
            <div
              className="ide-asset-thumb"
              style={{
                background: `linear-gradient(135deg, ${a.color}33, ${a.color}11)`,
              }}
            >
              <div className="tag">{a.kind}</div>
              <div style={{ color: a.color, opacity: 0.8 }}>
                <Icon name={a.icon} size={28} />
              </div>
            </div>
            <div className="ide-asset-label">{a.label}</div>
          </div>
        ))}
        {items.length === 0 && (
          <div
            style={{
              gridColumn: "1 / -1",
              padding: 24,
              textAlign: "center",
              color: "var(--ide-text-weak)",
              fontSize: 11,
            }}
          >
            No assets match “{query}”.
          </div>
        )}
      </div>
    </Panel>
  );
}

/* ═══════════════════════════════ TIMELINE ═══════════════════════════════ */

export function TimelinePanel({ onPopout }: { onPopout?: () => void }) {
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(3.4);
  const rafRef = useRef<number | null>(null);
  // Phase B : timeline data lue depuis le store. Laisse la porte ouverte
  // pour qu'un pattern recording mute `timeline.tracks` / `timeline.clips`
  // en Phase E via des actions dédiées.
  const timeline = useSceneEditorStore(selectTimeline);

  useEffect(() => {
    if (!playing) return;
    let last = performance.now();
    const tick = (now: number) => {
      const dt = (now - last) / 1000;
      last = now;
      setTime((t) => (t + dt > timeline.duration ? 0 : t + dt));
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, [playing, timeline.duration]);

  const pct = (time / timeline.duration) * 100;

  return (
    <Panel
      title="Timeline"
      icon="clock"
      onPopout={onPopout}
      actions={
        <span
          style={{
            fontFamily: "var(--ide-font-mono)",
            fontSize: 10,
            color: "var(--ide-text-dim)",
            padding: "0 6px",
          }}
        >
          {time.toFixed(2)} / {timeline.duration.toFixed(2)}s
        </span>
      }
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          padding: "8px 10px",
          borderBottom: "1px solid var(--ide-divider)",
        }}
      >
        <TBBtn icon="skip" title="To start" onClick={() => setTime(0)} />
        <TBBtn
          icon={playing ? "pause" : "play"}
          active={playing}
          title={playing ? "Pause" : "Play"}
          onClick={() => setPlaying(!playing)}
        />
        <TBBtn icon="stop" title="Stop" onClick={() => { setPlaying(false); setTime(0); }} />
        <TBBtn icon="record" danger title="Record" />
        <div style={{ width: 1, background: "var(--ide-divider)", alignSelf: "stretch", margin: "0 4px" }} />
        <TBBtn label="loop" />
        <TBBtn label="snap" active />
        <div style={{ flex: 1 }} />
        <span
          style={{ fontFamily: "var(--ide-font-mono)", fontSize: 10, color: "var(--ide-text-dim)" }}
        >
          120 fps · 4/4
        </span>
      </div>

      <div className="ide-timeline">
        <div className="ide-timeline-ruler">
          {Array.from({ length: Math.ceil(timeline.duration) + 1 }, (_, i) => (
            <div
              key={i}
              className="tick"
              style={{ left: `${(i / timeline.duration) * 100}%` }}
            >
              <span>{i}s</span>
            </div>
          ))}
          <div className="ide-playhead" style={{ left: `${pct}%` }} />
        </div>

        <div className="ide-timeline-tracks">
          {timeline.tracks.map((tr) => (
            <div key={tr.name} className="ide-timeline-track">
              <div className="ide-timeline-track-head">
                <Switch checked />
                <span>{tr.name}</span>
              </div>
              <div className="ide-timeline-track-lane">
                {timeline.clips
                  .filter((c) => c.track === tr.name)
                  .map((c, i) => (
                    <div
                      key={i}
                      className="clip"
                      style={{
                        left: `${(c.start / timeline.duration) * 100}%`,
                        width: `${((c.end - c.start) / timeline.duration) * 100}%`,
                      }}
                    >
                      {c.label}
                    </div>
                  ))}
                {tr.keys.map((k, i) => (
                  <div
                    key={i}
                    className="keyframe"
                    style={{ left: `${(k / timeline.duration) * 100}%` }}
                  />
                ))}
                <div className="ide-playhead" style={{ left: `${pct}%` }} />
              </div>
            </div>
          ))}
        </div>
      </div>
    </Panel>
  );
}

/* ═══════════════════════════════ PATTERNS ═══════════════════════════════ */

const TRIGGER_ICON: Record<string, IconName> = {
  chat: "text",
  hotkey: "keyboard",
  manual: "bolt",
};

export function PatternsPanel({ onPopout }: { onPopout?: () => void }) {
  const [recording, setRecording] = useState(false);
  const [selectedId, setSelectedId] = useState("p2");
  // Phase B : la liste des patterns vient du store. Permettra d'ajouter
  // un pattern via `record_start` → `record_stop` en Phase E (AI tools)
  // sans remount complet du panel.
  const patterns = useSceneEditorStore(selectPatterns);

  return (
    <Panel
      title="Patterns · Motion library"
      icon="wand"
      onPopout={onPopout}
      actions={
        <button className="ide-panel-btn" title="New pattern">
          <Icon name="plus" size={11} />
        </button>
      }
    >
      <div
        style={{
          padding: 10,
          borderBottom: "1px solid var(--ide-divider)",
          display: "flex",
          alignItems: "center",
          gap: 8,
        }}
      >
        <div
          style={{
            flex: 1,
            display: "flex",
            flexDirection: "column",
            gap: 4,
          }}
        >
          <div style={{ fontSize: 11, fontWeight: 600, color: "var(--ide-text)" }}>
            Record new pattern
          </div>
          <div style={{ fontSize: 10, color: "var(--ide-text-dim)" }}>
            Captures pose + expression + motion timeline.
          </div>
        </div>
        <TBBtn
          icon="record"
          label={recording ? "Stop" : "Record"}
          danger={recording}
          primary={!recording}
          onClick={() => setRecording((r) => !r)}
        />
      </div>

      {recording && (
        <div
          style={{
            margin: 10,
            padding: 10,
            background: "rgba(253,108,156,0.1)",
            border: "1px solid var(--ide-hot-pink)",
            borderRadius: 6,
            display: "flex",
            alignItems: "center",
            gap: 10,
            animation: "ide-pulse 1s infinite",
          }}
        >
          <span
            style={{
              width: 8,
              height: 8,
              borderRadius: "50%",
              background: "var(--ide-hot-pink)",
              boxShadow: "0 0 10px var(--ide-hot-pink)",
            }}
          />
          <div style={{ flex: 1, fontSize: 11, color: "var(--ide-text)" }}>
            Recording · 00:03.2 · 42 keyframes
          </div>
          <span style={{ fontFamily: "var(--ide-font-mono)", fontSize: 10, color: "var(--ide-hot-pink)" }}>
            LIVE
          </span>
        </div>
      )}

      <div style={{ padding: "4px 6px" }}>
        {patterns.map((p) => (
          <div
            key={p.id}
            onClick={() => setSelectedId(p.id)}
            style={{
              padding: "8px 10px",
              margin: "2px 0",
              borderRadius: 5,
              display: "flex",
              alignItems: "center",
              gap: 10,
              background: selectedId === p.id ? "rgba(224,142,254,0.12)" : "transparent",
              border: selectedId === p.id ? "1px solid var(--ide-mauve)" : "1px solid transparent",
              cursor: "pointer",
            }}
          >
            <button
              className="ide-panel-btn"
              style={{
                width: 24,
                height: 24,
                background: "rgba(127,227,176,0.12)",
                color: "var(--ide-green)",
              }}
              title="Play"
            >
              <Icon name="play" size={11} />
            </button>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 11, fontWeight: 500, color: "var(--ide-text)" }}>
                {p.name}
              </div>
              <div
                style={{
                  fontSize: 10,
                  color: "var(--ide-text-dim)",
                  fontFamily: "var(--ide-font-mono)",
                  display: "flex",
                  alignItems: "center",
                  gap: 6,
                }}
              >
                <Icon name={TRIGGER_ICON[p.triggerKind]} size={9} />
                {p.trigger} · {p.duration} · {p.actions} actions
              </div>
            </div>
            <button className="ide-panel-btn" title="Edit">
              <Icon name="wrench" size={10} />
            </button>
          </div>
        ))}
      </div>
    </Panel>
  );
}

/* ═══════════════════════════════ MIXER ═══════════════════════════════ */

function Meter({ level, peak }: { level: number; peak: number }) {
  const bars = 12;
  const lit = Math.round(level * bars);
  const peakBar = Math.min(bars - 1, Math.round(peak * bars));
  return (
    <div className="ide-meter">
      {Array.from({ length: bars }, (_, i) => {
        const on = i < lit;
        const isPeak = i === peakBar;
        const col =
          i < 8 ? "var(--ide-green)" : i < 10 ? "var(--ide-amber)" : "var(--ide-hot-pink)";
        return (
          <div
            key={i}
            className={`seg ${on ? "on" : ""}`}
            style={{
              background: on ? col : "rgba(255,255,255,0.06)",
              opacity: isPeak ? 1 : on ? 0.9 : 1,
              boxShadow: on ? `0 0 4px ${col}` : "none",
            }}
          />
        );
      })}
    </div>
  );
}

function ChannelStrip({ ch }: { ch: AudioChannel }) {
  const [level, setLevel] = useState(ch.level);
  const [muted, setMuted] = useState(ch.muted);
  const [solo, setSolo] = useState(ch.solo);
  const [meter, setMeter] = useState(level);
  const [peak, setPeak] = useState(level);

  useEffect(() => {
    const id = window.setInterval(() => {
      const next = muted ? 0 : Math.max(0, Math.min(1, level + (Math.random() - 0.5) * 0.3));
      setMeter(next);
      setPeak((p) => Math.max(next, p * 0.95));
    }, 120);
    return () => window.clearInterval(id);
  }, [level, muted]);

  return (
    <div className="ide-channel">
      <div className="ide-channel-name">{ch.name}</div>
      <div style={{ display: "flex", gap: 3, justifyContent: "center" }}>
        <button
          className="ide-panel-btn"
          style={{
            width: 22,
            height: 18,
            fontSize: 9,
            background: muted ? "rgba(253,108,156,0.2)" : undefined,
            color: muted ? "var(--ide-hot-pink)" : undefined,
          }}
          onClick={() => setMuted(!muted)}
        >
          M
        </button>
        <button
          className="ide-panel-btn"
          style={{
            width: 22,
            height: 18,
            fontSize: 9,
            background: solo ? "rgba(255,207,107,0.2)" : undefined,
            color: solo ? "var(--ide-amber)" : undefined,
          }}
          onClick={() => setSolo(!solo)}
        >
          S
        </button>
      </div>
      <div className="ide-fader">
        <input
          type="range"
          min={0}
          max={1}
          step={0.01}
          value={level}
          onChange={(e) => setLevel(+e.target.value)}
        />
      </div>
      <Meter level={meter} peak={peak} />
      <div
        style={{
          textAlign: "center",
          fontFamily: "var(--ide-font-mono)",
          fontSize: 9,
          color: "var(--ide-text-dim)",
        }}
      >
        {(level * 100).toFixed(0)} · {(meter * 6 - 6).toFixed(1)}dB
      </div>
    </div>
  );
}

export function MixerPanel({ onPopout }: { onPopout?: () => void }) {
  const master: AudioChannel = { id: "master", name: "Master", level: 0.8, muted: false, solo: false };
  // Phase B : channels audio tirés du store. Les Phase E (AI tools) pourront
  // ajouter `mixer.set_level(channel, value)` comme tool callable par Hermes.
  const channels = useSceneEditorStore(selectAudioChannels);

  return (
    <Panel
      title="Mixer · Audio"
      icon="sliders"
      onPopout={onPopout}
      actions={
        <span
          style={{
            fontFamily: "var(--ide-font-mono)",
            fontSize: 10,
            color: "var(--ide-green)",
            padding: "0 6px",
          }}
        >
          -6.3 dB
        </span>
      }
    >
      <div
        style={{
          display: "flex",
          padding: 10,
          gap: 2,
          overflowX: "auto",
          height: "100%",
          alignItems: "stretch",
        }}
      >
        {channels.map((c) => (
          <ChannelStrip key={c.id} ch={c} />
        ))}
        <div
          style={{
            width: 1,
            background: "var(--ide-divider)",
            margin: "0 6px",
            alignSelf: "stretch",
          }}
        />
        <ChannelStrip ch={master} />
      </div>
    </Panel>
  );
}

/* ═══════════════════════════════ FX ═══════════════════════════════ */

export function FXPanel({ onPopout }: { onPopout?: () => void }) {
  return (
    <Panel title="Effects · Post-process" icon="fx" onPopout={onPopout}>
      <PropSection title="Bloom">
        <PropRow label="Enabled"><Switch checked /></PropRow>
        <PropRow label="Intensity"><Slider value={0.65} /></PropRow>
        <PropRow label="Threshold"><Slider value={0.85} /></PropRow>
        <PropRow label="Radius"><Slider value={0.4} /></PropRow>
      </PropSection>
      <PropSection title="Color grading">
        <PropRow label="Exposure"><Slider value={0.6} min={-1} max={1} step={0.01} /></PropRow>
        <PropRow label="Contrast"><Slider value={0.55} /></PropRow>
        <PropRow label="Saturation"><Slider value={0.7} /></PropRow>
        <PropRow label="Temp"><Slider value={0.45} /></PropRow>
        <PropRow label="Tint col"><ColorPicker value="#fd6c9c" /></PropRow>
      </PropSection>
      <PropSection title="Film grain" defaultOpen={false}>
        <PropRow label="Enabled"><Switch checked /></PropRow>
        <PropRow label="Amount"><Slider value={0.15} /></PropRow>
      </PropSection>
      <PropSection title="Vignette" defaultOpen={false}>
        <PropRow label="Amount"><Slider value={0.3} /></PropRow>
        <PropRow label="Smoothness"><Slider value={0.5} /></PropRow>
      </PropSection>
      <PropSection title="Chromatic ab" defaultOpen={false}>
        <PropRow label="Enabled"><Switch checked={false} /></PropRow>
        <PropRow label="Amount"><Slider value={0.1} /></PropRow>
      </PropSection>
    </Panel>
  );
}

/* ═══════════════════════════════ STREAM ═══════════════════════════════ */

export function StreamPanel({ onPopout }: { onPopout?: () => void }) {
  const [live, setLive] = useState(true);
  return (
    <Panel title="Stream controls" icon="broadcast" onPopout={onPopout}>
      <div
        style={{
          padding: 14,
          borderBottom: "1px solid var(--ide-divider)",
          display: "flex",
          flexDirection: "column",
          gap: 10,
          alignItems: "center",
        }}
      >
        <button
          onClick={() => setLive(!live)}
          className="ide-tb-btn"
          style={{
            width: "100%",
            height: 44,
            fontSize: 13,
            fontWeight: 700,
            letterSpacing: "0.1em",
            fontFamily: "var(--ide-font-display)",
            background: live
              ? "linear-gradient(135deg, var(--ide-hot-pink), var(--ide-mauve))"
              : "rgba(127,227,176,0.2)",
            color: live ? "#fff" : "var(--ide-green)",
            border: live ? "none" : "1px solid var(--ide-green)",
            boxShadow: live ? "0 4px 24px rgba(253,108,156,0.45)" : "none",
          }}
        >
          {live ? "● LIVE · END STREAM" : "GO LIVE"}
        </button>
        {live && (
          <div style={{ display: "flex", gap: 14, fontFamily: "var(--ide-font-mono)", fontSize: 10 }}>
            <span style={{ color: "var(--ide-hot-pink)" }}>00:42:18</span>
            <span style={{ color: "var(--ide-text-dim)" }}>·</span>
            <span style={{ color: "var(--ide-cyan)" }}>1,247 viewers</span>
            <span style={{ color: "var(--ide-text-dim)" }}>·</span>
            <span style={{ color: "var(--ide-green)" }}>6432 kbps</span>
          </div>
        )}
      </div>
      <PropSection title="Active scene">
        <PropRow label="Scene">
          <Select value="Main · Talk" options={["Starting Soon", "Main · Talk", "Gaming", "BRB", "Ending"]} />
        </PropRow>
        <PropRow label="Transition">
          <Select value="Fade" options={["Cut", "Fade", "Slide", "Zoom", "Glitch"]} />
        </PropRow>
        <PropRow label="Duration"><Slider value={0.4} format={(v) => `${(v * 2).toFixed(1)}s`} /></PropRow>
      </PropSection>
      <PropSection title="Output" defaultOpen={false}>
        <PropRow label="Resolution"><Select value="1080p60" options={["720p30", "720p60", "1080p30", "1080p60", "1440p60"]} /></PropRow>
        <PropRow label="Bitrate"><Slider value={6500} min={2000} max={12000} step={100} format={(v) => `${v.toFixed(0)} kbps`} /></PropRow>
        <PropRow label="Encoder"><Select value="NVENC H.264" options={["NVENC H.264", "NVENC HEVC", "x264", "AMF"]} /></PropRow>
      </PropSection>
    </Panel>
  );
}

/* ═══════════════════════════════ PERF ═══════════════════════════════ */

export function PerfPanel({ onPopout }: { onPopout?: () => void }) {
  const [fpsData, setFpsData] = useState(() =>
    Array.from({ length: 40 }, () => 58 + Math.random() * 4),
  );
  const [cpu, setCpu] = useState(42);
  const [gpu, setGpu] = useState(68);
  const [ram, setRam] = useState(5.2);
  const [vram, setVram] = useState(3.8);

  useEffect(() => {
    const id = window.setInterval(() => {
      setFpsData((d) => [...d.slice(1), Math.max(45, Math.min(60, d[d.length - 1] + (Math.random() - 0.5) * 2))]);
      setCpu((v) => Math.max(20, Math.min(80, v + (Math.random() - 0.5) * 6)));
      setGpu((v) => Math.max(40, Math.min(95, v + (Math.random() - 0.5) * 5)));
      setRam((v) => Math.max(3, Math.min(8, v + (Math.random() - 0.5) * 0.2)));
      setVram((v) => Math.max(2, Math.min(6, v + (Math.random() - 0.5) * 0.15)));
    }, 800);
    return () => window.clearInterval(id);
  }, []);

  const fpsAvg = fpsData.reduce((a, b) => a + b, 0) / fpsData.length;

  return (
    <Panel title="Performance" icon="chart" onPopout={onPopout}>
      <div style={{ padding: 14 }}>
        <div
          style={{
            display: "flex",
            alignItems: "baseline",
            gap: 8,
            marginBottom: 6,
          }}
        >
          <span
            style={{
              fontFamily: "var(--ide-font-display)",
              fontSize: 32,
              fontWeight: 700,
              color: "var(--ide-green)",
            }}
          >
            {fpsAvg.toFixed(0)}
          </span>
          <span style={{ fontSize: 11, color: "var(--ide-text-dim)" }}>fps · avg</span>
        </div>
        <svg width="100%" height="48" viewBox="0 0 200 48" preserveAspectRatio="none">
          <defs>
            <linearGradient id="perfFill" x1="0" x2="0" y1="0" y2="1">
              <stop offset="0%" stopColor="var(--ide-green)" stopOpacity="0.5" />
              <stop offset="100%" stopColor="var(--ide-green)" stopOpacity="0" />
            </linearGradient>
          </defs>
          <polyline
            fill="url(#perfFill)"
            stroke="none"
            points={`0,48 ${fpsData
              .map((v, i) => `${(i / (fpsData.length - 1)) * 200},${48 - ((v - 40) / 25) * 48}`)
              .join(" ")} 200,48`}
          />
          <polyline
            fill="none"
            stroke="var(--ide-green)"
            strokeWidth="1.2"
            points={fpsData
              .map((v, i) => `${(i / (fpsData.length - 1)) * 200},${48 - ((v - 40) / 25) * 48}`)
              .join(" ")}
          />
        </svg>
      </div>

      <PropSection title="Resources">
        <PropRow label="CPU"><Slider value={cpu} min={0} max={100} format={(v) => `${v.toFixed(0)}%`} /></PropRow>
        <PropRow label="GPU"><Slider value={gpu} min={0} max={100} format={(v) => `${v.toFixed(0)}%`} /></PropRow>
        <PropRow label="RAM"><Slider value={ram} min={0} max={16} step={0.1} format={(v) => `${v.toFixed(1)} GB`} /></PropRow>
        <PropRow label="VRAM"><Slider value={vram} min={0} max={8} step={0.1} format={(v) => `${v.toFixed(1)} GB`} /></PropRow>
      </PropSection>

      <PropSection title="Network" defaultOpen={false}>
        <PropRow label="Up"><Slider value={6432} min={0} max={10000} format={(v) => `${v.toFixed(0)} kbps`} /></PropRow>
        <PropRow label="Dropped"><Slider value={0.2} min={0} max={5} step={0.01} format={(v) => `${v.toFixed(2)}%`} /></PropRow>
        <PropRow label="Latency"><Slider value={42} min={0} max={200} format={(v) => `${v.toFixed(0)}ms`} /></PropRow>
      </PropSection>
    </Panel>
  );
}
