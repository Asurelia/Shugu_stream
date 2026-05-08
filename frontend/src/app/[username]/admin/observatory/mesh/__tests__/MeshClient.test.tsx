/**
 * Test — Observatory Mesh client (Sprint mos-A, itération 2a).
 *
 * Couverture (1 test, MVP) :
 *   - La page rend le container mesh + la console SSE (vide au mount).
 *   - Une `EventSource` est instanciée sur la bonne URL au mount, fermée au unmount.
 *   - Un event SSE entrant est ajouté à la console live.
 *
 * Stratégie de mock :
 *   - `AdminShell` mocké pour ne rendre que `children` + `headerRight`.
 *   - `WorkersMesh` (chargé via `next/dynamic`) mocké statiquement vers un
 *     stub léger — évite d'embarquer `react-force-graph-2d` (canvas + d3,
 *     impossible à initialiser sereinement sous jsdom). On ne teste pas le
 *     rendu canvas ici ; le composant `WorkersMesh` reste pure-presentational
 *     (prend des props, dessine) et sera couvert par un test dédié séparé
 *     si on en sent le besoin.
 *   - `next/dynamic` est neutralisé pour qu'un import résolve immédiatement
 *     vers le module mocké (synchronicité indispensable pour le rendu sync
 *     de Testing Library).
 *   - `EventSource` stubbé via `vi.stubGlobal` — jsdom ne l'implémente pas.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, screen } from "@testing-library/react";

// ─── Mock AdminShell — ne rend que children + headerRight + title ─────────

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

// ─── Mock WorkersMesh — stub minimal (canvas non-testable sous jsdom) ─────

vi.mock("../WorkersMesh", () => ({
  HALO_DURATION_MS: 2000,
  WorkersMesh: (props: {
    nodes: Array<{ id: string; isCenter: boolean }>;
    width: number;
    height: number;
  }) => (
    <div
      data-testid="workers-mesh-stub"
      data-node-count={props.nodes.length}
      data-center={props.nodes.find((n) => n.isCenter)?.id ?? ""}
      style={{ width: props.width, height: props.height }}
    />
  ),
}));

// ─── Neutralise next/dynamic — résout vers le composant immédiatement ─────

vi.mock("next/dynamic", () => ({
  default: (loader: () => Promise<{ default: unknown } | unknown>) => {
    // En tests, on retourne un composant qui résout le loader synchronement
    // au premier render. Comme on a mocké `../WorkersMesh` au-dessus, le
    // loader hit notre mock et renvoie le stub. Mais on ne peut pas await
    // ici — on retourne donc un wrapper qui rend le stub via cache.
    let Resolved: React.ComponentType<unknown> | null = null;
    void (async () => {
      const mod = (await loader()) as { WorkersMesh?: React.ComponentType<unknown> } | React.ComponentType<unknown>;
      const candidate = (mod as { WorkersMesh?: React.ComponentType<unknown> }).WorkersMesh
        ?? (mod as { default?: React.ComponentType<unknown> }).default
        ?? (mod as React.ComponentType<unknown>);
      Resolved = candidate;
    })();
    const Wrapper = (props: Record<string, unknown>) => {
      if (Resolved === null) {
        // Loader pas encore résolu — placeholder (cas rare en pratique :
        // microtask déjà drainée au premier render des tests synchrones).
        return <div data-testid="dynamic-loading" />;
      }
      const C = Resolved;
      return <C {...props} />;
    };
    return Wrapper;
  },
}));

// ─── EventSource stub (jsdom ne l'a pas) ──────────────────────────────────

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

// On importe APRÈS les `vi.mock` pour que le hoisting Vitest les applique.
import { ObservatoryMeshClient } from "../_client";
import { OBSERVATORY_EVENTS_PATH, KNOWN_WORKERS } from "@/services/adminObservatoryClient";

describe("ObservatoryMeshClient", () => {
  it("rend le mesh + la console, ouvre EventSource sur la bonne URL, et consomme un event entrant", async () => {
    const view = render(<ObservatoryMeshClient />);
    // Laisse les microtasks se drainer pour que le `dynamic()` mocké
    // résolve son loader avant le premier assert mesh-stub.
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    // Container mesh + stub WorkersMesh présent.
    expect(screen.getByTestId("observatory-mesh-container")).toBeInTheDocument();
    const meshStub = screen.getByTestId("workers-mesh-stub");
    expect(meshStub).toBeInTheDocument();
    // Topology : 6 nœuds connus, centre = shugu_persona_brain.
    expect(meshStub.getAttribute("data-node-count")).toBe(String(KNOWN_WORKERS.length));
    expect(meshStub.getAttribute("data-center")).toBe("shugu_persona_brain");

    // Console live — présente, vide au mount.
    const consoleEl = screen.getByTestId("observatory-mesh-console");
    expect(consoleEl).toBeInTheDocument();
    expect(consoleEl.textContent).toContain("en attente");

    // EventSource : exactement une instance, URL correcte, non fermée.
    expect(EventSourceStub.instances).toHaveLength(1);
    const es = EventSourceStub.instances[0];
    expect(es.url).toBe(OBSERVATORY_EVENTS_PATH);
    expect(es.closed).toBe(false);

    // Push un event SSE — la console doit l'afficher.
    await act(async () => {
      es.onmessage?.(
        new MessageEvent("message", {
          data: JSON.stringify({
            ts: "2026-05-08T14:55:00.000Z",
            worker: "picker",
            type: "selection",
            payload: { id: 42 },
          }),
        }),
      );
    });
    expect(screen.getByTestId("observatory-mesh-console").textContent).toContain("picker");
    expect(screen.getByTestId("observatory-mesh-console").textContent).toContain("selection");

    // Cleanup ferme bien l'EventSource.
    view.unmount();
    expect(es.closed).toBe(true);
  });
});
