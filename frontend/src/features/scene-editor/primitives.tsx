/**
 * Scene Editor — primitives partagées (Panel, TabStrip, Splitter, Treeview,
 * PropSection/PropRow, Num, XYZ, Slider, ColorPicker, Switch, Select, TBBtn,
 * StatusBar, ContextMenu, Icon).
 *
 * Le style est piloté par `styles/scene-editor.css` (classes `ide-*`).
 * Ces primitives sont volontairement agnostiques du modèle : les pages IDE
 * les assemblent librement pour composer leurs docks.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";

/* ─────────────────────────────── ICONS ─────────────────────────────── */

export type IconName =
  | "caret" | "close" | "min" | "max" | "popout" | "drag" | "search" | "plus"
  | "folder" | "record" | "play" | "pause" | "stop" | "skip" | "undo" | "redo"
  | "move" | "rotate" | "scale" | "eye" | "eyeOff" | "lock" | "unlock"
  | "camera" | "person" | "image" | "text" | "audio" | "fx" | "scene"
  | "grid" | "wand" | "broadcast" | "mic" | "keyboard" | "bolt" | "link"
  | "plug" | "layers" | "sliders" | "ruler" | "clock" | "chart" | "warn"
  | "check" | "dot" | "code" | "wrench" | "heart" | "star";

