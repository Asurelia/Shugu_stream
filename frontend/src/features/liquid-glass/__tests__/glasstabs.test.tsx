/**
 * Tests for GlassTabs (I3.3 — Radix Tabs backend)
 *
 * Covers:
 *  1. Renders all tab labels
 *  2. role="tablist" is present on the list
 *  3. aria-selected="true" on the active tab (CSS selector compatibility)
 *  4. Keyboard navigation — ArrowRight cycles to the next tab
 *  5. Keyboard navigation — ArrowLeft cycles to the previous tab
 *  6. onChange called with the correct value on click
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React, { useState } from "react";
import { GlassTabs } from "../primitives";

const TABS = [
  { value: "a", label: "Alpha" },
  { value: "b", label: "Beta" },
  { value: "c", label: "Gamma" },
];

/* ── Helper: controlled wrapper so Radix state flows correctly ── */

function Controlled({ initial = "a" }: { initial?: string }) {
  const [tab, setTab] = useState(initial);
  return (
    <GlassTabs
      aria-label="Test tabs"
      tabs={TABS}
      value={tab}
      onChange={setTab}
    />
  );
}

describe("GlassTabs", () => {
  it("renders all tab labels", () => {
    render(<Controlled />);
    expect(screen.getByText("Alpha")).toBeDefined();
    expect(screen.getByText("Beta")).toBeDefined();
    expect(screen.getByText("Gamma")).toBeDefined();
  });

  it("has role='tablist' on the list element", () => {
    render(<Controlled />);
    expect(screen.getByRole("tablist")).toBeDefined();
  });

  it("marks the active tab with aria-selected='true'", () => {
    render(<Controlled initial="b" />);
    const betaTab = screen.getByRole("tab", { name: "Beta" });
    // Radix sets aria-selected="true" on the active Tabs.Trigger
    expect(betaTab.getAttribute("aria-selected")).toBe("true");
    // Inactive tabs must NOT be selected
    expect(screen.getByRole("tab", { name: "Alpha" }).getAttribute("aria-selected")).toBe("false");
    expect(screen.getByRole("tab", { name: "Gamma" }).getAttribute("aria-selected")).toBe("false");
  });

  it("calls onChange with the correct value on click", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <GlassTabs
        aria-label="Click test"
        tabs={TABS}
        value="a"
        onChange={onChange}
      />
    );
    await user.click(screen.getByRole("tab", { name: "Beta" }));
    expect(onChange).toHaveBeenCalledWith("b");
  });

  it("ArrowRight moves focus to the next tab", async () => {
    const user = userEvent.setup();
    render(<Controlled initial="a" />);
    // Focus the first tab (Alpha) then press ArrowRight
    const alphaTab = screen.getByRole("tab", { name: "Alpha" });
    alphaTab.focus();
    await user.keyboard("{ArrowRight}");
    // Radix roving focus: Beta tab should now be focused
    expect(document.activeElement).toBe(screen.getByRole("tab", { name: "Beta" }));
  });

  it("ArrowLeft moves focus to the previous tab", async () => {
    const user = userEvent.setup();
    render(<Controlled initial="b" />);
    // Focus Beta then press ArrowLeft
    const betaTab = screen.getByRole("tab", { name: "Beta" });
    betaTab.focus();
    await user.keyboard("{ArrowLeft}");
    // Radix roving focus: Alpha tab should now be focused
    expect(document.activeElement).toBe(screen.getByRole("tab", { name: "Alpha" }));
  });
});
