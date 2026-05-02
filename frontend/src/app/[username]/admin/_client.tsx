"use client";

/**
 * `/[username]/admin` — Live Control Center client island.
 *
 * Migration Pages Router → App Router (Sprint E5) :
 *   - `<Meta>` supprimé → métadonnées déclarées côté Server (`page.tsx`).
 *   - `AdminShell` migré vers `next/navigation` — fonctionne uniquement sous App Router.
 */
import Link from "next/link";

import { AdminShell } from "@/components/admin/AdminShell";
import {
  GlassCard,
  GlassSection,
  GlassRow,
  GlassButton,
  GlassPill,
} from "@/features/liquid-glass/primitives";

export function AdminHomeClient() {
  return (
    <AdminShell
      active="overview"
      title="Live Control"
      subtitle="Maîtrise ton flux, ton environnement et tes overrides."
      headerRight={
        <div className="flex items-center gap-2">
          <Link href="/" className="lgb lgb-ghost lgb-md" style={{ textDecoration: "none" }}>
            ⎋ Retour au live
          </Link>
          <button type="button" className="lgb lgb-secondary lgb-md">
            ● Start Stream
          </button>
        </div>
      }
    >
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_320px] gap-5">
        <section className="flex flex-col gap-5">
          <HeroPreview />
          <StatsGrid />
          <QuickActions />
          <RecentEvents />
        </section>
        <aside className="flex flex-col gap-4">
          <ChatPreview />
          <TopSupporters />
        </aside>
      </div>
    </AdminShell>
  );
}

function HeroPreview() {
  return (
    <GlassCard padded={false} className="overflow-hidden">
      <div
        className="relative aspect-video w-full flex items-center justify-center"
        style={{
          background:
            "radial-gradient(ellipse at 30% 40%, rgba(224,142,254,0.30) 0%, transparent 55%)," +
            "radial-gradient(ellipse at 80% 80%, rgba(129,236,255,0.18) 0%, transparent 55%)," +
            "linear-gradient(135deg, #15152a 0%, #0d0d18 100%)",
        }}
      >
        <div className="text-center">
          <div className="text-5xl mb-2 text-shugu-pink-glow inline-block">✦</div>
          <div className="font-mono text-shugu-cream-dim text-[11px] tracking-[0.22em] uppercase">
            Preview offline · connecte OBS
          </div>
        </div>

        {/* Overlays top-left */}
        <div className="absolute top-3 left-3 flex items-center gap-2">
          <GlassPill tone="secondary" dot>LIVE</GlassPill>
          <GlassPill>◇ 9 065</GlassPill>
          <GlassPill>00:41:22</GlassPill>
        </div>

        {/* Bitrate overlay */}
        <div className="absolute bottom-3 right-3 lg lg-pill px-3 py-1.5">
          <div className="lg-content">
            <div className="font-mono text-[9px] text-shugu-cream-dim uppercase tracking-wide">Bitrate</div>
            <div className="font-comfortaa font-bold text-shugu-tertiary text-[13px]">6,500 kbps</div>
          </div>
        </div>

        {/* Action bar */}
        <div className="absolute bottom-3 left-3 flex items-center gap-2">
          <button className="lgb lgb-ghost lgb-sm" type="button">Scène</button>
          <button className="lgb lgb-ghost lgb-sm" type="button">Caméra</button>
          <button className="lgb lgb-ghost lgb-sm" type="button">Micro</button>
        </div>
      </div>
    </GlassCard>
  );
}

function StatsGrid() {
  const stats = [
    { label: "FPS",       value: "60.0",  sub: "stable",  tone: "primary"   as const },
    { label: "Bitrate",   value: "6 500", sub: "kbps",    tone: "tertiary"  as const },
    { label: "CPU",       value: "14 %",  sub: "idle",    tone: "primary"   as const },
    { label: "Dropped",   value: "0.0",   sub: "frames",  tone: "secondary" as const },
  ];
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
      {stats.map((s) => (
        <GlassCard key={s.label} padded={false}>
          <div className="px-4 py-3">
            <div className="font-mono text-[10px] text-shugu-cream-dim uppercase tracking-[0.16em]">
              {s.label}
            </div>
            <div
              className="font-comfortaa font-bold text-xl mt-1"
              style={{
                color:
                  s.tone === "primary"   ? "#e08efe"
                : s.tone === "tertiary"  ? "#81ecff"
                :                          "#fd6c9c",
              }}
            >
              {s.value}
            </div>
            <div className="font-mono text-[10px] text-shugu-cream-dim">{s.sub}</div>
          </div>
        </GlassCard>
      ))}
    </div>
  );
}

