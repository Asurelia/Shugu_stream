/**
 * Route Next.js — `/shugu/admin/scene-composer` (legacy alias) — REDIRECT.
 *
 * Cette route static existait avant M2 (PR #26 review). Le pattern Shugu
 * pour les pages admin est `/[username]/admin/...` (cf. `scene-editor.tsx`),
 * et le Scene Composer rejoint maintenant cette convention.
 *
 * Pour ne pas casser d'éventuels bookmarks ou liens externes, on conserve
 * cette route comme **alias redirect** vers `/[username]/admin/scene-composer`
 * où `[username]` est l'opérateur authentifié.
 *
 * Stratégie :
 *   1. Server-side via `getServerSideProps` : on tente de récupérer le cookie
 *      d'auth et d'extraire le username pour redirect 308 directement (pas
 *      de flash de page côté client). Si pas de cookie → redirect vers
 *      `/login` (l'opérateur n'a rien à faire ici).
 *   2. Fallback client : au cas où le redirect SSR n'aboutit pas (ex: build
 *      static), un `useEffect` côté client appelle `fetchAuthStatus()` et
 *      redirige avec `router.replace`.
 *
 * Architecture : ce fichier ne charge PAS le `SceneComposerApp` — c'est un
 * pur dispatcher de redirect, ce qui garde la séparation propre entre
 * "route legacy" et "route officielle".
 */

import { useEffect } from "react";
import { useRouter } from "next/router";
import type { GetServerSideProps } from "next";
import { fetchAuthStatus } from "@/services/shuguClient";

// ─── Server-side redirect (idéal — pas de flash) ─────────────────────────────

export const getServerSideProps: GetServerSideProps = async (ctx) => {
  // On tente d'appeler `/auth/me` côté serveur en relayant les cookies de la
  // requête entrante. Si on a un username, on redirect 308 vers la route
  // officielle. Sinon, redirect vers /login.
  try {
    const cookie = ctx.req.headers.cookie ?? "";
    const host = ctx.req.headers.host ?? "localhost";
    const protocol = host.startsWith("localhost") ? "http" : "https";
    const resp = await fetch(`${protocol}://${host}/auth/me`, {
      headers: { cookie },
    });

    if (resp.ok) {
      const me = (await resp.json()) as { username?: string } | null;
      if (me?.username) {
        return {
          redirect: {
            destination: `/${encodeURIComponent(me.username)}/admin/scene-composer`,
            permanent: false,
          },
        };
      }
    }
  } catch {
    // Le SSR a échoué (réseau, parse) — on laisse le fallback client gérer.
  }

  // Pas d'auth ou erreur SSR : envoyer vers login.
  return {
    redirect: {
      destination: "/login",
      permanent: false,
    },
  };
};

// ─── Fallback client (jamais atteint en pratique avec getServerSideProps) ────

/**
 * Composant placeholder rendu uniquement si `getServerSideProps` n'a pas
 * pu rediriger (cas extrême — ex: hot-reload Next pendant dev). Refait
 * un check auth côté client et redirige.
 */
export default function LegacySceneComposerRedirect() {
  const router = useRouter();

  useEffect(() => {
    let cancelled = false;
    fetchAuthStatus().then((me) => {
      if (cancelled) return;
      if (me?.username) {
        router.replace(
          `/${encodeURIComponent(me.username)}/admin/scene-composer`,
        );
      } else {
        router.replace("/login");
      }
    });
    return () => {
      cancelled = true;
    };
  }, [router]);

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "#05050a",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        color: "rgba(255,255,255,0.35)",
        fontFamily: "system-ui, -apple-system, sans-serif",
        fontSize: 12,
        letterSpacing: "0.08em",
        textTransform: "uppercase",
      }}
    >
      <span>Redirection…</span>
    </div>
  );
}
