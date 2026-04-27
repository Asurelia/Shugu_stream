/**
 * Workspace 2D Overlays — placeholder Phase 1.
 * Phase 3 implémentera : safe area 1920x1080, templates, OverlayInspector.
 */

import { SplitLayout } from "../../shell/SplitLayout";

export function Workspace2D() {
  return (
    <SplitLayout id="overlays2d:left" direction="horizontal" defaultRatio={0.18}>
      <div className="sev2-panel sev2-panel--side">
        <PanelPlaceholder title="Templates" hint="SubGoal, LowerThird, FollowAlert, StatusBadge — Phase 3" />
      </div>
      <SplitLayout id="overlays2d:center-right" direction="horizontal" defaultRatio={0.78}>
        <SafeAreaPlaceholder />
        <div className="sev2-panel sev2-panel--side">
          <PanelPlaceholder title="Inspector" hint="Position / Size / Style / Animation / Data binding — Phase 3" />
        </div>
      </SplitLayout>
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

function SafeAreaPlaceholder() {
  return (
    <div className="sev2-viewport" aria-label="2D safe area">
      <div className="sev2-viewport-empty">
        <div className="sev2-viewport-icon" aria-hidden="true">▦</div>
        <div className="sev2-viewport-title">Safe Area 1920×1080</div>
        <div className="sev2-viewport-hint">
          Phase 3 ajoutera la safe area zoomable + drag-drop des templates.
        </div>
      </div>
    </div>
  );
}
