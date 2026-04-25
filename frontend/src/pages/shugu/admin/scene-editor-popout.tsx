/**
 * Route Next.js — fenêtre popout d'un panel du Scene Editor (Phase G).
 *
 * Ouverte par `openPanelWindow(panelKey)` (cf. `@/lib/editorPopout`) avec
 * `?panel=<key>` dans l'URL. La page monte UN SEUL panel isolé, le connecte
 * au store Zustand (identique au parent — BroadcastChannel synchronise les
 * deux côtés), et publie ses propres mutations pour que le parent se
 * réaligne.
 *
 * Choix d'implémentation :
 *  - route statique `/shugu/admin/scene-editor-popout` (pas `[username]`)
 *    parce que la popup hérite des cookies d'auth du parent mais n'a pas
 *    besoin d'un URL user-scoped : le store local est suffisant, le
 *    BroadcastChannel fait le pont avec le parent authentifié.
 *  - dynamic import `ssr:false` car on touche `window`, BroadcastChannel
 *    et le DOM popup dès le mount.
 *  - pas d'AdminAuthGuard bloquant : les `pages/[username]/admin/...`
 *    protègent le parent ; la popup tourne sous le même browsing context
 *    (cookies partagés same-origin) et NE fait pas d'appel API sensible.
 *    Garder une popup "open" après logout parent est acceptable — le
 *    `BroadcastChannel` cesse de recevoir dès que le parent ferme de toute
 *    façon, et un refresh popup tenterait `/auth/me`. Le scope Phase G
 *    est délibérément minimal pour ne pas réimplémenter tout l'IDE.
 */

import Head from "next/head";
import dynamic from "next/dynamic";

const SceneEditorPopoutApp = dynamic(
  () =>
    import("@/features/scene-editor/PopoutApp").then((m) => m.SceneEditorPopoutApp),
  { ssr: false },
);

export default function SceneEditorPopoutPage() {
  return (
    <>
      <Head>
        <title>Shugu · Popout</title>
        <meta name="viewport" content="width=device-width, initial-scale=1" />
      </Head>
      <div
        style={{
          position: "fixed",
          inset: 0,
          background: "#05050a",
          overflow: "hidden",
          isolation: "isolate",
        }}
      >
        <SceneEditorPopoutApp />
      </div>
    </>
  );
}
