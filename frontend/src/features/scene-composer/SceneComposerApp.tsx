/**
 * SceneComposerApp — shell principal du Scene Composer.
 *
 * Architecture Unity-style (référence SceneEditorApp.tsx Phase A/B) :
 *   - Panneau gauche : liste des scènes authoriées (ScenesListPanel)
 *   - Centre : PlayModeToolbar + viewer 3D (SceneComposerViewer, ssr:false)
 *   - Droite : inspecteur + catalogue d'assets (tabs)
 *
 * State UI géré via `useSceneComposerStore` (sélection, mode viewer,
 * preset caméra, layout, playMode, afkLoops, currentVrmaUrl).
 * Données métier fetchées par les panels eux-mêmes.
 *
 * Extensions E5.4 :
 *   - PlayModeToolbar : barre de contrôle Play/Stop + config AFK Loops
 *   - useAfkLoops : boucles AFK déterministes (animations VRMA idle auto)
 *   - currentVrmaUrl : piloté par useAfkLoops → passé comme vrmaUrl au viewer
 *
 * OUT OF SCOPE E5.5 :
 *   - Bridge Scene Editor ↔ Scene Composer
 *
 * @module SceneComposerApp
 */

import dynamic from "next/dynamic";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  useSceneComposerStore,
  selectCameraPreset,
  selectViewerMode,
  selectPanelLayout,
  selectPlayMode,
  selectAfkLoops,
  selectCurrentVrmaUrl,
} from "./store/useSceneComposerStore";
import { ScenesListPanel } from "./panels/ScenesListPanel";
import { SceneInspectorPanel } from "./panels/SceneInspectorPanel";
import { AssetCataloguePanel } from "./panels/AssetCataloguePanel";
import { PlayModeToolbar } from "./panels/PlayModeToolbar";
import { useAfkLoops } from "./viewer/afk/useAfkLoops";
import { getAssetCatalog } from "./api/catalogClient";
import type { VrmaAnimationEntry } from "./api/catalogClient";
import type { CameraPreset } from "./viewer/three-stage/createCamera";

// ─── Chargement dynamique du viewer (WebGL → pas de SSR) ─────────────────────

const SceneComposerViewer = dynamic(
  () =>
    import("./viewer/SceneComposerViewer").then((m) => m.SceneComposerViewer),
  { ssr: false },
);

// ─── Types ────────────────────────────────────────────────────────────────────

export interface SceneComposerAppProps {
  /** Callback de navigation retour (bouton ✕ ou Échap). */
  onExit: () => void;
  /** URL du VRM à charger par défaut (peut être vide). */
  defaultVrmUrl?: string;
}

// ─── Styles ───────────────────────────────────────────────────────────────────

const ROOT_STYLE: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  height: "100%",
  width: "100%",
  background: "#05050a",
  color: "#c8c8d8",
  fontFamily: "'Inter', 'Segoe UI', sans-serif",
  overflow: "hidden",
};

const TOOLBAR_STYLE: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  height: 36,
  background: "#0d0d14",
  borderBottom: "1px solid #1a1a28",
  padding: "0 12px",
  gap: 8,
  flexShrink: 0,
};

const WORKSPACE_STYLE: React.CSSProperties = {
  display: "flex",
  flex: 1,
  overflow: "hidden",
};

const LEFT_PANEL: React.CSSProperties = {
  width: 220,
  flexShrink: 0,
  borderRight: "1px solid #1a1a28",
  overflow: "hidden",
};

const CENTER_STYLE: React.CSSProperties = {
  flex: 1,
  position: "relative",
  overflow: "hidden",
};

const RIGHT_PANEL: React.CSSProperties = {
  width: 260,
  flexShrink: 0,
  borderLeft: "1px solid #1a1a28",
  display: "flex",
  flexDirection: "column",
  overflow: "hidden",
};

const TAB_BAR: React.CSSProperties = {
  display: "flex",
  background: "#0d0d14",
  borderBottom: "1px solid #1a1a28",
  flexShrink: 0,
};

const BTN_BASE: React.CSSProperties = {
  background: "none",
  border: "none",
  cursor: "pointer",
  fontSize: 12,
  padding: "4px 10px",
  color: "#666688",
};

const BTN_ACTIVE: React.CSSProperties = {
  ...BTN_BASE,
  color: "#9988dd",
  borderBottom: "2px solid #6655ee",
};

// ─── Composant ────────────────────────────────────────────────────────────────

type RightTab = "inspector" | "assets";

/**
 * Shell principal du Scene Composer.
 *
 * Responsabilités E5.4 ajoutées :
 * - Charge le catalogue VRMA au mount (pour useAfkLoops)
 * - Câble useAfkLoops avec la canvasRef (partagée avec le viewer via prop)
 * - Passe currentVrmaUrl comme vrmaUrl au viewer
 * - Rend PlayModeToolbar au-dessus du viewer
 */
