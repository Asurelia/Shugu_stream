/**
 * Scene Editor — app shell : menubar, toolbar, docks, pop-out windows.
 *
 * Gère 3 features transverses côté UI :
 *  - hotkeys globaux (W/E/R, F, A, Space, Del, ⌘Z/⌘⇧Z, ⌘D, ⌘S, 1-8) via
 *    `./hotkeys` + toast éphémère
 *  - drag & drop Assets → viewport via `DragDropContext` partagé
 *  - docking avancé : les tabs des 3 docks (viewport / right / bottom)
 *    peuvent être tirées d'un dock à l'autre. L'état vit ici dans
 *    `dockLayout`.
 *
 * Exporte `<SceneEditorApp />` que la page Next consomme directement.
 * Toute la navigation externe (back to admin) est paramétrable via `onExit`.
 */

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type DragEvent,
  type ReactNode,
} from "react";
import {
  DragDropContext,
  useDragDrop,
  type DockId,
  type DragPayload,
  type PanelKey as SharedPanelKey,
} from "./dnd-context";
import type { AssetItem } from "./mock-data";

export { useDragDrop } from "./dnd-context";
import {
  CtxMenuProvider,
  Icon,
  Select,
  Splitter,
  StatusBar,
  TBBtn,
  type IconName,
} from "./primitives";
import {
  GameViewPanel,
  HierarchyPanel,
  InspectorPanel,
  SceneViewPanel,
} from "./panels-main";
import {
  AssetsPanel,
  FXPanel,
  MixerPanel,
  PatternsPanel,
  PerfPanel,
  StreamPanel,
  TimelinePanel,
} from "./panels-aux";
import { HotkeyToast, useHotkeys, useToast, type Tool } from "./hotkeys";
// Phase G : helper popout multi-écran via BroadcastChannel. Remplace la
// logique `window.open` inline qui vivait ici et ajoute la sync
// bidirectionnelle parent ↔ popout.
import {
  openPanelWindow,
  publishPopout,
  subscribePopout,
  flushPopout,
  type PopoutMessage,
} from "@/lib/editorPopout";
// Phase B : le shell consomme maintenant les stores Zustand. useState locaux
// supprimés au profit de selectors (plus testables, permettent undo/redo
// global via zundo, et persistence du dock layout en localStorage).
import {
  useSceneEditorStore,
  selectCurrentScene,
  selectSelectedId,
  selectTool,
  selectLayoutPreset,
  selectScenes,
  LAYOUT_PRESETS,
  type LayoutPreset,
} from "@/stores/useSceneEditorStore";
import { useDockLayoutStore } from "@/stores/useDockLayoutStore";
// Phase D : on monte `useEditorWebSocket(currentScene)` une fois le store
// lu. Le hook gère son propre cycle de vie (connect / subscribe / cleanup)
// et ne dépend d'aucune prop passée ici — c'est intentionnel pour que la
// démo verbatim Phase A reste agnostique du backend.
import { useEditorWebSocket } from "@/lib/useEditorWebSocket";

/* ─────────────────────────── MENU DEFINITION ─────────────────────────── */

type MenuItem = { sep?: false; label: string; shortcut?: string } | { sep: true };

const MENUS: Record<string, MenuItem[]> = {
  File: [
    { label: "New Scene",     shortcut: "⌘N" },
    { label: "Open…",         shortcut: "⌘O" },
    { label: "Open Recent",   shortcut: "▸" },
    { sep: true },
    { label: "Save Scene",    shortcut: "⌘S" },
    { label: "Save As…",      shortcut: "⇧⌘S" },
    { label: "Export…",       shortcut: "⌘E" },
    { sep: true },
    { label: "Import assets…" },
    { label: "Project settings…" },
  ],
  Edit: [
    { label: "Undo",     shortcut: "⌘Z" },
    { label: "Redo",     shortcut: "⇧⌘Z" },
    { sep: true },
    { label: "Cut",      shortcut: "⌘X" },
    { label: "Copy",     shortcut: "⌘C" },
    { label: "Paste",    shortcut: "⌘V" },
    { label: "Duplicate",shortcut: "⌘D" },
    { sep: true },
    { label: "Preferences…" },
  ],
  Scene: [
    { label: "Add empty",  shortcut: "⇧A" },
    { label: "Add VRM…",   shortcut: "⇧⌘V" },
    { label: "Add overlay…" },
    { sep: true },
    { label: "Focus selected", shortcut: "F" },
    { label: "Frame all",      shortcut: "A" },
    { label: "Reset transforms" },
  ],
  Window: [
    { label: "Scene view",   shortcut: "1" },
    { label: "Live preview", shortcut: "2" },
    { label: "Hierarchy",    shortcut: "3" },
    { label: "Inspector",    shortcut: "4" },
    { label: "Assets",       shortcut: "5" },
    { label: "Timeline",     shortcut: "6" },
    { label: "Patterns",     shortcut: "7" },
    { label: "Mixer",        shortcut: "8" },
    { sep: true },
    { label: "Pop out active panel", shortcut: "⇧P" },
    { label: "Reset layout" },
  ],
  Go: [
    { label: "Go live",     shortcut: "⌘↵" },
    { label: "Stop stream", shortcut: "⇧⌘↵" },
    { sep: true },
    { label: "Switch scene ▸" },
  ],
  Help: [
    { label: "Shugu docs" },
    { label: "Keyboard shortcuts", shortcut: "⌘/" },
    { label: "About Shugu Editor" },
  ],
};

