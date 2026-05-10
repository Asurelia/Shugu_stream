/**
 * LoadingScreen unit tests — U4 audit UX (VRM loader progress + error fallback)
 *
 * Covers:
 *  1. Indeterminate state (progress=0 or omitted) renders spinner, no bar
 *  2. Determinate state (progress=0.5) renders a 50% progress bar, no spinner
 *  3. Error state renders the error message and "Réessayer" button
 *  4. Clicking "Réessayer" calls the onRetry callback
 */
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import React from "react";
import { LoadingScreen } from "../LoadingScreen";

afterEach(() => {
  cleanup();
});

describe("LoadingScreen — indeterminate (no progress)", () => {
  it("shows the spinner when progress is 0", () => {
    render(<LoadingScreen progress={0} />);
    // The spinner has animate-spin; check for the role="status" region.
    const status = screen.getByRole("status");
    expect(status).toBeInTheDocument();
    // No percentage text when indeterminate.
    expect(screen.queryByText(/\d+%/)).toBeNull();
    // The hint text appears.
    expect(screen.getByText(/quelques secondes/i)).toBeInTheDocument();
  });

  it("shows the spinner when progress prop is omitted", () => {
    render(<LoadingScreen />);
    const status = screen.getByRole("status");
    expect(status).toBeInTheDocument();
    expect(screen.getByText(/quelques secondes/i)).toBeInTheDocument();
  });
});

describe("LoadingScreen — determinate (progress > 0)", () => {
  it("renders a progress bar at 50% and shows '50%'", () => {
    const { container } = render(<LoadingScreen progress={0.5} />);
    // The percentage label is rendered in the descriptive text area.
    expect(screen.getByText("50%")).toBeInTheDocument();
    // The bar element carries the inline width style.
    const bar = container.querySelector<HTMLElement>('[style*="width: 50%"]');
    expect(bar).not.toBeNull();
  });

  it("aria-label reflects the current percentage", () => {
    render(<LoadingScreen progress={0.75} />);
    const status = screen.getByRole("status");
    expect(status).toHaveAttribute("aria-label", "Chargement 75%");
  });
});

describe("LoadingScreen — error state", () => {
  it("renders the error message and a 'Réessayer' button", () => {
    const err = new Error("VRM 404 — fichier introuvable");
    render(<LoadingScreen error={err} onRetry={vi.fn()} />);
    // Uses role="alert" for assertive a11y announcement.
    const alert = screen.getByRole("alert");
    expect(alert).toBeInTheDocument();
    expect(screen.getByText(/VRM 404/)).toBeInTheDocument();
    const retryBtn = screen.getByRole("button", { name: /réessayer/i });
    expect(retryBtn).toBeInTheDocument();
  });

  it("does not render 'Réessayer' when onRetry is not provided", () => {
    const err = new Error("Réseau indisponible");
    render(<LoadingScreen error={err} />);
    expect(screen.queryByRole("button", { name: /réessayer/i })).toBeNull();
  });

  it("clicking 'Réessayer' calls the onRetry callback exactly once", () => {
    const onRetry = vi.fn();
    const err = new Error("Timeout");
    render(<LoadingScreen error={err} onRetry={onRetry} />);
    fireEvent.click(screen.getByRole("button", { name: /réessayer/i }));
    expect(onRetry).toHaveBeenCalledOnce();
  });
});