export function SceneComposerApp({
  onExit,
  defaultVrmUrl = "",
}: SceneComposerAppProps) {
  const cameraPreset = useSceneComposerStore(selectCameraPreset);
  const viewerMode = useSceneComposerStore(selectViewerMode);
  const setCameraPreset = useSceneComposerStore((s) => s.setCameraPreset);
  const setViewerMode = useSceneComposerStore((s) => s.setViewerMode);
  const panelLayout = useSceneComposerStore(selectPanelLayout);

  // E5.4 — Play Mode + AFK Loops
  const playMode = useSceneComposerStore(selectPlayMode);
  const afkLoops = useSceneComposerStore(selectAfkLoops);
  const currentVrmaUrl = useSceneComposerStore(selectCurrentVrmaUrl);
  const setCurrentVrmaUrl = useSceneComposerStore((s) => s.setCurrentVrmaUrl);

  // Catalogue VRMA pour useAfkLoops — chargé au mount, non bloquant.
  const [vrmaCatalogue, setVrmaCatalogue] = useState<VrmaAnimationEntry[]>([]);
  useEffect(() => {
    getAssetCatalog()
      .then((catalog) => setVrmaCatalogue(catalog.vrma_animations))
      .catch(() => {
        // Silencieux — useAfkLoops fonctionne avec catalogue vide (no-op).
      });
  }, []);

  // Ref canvas partagée : SceneComposerViewer la gère, useAfkLoops l'écoute.
  // Note : SceneComposerViewer gère son propre canvasRef interne via useSceneRig.
  // useAfkLoops reçoit une ref séparée et lit les events sur le DOM réel une fois monté.
  // Le viewer monte avant useAfkLoops ne commence à écouter (poll toutes les 5s).
  const afkCanvasRef = useRef<HTMLCanvasElement | null>(null);

  // useAfkLoops — boucles AFK déterministes.
  // currentViewerCount=0 pour E5.4 (câblage réel prévu phase ultérieure).
  const { afkActive } = useAfkLoops({
    canvasRef: afkCanvasRef,
    playMode,
    afkLoops,
    vrmaCatalogue,
    currentViewerCount: 0,
    setCurrentVrmaUrl,
  });

  // Onglet actif du panneau droit.
  const [rightTab, setRightTab] = useState<RightTab>("inspector");

  const handlePreset = useCallback(
    (p: CameraPreset) => setCameraPreset(p),
    [setCameraPreset],
  );

  const toggleViewerMode = useCallback(() => {
    setViewerMode(viewerMode === "edit" ? "preview" : "edit");
  }, [viewerMode, setViewerMode]);

  // En mode fullscreen : on cache les panneaux latéraux.
  const showSidePanels = panelLayout !== "fullscreen";

  return (
    <div style={ROOT_STYLE}>
      {/* Toolbar */}
      <div style={TOOLBAR_STYLE}>
        <span style={{ fontWeight: 700, fontSize: 13, color: "#9988dd", letterSpacing: 0.5 }}>
          Scene Composer
        </span>

        <div style={{ flex: 1 }} />

        {/* Presets caméra */}
        {(["free", "front", "side", "top"] as CameraPreset[]).map((p) => (
          <button
            key={p}
            style={cameraPreset === p ? { ...BTN_BASE, color: "#bb99ff", background: "#1a1a2c" } : BTN_BASE}
            onClick={() => handlePreset(p)}
            title={`Vue ${p}`}
          >
            {p}
          </button>
        ))}

        <div style={{ width: 1, height: 18, background: "#1a1a28" }} />

        {/* Mode viewer */}
        <button
          style={{ ...BTN_BASE, color: viewerMode === "preview" ? "#99ddaa" : "#7766cc" }}
          onClick={toggleViewerMode}
          title={viewerMode === "edit" ? "Passer en mode prévisualisation" : "Passer en mode édition"}
        >
          {viewerMode === "edit" ? "Édition" : "Prévisualisation"}
        </button>

        {/* Quitter */}
        <button
          style={{ ...BTN_BASE, color: "#666677", marginLeft: 8 }}
          onClick={onExit}
          title="Fermer le Scene Composer"
          aria-label="Fermer"
        >
          ✕
        </button>
      </div>

      {/* Workspace */}
      <div style={WORKSPACE_STYLE}>
        {/* Gauche : liste des scènes */}
        {showSidePanels && (
          <div style={LEFT_PANEL}>
            <ScenesListPanel />
          </div>
        )}

        {/* Centre : PlayModeToolbar + viewer 3D */}
        <div style={{ ...CENTER_STYLE, display: "flex", flexDirection: "column" }}>
          {/* E5.4 : barre de contrôle Play/Stop + AFK Loops */}
          <PlayModeToolbar
            afkActive={afkActive}
            currentViewerCount={0}
          />
          {/* Viewer 3D — vrmaUrl piloté par currentVrmaUrl (AFK loops ou UI) */}
          <div style={{ flex: 1, position: "relative", overflow: "hidden" }}>
            <SceneComposerViewer
              vrmUrl={defaultVrmUrl}
              cameraPreset={cameraPreset}
              viewMode={viewerMode}
              vrmaUrl={currentVrmaUrl ?? undefined}
              vrmaLoop
            />
          </div>
        </div>

        {/* Droite : inspecteur + assets */}
        {showSidePanels && (
          <div style={RIGHT_PANEL}>
            <div style={TAB_BAR}>
              <button
                style={rightTab === "inspector" ? BTN_ACTIVE : BTN_BASE}
                onClick={() => setRightTab("inspector")}
              >
                Inspecteur
              </button>
              <button
                style={rightTab === "assets" ? BTN_ACTIVE : BTN_BASE}
                onClick={() => setRightTab("assets")}
              >
                Assets
              </button>
            </div>
            <div style={{ flex: 1, overflow: "hidden" }}>
              {rightTab === "inspector" ? (
                <SceneInspectorPanel />
              ) : (
                <AssetCataloguePanel />
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default SceneComposerApp;
