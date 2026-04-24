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
  TabStrip,
  type IconName,
  type TabDef,
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
import { MOCK_SCENES } from "./mock-data";
import { HotkeyToast, useHotkeys, useToast, type Tool } from "./hotkeys";

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

type DockLayout = Record<DockId, { tabs: PanelKey[]; active: PanelKey }>;

const DEFAULT_LAYOUT: DockLayout = {
  viewport: { tabs: ["scene", "live"], active: "scene" },
  right:    { tabs: ["inspector", "effects", "stream", "perf"], active: "inspector" },
  bottom:   { tabs: ["assets", "timeline", "patterns", "mixer"], active: "assets" },
};

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
  w.document.title = `Shugu · ${title}`;
  const styles = [...document.querySelectorAll("link[rel=stylesheet], style")]
    .map((el) => el.outerHTML)
    .join("\n");
  w.document.body.innerHTML = `
    <style>body{margin:0;background:#05050a;color:#f4ecff;}</style>
    ${styles}
    <div class="ide-root" style="height:100vh;width:100vw;">
      <div class="ide-menubar" style="height:28px">
        <div class="ide-menubar-brand">
          <div class="mark">S</div>
          <span style="font-size:11px">${title}</span>
        </div>
        <div class="ide-menubar-spacer"></div>
        <div class="ide-menubar-status"><span>Detached window</span></div>
      </div>
      <div style="flex:1;display:flex;padding:8px;min-height:0;">
        <div id="popout-root" style="flex:1;"></div>
      </div>
    </div>
  `;
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
  const [selectedId, setSelectedId] = useState<string | null>("shugu");
  const [tool, setTool] = useState<Tool>("move");
  const [layoutPreset, setLayoutPreset] = useState("Streaming");
  const [currentScene] = useState("s2");
  const [leftW, setLeftW] = useState(240);
  const [rightW, setRightW] = useState(320);
  const [bottomH, setBottomH] = useState(260);
  const [dockLayout, setDockLayout] = useState<DockLayout>(DEFAULT_LAYOUT);

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
    [showToast],
  );

  useHotkeys({
    setTool,
    undo:          () => {},
    redo:          () => {},
    duplicate:     () => {},
    save:          () => {},
    deleteSelected: () => setSelectedId(null),
    frameAll:       () => {},
    focusSelected:  () => {},
    togglePlay:     () => {},
    selectPanel,
    toast:          showToast,
  });

  const sceneName = MOCK_SCENES.find((s) => s.id === currentScene)?.name ?? "—";

  return (
    <DragDropContext.Provider value={dndCtx}>
      <CtxMenuProvider>
        <div className="ide-root">
          <Menubar onExit={onExit} />
          <MainToolbar tool={tool} setTool={setTool} layout={layoutPreset} setLayout={setLayoutPreset} />

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
                onResize={(d) => setLeftW((w) => Math.max(180, Math.min(400, w + d)))}
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
                onResize={(d) => setRightW((w) => Math.max(260, Math.min(460, w - d)))}
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
              onResize={(d) => setBottomH((h) => Math.max(160, Math.min(500, h - d)))}
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
