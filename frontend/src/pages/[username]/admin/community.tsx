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
} from "@/features/liquid-glass/primitives";
import { BarList, MetricTile } from "@/features/liquid-glass/dataviz";

/**
 * `/[username]/admin/community` — ta communauté, vue en une page.
 *
 * Trois axes : supporters (top + nouveaux), rangs/rôles, et modération
 * rapide via recherche utilisateur. Rempli avec des données mockées —
 * structure pensée pour accueillir un data layer plus tard.
 */
export default function CommunityPage() {
  const [tab, setTab] = useState<"all" | "subs" | "vips" | "mods">("all");
  const [query, setQuery] = useState("");

  const members = MEMBERS.filter((m) => {
    if (tab === "subs" && m.role !== "sub") return false;
    if (tab === "vips" && m.role !== "vip") return false;
    if (tab === "mods" && m.role !== "mod") return false;
    if (query && !m.name.toLowerCase().includes(query.toLowerCase())) return false;
    return true;
  });

  return (
    <>
      <Meta />
      <AdminShell
        active="community"
        title="Community"
        subtitle="Tes supporters, subs et rangs — tissés au veil."
      >
        <div className="grid grid-cols-1 lg:grid-cols-[1fr_320px] gap-5">
          <section className="flex flex-col gap-5">
            {/* KPIs */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <MetricTile label="Followers"  value="28 402"  delta="+312 (7j)" color="#e08efe" />
              <MetricTile label="Subs actifs" value="1 482"   delta="+24"       color="#fd6c9c" />
              <MetricTile label="VIPs"         value="38"      delta="+2"        color="#ffcf6b" />
              <MetricTile label="Mods"         value="12"      delta="stable"    color="#81ecff" />
            </div>

            {/* Members list */}
            <GlassSection
              title="Membres"
              subtitle={`${members.length} résultats`}
              right={
                <div className="flex items-center gap-2">
                  <GlassTabs
                    aria-label="Filtre rôle"
                    value={tab}
                    onChange={(v) => setTab(v as typeof tab)}
                    tabs={[
                      { value: "all",  label: "Tous" },
                      { value: "subs", label: "Subs" },
                      { value: "vips", label: "VIPs" },
                      { value: "mods", label: "Mods" },
                    ]}
                  />
                </div>
              }
            >
              <div className="mb-3">
                <GlassInput
                  placeholder="Rechercher un membre…"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  pill
                />
              </div>
              {members.length === 0 ? (
                <div className="text-[12px] text-shugu-cream-dim py-6 text-center">
                  Aucun membre ne correspond.
                </div>
              ) : (
                members.map((m) => (
                  <GlassRow
                    key={m.name}
                    label={
                      <span className="flex items-center gap-2">
                        <strong className="text-shugu-cream">{m.name}</strong>
                        {m.role === "mod" && <GlassPill tone="tertiary" dot>mod</GlassPill>}
                        {m.role === "vip" && <GlassPill tone="primary" dot>vip</GlassPill>}
                        {m.role === "sub" && <GlassPill tone="secondary">sub · {m.tier}</GlassPill>}
                      </span>
                    }
                    sub={`rejoint ${m.joined} · ${m.messages.toLocaleString("fr-FR")} messages`}
                    value={<span className="font-mono text-[12px] text-shugu-pink-soft">{m.support} ★</span>}
                    trailing={<GlassButton variant="subtle" size="sm">…</GlassButton>}
                  />
                ))
              )}
            </GlassSection>
          </section>

          {/* Rail droit */}
          <aside className="flex flex-col gap-4">
            <GlassSection title="Nouveaux cette semaine" subtitle="12 abonnés · 4 raids">
              {NEW_MEMBERS.map((m) => (
                <GlassRow
                  key={m.name}
                  label={<strong className="text-shugu-cream">{m.name}</strong>}
                  sub={m.via}
                  trailing={<GlassPill tone="primary">{m.role}</GlassPill>}
                />
              ))}
            </GlassSection>

            <GlassSection title="Rangs custom" subtitle="Badges affichés dans le chat.">
              <BarList
                color="#e08efe"
                unit=""
                rows={[
                  { label: "Lunar",     value: 820 },
                  { label: "Stellar",   value: 412 },
                  { label: "Nebula",    value: 180 },
                  { label: "Celestial", value:  48 },
                ]}
              />
              <div className="mt-3">
                <GlassButton variant="ghost" size="sm" block>+ créer un rang</GlassButton>
              </div>
            </GlassSection>

            <GlassSection title="Goal : subs" subtitle="Objectif 1 500 subs ce mois">
              <div
                className="h-3 rounded-full overflow-hidden mt-1"
                style={{ background: "rgba(255,255,255,0.05)" }}
              >
                <div
                  style={{
                    width: "98%", height: "100%",
                    background: "linear-gradient(90deg, #fd6c9c, #e08efe)",
                    boxShadow: "0 0 12px -2px rgba(253,108,156,0.5)",
                  }}
                />
              </div>
              <div className="flex justify-between mt-2 font-mono text-[11px] text-shugu-cream-dim">
                <span>1 482 / 1 500</span>
                <span>98 %</span>
              </div>
            </GlassSection>
          </aside>
        </div>
      </AdminShell>
    </>
  );
}

type Member = {
  name: string; role: "sub" | "vip" | "mod" | null;
  tier?: 1 | 2 | 3; joined: string; messages: number; support: number;
};
const MEMBERS: Member[] = [
  { name: "Nebula",     role: "mod",  joined: "janv. 2024",   messages: 14200, support: 12400 },
  { name: "StarDawnXO", role: "vip",  joined: "mars 2024",    messages: 11850, support:  8100 },
  { name: "Lumen",      role: "vip",  joined: "avr. 2024",    messages:  9800, support:  5060 },
  { name: "Stardust",   role: "sub", tier: 3, joined: "juin 2024",   messages:  7600, support:  3240 },
  { name: "Moonveil",   role: "sub", tier: 2, joined: "juil. 2024",  messages:  5120, support:  2180 },
  { name: "Astra",      role: "sub", tier: 1, joined: "août 2024",   messages:  3080, support:  1040 },
  { name: "Eclipse",    role: "mod",  joined: "sept. 2024",   messages:  2400, support:   820 },
  { name: "Halcyon",    role: null,           joined: "oct. 2024",    messages:  1250, support:   320 },
];
const NEW_MEMBERS = [
  { name: "Celeste", via: "Twitter",  role: "follow" },
  { name: "Polaris", via: "Raid · Lumen", role: "sub" },
  { name: "Vela",    via: "Discord",   role: "follow" },
  { name: "Orion",   via: "Direct",    role: "sub" },
];
