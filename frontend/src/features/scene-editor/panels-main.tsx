/**
 * Scene Editor — panneaux principaux : Scene view, Game view, Hierarchy,
 * Inspector.
 *
 * Ces panneaux consomment les primitives de `./primitives` et les mocks de
 * `./mock-data`. Ils sont sans état persistant (state local uniquement).
 */

import { useState, type DragEvent, type ReactNode } from "react";
import { useDragDrop } from "./dnd-context";
import {
  ColorPicker,
  Icon,
  PANEL_CENTERED_EMPTY,
  Panel,
  PropRow,
  PropSection,
  Select,
  Slider,
  Switch,
  TBBtn,
  Treeview,
  XYZ,
  Num,
  useCtxMenu,
  type IconName,
  type TreeNodeData,
} from "./primitives";
import { type InspectorData } from "./mock-data";
// Phase B : HierarchyPanel et InspectorPanel consomment désormais le store
// Zustand `useSceneEditorStore` au lieu des MOCK_* directs. Les données
// mockées restent dans `mock-data.ts` en seed initial du store, donc aucune
// régression visuelle vs Phase A (mêmes avatars, même scene active).
import {
  useSceneEditorStore,
  selectHierarchy,
  selectCurrentInspector,
  selectSelectedId,
} from "@/stores/useSceneEditorStore";
// Phase F : SceneView & GameView driverisés par le Three.js viewer legacy
// via l'adapter `viewer-adapter.tsx`. Le mock 2D CSS Phase A (silhouettes
// SVG + gizmos HTML) disparaît au profit du vrai canvas Three.js qui rend
// le VRM, la scène, le gizmo, et réagit à l'inspector.
import { ViewerAdapter } from "./viewer-adapter";

/* ═══════════════════════════════ SCENE VIEW ═══════════════════════════════ */

type SceneObj = {
  id: string;
  label: string;
  x: number;
  y: number;
  w: number;
  h: number;
  z: number;
  color: string;
};

const SCENE_OBJECTS: SceneObj[] = [
  { id: "set-bg",  label: "BG",    x: 5,  y: 5,  w: 90, h: 90, z: 0, color: "rgba(181,133,255,0.1)" },
  { id: "shugu",   label: "SHUGU", x: 30, y: 30, w: 16, h: 55, z: 2, color: "rgba(253,108,156,0.35)" },
  { id: "aura",    label: "AURA",  x: 55, y: 35, w: 14, h: 50, z: 2, color: "rgba(181,133,255,0.35)" },
  { id: "plant",   label: "PLANT", x: 8,  y: 55, w: 12, h: 30, z: 1, color: "rgba(127,227,176,0.35)" },
  { id: "chatbox", label: "CHAT",  x: 62, y: 8,  w: 32, h: 18, z: 3, color: "rgba(129,236,255,0.25)" },
  { id: "lower",   label: "L3RD",  x: 8,  y: 82, w: 50, h: 10, z: 3, color: "rgba(255,207,107,0.3)" },
];

type SceneViewProps = {
  selectedId?: string | null;
  onSelect?: (id: string | null) => void;
  onPopout?: () => void;
};

