/**
 * Scene store (Phase 2.A) — graph + selection + actions immuables via produce.
 *
 * Séparé du SceneEditorStore (UI shell) pour préserver la composition :
 * - useSceneEditorStore = UI seulement (workspace courant, palette, splits).
 * - useSceneStore = scène 3D (graph, selection, transforms à venir Phase 2.D).
 *
 * Pattern : Zustand + immer-like via produce. Toutes les mutations passent par
 * un updater qui clone les nodes et childIds touchés. Les nodes non touchés
 * gardent leurs refs (== reference equality dans les selectors).
 */

import { create } from "zustand";
import {
  ancestorIds,
  emptySceneGraph,
  isDescendantOf,
  ROOT_ID,
  walkSubtree,
  ZERO_VEC3,
  ONE_VEC3,
  type SceneGraph,
  type SceneNode,
  type SceneNodeId,
  type SceneNodeKind,
  type Vec3,
} from "./scene-types";

let counter = 0;
function makeId(): SceneNodeId {
  counter += 1;
  // ID humain-lisible pour debug Outliner (pas crypto-secure, c'est juste pour DOM keys).
  return `n_${Date.now().toString(36)}_${counter.toString(36)}`;
}

export type AddNodeArgs = {
  kind: Exclude<SceneNodeKind, "root">;
  name: string;
  parentId?: SceneNodeId;
  assetId?: string;
  position?: Vec3;
  rotationEuler?: Vec3;
  scale?: Vec3;
};

type SceneState = {
  graph: SceneGraph;
  selection: readonly SceneNodeId[];

  addNode: (args: AddNodeArgs) => SceneNodeId;
  removeNode: (id: SceneNodeId) => void;
  renameNode: (id: SceneNodeId, name: string) => void;
  toggleVisibility: (id: SceneNodeId) => void;
  toggleLock: (id: SceneNodeId) => void;
  moveNode: (id: SceneNodeId, newParentId: SceneNodeId, index: number) => void;

  setSelection: (ids: readonly SceneNodeId[]) => void;
  toggleSelection: (id: SceneNodeId) => void;
  clearSelection: () => void;
};

function withNode(graph: SceneGraph, id: SceneNodeId, mutator: (n: SceneNode) => SceneNode): SceneGraph {
  const n = graph.nodes[id];
  if (!n) return graph;
  return { ...graph, nodes: { ...graph.nodes, [id]: mutator(n) } };
}

function removeChildId(graph: SceneGraph, parentId: SceneNodeId, childId: SceneNodeId): SceneGraph {
  return withNode(graph, parentId, (p) => ({
    ...p,
    childIds: p.childIds.filter((c) => c !== childId),
  }));
}

function insertChildId(graph: SceneGraph, parentId: SceneNodeId, childId: SceneNodeId, index: number): SceneGraph {
  return withNode(graph, parentId, (p) => {
    const next = [...p.childIds];
    const i = Math.max(0, Math.min(next.length, index));
    next.splice(i, 0, childId);
    return { ...p, childIds: next };
  });
}

export const useSceneStore = create<SceneState>((set, get) => ({
  graph: emptySceneGraph(),
  selection: [],

  addNode: (args) => {
    const id = makeId();
    const parentId = args.parentId ?? ROOT_ID;
    const node: SceneNode = {
      id,
      kind: args.kind,
      name: args.name,
      parentId,
      childIds: [],
      visible: true,
      locked: false,
      assetId: args.assetId,
      position: args.position ?? ZERO_VEC3,
      rotationEuler: args.rotationEuler ?? ZERO_VEC3,
      scale: args.scale ?? ONE_VEC3,
    };
    set((s) => {
      let g = { ...s.graph, nodes: { ...s.graph.nodes, [id]: node } };
      g = insertChildId(g, parentId, id, g.nodes[parentId]?.childIds.length ?? 0);
      return { graph: g };
    });
    return id;
  },

  removeNode: (id) => {
    if (id === ROOT_ID) return;
    set((s) => {
      const g = s.graph;
      if (!g.nodes[id]) return s;
      // Collect subtree ids.
      const toRemove: SceneNodeId[] = [];
      walkSubtree(g, id, (n) => toRemove.push(n.id));
      const parentId = g.nodes[id].parentId;
      const nodes = { ...g.nodes };
      for (const rid of toRemove) delete nodes[rid];
      let next: SceneGraph = { ...g, nodes };
      if (parentId) next = removeChildId(next, parentId, id);
      const removedSet = new Set(toRemove);
      return {
        graph: next,
        selection: s.selection.filter((sid) => !removedSet.has(sid)),
      };
    });
  },

  renameNode: (id, name) => {
    set((s) => ({ graph: withNode(s.graph, id, (n) => ({ ...n, name })) }));
  },

  toggleVisibility: (id) => {
    set((s) => ({ graph: withNode(s.graph, id, (n) => ({ ...n, visible: !n.visible })) }));
  },

  toggleLock: (id) => {
    set((s) => ({ graph: withNode(s.graph, id, (n) => ({ ...n, locked: !n.locked })) }));
  },

  moveNode: (id, newParentId, index) => {
    if (id === ROOT_ID) return;
    set((s) => {
      const g = s.graph;
      const node = g.nodes[id];
      const newParent = g.nodes[newParentId];
      if (!node || !newParent) return s;
      // Anti-cycle : interdire de déposer sous soi-même ou un descendant.
      if (id === newParentId) return s;
      if (isDescendantOf(g, newParentId, id)) return s;
      const oldParentId = node.parentId ?? ROOT_ID;
      let next = removeChildId(g, oldParentId, id);
      next = withNode(next, id, (n) => ({ ...n, parentId: newParentId }));
      // Si on reste dans le même parent et qu'on insère après l'ancienne position,
      // l'index doit être ajusté car on a retiré une entrée.
      let target = index;
      if (oldParentId === newParentId) {
        const oldIndex = g.nodes[oldParentId].childIds.indexOf(id);
        if (oldIndex >= 0 && oldIndex < target) target -= 1;
      }
      next = insertChildId(next, newParentId, id, target);
      return { graph: next };
    });
  },

  setSelection: (ids) => {
    set({ selection: [...ids] });
  },

  toggleSelection: (id) => {
    set((s) => {
      const i = s.selection.indexOf(id);
      if (i === -1) return { selection: [...s.selection, id] };
      const next = [...s.selection];
      next.splice(i, 1);
      return { selection: next };
    });
  },

  clearSelection: () => set({ selection: [] }),
}));

/** Reset pour les tests Vitest. */
export function __resetSceneStoreForTest(): void {
  useSceneStore.setState({ graph: emptySceneGraph(), selection: [] });
  counter = 0;
}

/** Helpers d'accès dérivé (memoizable). */
export const sceneSelectors = {
  ancestorIds: (id: SceneNodeId) => ancestorIds(useSceneStore.getState().graph, id),
};