function QuickActions() {
  const actions = [
    { label: "Gameplay",      icon: "▶" },
    { label: "Just Chatting", icon: "✦" },
    { label: "BRB",           icon: "◷" },
    { label: "Aura (VRM)",    icon: "◇" },
  ];
  return (
    <GlassSection
      title="Scènes rapides"
      subtitle="Bascule en un tap — raccourci global G+1…4."
    >
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2.5 mt-1">
        {actions.map((a) => (
          <button
            key={a.label}
            type="button"
            className="lgb lgb-ghost lgb-lg flex-col !rounded-2xl !h-[88px]"
          >
            <span className="text-xl">{a.icon}</span>
            <span className="text-[11px] font-semibold">{a.label}</span>
          </button>
        ))}
      </div>
    </GlassSection>
  );
}

function RecentEvents() {
  const events = [
    { who: "Nebula",     what: "s&apos;est abonné · tier 2", t: "il y a 12s",  tone: "primary"   as const },
    { who: "StarDawnXO", what: "a envoyé 500 bits",           t: "il y a 34s",  tone: "warn"      as const },
    { who: "Stardust",   what: "a suivi la chaîne",           t: "il y a 1m",   tone: "tertiary"  as const },
    { who: "Lumen",      what: "raid · 128 viewers",          t: "il y a 2m",   tone: "secondary" as const },
  ];
  return (
    <GlassSection title="Événements récents" subtitle="Flux temps-réel des interactions viewer.">
      {events.map((e, i) => (
        <GlassRow
          key={i}
          label={<span><strong className="text-shugu-cream">{e.who}</strong> <span className="text-shugu-cream-dim">{e.what}</span></span>}
          sub={e.t}
          trailing={<GlassPill tone={e.tone}>{e.tone === "warn" ? "bits" : e.tone === "primary" ? "sub" : e.tone === "secondary" ? "raid" : "follow"}</GlassPill>}
        />
      ))}
    </GlassSection>
  );
}

function ChatPreview() {
  return (
    <GlassSection
      title="Live Chat"
      subtitle="Aperçu — rail complet sur /"
      right={<span className="w-1.5 h-1.5 rounded-full bg-shugu-pink animate-pulse" aria-hidden />}
    >
      <div className="space-y-2 mt-1">
        {[
          { u: "Nebula",     m: "The lighting 👏"       },
          { u: "StarDawnXO", m: "amazing stream"        },
          { u: "Stardust",   m: "What game is this?"    },
          { u: "Lumen",      m: "this UI is so clean 🔮" },
        ].map((x, i) => (
          <div
            key={i}
            className="rounded-xl px-3 py-2"
            style={{
              background: "rgba(20,20,32,0.55)",
              boxShadow: "inset 0 0 0 1px rgba(255,255,255,0.04)",
            }}
          >
            <span className="text-[11px] font-semibold text-shugu-pink-soft mr-2">{x.u}</span>
            <span className="text-[12px] text-shugu-cream">{x.m}</span>
          </div>
        ))}
      </div>
      <Link
        href="/"
        className="block mt-4 text-center text-[11px] text-shugu-cream-dim hover:text-shugu-pink-soft transition-colors"
      >
        → ouvrir le chat complet
      </Link>
    </GlassSection>
  );
}

function TopSupporters() {
  return (
    <GlassSection title="Top supporters" subtitle="Ce mois-ci.">
      {[
        { name: "Nebula",     v: "12 400 ★", tier: "admin" as const },
        { name: "StarDawnXO", v: "8 100 ★",  tier: "vip"   as const },
        { name: "Lumen",      v: "5 060 ★",  tier: null },
      ].map((s, i) => (
        <GlassRow
          key={s.name}
          label={<span className="flex items-center gap-2">
            <span className="text-shugu-cream-dim font-mono text-[11px] w-4">{i + 1}</span>
            <strong className="text-shugu-cream">{s.name}</strong>
            {s.tier === "admin" && <GlassPill tone="warn" dot>admin</GlassPill>}
            {s.tier === "vip"   && <GlassPill tone="primary" dot>vip</GlassPill>}
          </span>}
          value={<span className="font-mono text-shugu-pink-soft">{s.v}</span>}
        />
      ))}
      <div className="mt-3">
        <GlassButton variant="ghost" size="sm" block>
          voir tous les supporters →
        </GlassButton>
      </div>
    </GlassSection>
  );
}