export function SceneViewPanel({ selectedId, onSelect, onPopout }: SceneViewProps) {
  // Phase F : la toolbar intra-panel continue de driver les mêmes toggles
  // UX (tool, grid, safe zones) que Phase A. Le `tool` local est ré-aligné
  // avec le store côté main toolbar, mais on conserve ce state pour
  // préserver l'ergonomie "chaque panel a son mini-bouton" du design
  // bundle (évite le coupling serré entre les panels et main toolbar).
  const [tool, setTool] = useState<"move" | "rotate" | "scale">("move");
  const [zoom] = useState(100);
  const [showGrid, setShowGrid] = useState(true);
  const [showSafe, setShowSafe] = useState(true);

  const { payload, setPayload, droppedAsset, setDroppedAsset, toast } = useDragDrop();
  const [dropCoords, setDropCoords] = useState<{ x: number; y: number } | null>(null);
  const [dropActive, setDropActive] = useState(false);
  const isAssetDrag = payload?.kind === "asset";

  // NB Phase F : `selectedId` / `onSelect` restent reçus en props pour
  // rétro-compat avec `SceneEditorApp` (le shell les passe depuis le store
  // déjà — cf. `renderPanel`). Ils alimentent l'overlay de bordure
  // "selected" sur le drop marker (pas l'interaction 3D qui passe par le
  // gizmo Three.js directement via `ViewerAdapter`).
  void selectedId;
  void onSelect;

  const onViewportDragOver = (e: DragEvent<HTMLDivElement>) => {
    if (!isAssetDrag) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "copy";
    setDropActive(true);
    const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
    setDropCoords({
      x: ((e.clientX - r.left) / r.width) * 100,
      y: ((e.clientY - r.top) / r.height) * 100,
    });
  };
  const onViewportDragLeave = () => {
    setDropActive(false);
    setDropCoords(null);
  };
  const onViewportDrop = (e: DragEvent<HTMLDivElement>) => {
    if (!isAssetDrag || !payload || payload.kind !== "asset") return;
    e.preventDefault();
    const asset = payload.asset;
    setDroppedAsset(asset);
    toast(`Added · ${asset.label}`);
    setDropActive(false);
    setDropCoords(null);
    setPayload(null);
  };

  return (
    <Panel
      title="Scene"
      icon="scene"
      onPopout={onPopout}
      actions={
        <>
          <button className="ide-panel-btn" title="Reset camera">
            <Icon name="camera" size={11} />
          </button>
          <button className="ide-panel-btn" title="Frame all">
            <Icon name="max" size={10} />
          </button>
        </>
      }
    >
      <div
        className="ide-viewport"
        onDragOver={onViewportDragOver}
        onDragLeave={onViewportDragLeave}
        onDrop={onViewportDrop}
      >
        {showGrid && <div className="checker" />}

        <div className="ide-viewport-toolbar">
          <TBBtn icon="move" active={tool === "move"} onClick={() => setTool("move")} title="Move (W)" />
          <TBBtn icon="rotate" active={tool === "rotate"} onClick={() => setTool("rotate")} title="Rotate (E)" />
          <TBBtn icon="scale" active={tool === "scale"} onClick={() => setTool("scale")} title="Scale (R)" />
          <div style={{ width: 1, background: "var(--ide-divider)", alignSelf: "stretch", margin: "0 2px" }} />
          <TBBtn icon="grid" active={showGrid} onClick={() => setShowGrid(!showGrid)} title="Toggle grid" />
          <TBBtn icon="ruler" active={showSafe} onClick={() => setShowSafe(!showSafe)} title="Safe zones" />
        </div>

        <div
          className="ide-viewport-toolbar ide-viewport-toolbar-right"
          style={{ right: 8, left: "auto" }}
        >
          <TBBtn label="Free" active title="Camera mode" />
          <TBBtn label={`${zoom}%`} title="Zoom" />
        </div>

        {/* Phase F : le canvas Three.js remplace le mock 2D (silhouettes
            SVG + gizmos HTML). Le wrapper `.ide-scene-canvas` est conservé
            pour que les CSS du design bundle (background gradient,
            inset overlays safe-zones, label bas) trouvent leur conteneur. */}
        <div className="ide-scene-canvas">
          <ViewerAdapter viewMode="edit" />

          {showSafe && (
            <>
              <div style={{ position: "absolute", inset: "5% 5%", border: "1px dashed rgba(255,207,107,0.25)", pointerEvents: "none" }} />
              <div style={{ position: "absolute", inset: "10% 10%", border: "1px dashed rgba(127,227,176,0.2)", pointerEvents: "none" }} />
            </>
          )}

          {droppedAsset && (
            <div
              className="ide-gizmo"
              style={{
                left: "46%",
                top: "42%",
                width: "14%",
                height: "28%",
                zIndex: 40,
                borderColor: "var(--ide-hot-pink)",
                background: "rgba(253,108,156,0.12)",
                pointerEvents: "none",
              }}
            >
              <div className="gizmo-label">{droppedAsset.label} · NEW</div>
            </div>
          )}

          <div className="ide-scene-canvas-label">
            <span>SCENE · 1920 × 1080</span>
            <span style={{ color: "var(--ide-cyan)" }}>FREE CAM</span>
          </div>
        </div>

        {isAssetDrag && dropActive && dropCoords && (
          <div
            className="ide-drop-marker"
            style={{
              left: `${dropCoords.x}%`,
              top: `${dropCoords.y}%`,
            }}
          >
            <Icon name="plus" size={10} />
            <span>Drop to add</span>
          </div>
        )}
        {isAssetDrag && dropActive && <div className="ide-viewport-dropzone" />}

        <SceneMinimap selectedId={selectedId} />
      </div>
    </Panel>
  );
}

