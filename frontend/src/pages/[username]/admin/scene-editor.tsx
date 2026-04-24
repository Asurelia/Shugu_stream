import Head from "next/head";
import { useRouter } from "next/router";
import dynamic from "next/dynamic";

// Note Phase A : le design bundle Claude Design importait `scene-editor.css`
// directement ici. Next.js 13 pages router interdit l'import de global CSS
// hors du Custom `_app.tsx` (erreur "Global CSS cannot be imported from
// files other than your Custom <App>"). L'import a donc été déplacé vers
// `frontend/src/pages/_app.tsx` (même convention que globals.css /
// celestial-veil-tokens.css / liquid-glass.css / viewer-proto.css). Les
// classes `.ide-*` sont scoped sous `.ide-root`, donc pas de conflit avec
// le reste du site.

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
  const username = (router.query.username as string) || "shugu";

  const handleExit = () => {
    if (window.history.length > 1) {
      router.back();
    } else {
      router.push(`/${username}/admin`);
    }
  };

  return (
    <>
      <Head>
        <title>Scene Editor · Shugu</title>
        <meta name="viewport" content="width=device-width, initial-scale=1" />
      </Head>
      <div
        style={{
          position: "fixed",
          inset: 0,
          background: "#05050a",
          overflow: "hidden",
          // Neutralise le background animé du body global — le Scene Editor a
          // son propre chrome sombre d'IDE.
          isolation: "isolate",
        }}
      >
        <SceneEditorApp onExit={handleExit} />
      </div>
    </>
  );
}

// Disable the global `shugu-body` gradient class logic : on s'isole via le
// wrapper fixed ci-dessus, donc rien à faire côté _app.
