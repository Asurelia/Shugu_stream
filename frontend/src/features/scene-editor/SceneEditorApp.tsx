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

function popOutPanel(panelKey: string, title: string): Window | null {
  const w = window.open(
    "",
    `shugu-${panelKey}`,
    "width=520,height=640,menubar=no,toolbar=no,location=no,status=no",
  );
  if (!w) return null;

  // Note Phase B (fix nit L1 review Phase A) : on construit le shell popout
  // via DOM createElement + textContent plutôt que innerHTML pour neutraliser
  // toute possibilité d'injection via `title`. Le design bundle utilisait
  // innerHTML avec interpolation directe — acceptable car les call sites
  // passent des chaînes statiques aujourd'hui, mais Phase D introduira des
  // noms de scène user-controlled dans ce chemin. Les chaînes "styles"
  // viennent du document parent (trusted, statiques au build Next) donc on
  // les clone via `cloneNode(true)` qui préserve la structure sans parsing.
  const doc = w.document;
  doc.title = `Shugu · ${title}`;

  // Wipe any pre-existing body content for idempotence (re-popping out the
  // same panel name réutilise la même fenêtre par window.open convention).
  while (doc.body.firstChild) doc.body.removeChild(doc.body.firstChild);

  // Phase B (fix L-2 review) : les feuilles de style sont clonées dans
  // `<head>` pour éviter un FOUC et respecter la sémantique HTML. Phase A
  // les mettait dans `<body>` via innerHTML — non-bloquant mais théoriquement
  // render-blocking hors head selon le user-agent.
  const baseStyle = doc.createElement("style");
  baseStyle.textContent = "body{margin:0;background:#05050a;color:#f4ecff;}";
  doc.head.appendChild(baseStyle);

  // Clone les feuilles de style du document parent pour que les classes
  // `.ide-*` rendent identiquement dans la popup.
  const parentStyles = document.querySelectorAll("link[rel=stylesheet], style");
  parentStyles.forEach((el) => {
    doc.head.appendChild(el.cloneNode(true));
  });

  // Root container
  const root = doc.createElement("div");
  root.className = "ide-root";
  root.style.cssText = "height:100vh;width:100vw;";

  // Menubar
  const menubar = doc.createElement("div");
  menubar.className = "ide-menubar";
  menubar.style.height = "28px";

  const brand = doc.createElement("div");
  brand.className = "ide-menubar-brand";
  const mark = doc.createElement("div");
  mark.className = "mark";
  mark.textContent = "S";
  brand.appendChild(mark);
  const titleSpan = doc.createElement("span");
  titleSpan.style.fontSize = "11px";
  // textContent = escape natif → aucun risque XSS même si `title` contient
  // du HTML ou des guillemets. C'est la substance du fix L1.
  titleSpan.textContent = title;
  brand.appendChild(titleSpan);
  menubar.appendChild(brand);

  const spacer = doc.createElement("div");
  spacer.className = "ide-menubar-spacer";
  menubar.appendChild(spacer);

  const status = doc.createElement("div");
  status.className = "ide-menubar-status";
  const statusSpan = doc.createElement("span");
  statusSpan.textContent = "Detached window";
  status.appendChild(statusSpan);
  menubar.appendChild(status);

  root.appendChild(menubar);

  // Body area avec le popout-root que les consumers React peuvent cibler
  // plus tard (Phase G — actuellement pas utilisé mais préservé pour compat).
  const bodyWrap = doc.createElement("div");
  bodyWrap.style.cssText = "flex:1;display:flex;padding:8px;min-height:0;";
  const popoutRoot = doc.createElement("div");
  popoutRoot.id = "popout-root";
  popoutRoot.style.flex = "1";
  bodyWrap.appendChild(popoutRoot);
  root.appendChild(bodyWrap);

  doc.body.appendChild(root);

  return w;
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

  const handlePopout = useCallback((key: PanelKey) => {
    popOutPanel(key, PANEL_META[key].title);
  }, []);

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
                  onPopout={() => popOutPanel("hierarchy", "Hierarchy")}
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
