/**
 * Tests for GlassSwitch (I3.4) — Radix Switch backend
 *
 * Covers:
 *  1. Renders with role="switch" and correct aria-checked
 *  2. Click fires onChange with the toggled value
 *  3. Space key toggles (Radix-provided keyboard handling)
 *  4. aria-label is propagated to the DOM node
 *  5. disabled blocks click interaction
 *  6. disabled blocks Space key interaction
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { GlassSwitch } from "../primitives";

describe("GlassSwitch", () => {
  /* ── 1. Renders with correct ARIA attributes ──────────────── */

  it("renders with role='switch' and aria-checked=false when checked=false", () => {
    render(
      <GlassSwitch checked={false} onChange={vi.fn()} aria-label="Test switch" />
    );
    const sw = screen.getByRole("switch", { name: "Test switch" });
    expect(sw).toBeInTheDocument();
    expect(sw).toHaveAttribute("aria-checked", "false");
  });

  it("renders with aria-checked=true when checked=true", () => {
    render(
      <GlassSwitch checked={true} onChange={vi.fn()} aria-label="Test switch" />
    );
    const sw = screen.getByRole("switch", { name: "Test switch" });
    expect(sw).toHaveAttribute("aria-checked", "true");
  });

  /* ── 2. Click fires onChange ─────────────────────────────── */

  it("calls onChange(true) when clicked in unchecked state", () => {
    const onChange = vi.fn();
    render(
      <GlassSwitch checked={false} onChange={onChange} aria-label="Toggle me" />
    );
    fireEvent.click(screen.getByRole("switch", { name: "Toggle me" }));
    expect(onChange).toHaveBeenCalledOnce();
    expect(onChange).toHaveBeenCalledWith(true);
  });

  it("calls onChange(false) when clicked in checked state", () => {
    const onChange = vi.fn();
    render(
      <GlassSwitch checked={true} onChange={onChange} aria-label="Toggle me" />
    );
    fireEvent.click(screen.getByRole("switch", { name: "Toggle me" }));
    expect(onChange).toHaveBeenCalledOnce();
    expect(onChange).toHaveBeenCalledWith(false);
  });

  /* ── 3. Space key toggles (Radix keyboard handling) ─────── */

  it("calls onChange(true) when Space is pressed in unchecked state", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <GlassSwitch checked={false} onChange={onChange} aria-label="Keyboard switch" />
    );
    const sw = screen.getByRole("switch", { name: "Keyboard switch" });
    sw.focus();
    await user.keyboard(" ");
    expect(onChange).toHaveBeenCalledOnce();
    expect(onChange).toHaveBeenCalledWith(true);
  });

  /* ── 4. aria-label is propagated ────────────────────────── */

  it("applies aria-label to the underlying element", () => {
    render(
      <GlassSwitch checked={false} onChange={vi.fn()} aria-label="My custom label" />
    );
    expect(screen.getByRole("switch", { name: "My custom label" })).toBeInTheDocument();
  });

  /* ── 5. disabled blocks click ────────────────────────────── */

  it("does not call onChange when disabled and clicked", () => {
    const onChange = vi.fn();
    render(
      <GlassSwitch checked={false} onChange={onChange} disabled aria-label="Disabled switch" />
    );
    fireEvent.click(screen.getByRole("switch", { name: "Disabled switch" }));
    expect(onChange).not.toHaveBeenCalled();
  });

  /* ── 6. disabled blocks Space key ───────────────────────── */

  it("does not call onChange when disabled and Space is pressed", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <GlassSwitch checked={false} onChange={onChange} disabled aria-label="Disabled switch" />
    );
    const sw = screen.getByRole("switch", { name: "Disabled switch" });
    sw.focus();
    await user.keyboard(" ");
    expect(onChange).not.toHaveBeenCalled();
  });
});
