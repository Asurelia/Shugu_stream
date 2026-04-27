/**
 * SceneEditorV2App — racine du Scene Editor v2.
 *
 * Layout :
 *   ┌─ Topbar (36px) ──────────────────────────┐
 *   │ logo · scene name · workspace switcher · ⌘K │
 *   ├──────────────────────────────────────────┤
 *   │                                          │
 *   │           Workspace courant              │
 *   │                                          │
 *   ├──────────────────────────────────────────┤
 *   │ Statusbar (28px) workspace · state · mode │
 *   └──────────────────────────────────────────┘
 *
 * Hotkeys global :
 *   1 / 2 / 3   → switch workspace (hors input)
 *   Mod+K       → ouvre command palette
 *   Escape      → ferme command palette
 *
 * ErrorBoundary autour du workspace : un crash 3D ne tue pas le shell.
 */

import { ErrorBoundary } from "./ErrorBoundary";
import { Topbar } from "../shell/Topbar";
import { Statusbar } from "../shell/Statusbar";
import { CommandPalette } from "../command-palette/CommandPalette";
import { Workspace3D } from "../workspaces/scene3d/Workspace3D";
import { Workspace2D } from "../workspaces/overlays2d/Workspace2D";
import { WorkspaceShow } from "../workspaces/show/WorkspaceShow";
import { useSceneEditorStore } from "../store/useSceneEditorStore";
import { useHotkeys, type Binding } from "../hooks/useHotkeys";
import { WORKSPACES } from "./workspace-types";

export function SceneEditorV2App() {
  const currentWorkspace = useSceneEditorStore((s) => s.currentWorkspace);
  const setWorkspace = useSceneEditorStore((s) => s.setWorkspace);
  const togglePalette = useSceneEditorStore((s) => s.togglePalette);
  const openPalette = useSceneEditorStore((s) => s.openPalette);
  const closePalette = useSceneEditorStore((s) => s.closePalette);
  const paletteOpen = useSceneEditorStore((s) => s.paletteOpen);

  const bindings: Binding[] = [
    ...WORKSPACES.map<Binding>((w) => ({
      key: w.hotkey,
      handler: () => setWorkspace(w.id),
    })),
    { key: "k", mod: true, preventDefault: true, handler: () => togglePalette() },
    {
      key: "Escape",
      handler: () => {
        if (paletteOpen) closePalette();
      },
    },
    // Mod+P : explicit "open palette" for users who don't know Mod+K convention.
    { key: "p", mod: true, preventDefault: true, handler: () => openPalette() },
  ];
  useHotkeys(bindings);

  return (
    <div className="sev2-root">
      <Topbar />
      <main role="main" className="sev2-main">
        <ErrorBoundary>
          {currentWorkspace === "3d" && <Workspace3D />}
          {currentWorkspace === "2d" && <Workspace2D />}
          {currentWorkspace === "show" && <WorkspaceShow />}
        </ErrorBoundary>
      </main>
      <Statusbar />
      <CommandPalette />
    </div>
  );
}

// Default export for next/dynamic import compatibility.
export default SceneEditorV2App;
