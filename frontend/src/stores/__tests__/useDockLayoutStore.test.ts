/**
 * Tests unit — `useDockLayoutStore`.
 *
 * Couvre :
 *   - state initial (defaults identiques au design bundle)
 *   - splitter clamps (left [180,400], right [260,460], bottom [160,500])
 *   - sémantique du delta : left positif élargit, right/bottom positif rétrécit
 *     (alignée sur le comportement `w - d` des splitters originaux)
 *   - dock layout : `setDockLayout` accepte valeur directe + updater
 *   - persistence roundtrip localStorage (pattern Zustand `persist`)
 *   - reset layout → defaults restorés
 *
 * Isolation : chaque test reset le store avant d'exécuter (les stores Zustand
 * sont des modules singleton, donc l'état persiste entre tests si on ne
 * nettoie pas).
 */

import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  useDockLayoutStore,
  DEFAULT_DOCK_LAYOUT,
  DEFAULT_LEFT_W,
  DEFAULT_RIGHT_W,
  DEFAULT_BOTTOM_H,
} from "../useDockLayoutStore";

beforeEach(() => {
  // Reset le store aux valeurs par défaut avant chaque test. `resetLayout`
  // est l'action prévue pour ça par le store lui-même.
  useDockLayoutStore.getState().resetLayout();
  // On purge le localStorage pour que `persist` ne re-hydrate pas un état
  // laissé par un test précédent.
  if (typeof window !== "undefined") {
    window.localStorage.clear();
  }
});

afterEach(() => {
  useDockLayoutStore.getState().resetLayout();
});

describe("useDockLayoutStore · initial state", () => {
  it("expose le dockLayout par défaut identique au design bundle", () => {
    const { dockLayout } = useDockLayoutStore.getState();
    expect(dockLayout).toEqual(DEFAULT_DOCK_LAYOUT);
    // Sanity check sur les tabs par défaut de chaque dock (valeurs figées
    // par Phase A, ne doivent pas dériver silencieusement).
    expect(dockLayout.viewport.tabs).toEqual(["scene", "live"]);
    expect(dockLayout.viewport.active).toBe("scene");
    expect(dockLayout.right.tabs).toEqual(["inspector", "effects", "stream", "perf"]);
    expect(dockLayout.right.active).toBe("inspector");
    expect(dockLayout.bottom.tabs).toEqual(["assets", "timeline", "patterns", "mixer"]);
    expect(dockLayout.bottom.active).toBe("assets");
  });

  it("expose les splitter widths initiaux (240/320/260)", () => {
    const state = useDockLayoutStore.getState();
    expect(state.leftW).toBe(DEFAULT_LEFT_W);
    expect(state.rightW).toBe(DEFAULT_RIGHT_W);
    expect(state.bottomH).toBe(DEFAULT_BOTTOM_H);
  });
});

