/**
 * AdminModal a11y tests — U2 UX audit 2026-05-09.
 *
 * Verifies the accessibility guarantees brought by the GlassModal migration:
 *   - role="dialog" + aria-modal="true" present when open
 *   - aria-labelledby wires the dialog to its heading
 *   - Escape key fires onClose
 *   - Close button has aria-label="Fermer"
 *
 * Note: focus trap is NOT tested here — GlassModal does not yet implement
 * one. That is tracked as item I3 (Radix UI migration). This comment should
 * be updated when I3 lands.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { AdminModal } from "../AdminModal";

// Stub fetch so the polling useEffect does not crash in jsdom.
beforeEach(() => {
  // Return a never-resolving promise so we don't need to flush timers.
  global.fetch = vi.fn(() => new Promise(() => {})) as any;
});

afterEach(() => {
  cleanup();
});

describe("AdminModal a11y (U2 migration)", () => {
  it("renders nothing when closed", () => {
    const { container } = render(<AdminModal open={false} onClose={vi.fn()} />);
    expect(container.firstChild).toBeNull();
  });

  it("has role='dialog' and aria-modal='true' when open", () => {
    render(<AdminModal open onClose={vi.fn()} />);
    const dialog = screen.getByRole("dialog");
    expect(dialog).toBeInTheDocument();
    expect(dialog).toHaveAttribute("aria-modal", "true");
  });

  it("aria-labelledby points to the title heading", () => {
    render(<AdminModal open onClose={vi.fn()} />);
    const dialog = screen.getByRole("dialog");
    const labelId = dialog.getAttribute("aria-labelledby");
    expect(labelId).toBeTruthy();
    const heading = document.getElementById(labelId!);
    expect(heading).toBeInTheDocument();
    expect(heading?.textContent).toMatch(/Dashboard admin/);
  });

  it("close button has aria-label='Fermer'", () => {
    render(<AdminModal open onClose={vi.fn()} />);
    const closeBtn = screen.getByRole("button", { name: "Fermer" });
    expect(closeBtn).toBeInTheDocument();
  });

  it("pressing Escape calls onClose", () => {
    const onClose = vi.fn();
    render(<AdminModal open onClose={onClose} />);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("clicking the scrim calls onClose", () => {
    const onClose = vi.fn();
    render(<AdminModal open onClose={onClose} />);
    const dialog = screen.getByRole("dialog");
    // Click directly on the scrim (the dialog itself, not a child)
    fireEvent.click(dialog);
    expect(onClose).toHaveBeenCalledOnce();
  });
});
