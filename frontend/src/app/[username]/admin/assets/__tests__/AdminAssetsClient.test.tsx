/**
 * Tests for AssetsClient (audit UX P0 — design system migration).
 *
 * Couverture :
 *   1. render initial → liste affichée après fetch.
 *   2. click "Supprimer" → modal s'ouvre, click "Annuler" → modal se ferme.
 *   3. click "Supprimer" → modal → click "Supprimer" (confirm) → API appelée + toast.success.
 *   4. action échoue (deleteAsset) → toast.error avec description.
 *   5. form submit → createAsset appelé + toast.success.
 *
 * Stratégie de mock :
 *   - AdminShell stubbé pour rendre uniquement children — évite next/navigation.
 *   - @/services/adminAssetsClient mocké via vi.mock.
 *   - Render wrappé dans GlassToastProvider pour que useToast() fonctionne.
 *   - restoreMocks:true → mockResolvedValue default dans beforeEach (pattern MissionsClient).
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import React from "react";

import { GlassToastProvider } from "@/features/liquid-glass/primitives";
import { AssetsClient } from "../_client";
import { AdminAssetsError } from "@/services/adminAssetsClient";

// ─── Mock AdminShell ──────────────────────────────────────────────────────────

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

// ─── Mock adminAssetsClient ───────────────────────────────────────────────────

vi.mock("@/services/adminAssetsClient", async (importActual) => {
  const actual = await importActual<typeof import("@/services/adminAssetsClient")>();
  return {
    ...actual,
    listAssets: vi.fn(),
    createAsset: vi.fn(),
    toggleAsset: vi.fn(),
    deleteAsset: vi.fn(),
  };
});

import {
  listAssets,
  createAsset,
  deleteAsset,
} from "@/services/adminAssetsClient";

const mockListAssets = listAssets as ReturnType<typeof vi.fn>;
const mockCreateAsset = createAsset as ReturnType<typeof vi.fn>;
const mockDeleteAsset = deleteAsset as ReturnType<typeof vi.fn>;

// ─── Fixtures ─────────────────────────────────────────────────────────────────

const MOCK_ROW = {
  id: "row-1",
  kind: "gesture",
  slug: "wave_hello",
  display_name: "Wave Hello",
  payload: { url: "/animations/wave.fbx", source: "fbx" },
  is_active: true,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

const EMPTY_LIST = { items: [] };
const ONE_ITEM_LIST = { items: [MOCK_ROW] };

// ─── Helpers ──────────────────────────────────────────────────────────────────

function renderComponent() {
  return render(
    <GlassToastProvider>
      <AssetsClient />
    </GlassToastProvider>,
  );
}

// ─── Setup / teardown ────────────────────────────────────────────────────────

beforeEach(() => {
  vi.clearAllMocks();
  // Default: resolve with empty list.
  // Required because restoreMocks:true resets vi.fn() implementations between tests.
  mockListAssets.mockResolvedValue(EMPTY_LIST);
  mockCreateAsset.mockResolvedValue(MOCK_ROW);
  mockDeleteAsset.mockResolvedValue(undefined);
});

afterEach(() => {
  cleanup();
});

// ─── Tests ───────────────────────────────────────────────────────────────────

describe("AssetsClient", () => {
  it("Test 1: renders asset list on successful fetch", async () => {
    mockListAssets.mockResolvedValueOnce(ONE_ITEM_LIST);

    await act(async () => {
      renderComponent();
    });

    await waitFor(() =>
      expect(screen.getByText("wave_hello")).toBeInTheDocument(),
    );

    expect(screen.queryByText("Chargement échoué")).not.toBeInTheDocument();
  });

  it("Test 2: click 'Désactiver' opens modal; click 'Annuler' closes it", async () => {
    mockListAssets.mockResolvedValueOnce(ONE_ITEM_LIST);

    await act(async () => {
      renderComponent();
    });

    await waitFor(() =>
      expect(screen.getByText("wave_hello")).toBeInTheDocument(),
    );

    // Open modal — danger "Désactiver" is the second "Désactiver" button in the row
    // (first is the ghost toggle, second is the danger deactivate button)
    const deactivateBtns = screen.getAllByRole("button", { name: "Désactiver" });
    fireEvent.click(deactivateBtns[deactivateBtns.length - 1]);

    // Modal is open — Annuler button now visible
    const cancelBtn = await screen.findByRole("button", { name: "Annuler" });
    expect(cancelBtn).toBeInTheDocument();

    // Click Annuler
    fireEvent.click(cancelBtn);

    // Modal closes — "Annuler" button goes away
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Annuler" })).not.toBeInTheDocument(),
    );
  });

  it("Test 3: confirm deactivate calls API + shows toast.success", async () => {
    mockListAssets.mockResolvedValue(ONE_ITEM_LIST);
    mockDeleteAsset.mockResolvedValueOnce(undefined);

    await act(async () => {
      renderComponent();
    });

    await waitFor(() =>
      expect(screen.getByText("wave_hello")).toBeInTheDocument(),
    );

    // Open modal — click the row danger "Désactiver" (second button, after ghost toggle)
    const rowBtns = screen.getAllByRole("button", { name: "Désactiver" });
    fireEvent.click(rowBtns[rowBtns.length - 1]);

    // Confirm — after modal opens there are two "Désactiver" buttons; last is modal footer
    await act(async () => {
      const confirmBtns = await screen.findAllByRole("button", { name: "Désactiver" });
      fireEvent.click(confirmBtns[confirmBtns.length - 1]);
    });

    // deleteAsset should be called with the row id
    await waitFor(() =>
      expect(mockDeleteAsset).toHaveBeenCalledWith("row-1"),
    );

    // toast.success should appear — Radix duplicates in ToastAnnounce
    await waitFor(() =>
      expect(screen.getAllByText("Asset désactivé").length).toBeGreaterThanOrEqual(1),
    );
  });

  it("Test 4: deleteAsset failure shows toast.error with description", async () => {
    mockListAssets.mockResolvedValue(ONE_ITEM_LIST);
    mockDeleteAsset.mockRejectedValueOnce(
      new AdminAssetsError(500, "Contrainte FK violée"),
    );

    await act(async () => {
      renderComponent();
    });

    await waitFor(() =>
      expect(screen.getByText("wave_hello")).toBeInTheDocument(),
    );

    // Open modal — click the row danger "Désactiver" (second button, after ghost toggle)
    const rowBtns = screen.getAllByRole("button", { name: "Désactiver" });
    fireEvent.click(rowBtns[rowBtns.length - 1]);

    // Confirm — after modal opens there are two "Désactiver" buttons; last is modal footer
    await act(async () => {
      const confirmBtns = await screen.findAllByRole("button", { name: "Désactiver" });
      fireEvent.click(confirmBtns[confirmBtns.length - 1]);
    });

    // toast.error with description
    await waitFor(() =>
      expect(screen.getAllByText("Action échouée").length).toBeGreaterThanOrEqual(1),
    );

    expect(
      screen.getAllByText("Contrainte FK violée").length,
    ).toBeGreaterThanOrEqual(1);
  });

  it("Test 5: form submit calls createAsset + shows toast.success", async () => {
    mockListAssets.mockResolvedValue(EMPTY_LIST);
    mockCreateAsset.mockResolvedValueOnce(MOCK_ROW);

    await act(async () => {
      renderComponent();
    });

    await waitFor(() =>
      // Empty state shown
      expect(screen.getByText(/aucun gesture/i)).toBeInTheDocument(),
    );

    // Fill in the form
    const slugInput = screen.getByPlaceholderText("my_new_item");
    const displayNameInput = screen.getByPlaceholderText("My new item");

    fireEvent.change(slugInput, { target: { value: "wave_hello" } });
    fireEvent.change(displayNameInput, { target: { value: "Wave Hello" } });

    // Fill the URL field for gesture kind
    const urlInput = screen.getByPlaceholderText("/animations/wave.fbx");
    fireEvent.change(urlInput, { target: { value: "/animations/wave.fbx" } });

    // Submit
    const submitBtn = screen.getByRole("button", { name: "✦ Ajouter" });
    await act(async () => {
      fireEvent.click(submitBtn);
    });

    await waitFor(() =>
      expect(mockCreateAsset).toHaveBeenCalledWith(
        expect.objectContaining({
          kind: "gesture",
          slug: "wave_hello",
          display_name: "Wave Hello",
        }),
      ),
    );

    // toast.success — Radix duplicates in ToastAnnounce
    await waitFor(() =>
      expect(screen.getAllByText("Asset créé").length).toBeGreaterThanOrEqual(1),
    );
  });
});
