/**
 * Outliner panel (Phase 2.A) — arbre hiérarchique de la scène 3D.
 *
 * Pattern :
 * - Aplatit le SceneGraph stocké en liste DFS via walkSubtree (lazy, no memo
 *   pour Phase 2.A simple).
 * - Chaque ligne = treeitem avec aria-level (depth réel dans l'arbre).
 * - Click = sélection simple. Ctrl/Cmd + click = toggle multi.
 * - Eye / Lock buttons = toggle visibilité / verrou (stopPropagation pour ne
 *   pas modifier la sélection en cliquant sur l'icône).
 * - Search input filtre case-insensitive par nom (substring).
 * - Delete supprime la sélection courante.
 *
 * Phase 2.A laisse intentionnellement de côté :
 * - Drag-reorder visuel (Phase 2.A.2 ou 2.D — simple HTML5 dnd attendu)
 * - Rename inline (Phase 2.D)
 * - Right-click context menu (Phase 2.D)
 * - Virtualization (Phase 7 si > 500 nodes)
 */

import { useMemo, useState } from "react";
import { GlassInput } from "@/features/liquid-glass/primitives";
import { useSceneStore } from "../../../scene/useSceneStore";
import { walkSubtree, ROOT_ID, type SceneNode, type SceneNodeKind } from "../../../scene/scene-types";

const KIND_ICON: Record<SceneNodeKind, string> = {
  root: "✦",
  group: "▭",
  vrm: "☻",
  outfit: "⛁",
  prop: "▣",
  decor: "▩",
  light: "☼",
  camera: "⌖",
  vfx: "✨",
};

type FlatRow = { node: SceneNode; depth: number };

export function Outliner() {
  const graph = useSceneStore((s) => s.graph);
  const selection = useSceneStore((s) => s.selection);
  const setSelection = useSceneStore((s) => s.setSelection);
  const toggleSelection = useSceneStore((s) => s.toggleSelection);
  const toggleVisibility = useSceneStore((s) => s.toggleVisibility);
  const toggleLock = useSceneStore((s) => s.toggleLock);
  const removeNode = useSceneStore((s) => s.removeNode);
  const [query, setQuery] = useState("");

  const rows: FlatRow[] = useMemo(() => {
    const out: FlatRow[] = [];
    walkSubtree(graph, ROOT_ID, (n, depth) => {
      if (n.id === ROOT_ID) return;
      out.push({ node: n, depth });
    });
    return out;
  }, [graph]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter((r) => r.node.name.toLowerCase().includes(q));
  }, [rows, query]);

  const onRowClick = (id: string, e: React.MouseEvent) => {
    if (e.ctrlKey || e.metaKey) toggleSelection(id);
    else setSelection([id]);
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Delete" || e.key === "Backspace") {
      const targets = selection.filter((id) => id !== ROOT_ID);
      if (targets.length === 0) return;
      e.preventDefault();
      for (const id of targets) removeNode(id);
    }
  };

  return (
    <section className="sev2-outliner sev2-panel-body" aria-label="Outliner">
      <div className="sev2-panel-header">
        <span className="sev2-panel-title">Outliner</span>
        <span className="sev2-outliner-count">{rows.length}</span>
      </div>
      <div className="sev2-outliner-search">
        <GlassInput
          placeholder="Search nodes…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          pill
        />
      </div>
      {rows.length === 0 ? (
        <div className="sev2-panel-empty">
          <div className="sev2-panel-empty-icon" aria-hidden="true">◇</div>
          <div className="sev2-panel-empty-hint">Empty scene — drop an asset from the Library to start.</div>
        </div>
      ) : filtered.length === 0 ? (
        <div className="sev2-panel-empty">
          <div className="sev2-panel-empty-hint">No node matches &quot;{query}&quot;.</div>
        </div>
      ) : (
        <ul role="tree" aria-label="Scene hierarchy" className="sev2-outliner-list" tabIndex={0} onKeyDown={onKeyDown}>
          {filtered.map(({ node, depth }) => {
            const selected = selection.includes(node.id);
            return (
              <li
                key={node.id}
                role="treeitem"
                aria-level={depth}
                aria-selected={selected}
                aria-label={node.name}
                className={[
                  "sev2-outliner-row",
                  selected ? "sev2-outliner-row--selected" : "",
                  !node.visible ? "sev2-outliner-row--hidden" : "",
                  node.locked ? "sev2-outliner-row--locked" : "",
                ].filter(Boolean).join(" ")}
                style={{ paddingLeft: 6 + depth * 14 }}
                onClick={(e) => onRowClick(node.id, e)}
              >
                <span className="sev2-outliner-icon" aria-hidden="true">{KIND_ICON[node.kind] ?? "◇"}</span>
                <span className="sev2-outliner-name">{node.name}</span>
                <button
                  type="button"
                  aria-label={`Toggle visibility — ${node.name}`}
                  aria-pressed={!node.visible}
                  className="sev2-outliner-icon-btn"
                  onClick={(e) => { e.stopPropagation(); toggleVisibility(node.id); }}
                  title={node.visible ? "Hide" : "Show"}
                >
                  {node.visible ? "👁" : "—"}
                </button>
                <button
                  type="button"
                  aria-label={`Toggle lock — ${node.name}`}
                  aria-pressed={node.locked}
                  className="sev2-outliner-icon-btn"
                  onClick={(e) => { e.stopPropagation(); toggleLock(node.id); }}
                  title={node.locked ? "Unlock" : "Lock"}
                >
                  {node.locked ? "🔒" : "🔓"}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