const ICON_PATHS: Record<IconName, string> = {
  caret: "M5 3l5 5-5 5z",
  close: "M3 3l10 10M13 3L3 13",
  min: "M3 8h10",
  max: "M3 3h10v10H3z",
  popout: "M10 3h3v3M13 3L8 8M3 13h10V8",
  drag: "M5 4h1v1H5zM5 7h1v1H5zM5 10h1v1H5zM10 4h1v1h-1zM10 7h1v1h-1zM10 10h1v1h-1z",
  search: "M7 12a5 5 0 1 0 0-10 5 5 0 0 0 0 10zm4-1l3 3",
  plus: "M8 3v10M3 8h10",
  folder: "M2 4h4l1 2h7v7H2z",
  record: "M8 2a6 6 0 1 0 0 12A6 6 0 0 0 8 2z",
  play: "M4 3l10 5-10 5z",
  pause: "M4 3h3v10H4zM9 3h3v10H9z",
  stop: "M3 3h10v10H3z",
  skip: "M3 3v10l7-5zM11 3h2v10h-2z",
  undo: "M4 7a5 5 0 0 1 9 3M4 4v3h3",
  redo: "M12 7a5 5 0 0 0-9 3M12 4v3H9",
  move: "M8 2v12M2 8h12M8 2l-2 2M8 2l2 2M8 14l-2-2M8 14l2-2M2 8l2-2M2 8l2 2M14 8l-2-2M14 8l-2 2",
  rotate: "M3 8a5 5 0 1 1 2 4M3 4v4h4",
  scale: "M3 3v4M3 3h4M13 13v-4M13 13h-4M3 3l10 10",
  eye: "M1 8s2.5-5 7-5 7 5 7 5-2.5 5-7 5-7-5-7-5zm7 2a2 2 0 1 0 0-4 2 2 0 0 0 0 4z",
  eyeOff: "M2 2l12 12M5.5 5.5A7.3 7.3 0 0 0 1 8s2.5 5 7 5c1.3 0 2.5-.4 3.5-1M8 5c4.5 0 7 3 7 3a11 11 0 0 1-1.5 1.8M6.5 6.5a2 2 0 0 0 2.5 2.5",
  lock: "M4 7V5a4 4 0 0 1 8 0v2M3 7h10v7H3z",
  unlock: "M4 7V5a4 4 0 0 1 8 0M3 7h10v7H3z",
  camera: "M2 5h3l1-1h4l1 1h3v8H2z M8 11a2 2 0 1 0 0-4 2 2 0 0 0 0 4z",
  person: "M8 8a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM2 14c0-3 3-5 6-5s6 2 6 5",
  image: "M2 3h12v10H2z M2 10l3-3 3 3 2-2 3 3",
  text: "M3 4h10M8 4v9M5 13h6",
  audio: "M5 5v6H3V5zM9 3v10H7V3zM13 7v2h-2V7z",
  fx: "M3 8l3-3v2h4V5l3 3-3 3v-2H6v2z",
  scene: "M2 4h4v4H2zM10 4h4v4h-4zM2 10h4v4H2zM10 10h4v4h-4z",
  grid: "M2 2h5v5H2zM9 2h5v5H9zM2 9h5v5H2zM9 9h5v5H9z",
  wand: "M2 14l9-9M11 5l2 2M12 2l1 1M14 4l1 1M3 4l1 1",
  broadcast:
    "M3 5a7 7 0 0 0 0 6M5 7a3 3 0 0 0 0 2M13 5a7 7 0 0 1 0 6M11 7a3 3 0 0 1 0 2M8 7a1 1 0 1 0 0 2z",
  mic: "M8 2a2 2 0 0 0-2 2v4a2 2 0 1 0 4 0V4a2 2 0 0 0-2-2zM4 8a4 4 0 0 0 8 0M8 12v2",
  keyboard: "M2 5h12v7H2z M4 8h1M7 8h1M10 8h1M4 10h8",
  bolt: "M9 2L3 9h4l-1 5 6-7H8z",
  link: "M7 5l-2 2a2 2 0 1 0 3 3l1-1M9 11l2-2a2 2 0 1 0-3-3L7 7",
  plug: "M5 3v3M11 3v3M3 8h10v2a4 4 0 0 1-8 0V8zM8 14v-2",
  layers: "M8 2l6 3-6 3-6-3zM2 8l6 3 6-3M2 11l6 3 6-3",
  sliders: "M3 4h10M3 8h10M3 12h10M6 4v0M10 8v0M8 12v0",
  ruler: "M2 5h12v6H2zM5 5v2M8 5v3M11 5v2",
  clock: "M8 2a6 6 0 1 0 0 12A6 6 0 0 0 8 2zM8 5v3l2 2",
  chart: "M2 13h12M4 11V7M7 11V4M10 11V8M13 11V5",
  warn: "M8 2l7 12H1z M8 6v4M8 12v0.5",
  check: "M3 8l3 3 7-7",
  dot: "M8 7a1 1 0 1 0 0 2 1 1 0 0 0 0-2z",
  code: "M5 5L2 8l3 3M11 5l3 3-3 3M9 3l-2 10",
  wrench: "M3 13l6-6a3 3 0 0 1 4-4l-2 2 1 1 2-2a3 3 0 0 1-4 4l-6 6z",
  heart: "M8 13s-5-3-5-7a2.5 2.5 0 0 1 5-1 2.5 2.5 0 0 1 5 1c0 4-5 7-5 7z",
  star: "M8 2l2 4 4 .5-3 3 1 4-4-2-4 2 1-4-3-3 4-.5z",
};

type IconProps = { name: IconName; size?: number; className?: string };

export function Icon({ name, size = 14, className = "" }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.4"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
    >
      <path d={ICON_PATHS[name] ?? ICON_PATHS.dot} />
    </svg>
  );
}

/* ─────────────────────────── CONTEXT MENU ─────────────────────────── */

export type CtxMenuItem =
  | { sep: true }
  | {
      label: string;
      shortcut?: string;
      danger?: boolean;
      disabled?: boolean;
      onClick?: () => void;
    };

type CtxMenuState = { x: number; y: number; items: CtxMenuItem[] } | null;
const CtxMenuContext = createContext<((s: CtxMenuState) => void) | null>(null);

