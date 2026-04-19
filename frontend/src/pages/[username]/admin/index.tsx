import Link from "next/link";
import { Meta } from "@/components/meta";
import { AdminShell } from "@/components/admin/AdminShell";

/**
 * `/[username]/admin` — accueil dashboard (mockup
 * `tableau_de_bord_streamer_celestial_veil`).
 *
 * Layout :
 *  - Hero : preview stream + badges LIVE/viewers/uptime + bouton "Start Stream"
 *  - Grille : bitrate / dropped / CPU / FPS (sparkline mock)
 *  - Quick Actions : Gameplay / Just Chatting / Off / Aura (VRM)
 *  - Rail droit : Live Chat mini (preview — le vrai rail est sur `/`)
 *
 * Le contenu est statique/mock pour poser le layout. Les hooks temps-réel
 * (shuguClient, viewer count, stats) seront branchés dans une passe ultérieure.
 */
export default function AdminHome() {
  return (
    <>
      <Meta />
      <AdminShell
        active="overview"
        title="Live Control"
        subtitle="Maîtrise ton flux, ton environnement et tes overrides."
        headerRight={
          <div className="flex items-center gap-2">
            <Link
              href="/"
              className="veil-glass px-4 py-2 rounded-xl veil-body text-[12px] text-veil-on-surface hover:text-veil-primary transition-colors"
            >
              ⎋ Retour au live
            </Link>
            <button className="veil-gradient-primary text-white px-5 py-2 rounded-xl veil-headline text-[12px] tracking-wide veil-halo-pink hover:scale-[1.02] transition-transform">
              ● Start Stream
            </button>
          </div>
        }
      >
        <div className="grid grid-cols-1 lg:grid-cols-[1fr_320px] gap-5">
          {/* Colonne principale ------------------------------------- */}
          <section className="flex flex-col gap-5">
            <HeroPreview />
            <StatsGrid />
            <QuickActions />
          </section>

          {/* Rail droit : chat preview ----------------------------- */}
          <aside className="flex flex-col gap-4">
            <ChatPreview />
          </aside>
        </div>
      </AdminShell>
    </>
  );
}

function Card({
  children,
  style,
  className = "",
}: {
  children: React.ReactNode;
  style?: React.CSSProperties;
  className?: string;
}) {
  return (
    <div
      className={`rounded-2xl ${className}`}
      style={{
        background: "linear-gradient(180deg, rgba(30,30,45,0.85) 0%, rgba(26,26,40,0.95) 100%)",
        boxShadow: "inset 0 0 0 1px rgba(255,255,255,0.04), 0 14px 40px rgba(224,142,254,0.08)",
        ...style,
      }}
    >
      {children}
    </div>
  );
}

function HeroPreview() {
  return (
    <Card className="relative overflow-hidden">
      <div
        className="aspect-video w-full flex items-center justify-center"
        style={{
          background:
            "radial-gradient(ellipse at 30% 40%, rgba(224,142,254,0.30) 0%, transparent 55%)," +
            "radial-gradient(ellipse at 80% 80%, rgba(129,236,255,0.18) 0%, transparent 55%)," +
            "linear-gradient(135deg, #15152a 0%, #0d0d18 100%)",
        }}
      >
        <div className="text-center">
          <div className="text-5xl mb-2 text-veil-primary animate-veil-pulse-glow inline-block rounded-full px-2">
            ✦
          </div>
          <div className="veil-headline text-veil-on-surface-variant text-xs tracking-[0.22em] uppercase">
            Preview offline
          </div>
        </div>

        {/* Badges en haut gauche */}
        <div className="absolute top-3 left-3 flex items-center gap-2">
          <span className="veil-gradient-secondary text-white veil-body text-[10px] font-bold px-2.5 py-1 rounded-full veil-halo-pink tracking-wide">
            ● LIVE
          </span>
          <span className="veil-glass text-veil-on-surface veil-body text-[10px] font-semibold px-2.5 py-1 rounded-full">
            ◇ 9,065
          </span>
          <span className="veil-glass text-veil-on-surface-variant veil-body text-[10px] font-semibold px-2.5 py-1 rounded-full">
            00:41:22
          </span>
        </div>

        {/* Bitrate overlay bas droite */}
        <div className="absolute bottom-3 right-3 veil-glass px-3 py-1.5 rounded-lg">
          <div className="veil-body text-[9px] text-veil-on-surface-variant tracking-wide uppercase">
            Bitrate
          </div>
          <div className="veil-headline text-veil-tertiary text-[13px]">6,500 kbps</div>
        </div>
      </div>
    </Card>
  );
}

