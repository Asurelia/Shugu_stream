/**
 * Statusbar — barre inférieure 28px liquid-glass.
 *
 * Phase 1 = workspace courant + état dirty + indicateur "Edit Mode".
 * Phase 2+ ajoutera : fps render, ws latency, selection name, etc.
 */

import { GlassPill } from "@/features/liquid-glass/primitives";
import { useSceneEditorStore } from "../store/useSceneEditorStore";
import { WORKSPACES } from "../app/workspace-types";

export function Statusbar() {
  const currentWorkspace = useSceneEditorStore((s) => s.currentWorkspace);
  const dirty = useSceneEditorStore((s) => s.dirty);
  const ws = WORKSPACES.find((w) => w.id === currentWorkspace);

  return (
    <footer role="contentinfo" className="sev2-statusbar">
      <div className="sev2-statusbar-section">
        <span className="sev2-statusbar-label">workspace</span>
        <span className="sev2-statusbar-value">{ws?.label ?? currentWorkspace}</span>
      </div>
      <div className="sev2-statusbar-section">
        <span className="sev2-statusbar-label">state</span>
        <span className="sev2-statusbar-value">{dirty ? "dirty" : "saved"}</span>
      </div>
      <div className="sev2-statusbar-spacer" />
      <div className="sev2-statusbar-section">
        <GlassPill tone="primary" dot>
          edit
        </GlassPill>
      </div>
    </footer>
  );
}
