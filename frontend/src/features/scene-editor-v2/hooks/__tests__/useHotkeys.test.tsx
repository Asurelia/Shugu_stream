import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { useHotkeys } from "../useHotkeys";

function Probe(props: { onFire: (key: string) => void }) {
  useHotkeys([
    { key: "1", handler: () => props.onFire("1") },
    { key: "2", handler: () => props.onFire("2") },
    { key: "3", handler: () => props.onFire("3") },
    { key: "k", mod: true, handler: () => props.onFire("mod+k"), preventDefault: true },
    { key: "Escape", handler: () => props.onFire("escape") },
  ]);
  return <div data-testid="probe">probe</div>;
}

function dispatch(target: Element | Node | Window | Document, init: KeyboardEventInit & { key: string }) {
  // fireEvent.keyDown bubbles by default; pass on the element so target is correct.
  fireEvent.keyDown(target, init);
}

afterEach(() => { vi.restoreAllMocks(); });

describe("useHotkeys", () => {
  it("fires on plain key press dispatched from body", () => {
    const fire = vi.fn();
    render(<Probe onFire={fire} />);
    dispatch(document.body, { key: "2" });
    expect(fire).toHaveBeenCalledWith("2");
  });

  it("fires on Mod+K", () => {
    const fire = vi.fn();
    render(<Probe onFire={fire} />);
    dispatch(document.body, { key: "k", ctrlKey: true });
    expect(fire).toHaveBeenCalledWith("mod+k");
  });

  it("fires on Escape", () => {
    const fire = vi.fn();
    render(<Probe onFire={fire} />);
    dispatch(document.body, { key: "Escape" });
    expect(fire).toHaveBeenCalledWith("escape");
  });

  it("ignores plain keys when an INPUT is the event target", () => {
    const fire = vi.fn();
    render(
      <>
        <input data-testid="input" />
        <Probe onFire={fire} />
      </>,
    );
    dispatch(screen.getByTestId("input"), { key: "2" });
    expect(fire).not.toHaveBeenCalledWith("2");
  });

  it("ignores plain keys when a TEXTAREA is the event target", () => {
    const fire = vi.fn();
    render(
      <>
        <textarea data-testid="textarea" />
        <Probe onFire={fire} />
      </>,
    );
    dispatch(screen.getByTestId("textarea"), { key: "2" });
    expect(fire).not.toHaveBeenCalledWith("2");
  });

  it("STILL fires Mod+K even when input is the target (modifier shortcuts always active)", () => {
    const fire = vi.fn();
    render(
      <>
        <input data-testid="input" />
        <Probe onFire={fire} />
      </>,
    );
    dispatch(screen.getByTestId("input"), { key: "k", ctrlKey: true });
    expect(fire).toHaveBeenCalledWith("mod+k");
  });

  it("STILL fires Escape even when input is the target (escape closes things)", () => {
    const fire = vi.fn();
    render(
      <>
        <input data-testid="input" />
        <Probe onFire={fire} />
      </>,
    );
    dispatch(screen.getByTestId("input"), { key: "Escape" });
    expect(fire).toHaveBeenCalledWith("escape");
  });

  it("removes listener on unmount", () => {
    const fire = vi.fn();
    const { unmount } = render(<Probe onFire={fire} />);
    unmount();
    act(() => {
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "1" }));
    });
    expect(fire).not.toHaveBeenCalled();
  });

  it("respects shift modifier requirement", () => {
    const fire = vi.fn();
    function ShiftProbe() {
      useHotkeys([{ key: "S", shift: true, mod: true, handler: () => fire("shift+mod+s") }]);
      return null;
    }
    render(<ShiftProbe />);
    dispatch(document.body, { key: "S", ctrlKey: true });
    expect(fire).not.toHaveBeenCalled();
    dispatch(document.body, { key: "S", ctrlKey: true, shiftKey: true });
    expect(fire).toHaveBeenCalledWith("shift+mod+s");
  });
});
