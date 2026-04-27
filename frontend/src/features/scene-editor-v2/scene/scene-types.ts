/**
 * Data model de la scène 3D — fondation de Phase 2.
 *
 * Stockage flat (Record<id, node>) plutôt que tree récursif.
 *
 * Pourquoi flat :
 * - O(1) lookup par id (sélection multiple, drag-drop, transform updates).
 * - Drag-reorder simple : mutation parentId + childIds[parent], pas de
 *   restructuration profonde.
 * - Refs croisées possibles (un asset peut être instancié plusieurs fois).
 * - Sérialisation JSON triviale pour le backend Shugu.
 *
 * Tradeoffs :
 * - Lecture hiérarchie nécessite un walk récursif via childIds. Mais
 *   l'Outliner tree component peut le faire en rendu seulement, pas en
 *   storage.
 *
 * Ce model est conçu pour évoluer Phase 2.B (Library) → 2.C (Three.js
 * viewport) → 2.D (Properties Inspector). Donc il inclut déjà :
 * - Vec3 transform (XYZ position/rotation Euler/scale).
 * - assetId (ref vers le registry Library, optionnel pour les groupes).
 * - kind discriminator pour rendu typé (vrm, light, camera, prop, decor,
 *   vfx, group).
 * - flags visible / locked pour Outliner toggles.
 */

export type Vec3 = readonly [number, number, number];

export type SceneNodeKind =
  | "root"
  | "group"
  | "vrm"        // VRM avatar (Shugu, invités)
  | "outfit"     // outfit appliqué à un VRM (référence par child sous le VRM parent)
  | "prop"       // mesh statique 3D
  | "decor"      // élément de décor / environnement
  | "light"      // lumière 3D (key/fill/back/ambient/etc.)
  | "camera"     // caméra (preset ou custom)
  | "vfx";       // particules / effets

export type SceneNodeId = string;

export type SceneNode = {
  id: SceneNodeId;
  kind: SceneNodeKind;
  name: string;
  parentId: SceneNodeId | null;        // null pour root
  childIds: readonly SceneNodeId[];    // ordre = ordre d'affichage Outliner
  visible: boolean;
  locked: boolean;
  /** ref vers la Library (Phase 2.B) — optionnel selon kind. */
  assetId?: string;
  /** transform local. Le viewport Three.js (Phase 2.C) compose les world matrices. */
  position: Vec3;
  rotationEuler: Vec3;
  scale: Vec3;
  /** props kind-spécifiques (lighting params, camera fov, etc.) — keep loose en Phase 2.A. */
  data?: Readonly<Record<string, unknown>>;
};

export const ZERO_VEC3: Vec3 = [0, 0, 0] as const;
export const ONE_VEC3: Vec3 = [1, 1, 1] as const;
export const ROOT_ID: SceneNodeId = "root";

export type SceneGraph = Readonly<{
  rootId: SceneNodeId;
  nodes: Readonly<Record<SceneNodeId, SceneNode>>;
}>;

/** Crée un graph vide avec uniquement le root. */
export function emptySceneGraph(): SceneGraph {
  const root: SceneNode = {
    id: ROOT_ID,
    kind: "root",
    name: "Scene",
    parentId: null,
    childIds: [],
    visible: true,
    locked: false,
    position: ZERO_VEC3,
    rotationEuler: ZERO_VEC3,
    scale: ONE_VEC3,
  };
  return { rootId: ROOT_ID, nodes: { [ROOT_ID]: root } };
}

/** Renvoie la chaîne d'ancêtres du node (incluse), du node vers root. */
export function ancestorIds(graph: SceneGraph, id: SceneNodeId): SceneNodeId[] {
  const out: SceneNodeId[] = [];
  let cur: SceneNodeId | null = id;
  while (cur && graph.nodes[cur]) {
    out.push(cur);
    cur = graph.nodes[cur].parentId;
    if (out.length > 1000) break; // garde anti-cycle
  }
  return out;
}

/** True si `descendant` est sous `ancestor` (strictement) dans l'arbre. */
export function isDescendantOf(graph: SceneGraph, descendant: SceneNodeId, ancestor: SceneNodeId): boolean {
  if (descendant === ancestor) return false;
  const chain = ancestorIds(graph, descendant);
  return chain.includes(ancestor);
}

/** Walk récursif (DFS pre-order) depuis un node. Inclut le node lui-même. */
export function walkSubtree(graph: SceneGraph, id: SceneNodeId, fn: (n: SceneNode, depth: number) => void, depth = 0): void {
  const n = graph.nodes[id];
  if (!n) return;
  fn(n, depth);
  for (const childId of n.childIds) walkSubtree(graph, childId, fn, depth + 1);
}
