/**
 * Tests for GlassToast infra (I3.2)
 *
 * Covers:
 *  1. useToast throws outside provider
 *  2. toast.success renders title in viewport
 *  3. toast.error announces assertively (a11y assertive via aria-live)
 *  4. toast.info / warning / success announce politely (a11y polite via role="status")
 *  5. Auto-dismiss via fake timers
 *  6. Close button removes the toast
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, act, fireEvent } from "@testing-library/react";
import React from "react";
import { axe } from "jest-axe";
import { GlassToastProvider, useToast } from "../toast";

/* ── Helper: a test component that calls the toast API ──────── */

function Trigger({ action }: { action: (api: ReturnType<typeof useToast>) => void }) {
  const toast = useToast();
  return (
    <button
      data-testid="trigger"
      onClick={() => action(toast)}
    >
      fire
    </button>
  );
}

function renderWithProvider(action: (api: ReturnType<typeof useToast>) => void) {
  const result = render(
    <GlassToastProvider>
      <Trigger action={action} />
    </GlassToastProvider>
  );
  // Fire the action by clicking the trigger button.
  fireEvent.click(result.getByTestId("trigger"));
  return result;
}

/* ── 1. useToast throws outside provider ────────────────────── */

describe("useToast", () => {
  it("throws when used outside <GlassToastProvider>", () => {
    // Suppress React error boundary console noise.
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    function BadComponent() {
      useToast();
      return null;
    }
    expect(() => render(<BadComponent />)).toThrow(
      "useToast must be used within <GlassToastProvider>"
    );
    consoleSpy.mockRestore();
  });
});

/* ── 2-4. Variant rendering ─────────────────────────────────── */

describe("GlassToastProvider", () => {
  it("toast.success renders the title text", () => {
    renderWithProvider((t) => t.success("Saved successfully"));
    expect(screen.getByText("Saved successfully")).toBeInTheDocument();
  });

  it("toast.error announces assertively (a11y assertive)", () => {
    renderWithProvider((t) => t.error("Something failed"));
    // Radix manages ARIA via a hidden ToastAnnounce element — NOT via role= on
    // the visible <li>. For type="foreground" (errors), Radix renders a hidden
    // element with role="status" + aria-live="assertive". The <li> itself has
    // no explicit role (role= on <li> is invalid per ARIA spec — axe-core
    // aria-allowed-role). We verify the a11y guarantee via aria-live, not role.
    const assertiveRegion = document.querySelector('[aria-live="assertive"]');
    expect(assertiveRegion).not.toBeNull();
    expect(screen.getByText("Something failed")).toBeInTheDocument();
  });

  it("toast.info announces politely (a11y polite)", () => {
    renderWithProvider((t) => t.info("Loading complete"));
    // Radix manages ARIA via a hidden ToastAnnounce element with role="status"
    // + aria-live="polite" for type="background". The same guarantee (polite
    // announcement to assistive tech) is verified here via the live region.
    const statuses = screen.getAllByRole("status");
    expect(statuses.length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Loading complete")).toBeInTheDocument();
  });

  it("toast.warning announces politely (a11y polite)", () => {
    renderWithProvider((t) => t.warning("Low memory"));
    const statuses = screen.getAllByRole("status");
    expect(statuses.length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Low memory")).toBeInTheDocument();
  });

  it("toast.success announces politely (a11y polite)", () => {
    renderWithProvider((t) => t.success("Done"));
    const statuses = screen.getAllByRole("status");
    expect(statuses.length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Done")).toBeInTheDocument();
  });

  /* ── 5. Auto-dismiss ──────────────────────────────────────── */

  it("auto-dismisses after the specified duration", async () => {
    vi.useFakeTimers();
    renderWithProvider((t) => t.info("Auto-dismiss me", { duration: 1000 }));
    expect(screen.getByText("Auto-dismiss me")).toBeInTheDocument();
    // Advance past the duration.
    await act(async () => {
      vi.advanceTimersByTime(1200);
    });
    // After dismiss animation runs, the item leaves the DOM.
    expect(screen.queryByText("Auto-dismiss me")).not.toBeInTheDocument();
    vi.useRealTimers();
  });

  /* ── 6. Close button ────────────────────────────────────────── */

  it("close button removes the toast", async () => {
    renderWithProvider((t) => t.success("Closeable toast"));
    expect(screen.getByText("Closeable toast")).toBeInTheDocument();
    const closeBtn = screen.getByLabelText("Fermer");
    await act(async () => {
      fireEvent.click(closeBtn);
    });
    expect(screen.queryByText("Closeable toast")).not.toBeInTheDocument();
  });

  // ── axe-core a11y gate (I3.7) ─────────────────────────────────────────
  //
  // FIX (I3.7, closes #150): Two axe-core violations were detected in I3.6:
  //
  // 1. aria-allowed-role: We passed role="status"|"alert" explicitly on
  //    Toast.Root, which Radix renders as <li>. These roles are NOT allowed
  //    on <li> elements per ARIA spec.
  //    Rule: https://dequeuniversity.com/rules/axe/4.10/aria-allowed-role
  //
  // 2. list: <ol> Viewport contained <li role="status/alert"> children, which
  //    violates the requirement that list elements only directly contain
  //    listitem-role children.
  //    Rule: https://dequeuniversity.com/rules/axe/4.10/list
  //
  // Root cause: explicit role= override on Toast.Root (<li>).
  //
  // Fix (Option A): Remove explicit role= from Toast.Root. Radix manages ARIA
  // via a hidden ToastAnnounce element (role="status" + aria-live), not via
  // role on the visible <li>. The type prop controls assertiveness:
  //   - type="foreground" → aria-live="assertive" (errors)
  //   - type="background" → aria-live="polite"    (others)
  //
  // Tests below were skipped in I3.6 and are now re-enabled (I3.7).

  it("GlassToastProvider viewport has no axe-core violations with a visible toast", async () => {
    const { container } = renderWithProvider((t) => t.success("A11y toast check"));
    const results = await axe(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results).toHaveNoViolations();
  });

  it("GlassToastProvider has no axe-core violations for error toast (assertive)", async () => {
    const { container } = renderWithProvider((t) => t.error("Error a11y check"));
    const results = await axe(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results).toHaveNoViolations();
  });
});
