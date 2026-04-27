/**
 * Workspace Show / Preview — placeholder Phase 1.
 * Phase 4 implémentera : compositing temps réel 3D + 2D, quick triggers, metrics.
 */

import { SplitLayout } from "../../shell/SplitLayout";

export function WorkspaceShow() {
  return (
    <SplitLayout id="show:center-right" direction="horizontal" defaultRatio={0.74}>
      <CompositingPlaceholder />
      <div className="sev2-panel sev2-panel--side">
        <SplitLayout id="show:right-stack" direction="vertical" defaultRatio={0.34}>
          <PanelPlaceholder title="Live State" hint="Scène / outfit / anim / shot / vfx — Phase 4" />
          <SplitLayout id="show:right-stack-2" direction="vertical" defaultRatio={0.55}>
            <PanelPlaceholder title="Quick Triggers" hint="Actions live configurables — Phase 4" />
            <PanelPlaceholder title="Stream Metrics" hint="fps / latency / bitrate — Phase 4" />
          </SplitLayout>
        </SplitLayout>
      </div>
    </SplitLayout>
  );
}

function PanelPlaceholder({ title, hint }: { title: string; hint: string }) {
  return (
    <section className="sev2-panel-body" aria-label={title}>
      <div className="sev2-panel-header">
        <span className="sev2-panel-title">{title}</span>
      </div>
      <div className="sev2-panel-empty">
        <div className="sev2-panel-empty-icon" aria-hidden="true">◇</div>
        <div className="sev2-panel-empty-hint">{hint}</div>
      </div>
    </section>
  );
}

function CompositingPlaceholder() {
  return (
    <div className="sev2-viewport" aria-label="Show / Preview compositing">
      <div className="sev2-viewport-empty">
        <div className="sev2-viewport-icon" aria-hidden="true">◉</div>
        <div className="sev2-viewport-title">Show · Preview</div>
        <div className="sev2-viewport-hint">
          Phase 4 stack 3D viewport + overlays 2D = ce que voit le viewer en stream.
        </div>
      </div>
    </div>
  );
}
