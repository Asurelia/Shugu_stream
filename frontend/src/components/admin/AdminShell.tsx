import Link from "next/link";
import { useRouter } from "next/router";
import { useEffect, useState } from "react";
import { fetchAuthStatus, logout } from "@/services/shuguClient";

/**
 * Shell des pages `/[username]/admin/*` (mockups `tableau_de_bord_*`,
 * `live_control_center`, `analytics_community`, `assets_schedule`,
 * `admin_moderation`).
 *
 * Layout :
 *  - Sidebar gauche fixe (72px → 224px au hover desktop), `surface-container-low`
 *    + glow rose diffus. Logo "Aura AI" en haut, items de section au centre,
 *    "Start Stream" en bas + helpers (Help / Logout).
 *  - Contenu : padding large, fond `surface-dim` + nébuleuse floue radiale.
 *
 * Guard : si l'utilisateur n'est pas connecté OU que son username ne matche
 * pas `/[username]/admin/*`, redirect vers `/login`. Le match est
 * case-insensitive — on ne veut pas qu'un `/Spoukie/admin` renvoie 403 juste
 * à cause de la casse.
 */

type Section =
  | "overview"
  | "creator-home"
  | "scene-editor"
  | "analytics"
  | "community"
  | "assets"
  | "schedule"
  | "moderation";

type SidebarItem = {
  section: Section;
  label: string;
  path: string;
  icon: string;
};

const SIDEBAR: SidebarItem[] = [
  { section: "overview",     label: "Live Control",  path: "",               icon: "◉" },
  { section: "creator-home", label: "Creator Home",  path: "/creator-home",  icon: "✧" },
  { section: "scene-editor", label: "Scene Editor",  path: "/scene-editor",  icon: "◈" },
  { section: "analytics",    label: "Analytics",     path: "/analytics",     icon: "∿" },
  { section: "community",    label: "Community",     path: "/community",     icon: "✦" },
  { section: "assets",       label: "Assets",        path: "/assets",        icon: "◇" },
  { section: "schedule",     label: "Schedule",      path: "/schedule",      icon: "◷" },
  { section: "moderation",   label: "Moderation",    path: "/moderation",    icon: "⊘" },
];

type Props = {
  active: Section;
  title: string;
  subtitle?: string;
  headerRight?: React.ReactNode;
  children: React.ReactNode;
};

