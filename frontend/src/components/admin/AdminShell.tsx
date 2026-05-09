"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { fetchAuthStatus, logout } from "@/services/shuguClient";

/**
 * Shell des pages `/[username]/admin/*` — iOS 26 Liquid Glass rail.
 *
 * Sidebar "always 224px" plus lisible que la version hover-only : le HUD
 * viewer a déjà une densité forte, en admin on veut du calme + des labels
 * toujours visibles. Responsivé <md : bascule en barre horizontale scrollable.
 *
 * Guard : si l'utilisateur n'est pas connecté OU que son username ne matche
 * pas `/[username]/admin/*`, redirect vers `/login`.
 */

type Section =
  | "overview"
  | "creator-home"
  | "scene-editor"
  | "analytics"
  | "community"
  | "assets"
  | "schedule"
  | "moderation"
  | "users"
  | "observatory"
  | "observatory-missions"
  | "observatory-mesh";

type SidebarItem = { section: Section; label: string; path: string; icon: string };

const SIDEBAR: SidebarItem[] = [
  { section: "overview",     label: "Live Control",  path: "",               icon: "◉" },
  { section: "scene-editor", label: "Scene Editor",  path: "/scene-editor-v2",  icon: "◈" },
  { section: "observatory",  label: "Observatory",   path: "/observatory",   icon: "⌬" },
  { section: "observatory-mesh",     label: "Mesh",     path: "/observatory/mesh",     icon: "⊛" },
  { section: "observatory-missions", label: "Missions", path: "/observatory/missions", icon: "▦" },
  { section: "analytics",    label: "Analytics",     path: "/analytics",     icon: "∿" },
  { section: "community",    label: "Community",     path: "/community",     icon: "✦" },
  { section: "assets",       label: "Assets",        path: "/assets",        icon: "◇" },
  { section: "schedule",     label: "Schedule",      path: "/schedule",      icon: "◷" },
  { section: "moderation",   label: "Moderation",    path: "/moderation",    icon: "⊘" },
  { section: "users",        label: "Utilisateurs",  path: "/users",         icon: "◆" },
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
  // App Router : `useParams()` replaces `router.query` for dynamic segments.
  // `params.username` may be `string | string[] | undefined` depending on the
  // route shape — flatten to a single string here.
  const params = useParams<{ username?: string | string[] }>();
  const rawUsername = params?.username;
  const urlUsername = Array.isArray(rawUsername) ? rawUsername[0] : rawUsername;
  const [operator, setOperator] = useState<{ username: string; is_operator: boolean } | null>(null);
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
    // S1 fix: members who now get a 200 from /auth/me must not reach admin pages.
    if (!operator.is_operator) { router.replace("/"); return; }
    if (!urlUsername) return;
    if (operator.username.toLowerCase() !== urlUsername.toLowerCase()) {
      router.replace(`/${encodeURIComponent(operator.username)}/admin`);
    }
  }, [authChecked, operator, urlUsername, router]);

  const handleLogout = async () => { await logout(); router.push("/"); };

  const base = operator ? `/${encodeURIComponent(operator.username)}/admin` : "";
  const accountHref = operator ? `/${encodeURIComponent(operator.username)}/account` : "/login";

  return (
    <div className="lg-page font-quicksand">
      {/* Sidebar rail ----------------------------------------------- */}
      <aside
        className="lg-rail fixed left-0 top-0 z-30 hidden md:flex flex-col w-[224px]"
        style={{ height: "100vh" }}
      >
        {/* Logo + identité */}
        <div className="px-4 pt-5 pb-4 flex items-center gap-3 shrink-0">
          <div
            className="w-10 h-10 rounded-xl flex items-center justify-center shrink-0"
            style={{
              background: "linear-gradient(135deg, #e08efe 0%, #fd6c9c 100%)",
              boxShadow: "0 10px 24px -10px rgba(224,142,254,0.6), inset 0 1px 0 rgba(255,255,255,0.3)",
            }}
          >
            <span className="text-white text-lg font-bold">✦</span>
          </div>
          <div className="min-w-0">
            <div className="font-comfortaa font-bold text-shugu-cream text-sm tracking-tight truncate">
              {operator?.username ?? "—"}
            </div>
            <div className="font-mono text-[10px] text-shugu-cream-dim tracking-[0.18em] uppercase">
              Celestial Veil
            </div>
          </div>
        </div>

        {/* Nav */}
        <nav className="flex-1 px-3 py-2 flex flex-col gap-1 overflow-y-auto">
          <div className="px-3 pb-1 text-[10px] uppercase tracking-[0.18em] text-shugu-cream-dim font-mono">
            Dashboard
          </div>
          {SIDEBAR.map((item) => {
            const href = `${base}${item.path}`;
            const isActive = item.section === active;
            return (
              <Link
                key={item.section}
                href={base ? href : "#"}
                aria-disabled={!base}
                aria-current={isActive ? "page" : undefined}
                className={[
                  "flex items-center gap-3 px-3 py-2.5 rounded-xl transition-all text-[13px]",
                  isActive
                    ? "text-white"
                    : "text-shugu-cream-dim hover:text-shugu-cream hover:bg-white/[0.04]",
                ].join(" ")}
                style={isActive ? {
                  background: "linear-gradient(135deg, rgba(224,142,254,0.18) 0%, rgba(253,108,156,0.14) 100%)",
                  boxShadow: "inset 0 0 0 1px rgba(224,142,254,0.3), 0 0 18px -4px rgba(224,142,254,0.25)",
                } : undefined}
              >
                <span className="text-base shrink-0 w-5 text-center">{item.icon}</span>
                <span className="font-semibold whitespace-nowrap">{item.label}</span>
              </Link>
            );
          })}

          <div className="px-3 pt-4 pb-1 text-[10px] uppercase tracking-[0.18em] text-shugu-cream-dim font-mono">
            Compte
          </div>
          <Link
            href={accountHref}
            className="flex items-center gap-3 px-3 py-2.5 rounded-xl text-shugu-cream-dim hover:text-shugu-cream hover:bg-white/[0.04] transition-colors text-[13px]"
          >
            <span className="text-base shrink-0 w-5 text-center">☼</span>
            <span className="font-semibold">Paramètres</span>
          </Link>
          <Link
            href="/"
            className="flex items-center gap-3 px-3 py-2.5 rounded-xl text-shugu-cream-dim hover:text-shugu-cream hover:bg-white/[0.04] transition-colors text-[13px]"
          >
            <span className="text-base shrink-0 w-5 text-center">⎋</span>
            <span className="font-semibold">Retour au live</span>
          </Link>
        </nav>

        {/* Footer — Start Stream + Logout */}
        <div className="px-3 pt-2 pb-4 shrink-0 border-t border-white/5">
          <Link
            href="/"
            className="lgb lgb-primary lgb-md lgb-block mb-2"
            style={{ textDecoration: "none" }}
          >
            <span>●</span>
            <span>Start Stream</span>
          </Link>
          <button
            onClick={handleLogout}
            className="lgb lgb-subtle lgb-sm lgb-block"
          >
            <span>⏻</span><span>Déconnexion</span>
          </button>
        </div>
      </aside>

      {/* Mobile top rail -------------------------------------------- */}
      <nav
        className="md:hidden fixed top-0 left-0 right-0 z-30 flex items-center gap-2 overflow-x-auto px-3 py-2 lg-rail"
        style={{ borderRight: "0", borderBottom: "1px solid rgba(255,255,255,0.06)" }}
      >
        {SIDEBAR.map((item) => {
          const href = `${base}${item.path}`;
          const isActive = item.section === active;
          return (
            <Link
              key={item.section}
              href={base ? href : "#"}
              className={[
                "shrink-0 px-3 py-1.5 rounded-full text-[11px] font-semibold whitespace-nowrap transition-colors",
                isActive
                  ? "text-white bg-[linear-gradient(135deg,#e08efe,#d180ef)]"
                  : "text-shugu-cream-dim border border-white/10",
              ].join(" ")}
            >
              <span className="mr-1">{item.icon}</span>{item.label}
            </Link>
          );
        })}
      </nav>

      {/* Main -------------------------------------------------------- */}
      <main className="md:pl-[224px] pt-[44px] md:pt-0 min-h-screen">
        <div className="px-5 sm:px-8 pt-4 pb-8 sm:pt-5 max-w-[1400px] mx-auto">
          <div className="flex items-end justify-between mb-4 gap-4 flex-wrap">
            <div className="min-w-0">
              <h1 className="font-comfortaa font-bold text-2xl sm:text-3xl text-shugu-cream tracking-tight">
                {title}
              </h1>
              {subtitle && (
                <p className="text-shugu-cream-dim text-sm mt-1">
                  {subtitle}
                </p>
              )}
            </div>
            {headerRight && <div className="shrink-0">{headerRight}</div>}
          </div>

          {authChecked && operator ? children : (
            <div className="text-shugu-cream-dim text-sm py-20 text-center">
              chargement…
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
