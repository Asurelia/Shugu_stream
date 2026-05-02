/**
 * `/[username]/admin/scene-editor-v2` — App Router migration (Sprint E5).
 *
 * Page la plus complexe du sprint : `next/dynamic` avec `ssr: false` pour
 * `SceneEditorV2App` (qui utilise window APIs au mount), gardée derrière
 * `AdminAuthGuard` qui vérifie le cookie operator.
 *
 * Pattern Server shell + Client island préservé : la page Server exporte
 * `metadata`, le Client child mount le `<dynamic>` + l'auth guard.
 *
 * Phase 1 du Scene Editor v2 = shell uniquement (3 workspaces vides +
 * Command Palette + hotkeys). Coexiste avec `/admin/scene-editor` ancien
 * jusqu'au cleanup post-Phase 6.
 */
import type { Metadata, Viewport } from "next";

import { SceneEditorV2Client } from "./_client";

export const metadata: Metadata = {
  title: "Scene Editor v2 · Shugu",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
};

export default function SceneEditorV2Page() {
  return <SceneEditorV2Client />;
}