// SceneSilhouettes — conservé pour référence du design bundle, utilisé
// par les tests de régression visuelle (Phase 8). Pas rendu en Phase F+
// dans le flow principal — le canvas Three.js prend sa place dans la
// scène live.
// eslint-disable-next-line @typescript-eslint/no-unused-vars
function SceneSilhouettes() {
  return (
    <svg
      viewBox="0 0 160 90"
      preserveAspectRatio="xMidYMid slice"
      style={{ position: "absolute", inset: 0, width: "100%", height: "100%", opacity: 0.55 }}
    >
      <defs>
        <radialGradient id="shuguGlow" cx="50%" cy="40%" r="50%">
          <stop offset="0%" stopColor="#fd6c9c" stopOpacity="0.5" />
          <stop offset="100%" stopColor="#fd6c9c" stopOpacity="0" />
        </radialGradient>
      </defs>
      <rect x="0" y="0" width="160" height="90" fill="url(#shuguGlow)" />
      <path d="M12 82 L14 60 Q18 55 22 60 L24 82 Z" fill="#7fe3b0" opacity="0.4" />
      <circle cx="18" cy="56" r="6" fill="#7fe3b0" opacity="0.3" />
      <g transform="translate(55 80)">
        <ellipse cx="0" cy="-2" rx="10" ry="3" fill="#000" opacity="0.3" />
        <path d="M-5 -4 Q-5 -25 0 -28 Q5 -25 5 -4 Z" fill="#fd6c9c" opacity="0.7" />
        <circle cx="0" cy="-35" r="8" fill="#f4ecff" opacity="0.7" />
        <path d="M-10 -30 Q-8 -44 0 -45 Q8 -44 10 -30 Q6 -34 0 -33 Q-6 -34 -10 -30 Z" fill="#fd6c9c" />
        <circle cx="-2" cy="-36" r="1" fill="#0b0714" />
        <circle cx="3" cy="-36" r="1" fill="#0b0714" />
      </g>
      <g transform="translate(100 80)">
        <ellipse cx="0" cy="-2" rx="9" ry="3" fill="#000" opacity="0.3" />
        <path d="M-5 -4 Q-5 -23 0 -25 Q5 -23 5 -4 Z" fill="#b585ff" opacity="0.7" />
        <circle cx="0" cy="-32" r="7" fill="#f4ecff" opacity="0.7" />
        <path d="M-8 -28 Q-6 -40 0 -41 Q6 -40 8 -28 Q5 -32 0 -31 Q-5 -32 -8 -28 Z" fill="#81ecff" />
        <circle cx="-2" cy="-33" r="1" fill="#0b0714" />
        <circle cx="2" cy="-33" r="1" fill="#0b0714" />
      </g>
    </svg>
  );
}

function SceneMinimap({ selectedId }: { selectedId?: string | null }) {
  return (
    <div className="ide-minimap">
      <div className="ide-minimap-inner">
        {SCENE_OBJECTS.map((o) => (
          <div
            key={o.id}
            className="ide-minimap-node"
            style={{
              left: `${o.x}%`,
              top: `${o.y}%`,
              width: `${o.w}%`,
              height: `${o.h}%`,
              background: selectedId === o.id ? "var(--ide-pink)" : "rgba(255,255,255,0.35)",
            }}
          />
        ))}
        <div className="ide-minimap-frame" />
      </div>
    </div>
  );
}

