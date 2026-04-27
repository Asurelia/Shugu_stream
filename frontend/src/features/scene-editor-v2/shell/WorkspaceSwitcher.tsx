/**
 * WorkspaceSwitcher — onglets centraux (D1) Scene 3D / Overlays / Show.
 *
 * Wrapper sur GlassTabs liquid-glass : rend la liste WORKSPACES, lit le
 * currentWorkspace du store, propage le changement via setWorkspace.
 *
 * Le label inclut l'icône + texte. Hotkeys 1/2/3 sont gérés ailleurs
 * (useWorkspaceHotkeys) — ce composant n'est que la surface clic.
 */

import { GlassTabs } from "@/features/liquid-glass/primitives";
import { WORKSPACES, type WorkspaceId } from "../app/workspace-types";
import { useSceneEditorStore } from "../store/useSceneEditorStore";

export function WorkspaceSwitcher() {
  const currentWorkspace = useSceneEditorStore((s) => s.currentWorkspace);
  const setWorkspace = useSceneEditorStore((s) => s.setWorkspace);

  return (
    <GlassTabs
      aria-label="Workspaces"
      value={currentWorkspace}
      onChange={(v) => setWorkspace(v as WorkspaceId)}
      tabs={WORKSPACES.map((w) => ({
        value: w.id,
        label: (
          <span className="inline-flex items-center gap-2">
            <span aria-hidden="true">{w.icon}</span>
            <span>{w.label}</span>
            <span className="hidden sm:inline text-[10px] opacity-60 font-mono">
              {w.hotkey}
            </span>
          </span>
        ),
      }))}
    />
  );
}