/* ─────────────────────────── PANEL REGISTRY ─────────────────────────── */

export type PanelKey = SharedPanelKey;

type PanelMeta = { label: string; icon: IconName; title: string };

const PANEL_META: Record<PanelKey, PanelMeta> = {
  scene:     { label: "Scene",     icon: "scene",     title: "Scene view" },
  live:      { label: "Live",      icon: "broadcast", title: "Live preview" },
  inspector: { label: "Inspector", icon: "sliders",   title: "Inspector" },
  effects:   { label: "FX",        icon: "fx",        title: "Post-process" },
  stream:    { label: "Stream",    icon: "broadcast", title: "Stream" },
  perf:      { label: "Perf",      icon: "chart",     title: "Performance" },
  assets:    { label: "Assets",    icon: "folder",    title: "Assets" },
  timeline:  { label: "Timeline",  icon: "clock",     title: "Timeline" },
  patterns:  { label: "Patterns",  icon: "wand",      title: "Patterns" },
  mixer:     { label: "Mixer",     icon: "audio",     title: "Audio Mixer" },
};

/* Quick-key hotkeys (Window menu) — 1→Scene, 2→Live, … */
const HOTKEY_PANELS: Record<number, PanelKey> = {
  1: "scene",
  2: "live",
  3: "inspector",
  4: "assets",
  5: "timeline",
  6: "patterns",
  7: "mixer",
  8: "effects",
};

/* ─────────────────────────── DOCK LAYOUT ─────────────────────────── */

// Phase B (fix L-1 review) : le type `DockLayout` et les defaults vivaient
// en double ici et dans `useDockLayoutStore`. On tire désormais depuis le
// store pour éviter une éventuelle dérive silencieuse (si un panel est
// ajouté côté store sans toucher à cette déclaration).
import type { DockLayout } from "@/stores/useDockLayoutStore";

/* ─────────────────────────── MENUBAR ─────────────────────────── */

function Menubar({ onExit }: { onExit?: () => void }) {
  const [open, setOpen] = useState<string | null>(null);

  useEffect(() => {
    const close = () => setOpen(null);
    window.addEventListener("click", close);
    return () => window.removeEventListener("click", close);
  }, []);

  const backBtnStyle: CSSProperties = {
    height: 22,
    padding: "0 10px 0 8px",
    marginRight: 6,
    display: "inline-flex",
    alignItems: "center",
    gap: 6,
    background: "linear-gradient(135deg, rgba(224,142,254,0.15), rgba(253,108,156,0.1))",
    border: "1px solid rgba(224,142,254,0.3)",
    borderRadius: 5,
    color: "var(--ide-text)",
    fontFamily: "var(--ide-font-ui)",
    fontSize: 11,
    fontWeight: 600,
    cursor: "pointer",
  };

  return (
    <div className="ide-menubar">
      <button
        type="button"
        onClick={onExit}
        title="Back to admin dashboard"
        style={backBtnStyle}
      >
        <span style={{ display: "inline-block", transform: "rotate(180deg)", lineHeight: 0 }}>
          <Icon name="caret" size={10} />
        </span>
        <span>Admin</span>
      </button>

      <div className="ide-menubar-brand">
        <div className="mark">S</div>
        <span style={{ fontSize: 12, color: "var(--ide-text)" }}>Shugu&nbsp;</span>
        <span style={{ fontSize: 11, color: "var(--ide-text-dim)" }}>Scene Editor</span>
      </div>

      {Object.keys(MENUS).map((k) => (
        <div
          key={k}
          className={`ide-menubar-item ${open === k ? "open" : ""}`}
          onClick={(e) => { e.stopPropagation(); setOpen(open === k ? null : k); }}
          onMouseEnter={() => open && setOpen(k)}
        >
          {k}
          {open === k && (
            <div className="ide-menu-dropdown" onClick={(e) => e.stopPropagation()}>
              {MENUS[k].map((it, i) =>
                "sep" in it && it.sep ? (
                  <div key={i} className="sep" />
                ) : (
                  <div key={i} className="item">
                    <span>{(it as { label: string }).label}</span>
                    {(it as { shortcut?: string }).shortcut && (
                      <span className="shortcut">{(it as { shortcut?: string }).shortcut}</span>
                    )}
                  </div>
                ),
              )}
            </div>
          )}
        </div>
      ))}

      <div className="ide-menubar-spacer" />
      <div className="ide-menubar-status">
        <span>main.scene · <span style={{ color: "var(--ide-amber)" }}>edited</span></span>
        <span className="live">Live · 42:18 · 1.2K</span>
      </div>
    </div>
  );
}

