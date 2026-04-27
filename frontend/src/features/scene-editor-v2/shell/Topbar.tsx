/**
 * Topbar — barre supérieure 36px liquid-glass.
 *
 * Composition :
 * - Logo Shugu + nom de scène (inline-editable Phase 2+, en lecture seule pour Phase 1).
 * - Indicateur dirty (point rose si modifications non sauvegardées).
 * - WorkspaceSwitcher centré (3 onglets).
 * - Bouton Command Palette à droite (déclencheur visible + raccourci Mod+K).
 * - Bouton "exit" (retour /admin) à droite.
 */

import Link from "next/link";
import { useRouter } from "next/router";
import { GlassButton } from "@/features/liquid-glass/primitives";
import { useSceneEditorStore } from "../store/useSceneEditorStore";
import { WorkspaceSwitcher } from "./WorkspaceSwitcher";

export function Topbar() {
  const sceneName = useSceneEditorStore((s) => s.sceneName);
  const dirty = useSceneEditorStore((s) => s.dirty);
  const openPalette = useSceneEditorStore((s) => s.openPalette);
  const router = useRouter();
  const usernameRaw = router.query.username;
  const username = Array.isArray(usernameRaw) ? usernameRaw[0] : usernameRaw;
  const adminHref = username ? `/${encodeURIComponent(username)}/admin` : "/";

  return (
    <header role="banner" className="sev2-topbar">
      <div className="sev2-topbar-left">
        <Link href={adminHref} className="sev2-topbar-logo" aria-label="Retour à l'admin">
          <span aria-hidden="true">✦</span>
        </Link>
        <span className="sev2-topbar-scene" data-dirty={dirty ? "true" : "false"}>
          <span className="sev2-topbar-scene-label">scene</span>
          <span className="sev2-topbar-scene-name">{sceneName}</span>
          {dirty && (
            <span className="sev2-topbar-dirty" aria-label="Modifications non sauvées" title="Modifications non sauvées" />
          )}
        </span>
      </div>
      <div className="sev2-topbar-center">
        <WorkspaceSwitcher />
      </div>
      <div className="sev2-topbar-right">
        <GlassButton variant="ghost" size="sm" onClick={openPalette} aria-label="Ouvrir la palette de commandes">
          <span aria-hidden="true">⌘K</span>
          <span className="hidden lg:inline">Commands</span>
        </GlassButton>
        <Link href={adminHref} className="lgb lgb-subtle lgb-sm" style={{ textDecoration: "none" }}>
          <span aria-hidden="true">⎋</span>
          <span className="hidden lg:inline">Admin</span>
        </Link>
      </div>
    </header>
  );
}