/* ═══════════════════════════════ GAME VIEW ═══════════════════════════════ */

export function GameViewPanel({ onPopout }: { onPopout?: () => void }) {
  return (
    <Panel
      title="Live · What viewers see"
      icon="broadcast"
      onPopout={onPopout}
      actions={
        <span
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 5,
            padding: "0 6px",
            fontFamily: "var(--ide-font-mono)",
            fontSize: 10,
            color: "var(--ide-hot-pink)",
          }}
        >
          <span
            style={{
              width: 6,
              height: 6,
              borderRadius: "50%",
              background: "var(--ide-hot-pink)",
              boxShadow: "0 0 6px var(--ide-hot-pink)",
            }}
          />
          1.2K
        </span>
      }
    >
      <div className="ide-viewport">
        {/* Phase F : la Live preview rend le même canvas Three.js que
            SceneView mais en mode "preview" — gizmos cachés, caméra figée
            sur DEFAULT_SCENE_CAMERA de l'adapter. La SVG silhouette Phase A
            est retirée : on montre ce que le viewer verra réellement, pas
            un mock. Les overlays "chat" et "title" sont conservés car ils
            simulent l'UI OBS (hors scope du viewer 3D). */}
        <div className="ide-scene-canvas game-view">
          <ViewerAdapter viewMode="preview" />

          <div
            style={{
              position: "absolute",
              right: "3%",
              top: "8%",
              width: "32%",
              background: "rgba(18,14,30,0.7)",
              backdropFilter: "blur(16px)",
              border: "1px solid rgba(224,142,254,0.3)",
              borderRadius: 8,
              padding: "6px 8px",
              fontSize: 7,
              color: "#f4ecff",
            }}
          >
            <div
              style={{
                fontSize: 5,
                letterSpacing: "0.12em",
                textTransform: "uppercase",
                color: "var(--ide-pink)",
                marginBottom: 3,
              }}
            >
              ✦ chat
            </div>
            <div style={{ marginBottom: 2 }}>
              <b style={{ color: "#fd6c9c" }}>nova_chan:</b> welcome back!!
            </div>
            <div style={{ marginBottom: 2 }}>
              <b style={{ color: "#81ecff" }}>pixelking:</b> shugu so cute
            </div>
            <div>
              <b style={{ color: "#7fe3b0" }}>kira:</b> !dance
            </div>
          </div>

          <div
            style={{
              position: "absolute",
              left: "3%",
              bottom: "5%",
              padding: "4px 10px",
              background: "linear-gradient(90deg, rgba(224,142,254,0.25), transparent)",
              borderLeft: "2px solid var(--ide-pink)",
              fontSize: 9,
              color: "#f4ecff",
            }}
          >
            <div style={{ fontFamily: "var(--ide-font-display)", fontWeight: 700 }}>SHUGU</div>
            <div
              style={{
                fontSize: 6,
                color: "var(--ide-text-dim)",
                letterSpacing: "0.15em",
              }}
            >
              VTUBER · JUST CHATTING
            </div>
          </div>

          <div className="ide-scene-canvas-label">
            <span style={{ color: "var(--ide-hot-pink)" }}>● REC</span>
            <span>1080p60 · 6500 kbps</span>
            <span>00:42:18</span>
          </div>
        </div>
      </div>
    </Panel>
  );
}

/* ═══════════════════════════════ HIERARCHY ═══════════════════════════════ */

type HierarchyProps = {
  selectedId?: string | null;
  onSelect?: (id: string) => void;
  onPopout?: () => void;
};

