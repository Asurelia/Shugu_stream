/**
 * Workspace 3D — placeholder Phase 1.
 *
 * Phase 2 (PR 2.A-2.D) remplira :
 * - Outliner (gauche haut)
 * - Library (gauche bas)
 * - Viewport Three.js (centre)
 * - Properties Inspector (droite)
 *
 * Pour Phase 1 on rend juste 3 zones à la bonne place pour valider le SplitLayout
 * et donner un visuel cohérent avec le reste du shell.
 */

import { SplitLayout } from "../../shell/SplitLayout";
import { Outliner } from "./panels/Outliner";

export function Workspace3D() {
  return (
    <SplitLayout id="scene3d:left" direction="horizontal" defaultRatio={0.18}>
      <div className="sev2-panel sev2-panel--side">
        <SplitLayout id="scene3d:left-stack" direction="vertical" defaultRatio={0.55}>
          <Outliner />
          <PanelPlaceholder title="Library" hint="VRM, Outfits, Anims, Props, Decor, VFX — Phase 2.B" />
        </SplitLayout>
      </div>
      <SplitLayout id="scene3d:center-right" direction="horizontal" defaultRatio={0.78}>
        <ViewportPlaceholder />
        <div className="sev2-panel sev2-panel--side">
          <PanelPlaceholder title="Properties" hint="Transform / Material / Animation — Phase 2.D" />
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

function ViewportPlaceholder() {
  return (
    <div className="sev2-viewport" aria-label="3D viewport">
      <div className="sev2-viewport-empty">
        <div className="sev2-viewport-icon" aria-hidden="true">◈</div>
        <div className="sev2-viewport-title">3D Viewport</div>
        <div className="sev2-viewport-hint">
          Phase 2 branchera Three.js + VRM ici (réutilise scene-composer/viewer/three-stage).
        </div>
      </div>
    </div>
  );
}
