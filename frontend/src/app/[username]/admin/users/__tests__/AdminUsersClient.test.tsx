/**
 * Tests for AdminUsersClient (I3.5 batch 1).
 *
 * Covers:
 *  1. Happy path: page renders the user list returned by listUsers().
 *  2. Load error (AdminError) → toast.error("Chargement échoué") fires.
 *  3. Load error (network) → toast.error("Chargement échoué") with "Erreur réseau" fires.
 *  4. Commit action error (AdminError) → toast.error("Action échouée") fires.
 *     The modal stays open (pendingAction not cleared in catch).
 *
 * Strategy:
 *  - AdminShell is mocked to render children only (avoids next/navigation pull).
 *  - @/services/adminUsersClient is mocked to control listUsers / setVIP / deactivateUser.
 *  - Render is wrapped in GlassToastProvider so useToast() works.
 *  - We assert on the toast text rendered in the live region, not on the toast
 *    API directly — same approach as toast.test.tsx in I3.7.
 *
 * What is NOT covered (intentional scope):
 *  - Full pagination interaction (own unit if needed)
 *  - Modal grant/revoke/deactivate happy path (own unit)
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor, fireEvent, act } from "@testing-library/react";
import React from "react";

import { GlassToastProvider } from "@/features/liquid-glass/primitives";
import { AdminUsersClient } from "../_client";
import { AdminError } from "@/services/adminUsersClient";

// ─── Mock AdminShell — renders children + title only ─────────────────────────

vi.mock("@/components/admin/AdminShell", () => ({
  AdminShell: ({
    children,
    title,
    headerRight,
  }: {
    children: React.ReactNode;
    title: string;
    headerRight?: React.ReactNode;
  }) => (
    <div data-testid="admin-shell-stub">
      <h1>{title}</h1>
      <div data-testid="admin-shell-header-right">{headerRight}</div>
      <div data-testid="admin-shell-children">{children}</div>
    </div>
  ),
}));

// ─── Mock adminUsersClient ────────────────────────────────────────────────────

vi.mock("@/services/adminUsersClient", async (importActual) => {
  const actual = await importActual<typeof import("@/services/adminUsersClient")>();
  return {
    ...actual,
    listUsers: vi.fn(),
    setVIP: vi.fn(),
    deactivateUser: vi.fn(),
  };
});

// ─── Helpers ─────────────────────────────────────────────────────────────────

import { listUsers, setVIP } from "@/services/adminUsersClient";

const mockListUsers = listUsers as ReturnType<typeof vi.fn>;
const mockSetVIP = setVIP as ReturnType<typeof vi.fn>;

const MOCK_USER = {
  id: "u1",
  username: "alice",
  email: "alice@example.com",
  display_name: "Alice",
  email_verified: true,
  vip_active: false,
  vip_since: null,
  vip_until: null,
  created_at: "2024-01-01T00:00:00Z",
  last_seen_at: null,
  is_active: true,
};

function renderComponent() {
  return render(
    <GlassToastProvider>
      <AdminUsersClient />
    </GlassToastProvider>
  );
}

// ─── Setup / teardown ────────────────────────────────────────────────────────

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  cleanup();
});

// ─── Tests ───────────────────────────────────────────────────────────────────

describe("AdminUsersClient", () => {
  it("renders the user list on success", async () => {
    mockListUsers.mockResolvedValueOnce({ total: 1, items: [MOCK_USER] });

    renderComponent();

    await waitFor(() =>
      expect(screen.getByText("alice")).toBeInTheDocument()
    );

    expect(screen.getByText("alice@example.com")).toBeInTheDocument();
    // No error toast should be present.
    expect(screen.queryByText("Chargement échoué")).not.toBeInTheDocument();
  });

  it("fires toast.error with AdminError detail when listUsers rejects with AdminError", async () => {
    mockListUsers.mockRejectedValueOnce(
      new AdminError(403, "Accès opérateur requis")
    );

    renderComponent();

    // Radix Toast duplicates text into a hidden ToastAnnounce region for a11y
    // — use getAllByText which handles 1+ instances for both title and description.
    await waitFor(() =>
      expect(screen.getAllByText("Chargement échoué").length).toBeGreaterThanOrEqual(1)
    );

    expect(screen.getAllByText("Accès opérateur requis").length).toBeGreaterThanOrEqual(1);
  });

  it("fires toast.error with 'Erreur réseau' when listUsers rejects with a generic error", async () => {
    mockListUsers.mockRejectedValueOnce(new Error("Network error"));

    renderComponent();

    await waitFor(() =>
      expect(screen.getAllByText("Chargement échoué").length).toBeGreaterThanOrEqual(1)
    );

    // Radix Toast duplicates text into a hidden ToastAnnounce region for a11y
    // — use getAllByText which handles 1+ instances.
    expect(screen.getAllByText("Erreur réseau").length).toBeGreaterThanOrEqual(1);
  });

  it("fires toast.error('Action échouée') when commitAction rejects, modal stays open", async () => {
    // First load succeeds.
    mockListUsers.mockResolvedValue({ total: 1, items: [MOCK_USER] });
    // setVIP rejects with AdminError.
    mockSetVIP.mockRejectedValueOnce(new AdminError(422, "Quota VIP dépassé"));

    renderComponent();

    // Wait for the list to render.
    await waitFor(() => expect(screen.getByText("alice")).toBeInTheDocument());

    // Click "Promouvoir VIP" to open modal.
    const promoteBtn = screen.getByRole("button", { name: "Promouvoir VIP" });
    fireEvent.click(promoteBtn);

    // Modal should appear (confirmation button).
    expect(screen.getByRole("button", { name: "Confirmer" })).toBeInTheDocument();

    // Click "Confirmer".
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Confirmer" }));
    });

    // Toast should appear with error title and description.
    // Radix Toast duplicates text into hidden ToastAnnounce — use getAllByText.
    await waitFor(() =>
      expect(screen.getAllByText("Action échouée").length).toBeGreaterThanOrEqual(1)
    );

    // Radix Toast duplicates text into a hidden ToastAnnounce region for a11y
    // — use getAllByText which handles 1+ instances.
    expect(screen.getAllByText("Quota VIP dépassé").length).toBeGreaterThanOrEqual(1);

    // Modal stays open — pendingAction not cleared in catch.
    expect(screen.getByRole("button", { name: "Confirmer" })).toBeInTheDocument();
  });
});
