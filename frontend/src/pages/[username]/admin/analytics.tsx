import { Meta } from "@/components/meta";
import { AdminShell } from "@/components/admin/AdminShell";
import {
  GlassSection,
  GlassRow,
  GlassPill,
  GlassTabs,
  GlassButton,
} from "@/features/liquid-glass/primitives";
import { MetricTile, BarList, Sparkline, Heatmap } from "@/features/liquid-glass/dataviz";
import { useState } from "react";

/**
 * `/[username]/admin/analytics` — Harmonized Stream Pulse.
 *
 * Dashboard data-viz Liquid Glass. Tout est en mock — on pose la structure
 * (tuiles headline + viewer curve + top sources + heatmap activité + top
 * chats) pour que le câblage data soit trivial plus tard : chaque bloc
 * accepte son payload en props.
 */

const CURVES = {
  "7d":  [120, 180, 150, 260, 220, 310, 290, 380, 420, 360, 480, 540, 610, 580],
  "30d": Array.from({ length: 30 }, (_, i) => 200 + Math.round(Math.sin(i / 3) * 120 + i * 6)),
  "90d": Array.from({ length: 90 }, (_, i) => 150 + Math.round(Math.cos(i / 7) * 180 + i * 3)),
};

const HEATMAP: number[][] = Array.from({ length: 7 }, (_, d) =>
  Array.from({ length: 24 }, (_, h) => {
    const base = h >= 18 && h <= 23 ? 80 : h >= 12 && h <= 17 ? 40 : 10;
    const weekend = d >= 5 ? 1.4 : 1;
    return Math.round((base + Math.random() * 40) * weekend);
  })
);

export default function AnalyticsPage() {
  const [range, setRange] = useState<"7d" | "30d" | "90d">("7d");
  const curve = CURVES[range];

  return (
    <>
      <Meta />
      <AdminShell
        active="analytics"
        title="Harmonized Stream Pulse"
        subtitle="Métriques de stream et pouls de ta communauté."
        headerRight={
          <GlassTabs
            aria-label="Plage de temps"
            value={range}
            onChange={(v) => setRange(v as typeof range)}
            tabs={[
              { value: "7d", label: "7 j" },
              { value: "30d", label: "30 j" },
              { value: "90d", label: "90 j" },
            ]}
          />
        }
      >
        <div className="grid grid-cols-1 lg:grid-cols-[1fr_320px] gap-5">
          <section className="flex flex-col gap-5">
            {/* Headline tiles */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <MetricTile label="Viewers peak" value="12 482" delta="18%"  spark={curve} />
              <MetricTile label="Watch time"   value="428 h"  delta="9%"   spark={curve} color="#81ecff" />
              <MetricTile label="Followers"    value="+312"   delta="24%"  spark={curve} color="#fd6c9c" />
              <MetricTile label="Revenue"      value="€1,842" delta="-4%"  spark={curve} color="#ffcf6b" />
            </div>

            {/* Viewer curve */}
            <GlassSection
              title="Courbe viewers"
              subtitle={`Concurrents par heure — ${range === "7d" ? "7 derniers jours" : range === "30d" ? "30 derniers jours" : "90 derniers jours"}.`}
              right={<GlassPill tone="primary" dot>live</GlassPill>}
            >
              <div className="flex items-end gap-4 mt-1">
                <div className="flex-1">
                  <Sparkline data={curve} width={720} height={140} color="#e08efe" strokeWidth={2} />
                </div>
              </div>
              <div className="flex items-center justify-between mt-3 font-mono text-[11px] text-shugu-cream-dim">
                <span>début</span>
                <span>pic · {Math.max(...curve).toLocaleString("fr-FR")}</span>
                <span>maintenant</span>
              </div>
            </GlassSection>

            {/* Traffic sources + activity heatmap */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <GlassSection title="Sources de trafic" subtitle="D'où viennent tes viewers.">
                <BarList
                  rows={[
                    { label: "Direct",    value: 4820 },
                    { label: "Twitter/X", value: 2140 },
                    { label: "Discord",   value: 1580 },
                    { label: "Search",    value:  920 },
                    { label: "Referral",  value:  410 },
                  ]}
                />
              </GlassSection>
              <GlassSection title="Activité hebdomadaire" subtitle="Heure × jour — évènements chat.">
                <Heatmap data={HEATMAP} color="#e08efe" />
              </GlassSection>
            </div>

            {/* Top content */}
            <GlassSection title="Meilleurs streams" subtitle="Classés par watch time cumulé.">
              {[
                { title: "Baldur's Gate 3 · Act III finale",  date: "il y a 2 j",  watch: "68 h", peak: "11,2k" },
                { title: "Chill Just Chatting · AMA",          date: "il y a 5 j",  watch: "42 h", peak: "8,4k"  },
                { title: "Marathon Souls — 8h",                 date: "il y a 8 j",  watch: "38 h", peak: "6,9k"  },
                { title: "Drawing Aura — new expressions",     date: "il y a 12 j", watch: "22 h", peak: "4,1k"  },
              ].map((s) => (
                <GlassRow
                  key={s.title}
                  label={<strong className="text-shugu-cream">{s.title}</strong>}
                  sub={s.date}
                  value={<span className="font-mono text-[12px] text-shugu-cream-dim">{s.watch} · peak {s.peak}</span>}
                  trailing={<GlassButton variant="subtle" size="sm">VOD</GlassButton>}
                />
              ))}
            </GlassSection>
          </section>

          {/* Rail droit */}
          <aside className="flex flex-col gap-4">
            <GlassSection title="Top chatters" subtitle="Derniers 7 jours.">
              <BarList
                color="#fd6c9c"
                unit=" msg"
                rows={[
                  { label: "Nebula",     value: 1420 },
                  { label: "StarDawnXO", value: 1185 },
                  { label: "Lumen",      value:  980 },
                  { label: "Stardust",   value:  760 },
                  { label: "Moonveil",   value:  512 },
                ]}
              />
            </GlassSection>

            <GlassSection title="Revenue breakdown" subtitle="Répartition en €.">
              <BarList
                color="#ffcf6b"
                unit=" €"
                rows={[
                  { label: "Subs",       value: 1120 },
                  { label: "Bits/Tips",  value:  480 },
                  { label: "Ads",        value:  142 },
                  { label: "Merch",      value:  100 },
                ]}
              />
            </GlassSection>

            <GlassSection title="Goal actuel" subtitle="250 subs pour la prochaine palier.">
              <div
                className="h-3 rounded-full overflow-hidden mt-1"
                style={{ background: "rgba(255,255,255,0.05)" }}
              >
                <div
                  style={{
                    width: "68%", height: "100%",
                    background: "linear-gradient(90deg, #e08efe, #fd6c9c)",
                    boxShadow: "0 0 12px -2px rgba(224,142,254,0.5)",
                  }}
                />
              </div>
              <div className="flex justify-between mt-2 font-mono text-[11px] text-shugu-cream-dim">
                <span>170 / 250</span>
                <span>68 %</span>
              </div>
            </GlassSection>
          </aside>
        </div>
      </AdminShell>
    </>
  );
}