/* ─────────────────────────── TOOLBAR ─────────────────────────── */

function MainToolbar({
  tool, setTool, layout, setLayout,
}: {
  tool: Tool;
  setTool: (t: Tool) => void;
  layout: string;
  setLayout: (l: string) => void;
}) {
  return (
    <div className="ide-toolbar">
      <div className="ide-toolbar-group">
        <TBBtn icon="move"   active={tool === "move"}   onClick={() => setTool("move")}   title="Move (W)" />
        <TBBtn icon="rotate" active={tool === "rotate"} onClick={() => setTool("rotate")} title="Rotate (E)" />
        <TBBtn icon="scale"  active={tool === "scale"}  onClick={() => setTool("scale")}  title="Scale (R)" />
      </div>
      <div className="ide-toolbar-group">
        <TBBtn icon="undo" title="Undo (⌘Z)" />
        <TBBtn icon="redo" title="Redo (⇧⌘Z)" />
      </div>
      <div className="ide-toolbar-group">
        <TBBtn icon="person" label="Add VRM" />
        <TBBtn icon="image"  label="Add BG" />
        <TBBtn icon="text"   label="Overlay" />
        <TBBtn icon="fx"     label="FX" />
      </div>
      <div className="ide-toolbar-group">
        <TBBtn icon="wand"  label="Record pattern" />
        <TBBtn icon="bolt"  label="Trigger…" />
      </div>
      <div style={{ flex: 1 }} />
      <div className="ide-toolbar-group">
        <Select
          value={layout}
          options={["Streaming", "Editing", "Performance", "Custom…"]}
          onChange={setLayout}
        />
      </div>
      <div className="ide-toolbar-group">
        <TBBtn icon="broadcast" label="Go Live" primary />
      </div>
    </div>
  );
}

/* ─────────────────────────── POP-OUT ─────────────────────────── */

/**
 * Phase G : la logique `window.open` + injection DOM manuelle qui vivait
 * ici a été déplacée dans `@/lib/editorPopout` et s'appuie désormais sur
 * une vraie route Next.js (`/shugu/admin/scene-editor-popout?panel=xxx`)
 * qui monte React proprement et parle au parent via BroadcastChannel.
 *
 * On garde ce wrapper uniquement comme point d'entrée du shell — il est
 * appelé par `handlePopout` (MAIN APP) avec registration au tracking des
 * fenêtres ouvertes pour un cleanup propre à l'unmount.
 */
function popOutPanel(panelKey: string): Window | null {
  return openPanelWindow(panelKey);
}

/* ─────────────────────────── PANEL RENDERER ─────────────────────────── */

function renderPanel(
  key: PanelKey,
  ctx: {
    selectedId: string | null;
    onSelect: (id: string | null) => void;
    onPopout: (k: PanelKey) => void;
  },
): ReactNode {
  const pop = () => ctx.onPopout(key);
  switch (key) {
    case "scene":     return <SceneViewPanel selectedId={ctx.selectedId} onSelect={ctx.onSelect} onPopout={pop} />;
    case "live":      return <GameViewPanel  onPopout={pop} />;
    case "inspector": return <InspectorPanel selectedId={ctx.selectedId} onPopout={pop} />;
    case "effects":   return <FXPanel        onPopout={pop} />;
    case "stream":    return <StreamPanel    onPopout={pop} />;
    case "perf":      return <PerfPanel      onPopout={pop} />;
    case "assets":    return <AssetsPanel    onPopout={pop} />;
    case "timeline":  return <TimelinePanel  onPopout={pop} />;
    case "patterns":  return <PatternsPanel  onPopout={pop} />;
    case "mixer":     return <MixerPanel     onPopout={pop} />;
  }
}

/* ─────────────────────────── DOCK (tab container) ─────────────────────────── */

type DockProps = {
  dockId: DockId;
  tabs: PanelKey[];
  active: PanelKey;
  layout: DockLayout;
  setLayout: (l: DockLayout) => void;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  onPopout: (k: PanelKey) => void;
};

