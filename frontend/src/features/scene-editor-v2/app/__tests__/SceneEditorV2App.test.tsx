import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { SceneEditorV2App } from "../SceneEditorV2App";
import { __resetSceneEditorStoreForTest, useSceneEditorStore } from "../../store/useSceneEditorStore";

vi.mock("next/router", () => ({
  useRouter: () => ({ query: { username: "shugu" }, push: vi.fn(), replace: vi.fn(), back: vi.fn() }),
}));

beforeEach(() => __resetSceneEditorStoreForTest());

describe("SceneEditorV2App", () => {
  it("renders topbar, workspace area and statusbar", () => {
    render(<SceneEditorV2App />);
    expect(screen.getByRole("banner")).toBeInTheDocument();
    expect(screen.getByRole("main")).toBeInTheDocument();
    expect(screen.getByRole("contentinfo")).toBeInTheDocument();
  });

  it("renders the WorkspaceSwitcher with 3 tabs in topbar", () => {
    render(<SceneEditorV2App />);
    expect(screen.getByRole("tab", { name: /scene 3d/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /overlays/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /show/i })).toBeInTheDocument();
  });

  it("renders Workspace3D by default (3d viewport label)", () => {
    render(<SceneEditorV2App />);
    expect(screen.getByLabelText(/3d viewport/i)).toBeInTheDocument();
  });

  it("hotkey '2' switches to Workspace2D (safe area)", () => {
    render(<SceneEditorV2App />);
    fireEvent.keyDown(document.body, { key: "2" });
    expect(screen.getByLabelText(/2d safe area/i)).toBeInTheDocument();
    expect(useSceneEditorStore.getState().currentWorkspace).toBe("2d");
  });

  it("hotkey '3' switches to WorkspaceShow", () => {
    render(<SceneEditorV2App />);
    fireEvent.keyDown(document.body, { key: "3" });
    expect(screen.getByLabelText(/show \/ preview compositing/i)).toBeInTheDocument();
    expect(useSceneEditorStore.getState().currentWorkspace).toBe("show");
  });

  it("Mod+K opens the command palette", () => {
    render(<SceneEditorV2App />);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    fireEvent.keyDown(document.body, { key: "k", ctrlKey: true });
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("Escape closes the command palette", () => {
    render(<SceneEditorV2App />);
    act(() => useSceneEditorStore.getState().openPalette());
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    fireEvent.keyDown(document.body, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("statusbar shows current workspace label", () => {
    render(<SceneEditorV2App />);
    const status = screen.getByRole("contentinfo");
    expect(status.textContent).toMatch(/scene 3d/i);
    fireEvent.keyDown(document.body, { key: "2" });
    expect(status.textContent).toMatch(/overlays/i);
  });

  it("hotkey '1' is ignored when an INPUT is the event target", () => {
    render(
      <>
        <input data-testid="trap" />
        <SceneEditorV2App />
      </>,
    );
    act(() => useSceneEditorStore.getState().setWorkspace("show"));
    fireEvent.keyDown(screen.getByTestId("trap"), { key: "1" });
    expect(useSceneEditorStore.getState().currentWorkspace).toBe("show");
  });
});