function StatsGrid() {
  const stats = [
    { label: "FPS",       value: "60.0", sub: "stable",  tint: "primary" as const },
    { label: "Bitrate",   value: "6,500", sub: "kbps",   tint: "tertiary" as const },
    { label: "CPU usage", value: "14%",   sub: "idle",   tint: "primary" as const },
    { label: "Dropped",   value: "0.0",   sub: "frames", tint: "secondary" as const },
  ];
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
      {stats.map((s) => (
        <Card key={s.label} className="px-4 py-3">
          <div className="veil-body text-[10px] text-veil-on-surface-variant uppercase tracking-[0.16em]">
            {s.label}
          </div>
          <div
            className={`veil-headline text-xl mt-1 ${
              s.tint === "primary" ? "text-veil-primary"
                : s.tint === "tertiary" ? "text-veil-tertiary"
                : "text-veil-secondary"
            }`}
          >
            {s.value}
          </div>
          <div className="veil-body text-[10px] text-veil-on-surface-variant">
            {s.sub}
          </div>
        </Card>
      ))}
    </div>
  );
}

function QuickActions() {
  const actions = [
    { label: "Gameplay",     icon: "▶" },
    { label: "Just Chatting", icon: "✦" },
    { label: "BRB",          icon: "◷" },
    { label: "Aura (VRM)",    icon: "◇" },
  ];
  return (
    <Card className="p-4">
      <div className="flex items-center justify-between mb-3">
        <div>
          <div className="veil-headline text-veil-on-surface text-[13px] tracking-wide">
            Quick Actions &amp; Scenes
          </div>
          <div className="veil-body text-[11px] text-veil-on-surface-variant">
            bascule en un tap
          </div>
        </div>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2.5">
        {actions.map((a) => (
          <button
            key={a.label}
            className="flex flex-col items-center gap-1.5 py-3 rounded-xl veil-glass text-veil-on-surface hover:text-veil-primary hover:veil-halo-pink transition-all"
          >
            <span className="text-lg">{a.icon}</span>
            <span className="veil-body text-[11px] font-semibold">{a.label}</span>
          </button>
        ))}
      </div>
    </Card>
  );
}

function ChatPreview() {
  return (
    <Card className="p-4 min-h-[300px]">
      <div className="flex items-center gap-2 mb-3">
        <span className="w-1.5 h-1.5 rounded-full bg-veil-primary animate-live-pulse" />
        <span className="veil-headline text-[11px] uppercase tracking-[0.18em] text-veil-on-surface">
          Live Chat
        </span>
      </div>
      <div className="space-y-2">
        {["Nebula — The lighting 👏", "StarDawnXO — amazing stream", "Stardust — What game is this?"].map((m, i) => (
          <div
            key={i}
            className="rounded-xl px-3 py-2"
            style={{
              background: "rgba(36,36,52,0.7)",
              boxShadow: "inset 0 0 0 1px rgba(255,255,255,0.03)",
            }}
          >
            <span className="veil-body text-veil-on-surface text-[12px]">{m}</span>
          </div>
        ))}
      </div>
      <Link
        href="/"
        className="block mt-4 text-center veil-body text-[11px] text-veil-on-surface-variant hover:text-veil-primary transition-colors"
      >
        → ouvrir le chat complet
      </Link>
    </Card>
  );
}