export function CtxMenuProvider({ children }: { children: ReactNode }) {
  const [menu, setMenu] = useState<CtxMenuState>(null);

  useEffect(() => {
    if (!menu) return;
    const close = () => setMenu(null);
    window.addEventListener("click", close);
    window.addEventListener("scroll", close, true);
    return () => {
      window.removeEventListener("click", close);
      window.removeEventListener("scroll", close, true);
    };
  }, [menu]);

  return (
    <CtxMenuContext.Provider value={setMenu}>
      {children}
      {menu && (
        <div
          className="ide-ctxmenu"
          style={{ top: menu.y, left: menu.x }}
          onClick={(e) => e.stopPropagation()}
        >
          {menu.items.map((it, i) => {
            if ("sep" in it) return <div key={i} className="sep" />;
            return (
              <div
                key={i}
                className={`item ${it.disabled ? "disabled" : ""} ${it.danger ? "danger" : ""}`}
                onClick={() => {
                  if (it.disabled) return;
                  it.onClick?.();
                  setMenu(null);
                }}
              >
                <span>{it.label}</span>
                {it.shortcut && <span className="shortcut">{it.shortcut}</span>}
              </div>
            );
          })}
        </div>
      )}
    </CtxMenuContext.Provider>
  );
}

export function useCtxMenu() {
  const ctx = useContext(CtxMenuContext);
  if (!ctx) throw new Error("useCtxMenu must be used inside <CtxMenuProvider>");
  return ctx;
}

/* ───────────────────────────── PANEL ───────────────────────────── */

type PanelProps = {
  title?: string;
  icon?: IconName;
  actions?: ReactNode;
  onPopout?: () => void;
  onClose?: () => void;
  footer?: ReactNode;
  children?: ReactNode;
  focused?: boolean;
  noHeader?: boolean;
};

export function Panel({
  title,
  icon,
  actions,
  onPopout,
  onClose,
  footer,
  children,
  focused,
  noHeader,
}: PanelProps) {
  return (
    <div className={`ide-panel ${focused ? "focused" : ""}`}>
      {!noHeader && (
        <div className="ide-panel-header">
          <div className="ide-panel-title">
            {icon && <Icon name={icon} size={10} className="glyph" />}
            {title}
          </div>
          <div className="ide-panel-actions">
            {actions}
            {onPopout && (
              <button
                className="ide-panel-btn"
                title="Pop out in new window"
                onClick={onPopout}
              >
                <Icon name="popout" size={11} />
              </button>
            )}
            {onClose && (
              <button className="ide-panel-btn" title="Close" onClick={onClose}>
                <Icon name="close" size={10} />
              </button>
            )}
          </div>
        </div>
      )}
      <div className="ide-panel-body">{children}</div>
      {footer}
    </div>
  );
}

/* ───────────────────────────── TABSTRIP ───────────────────────────── */

export type TabDef = { id: string; label: string; icon?: IconName; dirty?: boolean };

type TabStripProps = {
  tabs: TabDef[];
  active: string;
  onSelect?: (id: string) => void;
  onClose?: (id: string) => void;
  onPopout?: () => void;
};

export function TabStrip({ tabs, active, onSelect, onClose, onPopout }: TabStripProps) {
  return (
    <div className="ide-tabstrip">
      {tabs.map((t) => (
        <div
          key={t.id}
          className={`ide-tab ${active === t.id ? "active" : ""} ${t.dirty ? "dirty" : ""}`}
          onClick={() => onSelect?.(t.id)}
        >
          {t.icon && <Icon name={t.icon} size={11} />}
          <span>{t.label}</span>
          <span className="dot" />
          {onClose && (
            <span
              className="close"
              onClick={(e) => {
                e.stopPropagation();
                onClose(t.id);
              }}
            >
              <Icon name="close" size={8} />
            </span>
          )}
        </div>
      ))}
      {onPopout && (
        <button
          className="ide-panel-btn"
          style={{ marginLeft: "auto", alignSelf: "center" }}
          title="Pop out active tab"
          onClick={onPopout}
        >
          <Icon name="popout" size={11} />
        </button>
      )}
    </div>
  );
}

/* ───────────────────────────── SPLITTER ───────────────────────────── */

type SplitterProps = {
  orientation?: "horizontal" | "vertical";
  onResize?: (deltaPx: number) => void;
};

