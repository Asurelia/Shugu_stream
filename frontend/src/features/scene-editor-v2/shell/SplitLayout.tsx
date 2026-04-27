/**
 * SplitLayout — primitive panneaux splittables Blender-like.
 *
 * 2 enfants côte-à-côte (horizontal) ou empilés (vertical) avec un divider
 * draggable au milieu. Le ratio (0..1) est persisté via le store
 * useSceneEditorStore (qui synchronise localStorage).
 *
 * - direction "horizontal" : enfants left/right, divider orienté vertical (4px wide).
 * - direction "vertical"   : enfants top/bottom, divider orienté horizontal (4px tall).
 *
 * Phase 1 = 2 enfants. Phase 2+ pourra étendre à N enfants si besoin (peu probable
 * — Blender lui-même compose plusieurs splits imbriqués pour faire du N).
 *
 * Accessibilité : separator ARIA + aria-valuenow/min/max. Pas de keyboard arrow nudge
 * en Phase 1 (extension Phase 7 polish).
 */

import { useEffect, useRef, useState, useCallback, type ReactNode } from "react";
import { useSceneEditorStore, readSplitRatio } from "../store/useSceneEditorStore";

export type SplitDirection = "horizontal" | "vertical";

export type SplitLayoutProps = {
  id: string;
  direction: SplitDirection;
  defaultRatio?: number;
  minRatio?: number;
  maxRatio?: number;
  children: [ReactNode, ReactNode];
  className?: string;
};

const MIN_DEFAULT = 0.05;
const MAX_DEFAULT = 0.95;

export function SplitLayout({
  id,
  direction,
  defaultRatio = 0.5,
  minRatio = MIN_DEFAULT,
  maxRatio = MAX_DEFAULT,
  children,
  className,
}: SplitLayoutProps) {
  const ratio = useSceneEditorStore((s) => s.splitRatios[id] ?? readSplitRatio(id, defaultRatio));
  const setSplitRatio = useSceneEditorStore((s) => s.setSplitRatio);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const [dragging, setDragging] = useState(false);

  const onMouseMove = useCallback(
    (e: MouseEvent) => {
      const root = rootRef.current;
      if (!root) return;
      const rect = root.getBoundingClientRect();
      const total = direction === "horizontal" ? rect.width : rect.height;
      if (total <= 0) return;
      const offset = direction === "horizontal" ? e.clientX - rect.left : e.clientY - rect.top;
      const next = Math.min(maxRatio, Math.max(minRatio, offset / total));
      setSplitRatio(id, next);
    },
    [direction, id, maxRatio, minRatio, setSplitRatio],
  );

  const onMouseUp = useCallback(() => {
    setDragging(false);
  }, []);

  useEffect(() => {
    if (!dragging) return;
    document.body.style.cursor = direction === "horizontal" ? "col-resize" : "row-resize";
    document.body.style.userSelect = "none";
    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", onMouseUp);
    return () => {
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", onMouseUp);
    };
  }, [dragging, direction, onMouseMove, onMouseUp]);

  const onSepMouseDown = (e: React.MouseEvent) => {
    e.preventDefault();
    setDragging(true);
  };

  const isHorizontal = direction === "horizontal";
  const valueNow = Math.round(ratio * 100);

  const firstStyle = isHorizontal
    ? { width: `${ratio * 100}%`, height: "100%" }
    : { width: "100%", height: `${ratio * 100}%` };
  const secondStyle = isHorizontal
    ? { width: `${(1 - ratio) * 100}%`, height: "100%" }
    : { width: "100%", height: `${(1 - ratio) * 100}%` };

  return (
    <div
      ref={rootRef}
      data-testid="split-root"
      className={["split-root", isHorizontal ? "split-horizontal" : "split-vertical", className]
        .filter(Boolean)
        .join(" ")}
      style={{
        display: "flex",
        flexDirection: isHorizontal ? "row" : "column",
        width: "100%",
        height: "100%",
        position: "relative",
        overflow: "hidden",
      }}
    >
      <div style={{ ...firstStyle, overflow: "hidden", position: "relative" }} data-split-pane="first">
        {children[0]}
      </div>
      <div
        role="separator"
        aria-orientation={isHorizontal ? "vertical" : "horizontal"}
        aria-valuenow={valueNow}
        aria-valuemin={Math.round(minRatio * 100)}
        aria-valuemax={Math.round(maxRatio * 100)}
        aria-label={`Split ratio ${id}`}
        tabIndex={0}
        onMouseDown={onSepMouseDown}
        style={{
          flex: "0 0 auto",
          width: isHorizontal ? "4px" : "100%",
          height: isHorizontal ? "100%" : "4px",
          cursor: isHorizontal ? "col-resize" : "row-resize",
          background: dragging ? "rgba(224,142,254,0.45)" : "rgba(255,255,255,0.04)",
          transition: "background 160ms ease",
          touchAction: "none",
          userSelect: "none",
        }}
      />
      <div style={{ ...secondStyle, overflow: "hidden", position: "relative" }} data-split-pane="second">
        {children[1]}
      </div>
    </div>
  );
}
