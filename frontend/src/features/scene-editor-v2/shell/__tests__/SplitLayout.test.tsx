import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { SplitLayout } from "../SplitLayout";
import { __resetSceneEditorStoreForTest, useSceneEditorStore } from "../../store/useSceneEditorStore";

beforeEach(() => __resetSceneEditorStoreForTest());

describe("SplitLayout", () => {
  it("renders both children", () => {
    render(
      <SplitLayout id="test-1" direction="horizontal">
        <div>Left</div>
        <div>Right</div>
      </SplitLayout>,
    );
    expect(screen.getByText("Left")).toBeInTheDocument();
    expect(screen.getByText("Right")).toBeInTheDocument();
  });

  it("renders a draggable separator with correct ARIA", () => {
    render(
      <SplitLayout id="test-2" direction="horizontal" defaultRatio={0.4}>
        <div>L</div>
        <div>R</div>
      </SplitLayout>,
    );
    const sep = screen.getByRole("separator");
    expect(sep).toHaveAttribute("aria-orientation", "vertical");
    expect(sep).toHaveAttribute("aria-valuenow", "40");
    expect(sep).toHaveAttribute("aria-valuemin", "5");
    expect(sep).toHaveAttribute("aria-valuemax", "95");
  });

  it("uses vertical orientation when direction=vertical", () => {
    render(
      <SplitLayout id="test-3" direction="vertical">
        <div>Top</div>
        <div>Bot</div>
      </SplitLayout>,
    );
    expect(screen.getByRole("separator")).toHaveAttribute("aria-orientation", "horizontal");
  });

  it("persists ratio in store after drag", () => {
    const setSpy = vi.spyOn(useSceneEditorStore.getState(), "setSplitRatio");
    const { container } = render(
      <SplitLayout id="test-4" direction="horizontal" defaultRatio={0.5}>
        <div>L</div>
        <div>R</div>
      </SplitLayout>,
    );
    // Mock container offsetWidth (jsdom returns 0).
    const root = container.querySelector("[data-testid=\"split-root\"]") as HTMLElement;
    Object.defineProperty(root, "getBoundingClientRect", {
      value: () => ({ left: 0, top: 0, right: 1000, bottom: 600, width: 1000, height: 600, x: 0, y: 0, toJSON() { return {}; } }),
    });

    const sep = screen.getByRole("separator");
    fireEvent.mouseDown(sep, { clientX: 500, clientY: 300 });
    fireEvent.mouseMove(window, { clientX: 700, clientY: 300 });
    fireEvent.mouseUp(window, { clientX: 700, clientY: 300 });

    expect(setSpy).toHaveBeenCalled();
    const [id, ratio] = setSpy.mock.calls[setSpy.mock.calls.length - 1];
    expect(id).toBe("test-4");
    expect(ratio).toBeGreaterThan(0.5);
    expect(ratio).toBeLessThanOrEqual(0.95);
  });

  it("clamps the ratio to [0.05, 0.95]", () => {
    const { container } = render(
      <SplitLayout id="test-5" direction="horizontal" defaultRatio={0.5}>
        <div>L</div>
        <div>R</div>
      </SplitLayout>,
    );
    const root = container.querySelector("[data-testid=\"split-root\"]") as HTMLElement;
    Object.defineProperty(root, "getBoundingClientRect", {
      value: () => ({ left: 0, top: 0, right: 1000, bottom: 600, width: 1000, height: 600, x: 0, y: 0, toJSON() { return {}; } }),
    });
    const sep = screen.getByRole("separator");
    fireEvent.mouseDown(sep, { clientX: 500 });
    fireEvent.mouseMove(window, { clientX: 9999 });
    fireEvent.mouseUp(window);
    expect(useSceneEditorStore.getState().splitRatios["test-5"]).toBeLessThanOrEqual(0.95);
    expect(useSceneEditorStore.getState().splitRatios["test-5"]).toBeGreaterThanOrEqual(0.05);
  });
});
