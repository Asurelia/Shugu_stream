import { useState } from "react";
import { Meta } from "@/components/meta";
import { AdminShell } from "@/components/admin/AdminShell";
import {
  GlassSection,
  GlassRow,
  GlassPill,
  GlassButton,
  GlassInput,
  GlassTabs,
  GlassSwitch,
  GlassCard,
} from "@/features/liquid-glass/primitives";

/**
 * `/[username]/admin/scene-editor` — Scene Editor.
 *
 * Page nouvelle. Structure : colonne gauche (liste de scènes), canvas
 * central (preview), colonne droite (panel propriétés de la source
 * sélectionnée). 100 % placeholder visuel — le bind avec OBS/Hermes viendra.
 */

type Source = {
  id: string; name: string; kind: "cam" | "display" | "vrm" | "overlay" | "chat";
  visible: boolean; locked: boolean;
};

const SCENES = [
  { id: "s1", name: "Gameplay",      active: true,  sources: 5 },
  { id: "s2", name: "Just Chatting", active: false, sources: 3 },
  { id: "s3", name: "BRB",           active: false, sources: 2 },
  { id: "s4", name: "Aura (VRM)",    active: false, sources: 4 },
  { id: "s5", name: "Starting soon", active: false, sources: 3 },
];

const INITIAL_SOURCES: Source[] = [
  { id: "src1", name: "Game capture",   kind: "display", visible: true,  locked: false },
  { id: "src2", name: "Webcam (main)",  kind: "cam",     visible: true,  locked: false },
  { id: "src3", name: "Aura VRM",       kind: "vrm",     visible: false, locked: false },
  { id: "src4", name: "Overlay chat",   kind: "chat",    visible: true,  locked: true  },
  { id: "src5", name: "Alerts overlay", kind: "overlay", visible: true,  locked: false },
];

