/**
 * AdminModal a11y tests — updated for I3.1 (Radix Dialog backend).
 *
 * Verifies the accessibility guarantees provided by GlassModal + Radix Dialog:
 *   - role="dialog" + aria-modal="true" present when open (Dialog.Content)
 *   - aria-labelledby wires the dialog to its heading
 *   - Escape key fires onClose (Radix listens on document, not window)
 *   - Close button has aria-label="Fermer"
 *   - Clicking the scrim (Overlay) fires onClose
 *   - Focus trap: Tab cycles within the open dialog (NEW — Radix native)
 *
 * Migration notes (I3.1 — Radix Dialog):
 *   - role="dialog" is now on Dialog.Content, not on the scrim div.
 *   - aria-modal="true" is explicitly forwarded to Dialog.Content.
 *   - Radix Escape handling listens on `document` (not `window`); tests use
 *     fireEvent.keyDown(document, ...) accordingly.
 *   - Scrim click test fires on the Overlay element (`.lg-scrim`) since
 *     Radix renders Overlay and Content as siblings inside the Portal.
 *   - Focus trap is now tested via userEvent.tab() cycling.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "jest-axe";
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
    // Radix Dialog listens on `document` (not `window`) for Escape.
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("clicking the scrim (Overlay) calls onClose", async () => {
    const onClose = vi.fn();
    render(<AdminModal open onClose={onClose} />);
    // Radix's DismissableLayer registers its `pointerdown` listener inside a
    // setTimeout(0) to avoid conflicts with the opening click. We flush the
    // microtask queue + one timer tick so the listener is registered before
    // we fire the event.
    await new Promise((r) => setTimeout(r, 0));
    // Radix renders Dialog.Overlay and Dialog.Content as siblings inside the
    // Portal. The Overlay carries the .lg-scrim class; a pointerdown on it
    // (outside Content) triggers DismissableLayer → onOpenChange(false) → onClose.
    const overlay = document.querySelector(".lg-scrim") as HTMLElement;
    expect(overlay).toBeInTheDocument();
    fireEvent.pointerDown(overlay);
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("Tab navigation cycles focus within the open dialog (focus trap)", async () => {
    const user = userEvent.setup();
    render(<AdminModal open onClose={vi.fn()} />);
    const dialog = screen.getByRole("dialog");
    // Collect all focusable elements inside the dialog
    const focusable = dialog.querySelectorAll<HTMLElement>(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
    );
    expect(focusable.length).toBeGreaterThan(0);
    // Tab through all focusable elements + one extra to confirm cycling back
    for (let i = 0; i <= focusable.length; i++) {
      await user.tab();
    }
    // After cycling, focus must remain inside the dialog
    expect(dialog).toContainElement(document.activeElement as HTMLElement);
  });

  // ── axe-core a11y gate (I3.6) ─────────────────────────────────────────
  // Color contrast is disabled: JSDOM has no canvas — axe cannot measure
  // computed colors reliably (may produce false positives). Tracked for
  // Playwright-based I3.7 follow-up.
  it("has no axe-core violations when open (excluding color-contrast)", async () => {
    const { container } = render(<AdminModal open onClose={vi.fn()} />);
    const results = await axe(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results).toHaveNoViolations();
  });
});