export function Splitter({ orientation = "horizontal", onResize }: SplitterProps) {
  const [dragging, setDragging] = useState(false);
  const startRef = useRef(0);

  useEffect(() => {
    if (!dragging) return;
    const onMove = (e: MouseEvent) => {
      const coord = orientation === "horizontal" ? e.clientX : e.clientY;
      const d = coord - startRef.current;
      startRef.current = coord;
      onResize?.(d);
    };
    const onUp = () => setDragging(false);
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, [dragging, orientation, onResize]);

  return (
    <div
      className={`ide-splitter ${orientation} ${dragging ? "dragging" : ""}`}
      onMouseDown={(e) => {
        startRef.current = orientation === "horizontal" ? e.clientX : e.clientY;
        setDragging(true);
      }}
    />
  );
}

/* ───────────────────────────── TREEVIEW ───────────────────────────── */

export type TreeNodeData = {
  id: string;
  label: string;
  icon?: IconName;
  kind?: string;
  open?: boolean;
  visible?: boolean;
  locked?: boolean;
  children?: TreeNodeData[];
};

type TreeProps = {
  nodes: TreeNodeData[];
  selectedId?: string | null;
  onSelect?: (id: string) => void;
  onContextMenu?: (node: TreeNodeData, e: React.MouseEvent) => void;
  toggleVisible?: (id: string) => void;
  toggleLock?: (id: string) => void;
};

function TreeNode({
  node,
  depth = 0,
  ...rest
}: TreeProps & { node: TreeNodeData; depth?: number }) {
  const [open, setOpen] = useState(node.open ?? true);
  const hasChildren = !!node.children?.length;
  const { selectedId, onSelect, onContextMenu, toggleVisible, toggleLock } = rest;

  return (
    <>
      <div
        className={`ide-tree-node ${selectedId === node.id ? "selected" : ""}`}
        style={{ paddingLeft: 6 + depth * 12 }}
        onClick={() => onSelect?.(node.id)}
        onContextMenu={(e) => {
          e.preventDefault();
          onContextMenu?.(node, e);
        }}
      >
        <span
          className={`caret ${hasChildren ? "" : "leaf"} ${open ? "expanded" : ""}`}
          onClick={(e) => {
            e.stopPropagation();
            setOpen((v) => !v);
          }}
        >
          <Icon name="caret" size={8} />
        </span>
        <span className={`icon ${node.kind || ""}`}>
          <Icon name={node.icon || "dot"} size={11} />
        </span>
        <span className="label">{node.label}</span>
        <span className="badges">
          {toggleVisible && (
            <button
              className={`badge-btn ${node.visible !== false ? "on" : ""}`}
              title={node.visible !== false ? "Visible" : "Hidden"}
              onClick={(e) => {
                e.stopPropagation();
                toggleVisible(node.id);
              }}
            >
              <Icon name={node.visible !== false ? "eye" : "eyeOff"} size={10} />
            </button>
          )}
          {toggleLock && (
            <button
              className={`badge-btn ${node.locked ? "on" : ""}`}
              title={node.locked ? "Locked" : "Unlocked"}
              onClick={(e) => {
                e.stopPropagation();
                toggleLock(node.id);
              }}
            >
              <Icon name={node.locked ? "lock" : "unlock"} size={10} />
            </button>
          )}
        </span>
      </div>
      {hasChildren && open && (
        <>
          {node.children!.map((c) => (
            <TreeNode key={c.id} node={c} depth={depth + 1} {...rest} nodes={[]} />
          ))}
        </>
      )}
    </>
  );
}

export function Treeview(props: TreeProps) {
  return (
    <div className="ide-tree">
      {props.nodes.map((n) => (
        <TreeNode key={n.id} node={n} depth={0} {...props} />
      ))}
    </div>
  );
}

/* ─────────────────────────── PROPERTY GRID ─────────────────────────── */

export function PropSection({
  title,
  actions,
  children,
  defaultOpen = true,
}: {
  title: string;
  actions?: ReactNode;
  children: ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="ide-propgrid-section">
      <div
        className={`ide-propgrid-section-header ${open ? "expanded" : ""}`}
        onClick={() => setOpen((v) => !v)}
      >
        <span className="caret">
          <Icon name="caret" size={8} />
        </span>
        <span>{title}</span>
        {actions && (
          <span className="actions" onClick={(e) => e.stopPropagation()}>
            {actions}
          </span>
        )}
      </div>
      {open && <div>{children}</div>}
    </div>
  );
}

export function PropRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="ide-propgrid-row">
      <div className="prop-label" title={label}>
        {label}
      </div>
      <div className="prop-value">{children}</div>
    </div>
  );
}