function Dock(props: DockProps) {
  const { dockId, tabs, active, layout, setLayout, selectedId, onSelect, onPopout } = props;
  const { payload, setPayload } = useDragDrop();
  const [dropHint, setDropHint] = useState<{ index: number; side: "before" | "after" } | null>(null);
  const [dockHover, setDockHover] = useState(false);

  const isTabDrag = payload?.kind === "tab";

  const handleSelect = (id: string) => {
    setLayout({ ...layout, [dockId]: { ...layout[dockId], active: id as PanelKey } });
  };

  // ── Tab-level drag & drop ─────────────────────────────────────────
  const onTabDragStart = (panel: PanelKey) => (e: DragEvent<HTMLDivElement>) => {
    setPayload({ kind: "tab", panel, fromDock: dockId });
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", `shugu-tab:${panel}`);
    (e.currentTarget as HTMLElement).classList.add("dragging");
  };
  const onTabDragEnd = (e: DragEvent<HTMLDivElement>) => {
    setPayload(null);
    setDropHint(null);
    (e.currentTarget as HTMLElement).classList.remove("dragging");
  };
  const onTabDragOver = (i: number) => (e: DragEvent<HTMLDivElement>) => {
    if (!isTabDrag) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
    const side = e.clientX < r.left + r.width / 2 ? "before" : "after";
    setDropHint({ index: i, side });
  };
  const onTabDrop = (i: number) => (e: DragEvent<HTMLDivElement>) => {
    if (!isTabDrag || !payload) return;
    e.preventDefault();
    e.stopPropagation();
    const side = dropHint?.side ?? "after";
    moveTab(payload, dockId, i + (side === "after" ? 1 : 0), layout, setLayout);
    setDropHint(null);
    setPayload(null);
  };

  // ── Dock-level drop (empty area or first tab) ─────────────────────
  const onDockDragOver = (e: DragEvent<HTMLDivElement>) => {
    if (!isTabDrag) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    setDockHover(true);
  };
  const onDockDragLeave = () => setDockHover(false);
  const onDockDrop = (e: DragEvent<HTMLDivElement>) => {
    if (!isTabDrag || !payload) return;
    e.preventDefault();
    if (!dropHint) moveTab(payload, dockId, tabs.length, layout, setLayout);
    setDockHover(false);
    setDropHint(null);
    setPayload(null);
  };

  return (
    <div
      style={{ display: "flex", flexDirection: "column", height: "100%", minHeight: 0, position: "relative" }}
      onDragOver={onDockDragOver}
      onDragLeave={onDockDragLeave}
      onDrop={onDockDrop}
    >
      <div className="ide-tabstrip" style={{ position: "relative" }}>
        {tabs.map((t, i) => {
          const meta = PANEL_META[t];
          const isActive = t === active;
          const hintCls =
            dropHint?.index === i
              ? dropHint.side === "before" ? "drop-before" : "drop-after"
              : "";
          return (
            <div
              key={t}
              className={`ide-tab ${isActive ? "active" : ""} ${hintCls}`}
              draggable
              onClick={() => handleSelect(t)}
              onDragStart={onTabDragStart(t)}
              onDragEnd={onTabDragEnd}
              onDragOver={onTabDragOver(i)}
              onDrop={onTabDrop(i)}
            >
              <Icon name={meta.icon} size={11} />
              <span>{meta.label}</span>
            </div>
          );
        })}
        <button
          className="ide-panel-btn"
          style={{ marginLeft: "auto", alignSelf: "center" }}
          title="Pop out active tab"
          onClick={() => onPopout(active)}
        >
          <Icon name="popout" size={11} />
        </button>
      </div>

      <div style={{ flex: 1, minHeight: 0, display: "flex", position: "relative" }}>
        {renderPanel(active, { selectedId, onSelect, onPopout })}
        {isTabDrag && (
          <div
            className={`ide-dock-dropzone ${dockHover ? "active" : ""}`}
            data-label={`Dock into ${dockId}`}
          />
        )}
      </div>
    </div>
  );
}

