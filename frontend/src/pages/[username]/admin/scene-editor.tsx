import Head from "next/head";
import { useRouter } from "next/router";
import dynamic from "next/dynamic";
import { AdminAuthGuard } from "@/components/admin/AdminAuthGuard";

// Note Phase A : le design bundle Claude Design importait `scene-editor.css`
// directement ici. Next.js 13 pages router interdit l'import de global CSS
// hors du Custom `_app.tsx` (erreur "Global CSS cannot be imported from
// files other than your Custom <App>"). L'import a donc été déplacé vers
// `frontend/src/pages/_app.tsx` (même convention que globals.css /
// celestial-veil-tokens.css / liquid-glass.css / viewer-proto.css). Les
// classes `.ide-*` sont scoped sous `.ide-root`, donc pas de conflit avec
// le reste du site.
//
// Note Phase B : ajout de `AdminAuthGuard` pour éviter qu'un visiteur non
// authentifié n'atteigne le Scene Editor (issue M2 du review Phase A). Le
// guard est un wrapper auth-only qui ne rend aucun chrome propre, donc le
// plein écran IDE est préservé tel quel une fois l'operator validé.

/**
 * `/[username]/admin/scene-editor` — Scene Editor plein écran.
 *
 * Ici on sort de l'AdminShell : le Scene Editor est un IDE densifié qui prend
 * 100 % du viewport (menubar + toolbar + docks + statusbar, cf.
 * `features/scene-editor`). Le retour vers l'admin dashboard se fait via le
 * bouton "Admin" en haut à gauche de la menubar (callback `onExit`).
 *
 * L'app est chargée en dynamic + ssr:false car elle dépend d'APIs browser
 * (window, popup, mesures DOM).
 */
const SceneEditorApp = dynamic(
  () => import("@/features/scene-editor").then((m) => m.SceneEditorApp),
  { ssr: false },
);

export default function SceneEditorPage() {
  const router = useRouter();

  return (
    <>
      <Head>
        <title>Scene Editor · Shugu</title>
        <meta name="viewport" content="width=device-width, initial-scale=1" />
      </Head>
      <AdminAuthGuard>
        {(operator) => {
          const handleExit = () => {
            if (window.history.length > 1) {
              router.back();
            } else {
              router.push(`/${encodeURIComponent(operator.username)}/admin`);
            }
          };
          return (
            <div
              style={{
                position: "fixed",
                inset: 0,
                background: "#05050a",
                overflow: "hidden",
                // Neutralise le background animé du body global — le Scene
                // Editor a son propre chrome sombre d'IDE.
                isolation: "isolate",
              }}
            >
              <SceneEditorApp onExit={handleExit} />
            </div>
          );
        }}
      </AdminAuthGuard>
    </>
  );
}

// Disable the global `shugu-body` gradient class logic : on s'isole via le
// wrapper fixed ci-dessus, donc rien à faire côté _app.
