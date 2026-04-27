import { describe, it, expect } from "vitest";
import { ancestorIds, emptySceneGraph, isDescendantOf, ROOT_ID, walkSubtree, type SceneGraph, type SceneNode } from "../scene-types";

function buildGraph(): SceneGraph {
  // root → A (group)
  //          ├── A1 (prop)
  //          └── A2 (prop)
  //      → B (vrm)
  const nodes: Record<string, SceneNode> = {
    [ROOT_ID]: {
      id: ROOT_ID, kind: "root", name: "Scene", parentId: null,
      childIds: ["A", "B"], visible: true, locked: false,
      position: [0, 0, 0], rotationEuler: [0, 0, 0], scale: [1, 1, 1],
    },
    A: {
      id: "A", kind: "group", name: "Group A", parentId: ROOT_ID,
      childIds: ["A1", "A2"], visible: true, locked: false,
      position: [0, 0, 0], rotationEuler: [0, 0, 0], scale: [1, 1, 1],
    },
    A1: {
      id: "A1", kind: "prop", name: "Prop 1", parentId: "A", childIds: [],
      visible: true, locked: false, position: [0,0,0], rotationEuler: [0,0,0], scale: [1,1,1],
    },
    A2: {
      id: "A2", kind: "prop", name: "Prop 2", parentId: "A", childIds: [],
      visible: true, locked: false, position: [0,0,0], rotationEuler: [0,0,0], scale: [1,1,1],
    },
    B: {
      id: "B", kind: "vrm", name: "Shugu", parentId: ROOT_ID, childIds: [],
      visible: true, locked: false, position: [0,0,0], rotationEuler: [0,0,0], scale: [1,1,1],
    },
  };
  return { rootId: ROOT_ID, nodes };
}

describe("emptySceneGraph", () => {
  it("creates a graph with only the root", () => {
    const g = emptySceneGraph();
    expect(g.rootId).toBe(ROOT_ID);
    expect(Object.keys(g.nodes)).toEqual([ROOT_ID]);
    expect(g.nodes[ROOT_ID].kind).toBe("root");
    expect(g.nodes[ROOT_ID].childIds).toHaveLength(0);
  });
});

describe("ancestorIds", () => {
  it("returns chain from node to root inclusive", () => {
    const g = buildGraph();
    expect(ancestorIds(g, "A1")).toEqual(["A1", "A", "root"]);
  });
  it("returns single id for the root itself", () => {
    const g = buildGraph();
    expect(ancestorIds(g, "root")).toEqual(["root"]);
  });
  it("returns empty for an unknown id", () => {
    const g = buildGraph();
    expect(ancestorIds(g, "nope")).toEqual([]);
  });
});

describe("isDescendantOf", () => {
  it("true when node is strictly under ancestor", () => {
    const g = buildGraph();
    expect(isDescendantOf(g, "A1", "A")).toBe(true);
    expect(isDescendantOf(g, "A1", "root")).toBe(true);
  });
  it("false when same id (strict)", () => {
    const g = buildGraph();
    expect(isDescendantOf(g, "A", "A")).toBe(false);
  });
  it("false when sibling", () => {
    const g = buildGraph();
    expect(isDescendantOf(g, "A1", "A2")).toBe(false);
    expect(isDescendantOf(g, "A", "B")).toBe(false);
  });
});

describe("walkSubtree", () => {
  it("visits in DFS pre-order with depth", () => {
    const g = buildGraph();
    const visited: Array<[string, number]> = [];
    walkSubtree(g, ROOT_ID, (n, depth) => visited.push([n.id, depth]));
    expect(visited).toEqual([
      ["root", 0],
      ["A", 1],
      ["A1", 2],
      ["A2", 2],
      ["B", 1],
    ]);
  });

  it("walks only the requested subtree", () => {
    const g = buildGraph();
    const ids: string[] = [];
    walkSubtree(g, "A", (n) => ids.push(n.id));
    expect(ids).toEqual(["A", "A1", "A2"]);
  });

  it("handles unknown id gracefully", () => {
    const g = buildGraph();
    const ids: string[] = [];
    walkSubtree(g, "ghost", (n) => ids.push(n.id));
    expect(ids).toEqual([]);
  });
});