/* Move a tab within / between docks. Keeps at least 1 tab per dock. */
function moveTab(
  payload: DragPayload,
  toDock: DockId,
  toIndex: number,
  layout: DockLayout,
  setLayout: (l: DockLayout) => void,
) {
  if (payload.kind !== "tab") return;
  const { panel, fromDock } = payload;

  const next: DockLayout = {
    viewport: { tabs: [...layout.viewport.tabs], active: layout.viewport.active },
    right:    { tabs: [...layout.right.tabs],    active: layout.right.active },
    bottom:   { tabs: [...layout.bottom.tabs],   active: layout.bottom.active },
  };

  // Refuse to empty the source dock entirely (always keep at least one tab)
  if (fromDock !== toDock && next[fromDock].tabs.length <= 1) return;

  // Remove from source
  const srcTabs = next[fromDock].tabs;
  const fromIdx = srcTabs.indexOf(panel);
  if (fromIdx === -1) return;
  srcTabs.splice(fromIdx, 1);

  // Adjust target index if we removed from earlier in the same dock
  let insertAt = toIndex;
  if (fromDock === toDock && fromIdx < toIndex) insertAt -= 1;
  insertAt = Math.max(0, Math.min(next[toDock].tabs.length, insertAt));

  // Insert into target
  next[toDock].tabs.splice(insertAt, 0, panel);
  next[toDock].active = panel;

  // If source's active tab was removed, pick a neighbour
  if (next[fromDock].active === panel) {
    next[fromDock].active = next[fromDock].tabs[Math.min(fromIdx, next[fromDock].tabs.length - 1)];
  }

  setLayout(next);
}

/* ─────────────────────────── MAIN APP ─────────────────────────── */

export type SceneEditorAppProps = {
  /** Called when user clicks the "Admin" back button in the menubar. */
  onExit?: () => void;
};

