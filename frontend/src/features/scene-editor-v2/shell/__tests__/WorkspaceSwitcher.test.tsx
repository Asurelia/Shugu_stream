import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { WorkspaceSwitcher } from "../WorkspaceSwitcher";
import { useSceneEditorStore, __resetSceneEditorStoreForTest } from "../../store/useSceneEditorStore";

beforeEach(() => __resetSceneEditorStoreForTest());

describe("WorkspaceSwitcher", () => {
  it("renders 3 tabs labelled Scene 3D / Overlays / Show", () => {
    render(<WorkspaceSwitcher />);
    expect(screen.getByRole("tab", { name: /scene 3d/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /overlays/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /show/i })).toBeInTheDocument();
  });

  it("marks the current workspace tab aria-selected=true", () => {
    render(<WorkspaceSwitcher />);
    expect(screen.getByRole("tab", { name: /scene 3d/i })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: /overlays/i })).toHaveAttribute("aria-selected", "false");
    expect(screen.getByRole("tab", { name: /show/i })).toHaveAttribute("aria-selected", "false");
  });

  it("changes the store currentWorkspace when a tab is clicked", () => {
    render(<WorkspaceSwitcher />);
    fireEvent.click(screen.getByRole("tab", { name: /overlays/i }));
    expect(useSceneEditorStore.getState().currentWorkspace).toBe("2d");
    fireEvent.click(screen.getByRole("tab", { name: /show/i }));
    expect(useSceneEditorStore.getState().currentWorkspace).toBe("show");
  });

  it("reflects external store changes in aria-selected", () => {
    render(<WorkspaceSwitcher />);
    act(() => {
      useSceneEditorStore.getState().setWorkspace("show");
    });
    expect(screen.getByRole("tab", { name: /show/i })).toHaveAttribute("aria-selected", "true");
  });
});
