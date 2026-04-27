import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { Outliner } from "../Outliner";
import { useSceneStore, __resetSceneStoreForTest } from "../../../../scene/useSceneStore";
import { ROOT_ID } from "../../../../scene/scene-types";

beforeEach(() => __resetSceneStoreForTest());

function seed() {
  const G = useSceneStore.getState().addNode({ kind: "group", name: "Decor" });
  const P1 = useSceneStore.getState().addNode({ kind: "prop", name: "Tree", parentId: G });
  const P2 = useSceneStore.getState().addNode({ kind: "prop", name: "Rock", parentId: G });
  const V = useSceneStore.getState().addNode({ kind: "vrm", name: "Shugu" });
  return { G, P1, P2, V };
}

describe("Outliner — rendering", () => {
  it("shows an empty hint when only root exists", () => {
    render(<Outliner />);
    expect(screen.getByText(/empty scene/i)).toBeInTheDocument();
  });

  it("renders all non-root nodes flat in DFS order", () => {
    seed();
    render(<Outliner />);
    const items = screen.getAllByRole("treeitem");
    const names = items.map((el) => el.textContent ?? "");
    expect(names[0]).toContain("Decor");
    expect(names[1]).toContain("Tree");
    expect(names[2]).toContain("Rock");
    expect(names[3]).toContain("Shugu");
  });

  it("indents children visually via aria-level (DFS depth)", () => {
    seed();
    render(<Outliner />);
    const items = screen.getAllByRole("treeitem");
    expect(items[0]).toHaveAttribute("aria-level", "1"); // Decor under root
    expect(items[1]).toHaveAttribute("aria-level", "2"); // Tree under Decor
    expect(items[2]).toHaveAttribute("aria-level", "2"); // Rock under Decor
    expect(items[3]).toHaveAttribute("aria-level", "1"); // Shugu under root
  });
});

describe("Outliner — selection", () => {
  it("clicking a row selects it (replaces selection)", () => {
    const { P1, P2 } = seed();
    render(<Outliner />);
    const trees = screen.getAllByRole("treeitem");
    fireEvent.click(trees[1]); // Tree
    expect(useSceneStore.getState().selection).toEqual([P1]);
    fireEvent.click(trees[2]); // Rock — replace
    expect(useSceneStore.getState().selection).toEqual([P2]);
  });

  it("Ctrl+click toggles selection", () => {
    const { P1, P2 } = seed();
    render(<Outliner />);
    const trees = screen.getAllByRole("treeitem");
    fireEvent.click(trees[1]);
    fireEvent.click(trees[2], { ctrlKey: true });
    expect(useSceneStore.getState().selection).toEqual([P1, P2]);
    fireEvent.click(trees[2], { ctrlKey: true });
    expect(useSceneStore.getState().selection).toEqual([P1]);
  });

  it("selected row exposes aria-selected=true", () => {
    const { V } = seed();
    act(() => useSceneStore.getState().setSelection([V]));
    render(<Outliner />);
    const shugu = screen.getAllByRole("treeitem").find((el) => el.textContent?.includes("Shugu"));
    expect(shugu).toHaveAttribute("aria-selected", "true");
  });
});

describe("Outliner — visibility / lock toggles", () => {
  it("clicking the eye toggles visibility (and stops selection propagation)", () => {
    const { P1 } = seed();
    render(<Outliner />);
    const eye = screen.getByLabelText(`Toggle visibility — Tree`);
    fireEvent.click(eye);
    expect(useSceneStore.getState().graph.nodes[P1].visible).toBe(false);
    expect(useSceneStore.getState().selection).not.toContain(P1);
  });

  it("clicking the lock toggles locked", () => {
    const { P1 } = seed();
    render(<Outliner />);
    const lock = screen.getByLabelText(`Toggle lock — Tree`);
    fireEvent.click(lock);
    expect(useSceneStore.getState().graph.nodes[P1].locked).toBe(true);
  });
});

describe("Outliner — empty / search", () => {
  it("filters by name (case-insensitive substring)", () => {
    seed();
    render(<Outliner />);
    const search = screen.getByPlaceholderText(/search/i);
    fireEvent.change(search, { target: { value: "tre" } });
    expect(screen.queryByText("Tree")).toBeInTheDocument();
    expect(screen.queryByText("Rock")).not.toBeInTheDocument();
    expect(screen.queryByText("Decor")).not.toBeInTheDocument();
  });

  it("shows no-match state when search is empty", () => {
    seed();
    render(<Outliner />);
    const search = screen.getByPlaceholderText(/search/i);
    fireEvent.change(search, { target: { value: "zzznomatch" } });
    expect(screen.getByText(/no node matches/i)).toBeInTheDocument();
  });
});

describe("Outliner — delete via key", () => {
  it("Delete key removes the selected node", () => {
    const { P1 } = seed();
    act(() => useSceneStore.getState().setSelection([P1]));
    render(<Outliner />);
    fireEvent.keyDown(screen.getByRole("tree"), { key: "Delete" });
    expect(useSceneStore.getState().graph.nodes[P1]).toBeUndefined();
  });

  it("Delete on root no-op", () => {
    seed();
    act(() => useSceneStore.getState().setSelection([ROOT_ID]));
    render(<Outliner />);
    fireEvent.keyDown(screen.getByRole("tree"), { key: "Delete" });
    expect(useSceneStore.getState().graph.nodes[ROOT_ID]).toBeDefined();
  });
});