export function SceneEditorApp({ onExit }: SceneEditorAppProps) {
  // Phase B : UI state tiré depuis `useSceneEditorStore`. Chaque selector
  // est scoped au champ strictement nécessaire pour ne re-render que quand
  // ce champ change (évite que le shell complet re-render quand l'utilisateur
  // bouge l'avatar par exemple).
  const selectedId = useSceneEditorStore(selectSelectedId);
  const setSelectedId = useSceneEditorStore((s) => s.setSelectedId);
  const tool = useSceneEditorStore(selectTool);
  const setTool = useSceneEditorStore((s) => s.setTool);
  const layoutPreset = useSceneEditorStore(selectLayoutPreset);
  const setLayoutPresetRaw = useSceneEditorStore((s) => s.setLayoutPreset);
  const currentScene = useSceneEditorStore(selectCurrentScene);

  // Phase D — branche la WS `/ws/editor` au store. Le hook ouvre la WS au
  // mount, appelle subscribe(currentScene) dès que c'est OPEN, et cleanup
  // au unmount. Les peers et remoteDraftDeltas sont mis à jour dans le
  // store via les actions addPeer / applyRemoteDraftUpdate.
  useEditorWebSocket(currentScene);

  // Phase B (fix H-1 review) : `LayoutPreset` est aligné verbatim sur les 4
  // options du Select MainToolbar ("Streaming" | "Editing" | "Performance"
  // | "Custom…"), donc le wrapper se contente de vérifier que la valeur
  // appartient bien à l'union avant de la pousser au store. En dev on warn
  // pour détecter un éventuel désalignement futur.
  const setLayoutPreset = useCallback(
    (name: string) => {
      if (LAYOUT_PRESETS.includes(name as LayoutPreset)) {
        setLayoutPresetRaw(name as LayoutPreset);
      } else if (process.env.NODE_ENV !== "production") {
        console.warn(
          `[SceneEditor] Ignoring unknown layout preset "${name}". ` +
            `Expected one of: ${LAYOUT_PRESETS.join(", ")}.`,
        );
      }
    },
    [setLayoutPresetRaw],
  );

  // Phase B : dock layout + splitter widths vivent dans useDockLayoutStore
  // (persist localStorage). Pour préserver la signature des callbacks
  // existants (port verbatim), on expose des setters qui appellent les
  // actions du store.
  const dockLayout = useDockLayoutStore((s) => s.dockLayout);
  const setDockLayoutRaw = useDockLayoutStore((s) => s.setDockLayout);
  const leftW = useDockLayoutStore((s) => s.leftW);
  const rightW = useDockLayoutStore((s) => s.rightW);
  const bottomH = useDockLayoutStore((s) => s.bottomH);
  const adjustLeftW = useDockLayoutStore((s) => s.adjustLeftW);
  const adjustRightW = useDockLayoutStore((s) => s.adjustRightW);
  const adjustBottomH = useDockLayoutStore((s) => s.adjustBottomH);

  // Wrapper compatible avec l'API `setDockLayout` du design (accepte valeur
  // ou updater). Permet à `Dock` et `selectPanel` de continuer à appeler
  // `setDockLayout((prev) => ...)` sans changement.
  const setDockLayout = useCallback(
    (next: DockLayout | ((prev: DockLayout) => DockLayout)) => {
      setDockLayoutRaw(next);
    },
    [setDockLayoutRaw],
  );

  // Note Phase B : les splitter width setters à l'ancienne (setLeftW /
  // setRightW / setBottomH) ne sont plus nécessaires car les callbacks des
  // Splitters utilisent maintenant directement `adjustLeftW/Right/Bottom`
  // (clamp min/max centralisé dans le store). Les valeurs brutes restent
  // lisibles via les selectors `leftW`, `rightW`, `bottomH`.

  // Drag payload shared across docks + assets
  const [dragPayload, setDragPayload] = useState<DragPayload | null>(null);
  const [droppedAsset, setDroppedAsset] = useState<AssetItem | null>(null);

  // Toast for hotkeys / drop feedback
  const { msg: toastMsg, show: showToast } = useToast();

  const dndCtx = useMemo(
    () => ({
      payload: dragPayload,
      setPayload: setDragPayload,
      droppedAsset,
      setDroppedAsset,
      toast: showToast,
    }),
    [dragPayload, droppedAsset, showToast],
  );

  /* ────────── Phase G — Pop-out multi-écran via BroadcastChannel ────────── */

  // Suivi des fenêtres popout ouvertes (une par panelKey max, car le
  // `windowName` de `openPanelWindow` est stable par panel → rouvrir re-focus).
  // On retient la ref pour pouvoir les close si le parent unmount, et pour
  // publier l'état initial dès qu'un popout signale `popout-ready`.
  const popoutWindowsRef = useRef<Map<PanelKey, Window>>(new Map());
  // Liste des panelKeys actuellement détachés (popout vivant). Permet de
  // re-publier un `state-sync` complet quand le store mute, sans spam si
  // aucun popout n'est ouvert.
  const [detachedPanels, setDetachedPanels] = useState<Set<PanelKey>>(
    () => new Set(),
  );
  // Ref pour lire la valeur la plus récente de `detachedPanels` depuis des
  // callbacks longs-vivants (subscribe Zustand). useState rerender mais les
  // closures capturent l'ancien Set si on ne passe pas par une ref.
  const detachedPanelsRef = useRef(detachedPanels);
  detachedPanelsRef.current = detachedPanels;

  // Flag anti-echo : quand on applique un `state-sync` reçu, on bypass le
  // publish outbound pour ne pas rebondir indéfiniment entre parent et popout.
  const applyingRemoteRef = useRef(false);

  /**
   * Construit un snapshot minimal du state à synchroniser. On n'envoie QUE
   * les champs réellement utiles au popout (selectedId, tool, layoutPreset,
   * currentScene). Pousser tout le store serait à la fois coûteux (mocks
   * volumineux) et inutile pour l'UX Phase G.
   */
  const snapshotSyncState = useCallback(() => {
    const s = useSceneEditorStore.getState();
    return {
      selectedId: s.selectedId,
      tool: s.tool,
      layoutPreset: s.layoutPreset,
      currentScene: s.currentScene,
    };
  }, []);

  /**
   * Applique un payload `state-sync` reçu au store Zustand. Protège contre
   * l'echo : pendant l'application on désactive le publish outbound.
   */
  const applyRemoteSync = useCallback(
    (payload: unknown) => {
      if (!payload || typeof payload !== "object") return;
      const p = payload as Partial<{
        selectedId: string | null;
        tool: Tool;
        layoutPreset: LayoutPreset;
        currentScene: string;
      }>;
      applyingRemoteRef.current = true;
      try {
        const store = useSceneEditorStore.getState();
        if (p.selectedId !== undefined && p.selectedId !== store.selectedId) {
          store.setSelectedId(p.selectedId);
        }
        if (p.tool !== undefined && p.tool !== store.tool) {
          store.setTool(p.tool);
        }
        if (
          p.layoutPreset !== undefined &&
          LAYOUT_PRESETS.includes(p.layoutPreset) &&
          p.layoutPreset !== store.layoutPreset
        ) {
          store.setLayoutPreset(p.layoutPreset);
        }
        if (
          p.currentScene !== undefined &&
          p.currentScene !== store.currentScene
        ) {
          store.setCurrentScene(p.currentScene);
        }
      } finally {
        // Release sur microtask pour laisser le subscribe s'exécuter avant
        // qu'on ne reprenne les publishes.
        queueMicrotask(() => {
          applyingRemoteRef.current = false;
        });
      }
    },
    [],
  );

  // Souscription globale au canal BroadcastChannel : tous les panels
  // partagent le même routing ici. Monté une seule fois au mount du shell.
  useEffect(() => {
    // Un handler par panelKey qui peut avoir un popout — on subscribe lazy
    // dès qu'un panel est détaché. Pour simplifier, on s'abonne à TOUS les
    // panel keys connus : le surcoût est nul (le filtre se fait à la
    // réception), et ça évite de gérer des subscribe/unsubscribe par cycle.
    const allKeys: PanelKey[] = Object.keys(PANEL_META) as PanelKey[];
    const unsubs: Array<() => void> = [];
    for (const key of allKeys) {
      const unsub = subscribePopout(key, (msg: PopoutMessage) => {
        // On ignore ses propres publishes (origin === 'parent') pour éviter
        // de s'auto-traiter. Seuls les messages venant du popout nous
        // intéressent côté parent.
        if (msg.origin !== "popout") return;
        switch (msg.type) {
          case "popout-ready":
            // Le popout vient de monter — on lui pousse le snapshot complet
            // pour qu'il parte aligné. Publish immédiat (debounce couvre
            // `state-sync`, pas les signaux).
            publishPopout({
              type: "state-sync",
              origin: "parent",
              panelKey: key,
              payload: snapshotSyncState(),
            });
            break;
          case "state-sync":
            // Mutation opérée dans le popout → on refléte côté parent.
            applyRemoteSync(msg.payload);
            break;
          case "popout-closed":
            // Fenêtre fermée proprement : on nettoie notre tracking.
            popoutWindowsRef.current.delete(key);
            setDetachedPanels((prev) => {
              if (!prev.has(key)) return prev;
              const next = new Set(prev);
              next.delete(key);
              return next;
            });
            break;
          case "panel-action":
            // Placeholder pour Phase G+ — pas d'usage dans Phase G strict.
            break;
        }
      });
      unsubs.push(unsub);
    }
    return () => {
      unsubs.forEach((u) => u());
    };
  }, [applyRemoteSync, snapshotSyncState]);

  // Republie les mutations locales vers les popouts quand le store change.
  // On subscribe directement à Zustand pour observer TOUS les change events
  // sans passer par un hook (ce qui causerait un re-render du shell entier).
  useEffect(() => {
    const unsub = useSceneEditorStore.subscribe((state, prev) => {
      if (applyingRemoteRef.current) return;
      const detached = detachedPanelsRef.current;
      if (detached.size === 0) return;
      // Ne publie que si un des champs sync a changé — évite du trafic
      // superflu (ex : toggle visibility d'un node dans hierarchy ne doit
      // pas déclencher de sync popout puisque ce champ n'est pas synced).
      const changed =
        state.selectedId !== prev.selectedId ||
        state.tool !== prev.tool ||
        state.layoutPreset !== prev.layoutPreset ||
        state.currentScene !== prev.currentScene;
      if (!changed) return;
      const payload = snapshotSyncState();
      detached.forEach((panelKey) => {
        publishPopout({
          type: "state-sync",
          origin: "parent",
          panelKey,
          payload,
        });
      });
    });
    return () => {
      unsub();
    };
  }, [snapshotSyncState]);

  // Poll des windows popout : si le user ferme la fenêtre via l'OS (sans
  // que le popout ait eu le temps d'envoyer `popout-closed`), on détecte
  // ça via `win.closed` et on nettoie. Interval raisonnable — 1s suffit,
  // pas besoin d'un check plus fin pour un détect de fermeture.
  useEffect(() => {
    if (detachedPanels.size === 0) return;
    const interval = setInterval(() => {
      const windows = popoutWindowsRef.current;
      windows.forEach((win, key) => {
        if (win.closed) {
          windows.delete(key);
          setDetachedPanels((prev) => {
            if (!prev.has(key)) return prev;
            const next = new Set(prev);
            next.delete(key);
            return next;
          });
        }
      });
    }, 1000);
    return () => clearInterval(interval);
  }, [detachedPanels]);

  // Cleanup final : flush le dernier state-sync en attente (debounce 50ms)
  // pour ne pas perdre une mutation effectuée juste avant un unmount.
  useEffect(() => {
    return () => {
      flushPopout();
    };
  }, []);

  const handlePopout = useCallback(
    (key: PanelKey) => {
      const existing = popoutWindowsRef.current.get(key);
      // Si la fenêtre existe encore et n'est pas closed, on re-focus au lieu
      // de rouvrir (convention du browser : same windowName = même tab).
      if (existing && !existing.closed) {
        try {
          existing.focus();
        } catch {
          /* certains browsers throw en focus cross-origin */
        }
        return;
      }
      const win = popOutPanel(key);
      if (!win) return;
      popoutWindowsRef.current.set(key, win);
      setDetachedPanels((prev) => {
        if (prev.has(key)) return prev;
        const next = new Set(prev);
        next.add(key);
        return next;
      });
      // Ne push pas de snapshot ici : on attend que le popout signale
      // `popout-ready` (sinon race condition — le popout peut ne pas encore
      // avoir monté son `subscribePopout`).
    },
    [],
  );

  // ── Hotkey wiring ────────────────────────────────────────────────
  const selectPanel = useCallback(
    (idx: number) => {
      const key = HOTKEY_PANELS[idx];
      if (!key) return;
      setDockLayout((prev) => {
        const dockId = findDockFor(prev, key);
        if (!dockId) return prev;
        showToast(`Focus · ${PANEL_META[key].label}`);
        return { ...prev, [dockId]: { ...prev[dockId], active: key } };
      });
    },
    [showToast, setDockLayout],
  );

  useHotkeys({
    setTool,
    // Phase B : branchage zundo sur les hotkeys ⌘Z / ⌘⇧Z. Le temporal store
    // suit `currentScene`, `layoutPreset`, `hierarchy` (cf. partialize dans
    // useSceneEditorStore). Les phases ultérieures élargiront le scope aux
    // vrais edits (avatar position, camera FOV, etc.).
    undo:          () => useSceneEditorStore.temporal.getState().undo(),
    redo:          () => useSceneEditorStore.temporal.getState().redo(),
    duplicate:     () => {},
    save:          () => {},
    deleteSelected: () => setSelectedId(null),
    frameAll:       () => {},
    focusSelected:  () => {},
    togglePlay:     () => {},
    selectPanel,
    toast:          showToast,
  });

  // Phase B (fix M-1 review) : le status bar tire la liste des scènes depuis
  // le store au lieu d'importer `MOCK_SCENES` directement, pour qu'un futur
  // `setScenes()` (Phase C quand on plug `/api/registry/scene`) propage
  // automatiquement au label.
  const scenes = useSceneEditorStore(selectScenes);
  const sceneName = scenes.find((s) => s.id === currentScene)?.name ?? "—";

  return (
    <DragDropContext.Provider value={dndCtx}>
      <CtxMenuProvider>
        <div className="ide-root">
          <Menubar onExit={onExit} />
          <MainToolbar
            tool={tool}
            setTool={setTool}
            layout={layoutPreset}
            setLayout={setLayoutPreset}
          />

          <div className="ide-workspace">
            <div className="ide-dock" style={{ flex: 1 }}>
              <div style={{ width: leftW, display: "flex", flexShrink: 0 }}>
                <HierarchyPanel
                  selectedId={selectedId}
                  onSelect={setSelectedId}
                  onPopout={() => popOutPanel("hierarchy")}
                />
              </div>
              <Splitter
                orientation="horizontal"
                onResize={(d) => adjustLeftW(d)}
              />

              <div style={{ flex: 1, display: "flex", minWidth: 0 }}>
                <Dock
                  dockId="viewport"
                  tabs={dockLayout.viewport.tabs}
                  active={dockLayout.viewport.active}
                  layout={dockLayout}
                  setLayout={setDockLayout}
                  selectedId={selectedId}
                  onSelect={setSelectedId}
                  onPopout={handlePopout}
                />
              </div>

              <Splitter
                orientation="horizontal"
                onResize={(d) => adjustRightW(d)}
              />
              <div style={{ width: rightW, display: "flex", flexShrink: 0 }}>
                <Dock
                  dockId="right"
                  tabs={dockLayout.right.tabs}
                  active={dockLayout.right.active}
                  layout={dockLayout}
                  setLayout={setDockLayout}
                  selectedId={selectedId}
                  onSelect={setSelectedId}
                  onPopout={handlePopout}
                />
              </div>
            </div>

            <Splitter
              orientation="vertical"
              onResize={(d) => adjustBottomH(d)}
            />

            <div style={{ height: bottomH, display: "flex", flexShrink: 0 }}>
              <Dock
                dockId="bottom"
                tabs={dockLayout.bottom.tabs}
                active={dockLayout.bottom.active}
                layout={dockLayout}
                setLayout={setDockLayout}
                selectedId={selectedId}
                onSelect={setSelectedId}
                onPopout={handlePopout}
              />
            </div>
          </div>

          <StatusBar
            items={[
              { icon: "scene", label: "Scene:", value: sceneName },
              { icon: "person", label: "Selected:", value: selectedId ?? "—" },
              { spacer: true },
              { kind: "ok",   dot: true, label: "Tracking:", value: "iPhone · 60fps" },
              { kind: "ok",   dot: true, label: "Audio:",    value: "48kHz · 8ms" },
              { kind: "warn", dot: true, label: "VRAM:",     value: "4.8/8 GB" },
              { kind: "ok",   dot: true, label: "Network:",  value: "6432 kbps" },
              { label: "·", value: "" },
              { label: "Shugu Editor v0.8.2" },
            ]}
          />

          <HotkeyToast msg={toastMsg} />
        </div>
      </CtxMenuProvider>
    </DragDropContext.Provider>
  );
}

function findDockFor(layout: DockLayout, key: PanelKey): DockId | null {
  if (layout.viewport.tabs.includes(key)) return "viewport";
  if (layout.right.tabs.includes(key)) return "right";
  if (layout.bottom.tabs.includes(key)) return "bottom";
  return null;
}

export default SceneEditorApp;
