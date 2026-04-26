/**
 * Route Next.js — `/[username]/admin/scene-composer` — Scene Composer plein écran.
 *
 * Aligne le Scene Composer sur le pattern dynamic `[username]/admin/...`
 * utilisé par `scene-editor.tsx` (cohérence URL — chaque opérateur a SA
 * propre URL signée par username, pas une route statique partagée).
 *
 * Authentification : `AdminAuthGuard` valide que l'opérateur connecté
 * matche le `:username` de l'URL avant de monter le composer. Non-auth →
 * redirect vers `/login`. Mismatch → redirect vers la page de l'opérateur
 * connecté (cf. AdminAuthGuard ligne 96 — note : ce redirect cible
 * aujourd'hui `scene-editor` ; un fix transverse est nécessaire pour
 * préserver le path `scene-composer`, hors scope M2).
 *
 * WebGL : chargé via `dynamic(ssr:false)` — `SceneComposerApp` monte un
 * `<canvas>` avec WebGLRenderer qui ne peut pas tourner en SSR Node.js.
 *
 * Compat : l'ancienne route static `/shugu/admin/scene-composer` est
 * conservée comme alias redirect — voir `pages/shugu/admin/scene-composer.tsx`.
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
