import { useState } from "react";
import { Meta } from "@/components/meta";
import {
  GlassCard,
  GlassButton,
  GlassInput,
  GlassPill,
  GlassTabs,
  GlassModal,
  GlassSwitch,
  GlassSection,
  GlassRow,
} from "@/features/liquid-glass/primitives";
import { Sparkline, BarList, Heatmap, MetricTile } from "@/features/liquid-glass/dataviz";

/**
 * `/lg-preview` — smoke test visuel des primitives Liquid Glass.
 *
 * Sans runner de tests configuré, cette page vérifie que l'import + le
 * rendu de chaque primitive fonctionnent. Ouvre-la en dev : si tout
 * s'affiche et que la console reste vide, la lib est saine.
 */

const CURVE = [30, 42, 38, 55, 49, 70, 62, 88, 80, 95, 110, 120, 135, 128];
const HEAT = Array.from({ length: 7 }, (_, d) =>
  Array.from({ length: 24 }, (_, h) => Math.round(Math.abs(Math.sin((d + 1) * (h + 1) / 7)) * 100))
);

export default function LGPreview() {
  const [tab, setTab] = useState("a");
  const [modal, setModal] = useState(false);
  const [swA, setSwA] = useState(true);
  const [swB, setSwB] = useState(false);

  return (
    <>
      <Meta />
      <div className="lg-page font-quicksand min-h-screen px-6 py-10">
        <header className="mb-8 max-w-5xl mx-auto">
          <div className="font-mono text-[10px] uppercase tracking-[0.22em] text-shugu-cream-dim">
            liquid-glass · smoke test
          </div>
          <h1 className="font-comfortaa font-bold text-2xl text-shugu-cream mt-1">
            Primitives preview
          </h1>
          <p className="text-[12px] text-shugu-cream-dim mt-1">
            Ouvre la console : si elle est vide et que tout est visible, la lib est saine.
          </p>
        </header>

        <main className="grid grid-cols-1 lg:grid-cols-2 gap-5 max-w-5xl mx-auto">
          {/* Buttons */}
          <GlassSection title="GlassButton" subtitle="variants · sizes · block">
            <div className="flex flex-wrap gap-2">
              <GlassButton variant="primary"   size="sm">primary sm</GlassButton>
              <GlassButton variant="primary"   size="md">primary md</GlassButton>
              <GlassButton variant="primary"   size="lg">primary lg</GlassButton>
            </div>
            <div className="flex flex-wrap gap-2 mt-2">
              <GlassButton variant="secondary">secondary</GlassButton>
              <GlassButton variant="ghost">ghost</GlassButton>
              <GlassButton variant="subtle">subtle</GlassButton>
              <GlassButton variant="danger">danger</GlassButton>
            </div>
            <div className="mt-3">
              <GlassButton variant="primary" block>block button ♡</GlassButton>
            </div>
            <div className="mt-3">
              <GlassButton variant="primary" disabled>disabled</GlassButton>
            </div>
          </GlassSection>

          {/* Inputs */}
          <GlassSection title="GlassInput" subtitle="label · hint · error · pill">
            <div className="flex flex-col gap-3">
              <GlassInput label="Nom" placeholder="Nebula" />
              <GlassInput label="Email" type="email" hint="On ne le montre jamais en public." />
              <GlassInput label="Mot de passe" type="password" error="Minimum 8 caractères." />
              <GlassInput placeholder="Rechercher…" pill />
            </div>
          </GlassSection>

          {/* Pills */}
          <GlassSection title="GlassPill" subtitle="tones · dot">
            <div className="flex flex-wrap gap-2">
              <GlassPill>default</GlassPill>
              <GlassPill tone="primary" dot>primary</GlassPill>
              <GlassPill tone="secondary">secondary</GlassPill>
              <GlassPill tone="tertiary">tertiary</GlassPill>
              <GlassPill tone="warn">warn</GlassPill>
              <GlassPill tone="danger" dot>danger</GlassPill>
            </div>
          </GlassSection>

          {/* Tabs */}
          <GlassSection title="GlassTabs" subtitle="contrôlé">
            <GlassTabs
              aria-label="Preview tabs"
              value={tab}
              onChange={setTab}
              tabs={[
                { value: "a", label: "Overview" },
                { value: "b", label: "Activité" },
                { value: "c", label: "Paramètres" },
              ]}
            />
            <div className="text-[12px] text-shugu-cream-dim mt-3 font-mono">value = {tab}</div>
          </GlassSection>

          {/* Switches + Rows */}
          <GlassSection title="GlassSwitch & GlassRow" subtitle="dans une section">
            <GlassRow
              label="Notifications chat"
              sub="mentions + raids"
              trailing={<GlassSwitch checked={swA} onChange={setSwA} aria-label="Notifs chat" />}
            />
            <GlassRow
              label="Notifications VOD"
              sub="render terminé"
              trailing={<GlassSwitch checked={swB} onChange={setSwB} aria-label="Notifs VOD" />}
            />
            <GlassRow
              label="Live depuis"
              sub="Nebula · 2h 14min"
              value={<span className="font-mono text-[12px] text-shugu-cream-dim">2h14</span>}
              trailing={<GlassPill tone="primary" dot>live</GlassPill>}
            />
          </GlassSection>

          {/* Modal */}
          <GlassSection title="GlassModal" subtitle="scrim blur · close on scrim">
            <GlassButton variant="primary" onClick={() => setModal(true)}>ouvrir la modale</GlassButton>
            <GlassModal
              open={modal}
              onClose={() => setModal(false)}
              title="Confirmer l'action"
              footer={
                <>
                  <GlassButton variant="ghost" onClick={() => setModal(false)}>annuler</GlassButton>
                  <GlassButton variant="primary" onClick={() => setModal(false)}>confirmer</GlassButton>
                </>
              }
            >
              <p className="text-[13px] text-shugu-cream-dim">
                Tu peux fermer via le scrim, la touche Escape, ou les boutons.
              </p>
            </GlassModal>
          </GlassSection>

          {/* Card raw */}
          <GlassCard>
            <div className="font-mono text-[10px] uppercase tracking-[0.22em] text-shugu-cream-dim">
              GlassCard
            </div>
            <h3 className="font-comfortaa font-bold text-lg text-shugu-cream mt-1">
              Carte brute
            </h3>
            <p className="text-[12px] text-shugu-cream-dim mt-1">
              Le conteneur de base. Toutes les sections utilisent ça en dessous.
            </p>
          </GlassCard>

          {/* Dataviz */}
          <GlassSection title="Dataviz" subtitle="Sparkline · BarList · Heatmap · MetricTile">
            <div className="grid grid-cols-2 gap-2 mb-3">
              <MetricTile label="Viewers"   value="1 284" delta="+12%" spark={CURVE} />
              <MetricTile label="Watchtime" value="42 h"  delta="-3%"  spark={CURVE} color="#81ecff" />
            </div>
            <div className="mb-3">
              <Sparkline data={CURVE} width={320} height={56} color="#fd6c9c" />
            </div>
            <div className="mb-3">
              <BarList
                rows={[
                  { label: "Twitter",  value: 420 },
                  { label: "Discord",  value: 280 },
                  { label: "Direct",   value: 180 },
                ]}
              />
            </div>
            <Heatmap data={HEAT} />
          </GlassSection>
        </main>
      </div>
    </>
  );
}