export default function SceneEditorPage() {
  const [activeScene, setActiveScene] = useState("s1");
  const [sources, setSources] = useState(INITIAL_SOURCES);
  const [selectedId, setSelectedId] = useState("src2");
  const selected = sources.find((s) => s.id === selectedId) ?? sources[0];

  const toggleVisible = (id: string) =>
    setSources(sources.map((s) => (s.id === id ? { ...s, visible: !s.visible } : s)));

  return (
    <>
      <Meta />
      <AdminShell
        active="scene-editor"
        title="Scene Editor"
        subtitle="Construis et bascule tes scènes — OBS/Hermes bridge à venir."
        headerRight={
          <div className="flex items-center gap-2">
            <GlassButton variant="ghost"     size="sm">Import OBS</GlassButton>
            <GlassButton variant="primary"   size="sm">Appliquer</GlassButton>
          </div>
        }
      >
        <div className="grid grid-cols-1 lg:grid-cols-[220px_1fr_280px] gap-5">
          {/* Scenes list */}
          <GlassSection title="Scènes" subtitle={`${SCENES.length} scènes`}>
            <div className="flex flex-col gap-1.5">
              {SCENES.map((s) => (
                <button
                  key={s.id}
                  onClick={() => setActiveScene(s.id)}
                  className={`flex items-center justify-between px-3 py-2 rounded-xl text-[13px] transition-colors ${
                    s.id === activeScene
                      ? "text-white bg-[linear-gradient(135deg,rgba(224,142,254,0.18),rgba(253,108,156,0.14))]"
                      : "text-shugu-cream-dim hover:text-shugu-cream hover:bg-white/[0.04]"
                  }`}
                  style={s.id === activeScene ? {
                    boxShadow: "inset 0 0 0 1px rgba(224,142,254,0.3), 0 0 16px -4px rgba(224,142,254,0.25)",
                  } : undefined}
                >
                  <span className="font-semibold flex items-center gap-2">
                    {s.active && <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#fd6c9c", boxShadow: "0 0 8px #fd6c9c" }} />}
                    {s.name}
                  </span>
                  <span className="font-mono text-[10px] text-shugu-cream-dim">{s.sources}</span>
                </button>
              ))}
              <GlassButton variant="ghost" size="sm" block className="mt-2">+ nouvelle scène</GlassButton>
            </div>
          </GlassSection>

          {/* Canvas */}
          <div className="flex flex-col gap-4">
            <GlassCard padded={false} className="overflow-hidden">
              <div
                className="relative aspect-video flex items-center justify-center"
                style={{
                  background:
                    "radial-gradient(ellipse at 30% 40%, rgba(224,142,254,0.30) 0%, transparent 55%)," +
                    "radial-gradient(ellipse at 80% 80%, rgba(129,236,255,0.18) 0%, transparent 55%)," +
                    "linear-gradient(135deg, #15152a 0%, #0d0d18 100%)",
                }}
              >
                {/* Mock source frames */}
                {sources.filter((s) => s.visible).map((s, i) => (
                  <div
                    key={s.id}
                    onClick={() => setSelectedId(s.id)}
                    className="absolute cursor-pointer transition-all"
                    style={{
                      width: `${30 + (i * 8) % 25}%`,
                      height: `${22 + (i * 6) % 18}%`,
                      top:    `${8 + (i * 18) % 60}%`,
                      left:   `${6 + (i * 22) % 60}%`,
                      borderRadius: 12,
                      border: s.id === selectedId
                        ? "2px solid #e08efe"
                        : "1px dashed rgba(255,255,255,0.2)",
                      background: "rgba(20,20,32,0.4)",
                      boxShadow: s.id === selectedId
                        ? "0 0 20px -4px rgba(224,142,254,0.6)"
                        : "none",
                    }}
                  >
                    <div className="text-[10px] text-shugu-cream-dim p-1.5 font-mono">{s.kind} · {s.name}</div>
                  </div>
                ))}

                <div className="absolute bottom-3 left-3 flex items-center gap-2">
                  <GlassPill tone="secondary" dot>LIVE</GlassPill>
                  <GlassPill>1920×1080 · 60fps</GlassPill>
                </div>
              </div>
            </GlassCard>

            {/* Sources list */}
            <GlassSection title="Sources" subtitle="Ordre z-index — glisse pour réordonner.">
              {sources.map((s) => (
                <GlassRow
                  key={s.id}
                  label={
                    <button
                      onClick={() => setSelectedId(s.id)}
                      className={`flex items-center gap-2 ${s.id === selectedId ? "text-shugu-pink-glow" : "text-shugu-cream"}`}
                    >
                      <span className="font-mono text-[10px] text-shugu-cream-dim w-10">{s.kind}</span>
                      <strong>{s.name}</strong>
                      {s.locked && <span className="text-[10px] text-shugu-cream-dim">🔒</span>}
                    </button>
                  }
                  trailing={
                    <GlassSwitch
                      checked={s.visible}
                      onChange={() => toggleVisible(s.id)}
                      aria-label={`Visibilité ${s.name}`}
                    />
                  }
                />
              ))}
              <div className="mt-2">
                <GlassButton variant="ghost" size="sm" block>+ ajouter une source</GlassButton>
              </div>
            </GlassSection>
          </div>

          {/* Properties panel */}
          <GlassSection title="Propriétés" subtitle={selected.name}>
            <div className="flex flex-col gap-3">
              <GlassInput label="Nom" value={selected.name} readOnly />
              <GlassInput label="Type" value={selected.kind} readOnly />

              <div className="grid grid-cols-2 gap-2">
                <GlassInput label="Position X" type="number" defaultValue={0} />
                <GlassInput label="Position Y" type="number" defaultValue={0} />
                <GlassInput label="Width"      type="number" defaultValue={960} />
                <GlassInput label="Height"     type="number" defaultValue={540} />
              </div>

              <div className="mt-1 space-y-2">
                <GlassTabs
                  aria-label="Transform"
                  value="transform"
                  onChange={() => {}}
                  tabs={[
                    { value: "transform", label: "Transform" },
                    { value: "filters",   label: "Filtres" },
                    { value: "audio",     label: "Audio" },
                  ]}
                />
              </div>

              <GlassRow
                label="Visible"
                trailing={<GlassSwitch checked={selected.visible} onChange={() => toggleVisible(selected.id)} aria-label="Visible" />}
              />
              <GlassRow
                label="Verrouillé"
                trailing={<GlassSwitch checked={selected.locked} onChange={() => {}} aria-label="Lock" />}
              />

              <GlassButton variant="danger" size="sm" block className="mt-3">
                Supprimer la source
              </GlassButton>
            </div>
          </GlassSection>
        </div>
      </AdminShell>
    </>
  );
}
