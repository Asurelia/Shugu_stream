/**
 * Test — Observatory client (Sprint mos-A, itération 1).
 *
 * Couverture minimale (MVP, 1 test) :
 *   - La grille de placeholder cards rend les 6 workers connus.
 *   - La console live (node SSE) est présente, vide au mount.
 *   - L'EventSource est instancié sur la bonne URL au mount.
 *
 * Stratégie de mock :
 *   - `EventSource` est stubbé via `vi.stubGlobal` — jsdom ne l'implémente
 *     pas. On capture l'instance pour vérifier l'URL et la cleanup.
 *   - `AdminShell` est mocké pour rendre uniquement `children` — évite
 *     de pull `next/navigation` + `fetchAuthStatus` dans ce test unitaire.
 *     Les tests d'intégration AdminShell viendront séparément si besoin.
 *
 * Ce qui n'est pas couvert ici (volontaire — itération 1) :
 *   - reconnexion / backoff EventSource (pas implémenté en MVP)
 *   - parse + formatage de logs sous trafic (couvert plus profondément
 *     par l'itération 2 quand le mesh viz consommera ces events)
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

import { ObservatoryClient } from "../_client";
import { OBSERVATORY_EVENTS_PATH, KNOWN_WORKERS } from "@/services/adminObservatoryClient";

// ─── Mock AdminShell — on rend juste `children` + `headerRight` ────────────

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

// ─── Stub EventSource — jsdom ne l'a pas ───────────────────────────────────

class EventSourceStub {
  static instances: EventSourceStub[] = [];
  url: string;
  onopen: ((ev: Event) => void) | null = null;
  onmessage: ((ev: MessageEvent<string>) => void) | null = null;
  onerror: ((ev: Event) => void) | null = null;
  closed = false;

  constructor(url: string) {
    this.url = url;
    EventSourceStub.instances.push(this);
  }
  close(): void {
    this.closed = true;
  }
}

beforeEach(() => {
  EventSourceStub.instances = [];
  vi.stubGlobal("EventSource", EventSourceStub);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("ObservatoryClient", () => {
  it("rend les 6 cartes worker placeholder + la console SSE, et ouvre une EventSource sur la bonne URL", () => {
    render(<ObservatoryClient />);

    // Grille de cartes — un test par worker connu.
    const grid = screen.getByTestId("observatory-worker-grid");
    expect(grid).toBeInTheDocument();
    for (const name of KNOWN_WORKERS) {
      const card = screen.getByTestId(`observatory-worker-card-${name}`);
      expect(card).toBeInTheDocument();
      expect(card.textContent).toContain(name);
    }

    // Console live — présente, vide au mount.
    const console_ = screen.getByTestId("observatory-console");
    expect(console_).toBeInTheDocument();
    expect(console_.textContent).toContain("en attente");

    // EventSource stub : exactement une instance, sur le bon path.
    expect(EventSourceStub.instances).toHaveLength(1);
    expect(EventSourceStub.instances[0].url).toBe(OBSERVATORY_EVENTS_PATH);
    expect(EventSourceStub.instances[0].closed).toBe(false);
  });
});