/* ───────────────────────────── NUM / XYZ ───────────────────────────── */

type Axis = "x" | "y" | "z";

export function Num({
  axis,
  value,
  onChange,
  unit,
  step = 1,
  min,
  max,
}: {
  axis?: Axis;
  value: number;
  onChange?: (v: number) => void;
  unit?: string;
  step?: number;
  min?: number;
  max?: number;
}) {
  const [v, setV] = useState<string>(String(value));
  useEffect(() => setV(String(value)), [value]);

  const commit = useCallback(
    (raw: string) => {
      let n = parseFloat(raw);
      if (isNaN(n)) return;
      if (min != null) n = Math.max(min, n);
      if (max != null) n = Math.min(max, n);
      onChange?.(n);
    },
    [min, max, onChange],
  );

  const dragStart = useRef<{ x: number; val: number } | null>(null);
  useEffect(() => {
    if (!dragStart.current) return;
    const onMove = (e: MouseEvent) => {
      if (!dragStart.current) return;
      const dx = e.clientX - dragStart.current.x;
      commit(String(dragStart.current.val + dx * step));
    };
    const onUp = () => {
      dragStart.current = null;
      document.body.style.cursor = "";
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  });

  return (
    <div className="ide-num">
      {axis && (
        <span
          className={`axis ${axis}`}
          style={{ cursor: "ew-resize" }}
          onMouseDown={(e) => {
            dragStart.current = { x: e.clientX, val: parseFloat(v) || 0 };
            document.body.style.cursor = "ew-resize";
          }}
        >
          {axis.toUpperCase()}
        </span>
      )}
      <input
        type="text"
        value={v}
        onChange={(e) => setV(e.target.value)}
        onBlur={() => commit(v)}
        onKeyDown={(e) => {
          if (e.key === "Enter") (e.target as HTMLInputElement).blur();
        }}
      />
      {unit && <span className="unit">{unit}</span>}
    </div>
  );
}

export function XYZ({
  value,
  onChange,
}: {
  value: [number, number, number];
  onChange?: (v: [number, number, number]) => void;
}) {
  const [x, y, z] = value;
  return (
    <div className="ide-xyz">
      <Num axis="x" value={x} onChange={(v) => onChange?.([v, y, z])} />
      <Num axis="y" value={y} onChange={(v) => onChange?.([x, v, z])} />
      <Num axis="z" value={z} onChange={(v) => onChange?.([x, y, v])} />
    </div>
  );
}

/* ───────────────────────────── SLIDER ───────────────────────────── */

export function Slider({
  value = 0,
  min = 0,
  max = 1,
  step = 0.01,
  onChange,
  showValue = true,
  format,
}: {
  value?: number;
  min?: number;
  max?: number;
  step?: number;
  onChange?: (v: number) => void;
  showValue?: boolean;
  format?: (v: number) => string;
}) {
  const trackRef = useRef<HTMLDivElement | null>(null);
  const [dragging, setDragging] = useState(false);
  const pct = ((value - min) / (max - min)) * 100;

  const set = useCallback(
    (clientX: number) => {
      if (!trackRef.current) return;
      const r = trackRef.current.getBoundingClientRect();
      const p = Math.max(0, Math.min(1, (clientX - r.left) / r.width));
      let v = min + p * (max - min);
      if (step) v = Math.round(v / step) * step;
      onChange?.(+v.toFixed(4));
    },
    [min, max, step, onChange],
  );

  useEffect(() => {
    if (!dragging) return;
    const onMove = (e: MouseEvent) => set(e.clientX);
    const onUp = () => setDragging(false);
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, [dragging, set]);

  return (
    <div className="ide-slider">
      <div
        className="ide-slider-track"
        ref={trackRef}
        onMouseDown={(e) => {
          setDragging(true);
          set(e.clientX);
        }}
      >
        <div className="ide-slider-fill" style={{ width: `${pct}%` }} />
        <div className="ide-slider-thumb" style={{ left: `${pct}%` }} />
      </div>
      {showValue && (
        <div className="ide-slider-value">
          {format ? format(value) : value.toFixed(step < 1 ? 2 : 0)}
        </div>
      )}
    </div>
  );
}

/* ───────────────────────────── COLOR PICKER ───────────────────────────── */

export function ColorPicker({
  value = "#e08efe",
  onChange,
}: {
  value?: string;
  onChange?: (hex: string) => void;
}) {
  const ref = useRef<HTMLInputElement | null>(null);
  return (
    <label className="ide-color" style={{ position: "relative" }}>
      <span className="swatch" style={{ background: value }} />
      <span>{value.toUpperCase()}</span>
      <input
        ref={ref}
        type="color"
        value={value}
        onChange={(e) => onChange?.(e.target.value)}
        style={{
          position: "absolute",
          width: 0,
          height: 0,
          opacity: 0,
          pointerEvents: "none",
        }}
      />
      <span
        style={{ position: "absolute", inset: 0 }}
        onClick={() => ref.current?.click()}
      />
    </label>
  );
}

/* ───────────────────────────── SWITCH / SELECT ───────────────────────────── */

export function Switch({
  checked,
  onChange,
}: {
  checked: boolean;
  onChange?: (v: boolean) => void;
}) {
  return (
    <button
      className="ide-switch-mini"
      aria-checked={checked}
      onClick={() => onChange?.(!checked)}
    />
  );
}

export type SelectOption = string | { value: string; label: string };

export function Select({
  value,
  options,
  onChange,
}: {
  value: string;
  options: SelectOption[];
  onChange?: (v: string) => void;
}) {
  return (
    <select
      className="ide-select"
      value={value}
      onChange={(e) => onChange?.(e.target.value)}
    >
      {options.map((o) => {
        const v = typeof o === "string" ? o : o.value;
        const l = typeof o === "string" ? o : o.label;
        return (
          <option key={v} value={v}>
            {l}
          </option>
        );
      })}
    </select>
  );
}

/* ───────────────────────────── TBBtn / STATUSBAR ───────────────────────────── */

export function TBBtn({
  icon,
  label,
  active,
  danger,
  primary,
  onClick,
  title,
}: {
  icon?: IconName;
  label?: string;
  active?: boolean;
  danger?: boolean;
  primary?: boolean;
  onClick?: () => void;
  title?: string;
}) {
  return (
    <button
      className={`ide-tb-btn ${active ? "active" : ""} ${danger ? "danger" : ""} ${primary ? "primary" : ""}`}
      onClick={onClick}
      title={title || label}
    >
      {icon && <Icon name={icon} size={13} className="glyph" />}
      {label && <span>{label}</span>}
    </button>
  );
}

export type StatusItem =
  | { spacer: true }
  | {
      label: string;
      value?: string;
      dot?: boolean;
      icon?: IconName;
      kind?: "ok" | "warn" | "danger";
    };

export function StatusBar({ items = [] }: { items?: StatusItem[] }) {
  return (
    <div className="ide-statusbar">
      {items.map((it, i) => {
        if ("spacer" in it) return <div key={i} className="ide-statusbar-spacer" />;
        return (
          <div key={i} className={`item ${it.kind || ""}`}>
            {it.dot && <span className="dot" />}
            {it.icon && <Icon name={it.icon} size={10} />}
            <span>{it.label}</span>
            {it.value != null && <span className="val">{it.value}</span>}
          </div>
        );
      })}
    </div>
  );
}

/* Shared inline style helper used by some panels */
export const PANEL_CENTERED_EMPTY: CSSProperties = {
  padding: "20px 14px",
  color: "var(--ide-text-weak)",
  fontSize: 11,
  textAlign: "center",
};
