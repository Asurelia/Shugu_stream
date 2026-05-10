/**
 * AdminAuthGuard — tests unitaires Vitest.
 *
 * Couverture :
 *   1. `redirectPath` fourni explicitement + mismatch username
 *      → `router.replace` appelé avec la valeur fournie (verbatim).
 *   2. Pas de `redirectPath` + mismatch sur `/john/admin/scene-editor-v2`
 *      → défaut intelligent : `/{operator}/admin/scene-editor-v2`
 *      (comportement identique à l'ancienne valeur hardcodée).
 *   3. Pas de `redirectPath` + mismatch sur `/john/admin/analytics`
 *      → défaut intelligent : `/{operator}/admin/analytics`
 *      (prouve que le guard n'est plus hardcodé sur scene-editor-v2 —
 *      test de régression pour le bug corrigé dans cette PR).
 *   4. Pas de mismatch (username correct) → children rendu, pas de redirect.
 *   5. Pas d'operator (non connecté) → redirect `/login`.
 *   6. Member non-operator → redirect `/`.
 *
 * Refs : audit/UX-AUDIT-2026-05-09.md — follow-up AdminAuthGuard hardcodé.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { AdminAuthGuard } from "../AdminAuthGuard";
import type { Operator } from "../AdminAuthGuard";

// ── Mocks ────────────────────────────────────────────────────────────────────

const replaceMock = vi.fn();

// next/navigation mock — overridable par test via vi.mocked(usePathname) etc.
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: replaceMock }),
  useParams: () => ({ username: "john" }),
  usePathname: vi.fn(() => "/john/admin/scene-editor-v2"),
}));

// shuguClient mock — résolu par chaque test selon le scénario.
vi.mock("@/services/shuguClient", () => ({
  fetchAuthStatus: vi.fn(),
}));

// ── Helpers ───────────────────────────────────────────────────────────────────

import { usePathname } from "next/navigation";
import { fetchAuthStatus } from "@/services/shuguClient";

/** Rend AdminAuthGuard avec un children indicateur pour détecter le rendu. */
function renderGuard(props: Partial<React.ComponentProps<typeof AdminAuthGuard>> = {}) {
  const childSpy = vi.fn((_op: Operator) => <div data-testid="content">ok</div>);
  const result = render(
    <AdminAuthGuard {...props}>
      {childSpy}
    </AdminAuthGuard>
  );
  return { ...result, childSpy };
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("AdminAuthGuard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Défaut pathname pour chaque test (peut être surchargé dans le test).
    vi.mocked(usePathname).mockReturnValue("/john/admin/scene-editor-v2");
  });

  // ── Test 1 : redirectPath explicite ─────────────────────────────────────
  it("utilise redirectPath fourni (override explicite) sur mismatch username", async () => {
    // operator.username = "alice", URL username = "john" → mismatch.
    vi.mocked(fetchAuthStatus).mockResolvedValue({
      username: "alice",
      role: "operator",
      is_operator: true,
    });

    renderGuard({ redirectPath: "/alice/admin/custom-page" });

    await waitFor(() => {
      expect(replaceMock).toHaveBeenCalledWith("/alice/admin/custom-page");
    });
    expect(replaceMock).toHaveBeenCalledTimes(1);
  });

  // ── Test 2 : défaut intelligent — scene-editor-v2 (rétro-compat) ────────
  it("calcule le défaut intelligent sur /john/admin/scene-editor-v2 → /{op}/admin/scene-editor-v2", async () => {
    vi.mocked(usePathname).mockReturnValue("/john/admin/scene-editor-v2");
    vi.mocked(fetchAuthStatus).mockResolvedValue({
      username: "alice",
      role: "operator",
      is_operator: true,
    });

    renderGuard();

    await waitFor(() => {
      expect(replaceMock).toHaveBeenCalledWith("/alice/admin/scene-editor-v2");
    });
    expect(replaceMock).toHaveBeenCalledTimes(1);
  });

  // ── Test 3 : défaut intelligent — analytics (régression bug hardcode) ───
  it("calcule le défaut intelligent sur /john/admin/analytics → /{op}/admin/analytics", async () => {
    // C'est le test de régression principal : avant le fix, ce cas redirigait
    // vers scene-editor-v2 au lieu de garder la page analytics.
    vi.mocked(usePathname).mockReturnValue("/john/admin/analytics");
    vi.mocked(fetchAuthStatus).mockResolvedValue({
      username: "alice",
      role: "operator",
      is_operator: true,
    });

    renderGuard();

    await waitFor(() => {
      expect(replaceMock).toHaveBeenCalledWith("/alice/admin/analytics");
    });
    expect(replaceMock).toHaveBeenCalledTimes(1);
  });

  // ── Test 4 : pas de mismatch → children rendu ───────────────────────────
  it("rend les children quand le username correspond (pas de redirect)", async () => {
    // operator.username = "john" = URL username "john" → pas de mismatch.
    vi.mocked(fetchAuthStatus).mockResolvedValue({
      username: "john",
      role: "operator",
      is_operator: true,
    });

    const { childSpy } = renderGuard();

    await waitFor(() => {
      expect(screen.getByTestId("content")).toBeInTheDocument();
    });
    // children reçoit l'objet operator complet (AuthResponse satisfait Operator)
    expect(childSpy).toHaveBeenCalledWith(expect.objectContaining({ username: "john", is_operator: true }));
    expect(replaceMock).not.toHaveBeenCalled();
  });

  // ── Test 5 : non connecté → redirect /login ────────────────────────────
  it("redirige vers /login quand fetchAuthStatus renvoie null (non connecté)", async () => {
    vi.mocked(fetchAuthStatus).mockResolvedValue(null);

    renderGuard();

    await waitFor(() => {
      expect(replaceMock).toHaveBeenCalledWith("/login");
    });
  });

  // ── Test 6 : member non-operator → redirect / ──────────────────────────
  it("redirige vers / quand l'utilisateur n'est pas operator (is_operator=false)", async () => {
    vi.mocked(fetchAuthStatus).mockResolvedValue({
      username: "john",
      role: "member",
      is_operator: false,
    });

    renderGuard();

    await waitFor(() => {
      expect(replaceMock).toHaveBeenCalledWith("/");
    });
  });
});