export function HierarchyPanel({ selectedId, onSelect, onPopout }: HierarchyProps) {
  // Phase B : l'arbre vit dans le store et les toggles passent par des actions
  // du store. Ça débloque l'undo/redo ⌘Z sur ces gestes (partialize inclut
  // `hierarchy` dans le temporal snapshot), et ça prépare Phase D où l'arbre
  // sera synchronisé cross-operator via WebSocket.
  const nodes = useSceneEditorStore(selectHierarchy);
  const toggleVisible = useSceneEditorStore((s) => s.toggleNodeVisibility);
  const toggleLock = useSceneEditorStore((s) => s.toggleNodeLock);
  const ctxMenu = useCtxMenu();

  const handleCtx = (node: TreeNodeData, e: React.MouseEvent) => {
    ctxMenu({
      x: e.clientX,
      y: e.clientY,
      items: [
        { label: "Rename", shortcut: "F2" },
        { label: "Duplicate", shortcut: "⌘D" },
        { label: "Group", shortcut: "⌘G" },
        { sep: true },
        { label: "Lock", onClick: () => toggleLock(node.id) },
        { label: "Hide", onClick: () => toggleVisible(node.id) },
        { sep: true },
        { label: "Delete", shortcut: "⌫", danger: true },
      ],
    });
  };

  return (
    <Panel
      title="Hierarchy"
      icon="layers"
      onPopout={onPopout}
      actions={
        <>
          <button className="ide-panel-btn" title="Add object">
            <Icon name="plus" size={11} />
          </button>
          <button className="ide-panel-btn" title="Filter">
            <Icon name="search" size={10} />
          </button>
        </>
      }
    >
      <Treeview
        nodes={nodes}
        selectedId={selectedId}
        onSelect={onSelect}
        onContextMenu={handleCtx}
        toggleVisible={toggleVisible}
        toggleLock={toggleLock}
      />
    </Panel>
  );
}

/* ═══════════════════════════════ INSPECTOR ═══════════════════════════════ */

type InspectorProps = { selectedId?: string | null; onPopout?: () => void };

