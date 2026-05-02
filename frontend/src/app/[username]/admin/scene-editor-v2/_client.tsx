"use client";

/**
 * Scene Editor v2 client island.
 *
 * Migration Pages Router → App Router (Sprint E5) :
 *   - `next/dynamic` avec `{ ssr: false }` reste valide en App Router MAIS
 *     uniquement à l'intérieur d'un Client Component. La directive
 *     `"use client"` au top de ce fichier rend l'option valide.
 *   - `<Head>` Pages Router supprimé → métadonnées déclarées côté Server
 *     (`page.tsx`).
 *   - `AdminAuthGuard` migré vers `next/navigation` dans son module — ce
 *     composant fonctionne désormais uniquement sous App Router (toutes les
 *     pages admin migrent ensemble Sprint E5).
 */
import dynamic from "next/dynamic";

import { AdminAuthGuard } from "@/components/admin/AdminAuthGuard";

const SceneEditorV2App = dynamic(
  () => import("@/features/scene-editor-v2").then((m) => m.SceneEditorV2App),
  { ssr: false },
);

export function SceneEditorV2Client() {
  return <AdminAuthGuard>{() => <SceneEditorV2App />}</AdminAuthGuard>;
}
