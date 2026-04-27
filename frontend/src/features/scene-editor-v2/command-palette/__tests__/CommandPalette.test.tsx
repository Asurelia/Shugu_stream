import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { CommandPalette } from "../CommandPalette";
import { useSceneEditorStore, __resetSceneEditorStoreForTest } from "../../store/useSceneEditorStore";

beforeEach(() => __resetSceneEditorStoreForTest());

describe("CommandPalette", () => {
  it("renders nothing when paletteOpen=false", () => {
    render(<CommandPalette />);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("renders the modal dialog when paletteOpen=true", () => {
    act(() => useSceneEditorStore.getState().openPalette());
    render(<CommandPalette />);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("shows all commands by default", () => {
    act(() => useSceneEditorStore.getState().openPalette());
    render(<CommandPalette />);
    expect(screen.getByText("Switch to Scene 3D")).toBeInTheDocument();
    expect(screen.getByText("Switch to Overlays 2D")).toBeInTheDocument();
    expect(screen.getByText("Switch to Show / Preview")).toBeInTheDocument();
  });

  it("filters commands as user types in search", () => {
    act(() => useSceneEditorStore.getState().openPalette());
    render(<CommandPalette />);
    const input = screen.getByRole("combobox");
    fireEvent.change(input, { target: { value: "overlay" } });
    expect(screen.getByText("Switch to Overlays 2D")).toBeInTheDocument();
    expect(screen.queryByText("Switch to Scene 3D")).not.toBeInTheDocument();
  });

  it("runs command on click and closes palette", () => {
    act(() => useSceneEditorStore.getState().openPalette());
    render(<CommandPalette />);
    fireEvent.click(screen.getByText("Switch to Show / Preview"));
    expect(useSceneEditorStore.getState().currentWorkspace).toBe("show");
    expect(useSceneEditorStore.getState().paletteOpen).toBe(false);
  });

  it("Enter runs the first matching command", () => {
    act(() => useSceneEditorStore.getState().openPalette());
    render(<CommandPalette />);
    const input = screen.getByRole("combobox");
    fireEvent.change(input, { target: { value: "show" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(useSceneEditorStore.getState().currentWorkspace).toBe("show");
    expect(useSceneEditorStore.getState().paletteOpen).toBe(false);
  });

  it("ArrowDown / ArrowUp moves the active option", () => {
    act(() => useSceneEditorStore.getState().openPalette());
    render(<CommandPalette />);
    const input = screen.getByRole("combobox");
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "Enter" });
    // Default order: 3d → 2d → show. Two ArrowDowns = activate "Show".
    expect(useSceneEditorStore.getState().currentWorkspace).toBe("show");
  });

  it("Escape closes palette", () => {
    act(() => useSceneEditorStore.getState().openPalette());
    render(<CommandPalette />);
    const input = screen.getByRole("combobox");
    fireEvent.keyDown(input, { key: "Escape" });
    expect(useSceneEditorStore.getState().paletteOpen).toBe(false);
  });

  it("shows empty state when no command matches", () => {
    act(() => useSceneEditorStore.getState().openPalette());
    render(<CommandPalette />);
    const input = screen.getByRole("combobox");
    fireEvent.change(input, { target: { value: "zzzzzznomatch" } });
    expect(screen.getByText(/no command/i)).toBeInTheDocument();
  });
});