export function AdminShell({ active, title, subtitle, headerRight, children }: Props) {
  const router = useRouter();
  const rawUsername = router.query.username;
  const urlUsername = Array.isArray(rawUsername) ? rawUsername[0] : rawUsername;
  const [operator, setOperator] = useState<{ username: string } | null>(null);
  const [authChecked, setAuthChecked] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetchAuthStatus().then((me) => {
      if (cancelled) return;
      setOperator(me);
      setAuthChecked(true);
    });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!authChecked) return;
    if (!operator) { router.replace("/login"); return; }
    if (!urlUsername) return;
    if (operator.username.toLowerCase() !== urlUsername.toLowerCase()) {
      // L'opérateur n'est pas propriétaire du dashboard demandé : on renvoie
      // vers le sien plutôt que sur une page blanche ou un 403.
      router.replace(`/${encodeURIComponent(operator.username)}/admin`);
    }
  }, [authChecked, operator, urlUsername, router]);

  const handleLogout = async () => { await logout(); router.push("/"); };

  const base = operator
    ? `/${encodeURIComponent(operator.username)}/admin`
    : "";

  return (
    <div
      className="font-quicksand min-h-screen text-veil-on-surface"
      style={{
        background:
          "radial-gradient(ellipse at 80% 10%, rgba(224,142,254,0.12) 0%, transparent 55%)," +
          "radial-gradient(ellipse at 15% 85%, rgba(129,236,255,0.08) 0%, transparent 55%)," +
          "#0d0d18",
      }}
    >
      {/* Sidebar ----------------------------------------------------- */}
      <aside
        className="fixed left-0 top-0 bottom-0 z-30 flex flex-col w-[72px] hover:w-[224px] group transition-[width] duration-200"
        style={{
          background:
            "linear-gradient(180deg, rgba(18,18,30,0.95) 0%, rgba(13,13,24,0.98) 100%)",
          backdropFilter: "blur(20px)",
          WebkitBackdropFilter: "blur(20px)",
          boxShadow: "inset -1px 0 0 0 rgba(224,142,254,0.08), 8px 0 40px rgba(0,0,0,0.25)",
        }}
      >
        {/* Logo + identité */}
        <div className="px-4 py-5 flex items-center gap-3 shrink-0">
          <div className="w-10 h-10 rounded-xl veil-gradient-primary flex items-center justify-center shrink-0 veil-halo-pink">
            <span className="text-white text-lg">✦</span>
          </div>
          <div className="min-w-0 opacity-0 group-hover:opacity-100 transition-opacity duration-200">
            <div className="veil-headline text-veil-on-surface text-sm tracking-tight truncate">
              {operator?.username ?? "—"}
            </div>
            <div className="veil-body text-[10px] text-veil-on-surface-variant tracking-[0.18em] uppercase truncate">
              Celestial Veil
            </div>
          </div>
        </div>

        {/* Nav */}
        <nav className="flex-1 px-2.5 py-2 flex flex-col gap-1 overflow-hidden">
          {SIDEBAR.map((item) => {
            const href = `${base}${item.path}`;
            const isActive = item.section === active;
            return (
              <Link
                key={item.section}
                href={base ? href : "#"}
                aria-disabled={!base}
                className={[
                  "flex items-center gap-3 px-3 py-2.5 rounded-xl transition-all",
                  isActive
                    ? "veil-gradient-primary text-white veil-halo-pink"
                    : "text-veil-on-surface-variant hover:text-veil-on-surface hover:bg-white/5",
                ].join(" ")}
              >
                <span className="text-base shrink-0 w-5 text-center">{item.icon}</span>
                <span className="veil-body text-[13px] font-semibold whitespace-nowrap opacity-0 group-hover:opacity-100 transition-opacity duration-200">
                  {item.label}
                </span>
              </Link>
            );
          })}
        </nav>

        {/* CTA Start Stream */}
        <div className="px-3 pb-3 shrink-0">
          <Link
            href="/"
            className="flex items-center justify-center gap-2 w-full py-2.5 rounded-xl veil-gradient-secondary text-white veil-halo-pink hover:scale-[1.02] transition-transform"
          >
            <span>●</span>
            <span className="veil-headline text-[12px] tracking-wide whitespace-nowrap opacity-0 group-hover:opacity-100 transition-opacity duration-200">
              Start Stream
            </span>
          </Link>
        </div>

        {/* Footer helpers */}
        <div className="px-2.5 pb-4 flex flex-col gap-1 shrink-0">
          <Link
            href="/"
            className="flex items-center gap-3 px-3 py-2 rounded-xl text-veil-on-surface-variant hover:text-veil-on-surface hover:bg-white/5 transition-colors"
          >
            <span className="text-base w-5 text-center">?</span>
            <span className="veil-body text-[12px] whitespace-nowrap opacity-0 group-hover:opacity-100 transition-opacity">
              Help
            </span>
          </Link>
          <button
            onClick={handleLogout}
            className="flex items-center gap-3 px-3 py-2 rounded-xl text-veil-on-surface-variant hover:text-veil-secondary hover:bg-white/5 transition-colors text-left"
          >
            <span className="text-base w-5 text-center">⏻</span>
            <span className="veil-body text-[12px] whitespace-nowrap opacity-0 group-hover:opacity-100 transition-opacity">
              Logout
            </span>
          </button>
        </div>
      </aside>

      {/* Main -------------------------------------------------------- */}
      <main className="pl-[72px] min-h-screen">
        <div className="px-8 py-7 max-w-[1400px] mx-auto">
          <div className="flex items-end justify-between mb-6 gap-4 flex-wrap">
            <div className="min-w-0">
              <h1 className="veil-headline text-2xl sm:text-3xl text-veil-on-surface tracking-tight">
                {title}
              </h1>
              {subtitle && (
                <p className="veil-body text-veil-on-surface-variant text-sm mt-1">
                  {subtitle}
                </p>
              )}
            </div>
            {headerRight && <div className="shrink-0">{headerRight}</div>}
          </div>

          {authChecked && operator ? children : (
            <div className="veil-body text-veil-on-surface-variant text-sm py-20 text-center">
              chargement…
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