describe("useDockLayoutStore · splitter clamps", () => {
  it("adjustLeftW : delta positif élargit dans [180, 400]", () => {
    const { adjustLeftW } = useDockLayoutStore.getState();
    adjustLeftW(50); // 240 → 290
    expect(useDockLayoutStore.getState().leftW).toBe(290);
    adjustLeftW(200); // 290 + 200 = 490 → clamp à 400
    expect(useDockLayoutStore.getState().leftW).toBe(400);
  });

  it("adjustLeftW : delta négatif rétrécit, min 180", () => {
    const { adjustLeftW } = useDockLayoutStore.getState();
    adjustLeftW(-200); // 240 − 200 = 40 → clamp à 180
    expect(useDockLayoutStore.getState().leftW).toBe(180);
  });

  it("adjustRightW : sémantique inversée (delta positif RÉDUIT) dans [260, 460]", () => {
    // Convention héritée de SceneEditorApp : le splitter droit utilise
    // `w - delta` car le dock droit grossit quand on tire vers la gauche.
    const { adjustRightW } = useDockLayoutStore.getState();
    adjustRightW(50); // 320 − 50 = 270
    expect(useDockLayoutStore.getState().rightW).toBe(270);
    adjustRightW(-100); // 270 − (−100) = 370
    expect(useDockLayoutStore.getState().rightW).toBe(370);
    adjustRightW(-500); // 370 − (−500) = 870 → clamp à 460
    expect(useDockLayoutStore.getState().rightW).toBe(460);
  });

  it("adjustBottomH : sémantique inversée dans [160, 500]", () => {
    const { adjustBottomH } = useDockLayoutStore.getState();
    adjustBottomH(40); // 260 − 40 = 220
    expect(useDockLayoutStore.getState().bottomH).toBe(220);
    adjustBottomH(-500); // 220 − (−500) = 720 → clamp à 500
    expect(useDockLayoutStore.getState().bottomH).toBe(500);
    adjustBottomH(500); // 500 − 500 = 0 → clamp à 160
    expect(useDockLayoutStore.getState().bottomH).toBe(160);
  });

  it("setLeftW clampe une valeur brute hors [180, 400]", () => {
    const { setLeftW } = useDockLayoutStore.getState();
    setLeftW(50);
    expect(useDockLayoutStore.getState().leftW).toBe(180);
    setLeftW(5000);
    expect(useDockLayoutStore.getState().leftW).toBe(400);
    setLeftW(250);
    expect(useDockLayoutStore.getState().leftW).toBe(250);
  });
});

describe("useDockLayoutStore · dock layout mutation", () => {
  it("setDockLayout accepte une valeur directe", () => {
    const { setDockLayout } = useDockLayoutStore.getState();
    setDockLayout({
      ...DEFAULT_DOCK_LAYOUT,
      viewport: { tabs: ["live", "scene"], active: "live" },
    });
    const { dockLayout } = useDockLayoutStore.getState();
    expect(dockLayout.viewport.tabs).toEqual(["live", "scene"]);
    expect(dockLayout.viewport.active).toBe("live");
    // Les autres docks restent inchangés.
    expect(dockLayout.right.tabs).toEqual(DEFAULT_DOCK_LAYOUT.right.tabs);
  });

  it("setDockLayout accepte un updater `(prev) => next`", () => {
    const { setDockLayout } = useDockLayoutStore.getState();
    setDockLayout((prev) => ({
      ...prev,
      right: { ...prev.right, active: "perf" },
    }));
    expect(useDockLayoutStore.getState().dockLayout.right.active).toBe("perf");
  });
});

describe("useDockLayoutStore · persist (localStorage roundtrip)", () => {
  it("sauvegarde les changements dans localStorage", async () => {
    const { adjustLeftW, setDockLayout } = useDockLayoutStore.getState();
    adjustLeftW(30); // 240 → 270
    setDockLayout((prev) => ({ ...prev, viewport: { ...prev.viewport, active: "live" } }));

    // Zustand persist écrit de manière synchrone sur localStorage.
    const raw = window.localStorage.getItem("shugu:scene-editor:dock-layout:v1");
    expect(raw).toBeTruthy();

    const parsed = JSON.parse(raw!);
    expect(parsed.state.leftW).toBe(270);
    expect(parsed.state.dockLayout.viewport.active).toBe("live");
    expect(parsed.version).toBe(1);
  });

  it("resetLayout efface les modifs et restaure les defaults", () => {
    const { adjustLeftW, adjustRightW, adjustBottomH, setDockLayout, resetLayout } =
      useDockLayoutStore.getState();

    adjustLeftW(50);
    adjustRightW(30);
    adjustBottomH(20);
    setDockLayout((prev) => ({
      ...prev,
      bottom: { ...prev.bottom, active: "timeline" },
    }));

    resetLayout();

    const state = useDockLayoutStore.getState();
    expect(state.leftW).toBe(DEFAULT_LEFT_W);
    expect(state.rightW).toBe(DEFAULT_RIGHT_W);
    expect(state.bottomH).toBe(DEFAULT_BOTTOM_H);
    expect(state.dockLayout).toEqual(DEFAULT_DOCK_LAYOUT);
  });
});
