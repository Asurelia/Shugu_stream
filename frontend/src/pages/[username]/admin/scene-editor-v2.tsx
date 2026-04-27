/**
 * `/[username]/admin/scene-editor-v2` — Scene Editor v2 plein écran.
 *
 * Phase 1 = shell uniquement (3 workspaces vides + Command Palette + hotkeys).
 * L'app est chargée en dynamic + ssr:false car elle dépend de window APIs
 * (localStorage, addEventListener keydown au mount, etc.).
 *
 * Coexiste avec /admin/scene-editor (ancien) jusqu'à Phase 6 cleanup.
 */

import Head from "next/head";
import dynamic from "next/dynamic";
import { AdminAuthGuard } from "@/components/admin/AdminAuthGuard";

const SceneEditorV2App = dynamic(
  () => import("@/features/scene-editor-v2").then((m) => m.SceneEditorV2App),
  { ssr: false },
);

export default function SceneEditorV2Page() {
  return (
    <>
      <Head>
        <title>Scene Editor v2 · Shugu</title>
        <meta name="viewport" content="width=device-width, initial-scale=1" />
      </Head>
      <AdminAuthGuard>{() => <SceneEditorV2App />}</AdminAuthGuard>
    </>
  );
}
