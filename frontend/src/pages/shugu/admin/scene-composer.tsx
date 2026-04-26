/**
 * Route Next.js — `/shugu/admin/scene-composer` — Scene Composer plein écran.
 *
 * Route statique (pas `[username]/admin/...`) pour deux raisons :
 *  1. `AdminAuthGuard` (ligne 96) hardcode un redirect vers
 *     `/${username}/admin/scene-editor` en cas de mismatch username. Mettre
 *     le Scene Composer sous `[username]/admin/` ferait potentiellement boucler
 *     ce redirect si un opérateur navigue directement par URL.
 *  2. Cohérence avec `scene-editor-popout.tsx` qui utilise la même convention
 *     de route statique sous `/shugu/admin/`.
 *
 * Authentification : `AdminAuthGuard` en render-prop valide que l'opérateur
 * est connecté avant de rendre l'app. Non-auth → redirect vers login.
 *
 * WebGL : chargé via `dynamic(ssr:false)` — `SceneComposerApp` monte un
 * `<canvas>` avec WebGLRenderer qui ne peut pas tourner en SSR Node.js.
 */

import Head from "next/head";
import { useRouter } from "next/router";
import dynamic from "next/dynamic";
import { AdminAuthGuard } from "@/components/admin/AdminAuthGuard";

/** SceneComposerApp chargé dynamiquement (WebGL + window APIs → no SSR). */
const SceneComposerApp = dynamic(
  () =>
    import("@/features/scene-composer").then((m) => m.SceneComposerApp),
  { ssr: false },
);

export default function SceneComposerPage() {
  const router = useRouter();

  return (
    <>
      <Head>
        <title>Scene Composer · Shugu</title>
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
                // Neutralise le gradient animé global du body — le Composer
                // a son propre chrome sombre.
                isolation: "isolate",
              }}
            >
              <SceneComposerApp onExit={handleExit} />
            </div>
          );
        }}
      </AdminAuthGuard>
    </>
  );
}
