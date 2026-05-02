/**
 * `/shugu/admin/scene-composer` — legacy alias redirect (Sprint E4 migration).
 *
 * Avant M2 (PR #26), c'était la route static officielle. Le pattern Shugu
 * pour les pages admin est désormais `/[username]/admin/...` — Scene Composer
 * rejoint cette convention. Cette route reste comme alias 308 pour ne pas
 * casser les bookmarks externes.
 *
 * Migration Pages Router → App Router (Sprint E4) :
 *   - `getServerSideProps` async + redirect Pages → async Server Component
 *     + `redirect()` from `next/navigation`.
 *   - `ctx.req.headers.cookie` → `cookies()` from `next/headers` (async API
 *     en Next 15+).
 *   - Plus besoin de fallback client : `redirect()` côté Server est garanti
 *     d'aboutir avant tout rendu, donc zéro flash. Le composant placeholder
 *     legacy est supprimé.
 *
 * Architecture : pure dispatcher, ne charge pas `SceneComposerApp` (séparation
 * "route legacy" vs "route officielle" préservée).
 */
import { cookies, headers } from "next/headers";
import { redirect } from "next/navigation";

export default async function LegacySceneComposerRedirect() {
  // Construit l'URL absolue vers /auth/me en relayant les cookies entrants.
  // L'host est lu depuis les headers de la request entrante (Next 15+ async
  // API). En dev `localhost` → http, sinon https (prod nginx force https).
  let destination = "/login";
  try {
    const cookieStore = await cookies();
    const headerStore = await headers();
    const host = headerStore.get("host") ?? "localhost";
    const protocol = host.startsWith("localhost") ? "http" : "https";
    const cookieHeader = cookieStore
      .getAll()
      .map((c) => `${c.name}=${c.value}`)
      .join("; ");

    const resp = await fetch(`${protocol}://${host}/auth/me`, {
      headers: { cookie: cookieHeader },
      // `cache: 'no-store'` indispensable — on veut l'auth en temps réel,
      // pas une réponse cached d'un autre user.
      cache: "no-store",
    });

    if (resp.ok) {
      const me = (await resp.json()) as { username?: string } | null;
      if (me?.username) {
        destination = `/${encodeURIComponent(me.username)}/admin/scene-editor-v2`;
      }
    }
  } catch {
    // Réseau/parse failed — laisse `destination` par défaut sur "/login".
  }

  redirect(destination);
}
