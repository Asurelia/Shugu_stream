import { describe, it, expect, beforeEach } from "vitest";
import { useSceneStore, __resetSceneStoreForTest } from "../useSceneStore";
import { ROOT_ID } from "../scene-types";

beforeEach(() => __resetSceneStoreForTest());

describe("useSceneStore — add / remove / rename", () => {
  it("starts with an empty graph (root only)", () => {
    const { graph } = useSceneStore.getState();
    expect(Object.keys(graph.nodes)).toEqual([ROOT_ID]);
  });

  it("addNode appends a child under root by default", () => {
    const id = useSceneStore.getState().addNode({ kind: "prop", name: "Cube" });
    const g = useSceneStore.getState().graph;
    expect(g.nodes[id].kind).toBe("prop");
    expect(g.nodes[id].name).toBe("Cube");
    expect(g.nodes[id].parentId).toBe(ROOT_ID);
    expect(g.nodes[ROOT_ID].childIds).toContain(id);
  });

  it("addNode under a specific parent group", () => {
    const groupId = useSceneStore.getState().addNode({ kind: "group", name: "Decor" });
    const propId = useSceneStore.getState().addNode({ kind: "prop", name: "Tree", parentId: groupId });
    expect(useSceneStore.getState().graph.nodes[propId].parentId).toBe(groupId);
    expect(useSceneStore.getState().graph.nodes[groupId].childIds).toContain(propId);
  });

  it("removeNode removes the node and its descendants", () => {
    const A = useSceneStore.getState().addNode({ kind: "group", name: "A" });
    const A1 = useSceneStore.getState().addNode({ kind: "prop", name: "A1", parentId: A });
    const A2 = useSceneStore.getState().addNode({ kind: "prop", name: "A2", parentId: A });
    useSceneStore.getState().removeNode(A);
    const g = useSceneStore.getState().graph;
    expect(g.nodes[A]).toBeUndefined();
    expect(g.nodes[A1]).toBeUndefined();
    expect(g.nodes[A2]).toBeUndefined();
    expect(g.nodes[ROOT_ID].childIds).not.toContain(A);
  });

  it("removeNode refuses to remove root", () => {
    useSceneStore.getState().removeNode(ROOT_ID);
    expect(useSceneStore.getState().graph.nodes[ROOT_ID]).toBeDefined();
  });

  it("renameNode updates the name", () => {
    const id = useSceneStore.getState().addNode({ kind: "prop", name: "Old" });
    useSceneStore.getState().renameNode(id, "New");
    expect(useSceneStore.getState().graph.nodes[id].name).toBe("New");
  });
});

describe("useSceneStore — visibility / lock toggles", () => {
  it("toggleVisibility flips the visible flag", () => {
    const id = useSceneStore.getState().addNode({ kind: "prop", name: "T" });
    expect(useSceneStore.getState().graph.nodes[id].visible).toBe(true);
    useSceneStore.getState().toggleVisibility(id);
    expect(useSceneStore.getState().graph.nodes[id].visible).toBe(false);
    useSceneStore.getState().toggleVisibility(id);
    expect(useSceneStore.getState().graph.nodes[id].visible).toBe(true);
  });

  it("toggleLock flips the locked flag", () => {
    const id = useSceneStore.getState().addNode({ kind: "prop", name: "T" });
    useSceneStore.getState().toggleLock(id);
    expect(useSceneStore.getState().graph.nodes[id].locked).toBe(true);
  });
});

describe("useSceneStore — selection", () => {
  it("setSelection replaces the selection with the given ids", () => {
    const a = useSceneStore.getState().addNode({ kind: "prop", name: "a" });
    const b = useSceneStore.getState().addNode({ kind: "prop", name: "b" });
    useSceneStore.getState().setSelection([a, b]);
    expect(useSceneStore.getState().selection).toEqual([a, b]);
  });

  it("toggleSelection adds when missing, removes when present", () => {
    const a = useSceneStore.getState().addNode({ kind: "prop", name: "a" });
    useSceneStore.getState().toggleSelection(a);
    expect(useSceneStore.getState().selection).toContain(a);
    useSceneStore.getState().toggleSelection(a);
    expect(useSceneStore.getState().selection).not.toContain(a);
  });

  it("clearSelection empties the selection", () => {
    const a = useSceneStore.getState().addNode({ kind: "prop", name: "a" });
    useSceneStore.getState().setSelection([a]);
    useSceneStore.getState().clearSelection();
    expect(useSceneStore.getState().selection).toEqual([]);
  });

  it("removed node is dropped from selection", () => {
    const a = useSceneStore.getState().addNode({ kind: "prop", name: "a" });
    useSceneStore.getState().setSelection([a]);
    useSceneStore.getState().removeNode(a);
    expect(useSceneStore.getState().selection).not.toContain(a);
  });
});

describe("useSceneStore — moveNode (re-parent / re-order)", () => {
  it("moveNode changes parent and inserts at index", () => {
    const G1 = useSceneStore.getState().addNode({ kind: "group", name: "G1" });
    const G2 = useSceneStore.getState().addNode({ kind: "group", name: "G2" });
    const item = useSceneStore.getState().addNode({ kind: "prop", name: "item", parentId: G1 });
    useSceneStore.getState().moveNode(item, G2, 0);
    const g = useSceneStore.getState().graph;
    expect(g.nodes[item].parentId).toBe(G2);
    expect(g.nodes[G1].childIds).not.toContain(item);
    expect(g.nodes[G2].childIds[0]).toBe(item);
  });

  it("moveNode rejects creating a cycle (drop on descendant)", () => {
    const G = useSceneStore.getState().addNode({ kind: "group", name: "G" });
    const child = useSceneStore.getState().addNode({ kind: "group", name: "child", parentId: G });
    const before = useSceneStore.getState().graph.nodes[G].parentId;
    useSceneStore.getState().moveNode(G, child, 0); // try to put G under its own descendant
    expect(useSceneStore.getState().graph.nodes[G].parentId).toBe(before);
    expect(useSceneStore.getState().graph.nodes[child].parentId).toBe(G);
  });

  it("moveNode within same parent re-orders", () => {
    const a = useSceneStore.getState().addNode({ kind: "prop", name: "a" });
    const b = useSceneStore.getState().addNode({ kind: "prop", name: "b" });
    const c = useSceneStore.getState().addNode({ kind: "prop", name: "c" });
    useSceneStore.getState().moveNode(c, ROOT_ID, 0);
    expect(useSceneStore.getState().graph.nodes[ROOT_ID].childIds).toEqual([c, a, b]);
  });
});
