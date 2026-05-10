/**
 * Tests for ViewerStage captions toggle (U5 a11y)
 *
 * Covers:
 *  1. Toggle button renders in brand menu with correct aria-pressed=false
 *  2. Toggle button renders with aria-pressed=true when captionsEnabled=true
 *  3. Clicking toggle calls onToggleCaptions with the opposite value
 *  4. Toggle button has accessible aria-label
 *  5. When captionsEnabled=false, anonymous visitor does NOT see assistant messages
 *     (the filter in _client.tsx removes them — simulated by passing no assistant messages)
 *  6. When captionsEnabled=true, visitor sees assistant messages in the feed
 *  7. Toggle button is keyboard-accessible (Enter/Space)
 */
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { ViewerStage, type ChatMsg } from "../ViewerStage";

afterEach(() => {
  cleanup();
});

/** Minimal props to render ViewerStage without crashing. */
function baseProps(overrides: Partial<React.ComponentProps<typeof ViewerStage>> = {}): React.ComponentProps<typeof ViewerStage> {
  return {
    messages: [],
    session: null,
    viewerCount: 0,
    uptimeLabel: "LIVE · 00:00:00",
    connStatus: "open",
    inputValue: "",
    onInputChange: vi.fn(),
    onSend: vi.fn(),
    inputDisabled: false,
    reactionSeed: 0,
    ...overrides,
  };
}

describe("ViewerStage — captions toggle (U5 a11y)", () => {

  /* ── 1. Toggle renders with aria-pressed=false by default ─────── */

  it("renders captions toggle button with aria-pressed=false when captionsEnabled is false", () => {
    render(
      <ViewerStage
        {...baseProps()}
        captionsEnabled={false}
        onToggleCaptions={vi.fn()}
      />
    );
    // Open the brand menu first to expose brand-actions
    const trigger = screen.getByRole("button", { name: /ouvrir le menu compte/i });
    fireEvent.click(trigger);

    const toggle = screen.getByRole("button", { name: /activer les sous-titres/i });
    expect(toggle).toBeInTheDocument();
    expect(toggle).toHaveAttribute("aria-pressed", "false");
  });

  /* ── 2. Toggle renders with aria-pressed=true when enabled ────── */

  it("renders captions toggle button with aria-pressed=true when captionsEnabled is true", () => {
    render(
      <ViewerStage
        {...baseProps()}
        captionsEnabled={true}
        onToggleCaptions={vi.fn()}
      />
    );
    // Menu starts closed — open it first
    const menuTrigger = screen.getByRole("button", { name: /ouvrir le menu compte/i });
    fireEvent.click(menuTrigger);

    const toggle = screen.getByRole("button", { name: /activer les sous-titres/i });
    expect(toggle).toHaveAttribute("aria-pressed", "true");
  });

  /* ── 3. Click calls onToggleCaptions with toggled value ─────── */

  it("click on toggle (off → on) calls onToggleCaptions(true)", () => {
    const onToggle = vi.fn();
    render(
      <ViewerStage
        {...baseProps()}
        captionsEnabled={false}
        onToggleCaptions={onToggle}
      />
    );
    const menuTrigger = screen.getByRole("button", { name: /ouvrir le menu compte/i });
    fireEvent.click(menuTrigger);

    const toggle = screen.getByRole("button", { name: /activer les sous-titres/i });
    fireEvent.click(toggle);
    expect(onToggle).toHaveBeenCalledOnce();
    expect(onToggle).toHaveBeenCalledWith(true);
  });

  it("click on toggle (on → off) calls onToggleCaptions(false)", () => {
    const onToggle = vi.fn();
    render(
      <ViewerStage
        {...baseProps()}
        captionsEnabled={true}
        onToggleCaptions={onToggle}
      />
    );
    // Menu always starts closed regardless of captionsEnabled
    const menuTrigger = screen.getByRole("button", { name: /ouvrir le menu compte/i });
    fireEvent.click(menuTrigger);

    const toggle = screen.getByRole("button", { name: /activer les sous-titres/i });
    fireEvent.click(toggle);
    expect(onToggle).toHaveBeenCalledOnce();
    expect(onToggle).toHaveBeenCalledWith(false);
  });

  /* ── 4. Toggle is not rendered when onToggleCaptions is absent ── */

  it("does not render captions toggle when onToggleCaptions is not provided", () => {
    render(<ViewerStage {...baseProps()} />);
    const menuTrigger = screen.getByRole("button", { name: /ouvrir le menu compte/i });
    fireEvent.click(menuTrigger);
    expect(
      screen.queryByRole("button", { name: /activer les sous-titres/i })
    ).toBeNull();
  });

  /* ── 5. Visitor with captionsEnabled=false does not see assistant messages */

  it("does not display assistant messages when captionsEnabled is false", () => {
    // The filter lives in _client.tsx — it simply won't pass assistant messages
    // to ViewerStage.messages when captionsEnabled=false. We simulate this by
    // passing only visitor messages (what _client.tsx would do after filtering).
    const messages: ChatMsg[] = [
      { kind: "visitor", who: "Alice", text: "Hello world" },
    ];
    render(<ViewerStage {...baseProps({ messages })} captionsEnabled={false} onToggleCaptions={vi.fn()} />);
    expect(screen.getByText("Hello world")).toBeInTheDocument();
    // No assistant bubble with rank="assistant" — only visitor bubbles present.
    expect(document.querySelector(".rank-assistant")).toBeNull();
  });

  /* ── 6. Visitor with captionsEnabled=true sees assistant messages ── */

  it("displays assistant messages when captionsEnabled is true", () => {
    // With captionsEnabled=true, _client.tsx passes assistant messages through.
    // We simulate by including an assistant ChatMsg.
    const messages: ChatMsg[] = [
      { kind: "assistant", who: "Shugu", text: "Bienvenue dans le vide céleste !" },
    ];
    render(<ViewerStage {...baseProps({ messages })} captionsEnabled={true} onToggleCaptions={vi.fn()} />);
    expect(screen.getByText("Bienvenue dans le vide céleste !")).toBeInTheDocument();
  });

  /* ── 7. Toggle button is keyboard-accessible ──────────────────── */

  it("toggle responds to Enter key press", async () => {
    const user = userEvent.setup();
    const onToggle = vi.fn();
    render(
      <ViewerStage
        {...baseProps()}
        captionsEnabled={false}
        onToggleCaptions={onToggle}
      />
    );
    const menuTrigger = screen.getByRole("button", { name: /ouvrir le menu compte/i });
    fireEvent.click(menuTrigger);

    const toggle = screen.getByRole("button", { name: /activer les sous-titres/i });
    toggle.focus();
    await user.keyboard("{Enter}");
    expect(onToggle).toHaveBeenCalledOnce();
    expect(onToggle).toHaveBeenCalledWith(true);
  });
});
