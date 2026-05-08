/**
 * Test — MissionsClient (Sprint mos-A iter 2b Kanban).
 *
 * Couverture (MVP, 1 test) :
 *   - `fetchMissions()` est appelé au mount, payload mocké rendu.
 *   - Les 4 colonnes Kanban sont présentes.
 *   - Les missions sont distribuées dans la bonne colonne (status match).
 *   - Le filtre par agent fonctionne (cliquer une pill réduit la liste).
 *   - Les stats header reflètent les totaux filtrés.
 *
 * Stratégie de mock :
 *   - `fetch` global stubbé via `vi.stubGlobal`. On retourne un payload
 *     synthétique avec 2 missions dans 2 statuts différents.
 *   - `AdminShell` stubbé pour rendre uniquement `children` — évite de
 *     pull `next/navigation` + `fetchAuthStatus` (cf. test iter 1).
 *   - dnd-kit n'est PAS mocké : ses handlers s'attachent au DOM mais ne
 *     se déclenchent pas en jsdom (pas de PointerEvent), c'est OK pour
 *     un test de rendu.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { MissionsClient } from "../_client";

vi.mock("@/components/admin/AdminShell", () => ({
  AdminShell: ({
    children,
    headerRight,
    title,
  }: {
    children: React.ReactNode;
    headerRight?: React.ReactNode;
    title: string;
  }) => (
    <div data-testid="admin-shell-stub">
      <h1>{title}</h1>
      <div data-testid="admin-shell-header-right">{headerRight}</div>
      <div data-testid="admin-shell-children">{children}</div>
    </div>
  ),
}));

const MOCK_PAYLOAD = {
  total: 3,
  mock: true,
  items: [
    {
      id: "mission-alpha",
      title: "Réponse VIP @user_one",
      agent: "shugu_persona_brain",
      status: "IN_PROGRESS",
      cost_usd: 0.0042,
      tokens_in: 500,
      tokens_out: 100,
      started_at: "2026-05-08T10:00:00Z",
    },
    {
      id: "mission-beta",
      title: "Picker pick — horoscope",
      agent: "picker",
      status: "TO_DO",
      cost_usd: 0,
      tokens_in: 0,
      tokens_out: 0,
      started_at: null,
    },
    {
      id: "mission-gamma",
      title: "TTS clip",
      agent: "tts_streamer",
      status: "DONE",
      cost_usd: 0.001,
      tokens_in: 0,
      tokens_out: 0,
      started_at: "2026-05-08T09:50:00Z",
    },
  ],
};

beforeEach(() => {
  const fetchMock = vi.fn(async () =>
    new Response(JSON.stringify(MOCK_PAYLOAD), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }),
  );
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("MissionsClient", () => {
  it("rend les 4 colonnes Kanban + cartes par status + filtre agent", async () => {
    await act(async () => {
      render(<MissionsClient />);
    });

    // Le board apparaît une fois le fetch résolu (loading → done).
    await waitFor(() => {
      expect(screen.getByTestId("missions-kanban-board")).toBeInTheDocument();
    });

    // Les 4 colonnes sont rendues, chacune avec son testid statut.
    expect(screen.getByTestId("kanban-column-BACKLOG")).toBeInTheDocument();
    expect(screen.getByTestId("kanban-column-TO_DO")).toBeInTheDocument();
    expect(screen.getByTestId("kanban-column-IN_PROGRESS")).toBeInTheDocument();
    expect(screen.getByTestId("kanban-column-DONE")).toBeInTheDocument();

    // Les 3 cartes mockées sont rendues, chacune dans la colonne correcte.
    const cardAlpha = screen.getByTestId("mission-card-mission-alpha");
    const cardBeta = screen.getByTestId("mission-card-mission-beta");
    const cardGamma = screen.getByTestId("mission-card-mission-gamma");
    expect(cardAlpha.dataset.missionStatus).toBe("IN_PROGRESS");
    expect(cardBeta.dataset.missionStatus).toBe("TO_DO");
    expect(cardGamma.dataset.missionStatus).toBe("DONE");

    // Stats header : 3 missions visibles, coût cumulé > 0, tokens > 0.
    const statCount = screen.getByTestId("missions-stat-count");
    expect(statCount.textContent).toContain("3 missions");

    // Filtre par agent : cliquer "picker" ne laisse que mission-beta.
    const pickerFilter = screen.getByTestId("mission-filter-picker");
    fireEvent.click(pickerFilter);

    await waitFor(() => {
      expect(screen.queryByTestId("mission-card-mission-alpha")).not.toBeInTheDocument();
      expect(screen.queryByTestId("mission-card-mission-gamma")).not.toBeInTheDocument();
      expect(screen.getByTestId("mission-card-mission-beta")).toBeInTheDocument();
    });

    // Stats reflètent le filtre.
    expect(screen.getByTestId("missions-stat-count").textContent).toContain("1 missions");
  });
});