export function InspectorPanel({ selectedId: _selectedId, onPopout }: InspectorProps) {
  // Phase B : l'Inspector tire son contenu depuis le selector
  // `selectCurrentInspector` qui combine `selectedId` + `inspectorById`. Le
  // prop `selectedId` reste accepté pour compat API mais est ignoré au
  // profit du store — les deux sont forcément égaux tant que `onSelect`
  // utilise `useSceneEditorStore.setSelectedId` (ce qui est le cas depuis
  // SceneEditorApp refactor).
  const data: InspectorData | null = useSceneEditorStore(selectCurrentInspector);
  // Phase F : on lit selectedId du store pour que l'attribute
  // `data-inspector-selected-id` soit **la** vérité observable par les tests
  // E2E (pas le prop legacy qui est devenu un fossile d'API).
  const selectedId = useSceneEditorStore(selectSelectedId);
  void _selectedId;

  if (!data) {
    return (
      <Panel title="Inspector" icon="sliders" onPopout={onPopout}>
        <div style={PANEL_CENTERED_EMPTY}>
          <Icon name="wand" size={28} className="glyph" />
          <div style={{ marginTop: 8 }}>
            Select an object in the scene or hierarchy to edit its properties.
          </div>
        </div>
      </Panel>
    );
  }

  return (
    <Panel title={`Inspector · ${data.kind}`} icon="sliders" onPopout={onPopout}>
      <div
        style={{
          padding: "10px 10px 6px",
          borderBottom: "1px solid var(--ide-divider)",
          display: "flex",
          alignItems: "center",
          gap: 8,
        }}
      >
        <input
          type="text"
          defaultValue={data.name}
          style={{
            flex: 1,
            height: 26,
            background: "rgba(0,0,0,0.35)",
            border: "1px solid var(--ide-divider)",
            borderRadius: 5,
            color: "var(--ide-text)",
            padding: "0 8px",
            fontSize: 12,
            fontFamily: "var(--ide-font-ui)",
            fontWeight: 600,
            outline: "none",
          }}
        />
        <Switch checked />
      </div>

      {/* Phase F : data-attributes exposent les valeurs transform courantes
          pour que les tests E2E (gizmo drag → Inspector) puissent asserter
          sans traverser le DOM complexe de `XYZ` (6 inputs). On met à 3
          décimales pour que la comparaison de tests reste déterministe
          face aux float64 roundings du TransformControls. */}
      <div
        data-testid="inspector-transform"
        data-inspector-selected-id={selectedId ?? ""}
        data-inspector-pos-x={data.transform.pos[0].toFixed(3)}
        data-inspector-pos-y={data.transform.pos[1].toFixed(3)}
        data-inspector-pos-z={data.transform.pos[2].toFixed(3)}
        data-inspector-rot-y={data.transform.rot[1].toFixed(3)}
      >
        <PropSection
          title="Transform"
          actions={
            <button className="ide-panel-btn" title="Reset">
              <Icon name="undo" size={10} />
            </button>
          }
        >
          <PropRow label="Position"><XYZ value={data.transform.pos} /></PropRow>
          <PropRow label="Rotation"><XYZ value={data.transform.rot} /></PropRow>
          <PropRow label="Scale"><XYZ value={data.transform.scale} /></PropRow>
        </PropSection>
      </div>

      {data.vrm && (
        <PropSection title="VRM Avatar">
          <PropRow label="Model">
            <div className="ide-color" style={{ flex: 1 }}>
              <Icon name="person" size={11} />
              <span>{data.vrm.model}</span>
            </div>
          </PropRow>
          <PropRow label="Expression">
            <Select
              value={data.vrm.expression}
              options={["Neutral", "Happy", "Sad", "Angry", "Surprised", "Relaxed", "Shy"]}
            />
          </PropRow>
          <PropRow label="Blink"><Switch checked={data.vrm.blink} /></PropRow>
          <PropRow label="Look at cam"><Switch checked={data.vrm.lookAtCamera} /></PropRow>
        </PropSection>
      )}

      {data.render && (
        <PropSection title="Render">
          <PropRow label="Opacity"><Slider value={data.render.opacity} /></PropRow>
          {data.render.outline != null && (
            <PropRow label="Outline"><Switch checked={data.render.outline} /></PropRow>
          )}
          {data.render.outlineColor && (
            <PropRow label="Outline col"><ColorPicker value={data.render.outlineColor} /></PropRow>
          )}
          {data.render.rimLight != null && (
            <PropRow label="Rim light"><Slider value={data.render.rimLight} /></PropRow>
          )}
          {data.render.shadow != null && (
            <PropRow label="Cast shadow"><Switch checked={data.render.shadow} /></PropRow>
          )}
          {data.render.tint && (
            <PropRow label="Tint"><ColorPicker value={data.render.tint} /></PropRow>
          )}
          {data.render.blur != null && (
            <PropRow label="Blur"><Slider value={data.render.blur} min={0} max={20} step={0.1} /></PropRow>
          )}
          {data.render.parallax != null && (
            <PropRow label="Parallax"><Slider value={data.render.parallax} /></PropRow>
          )}
        </PropSection>
      )}

      {data.camera && (
        <PropSection title="Camera">
          <PropRow label="FOV">
            <Slider
              value={data.camera.fov}
              min={10}
              max={120}
              step={1}
              format={(v) => `${v.toFixed(0)}°`}
            />
          </PropRow>
          <PropRow label="Near"><Num value={data.camera.near} unit="m" /></PropRow>
          <PropRow label="Far"><Num value={data.camera.far} unit="m" /></PropRow>
          <PropRow label="DOF"><Switch checked={data.camera.dof} /></PropRow>
          <PropRow label="Focus"><Num value={data.camera.focusDistance} unit="m" /></PropRow>
          <PropRow label="Aperture">
            <Slider
              value={data.camera.aperture}
              min={1.4}
              max={22}
              step={0.1}
              format={(v) => `f/${v.toFixed(1)}`}
            />
          </PropRow>
        </PropSection>
      )}

      {data.tracking && (
        <PropSection title="Tracking" defaultOpen={false}>
          <PropRow label="Source">
            <Select
              value={data.tracking.source}
              options={["iPhone LiveLink", "Webcam", "AI-driven", "Manual"]}
            />
          </PropRow>
          <PropRow label="Smoothing"><Slider value={data.tracking.blendshapeSmoothing} /></PropRow>
          <PropRow label="Hand track"><Switch checked={data.tracking.handTracking} /></PropRow>
        </PropSection>
      )}
    </Panel>
  );
}

/* Small helper re-export for convenience */
export type { IconName, ReactNode };
