/**
 * Tests — `useAfkLoops` (Phase E5.4).
 *
 * Couverture :
 *   1. selectIdleVrma : retourne null si catalogue vide.
 *   2. selectIdleVrma : préfère VRMA idle+loop parmi les candidates.
 *   3. selectIdleVrma : fallback sur idle sans loop si aucune idle+loop.
 *   4. selectIdleVrma : fallback sur première VRMA si aucun slug idle.
 *   5. selectIdleVrma : reconnaît tous les mots-clés (idle, breathe, wait, stand).
 *   6. checkAfkConditions : false si playMode="stopped".
 *   7. checkAfkConditions : false si afkLoops.enabled=false.
 *   8. checkAfkConditions : false si currentViewerCount >= viewerThreshold.
 *   9. checkAfkConditions : false si elapsed < idleSeconds * 1000.
 *  10. checkAfkConditions : true si toutes les conditions sont réunies.
 *  11. useAfkLoops : setInterval déclenche setCurrentVrmaUrl après idleSeconds.
 *  12. useAfkLoops : cleanup clearInterval au unmount.
 *  13. useAfkLoops : pas de déclenchement si playMode="stopped".
 *  14. useAfkLoops : pas de déclenchement si catalogue vide.
 *  15. useAfkLoops : activité pointermove reset le délai d'inactivité.
 *  16. useAfkLoops : activité keydown reset le délai d'inactivité.
 *
 * Pattern : vi.useFakeTimers() pour contrôler setInterval de façon déterministe.
 * Pas de rendu React (renderHook) — les fonctions pures testées unitairement.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import {
  selectIdleVrma,
  checkAfkConditions,
  useAfkLoops,
} from "../useAfkLoops";
import type { VrmaAnimationEntry } from "../../../api/catalogClient";
import type { AfkLoopsConfig } from "../../../store/useSceneComposerStore";

// ─── Fixtures ─────────────────────────────────────────────────────────────────

function makeVrma(slug: string, file: string, loop = false): VrmaAnimationEntry {
  return { slug, file, duration_ms: 3000, loop };
}

const DEFAULT_AFD_CONFIG: AfkLoopsConfig = {
  enabled: true,
  viewerThreshold: 5,
  idleSeconds: 30,
};

// ─── Tests selectIdleVrma ─────────────────────────────────────────────────────

describe("selectIdleVrma", () => {
  it("retourne null si le catalogue est vide", () => {
    expect(selectIdleVrma([])).toBeNull();
  });

  it("préfère la VRMA idle+loop parmi les candidates", () => {
    const catalogue = [
      makeVrma("idle_breathe", "/idle_breathe.vrma", false),
      makeVrma("idle_loop", "/idle_loop.vrma", true),
      makeVrma("wave", "/wave.vrma", false),
    ];
    // Avec un seul idle+loop, doit toujours retourner idle_loop
    const results = new Set<string | null>();
    for (let i = 0; i < 20; i++) {
      results.add(selectIdleVrma(catalogue));
    }
    expect(results.has("/idle_loop.vrma")).toBe(true);
    // idle_breathe (loop=false) ne devrait pas être retourné quand idle+loop existe
    expect(results.has("/idle_breathe.vrma")).toBe(false);
    expect(results.has("/wave.vrma")).toBe(false);
  });

  it("fallback sur idle sans loop si aucune idle+loop", () => {
    const catalogue = [
      makeVrma("idle_a", "/idle_a.vrma", false),
      makeVrma("idle_b", "/idle_b.vrma", false),
      makeVrma("jump", "/jump.vrma", false),
    ];
    const results = new Set<string | null>();
    for (let i = 0; i < 30; i++) {
      results.add(selectIdleVrma(catalogue));
    }
    // Doit piocher parmi idle_a et idle_b uniquement
    expect(results.has("/jump.vrma")).toBe(false);
    expect(results.has(null)).toBe(false);
  });

  it("fallback sur la première VRMA si aucun slug idle", () => {
    const catalogue = [
      makeVrma("run", "/run.vrma", false),
      makeVrma("jump", "/jump.vrma", false),
    ];
    // Aucun slug idle → fallback sur première
    expect(selectIdleVrma(catalogue)).toBe("/run.vrma");
  });

  it("reconnaît tous les mots-clés idle, breathe, wait, stand", () => {
    const keywords = [
      { slug: "shugu_idle_01", file: "/idle.vrma" },
      { slug: "breathe_deep", file: "/breathe.vrma" },
      { slug: "wait_ambient", file: "/wait.vrma" },
      { slug: "stand_relax", file: "/stand.vrma" },
    ];
    for (const { slug, file } of keywords) {
      const catalogue: VrmaAnimationEntry[] = [
        { slug, file, duration_ms: 2000, loop: false },
        makeVrma("run", "/run.vrma", false),
      ];
      // Le slug keyword doit être préféré au "run"
      const result = selectIdleVrma(catalogue);
      expect(result).toBe(file);
    }
  });
});

// ─── Tests checkAfkConditions ─────────────────────────────────────────────────

describe("checkAfkConditions", () => {
  it("retourne false si playMode='stopped'", () => {
    expect(checkAfkConditions("stopped", DEFAULT_AFD_CONFIG, 0, 60_000)).toBe(false);
  });

  it("retourne false si afkLoops.enabled=false", () => {
    const config: AfkLoopsConfig = { ...DEFAULT_AFD_CONFIG, enabled: false };
    expect(checkAfkConditions("playing", config, 0, 60_000)).toBe(false);
  });

  it("retourne false si currentViewerCount >= viewerThreshold", () => {
    // threshold=5, viewers=5 → false (seuil non franchi)
    expect(checkAfkConditions("playing", DEFAULT_AFD_CONFIG, 5, 60_000)).toBe(false);
    // viewers=6 → false
    expect(checkAfkConditions("playing", DEFAULT_AFD_CONFIG, 6, 60_000)).toBe(false);
  });

  it("retourne false si elapsed < idleSeconds * 1000", () => {
    // idleSeconds=30, elapsed=29999ms → false
    expect(checkAfkConditions("playing", DEFAULT_AFD_CONFIG, 0, 29_999)).toBe(false);
  });

  it("retourne true si toutes les conditions sont réunies", () => {
    // playing + enabled + viewers=0 < 5 + elapsed=30000ms >= 30s
    expect(checkAfkConditions("playing", DEFAULT_AFD_CONFIG, 0, 30_000)).toBe(true);
    // elapsed bien au-delà du seuil
    expect(checkAfkConditions("playing", DEFAULT_AFD_CONFIG, 2, 120_000)).toBe(true);
  });
});

// ─── Tests useAfkLoops (renderHook + fake timers) ────────────────────────────

describe("useAfkLoops hook", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  function makeCanvas(): React.RefObject<HTMLCanvasElement | null> {
    const canvas = document.createElement("canvas");
    return { current: canvas };
  }

  it("déclenche setCurrentVrmaUrl après idleSeconds quand playMode=playing", () => {
    const setCurrentVrmaUrl = vi.fn();
    const canvasRef = makeCanvas();
    const catalogue: VrmaAnimationEntry[] = [
      makeVrma("idle_stand", "/idle_stand.vrma", true),
    ];

    renderHook(() =>
      useAfkLoops({
        canvasRef,
        playMode: "playing",
        afkLoops: { enabled: true, viewerThreshold: 5, idleSeconds: 30 },
        vrmaCatalogue: catalogue,
        currentViewerCount: 0,
        setCurrentVrmaUrl,
      })
    );

    // Avance de 30s (idle threshold) + 5s (premier poll)
    act(() => {
      vi.advanceTimersByTime(35_000);
    });

    expect(setCurrentVrmaUrl).toHaveBeenCalledWith("/idle_stand.vrma");
  });

  it("ne déclenche pas si playMode='stopped'", () => {
    const setCurrentVrmaUrl = vi.fn();
    const canvasRef = makeCanvas();
    const catalogue: VrmaAnimationEntry[] = [makeVrma("idle", "/idle.vrma", true)];

    renderHook(() =>
      useAfkLoops({
        canvasRef,
        playMode: "stopped",
        afkLoops: DEFAULT_AFD_CONFIG,
        vrmaCatalogue: catalogue,
        currentViewerCount: 0,
        setCurrentVrmaUrl,
      })
    );

    act(() => {
      vi.advanceTimersByTime(120_000);
    });

    expect(setCurrentVrmaUrl).not.toHaveBeenCalled();
  });

  it("ne déclenche pas si le catalogue est vide", () => {
    const setCurrentVrmaUrl = vi.fn();
    const canvasRef = makeCanvas();

    renderHook(() =>
      useAfkLoops({
        canvasRef,
        playMode: "playing",
        afkLoops: DEFAULT_AFD_CONFIG,
        vrmaCatalogue: [],
        currentViewerCount: 0,
        setCurrentVrmaUrl,
      })
    );

    act(() => {
      vi.advanceTimersByTime(120_000);
    });

    expect(setCurrentVrmaUrl).not.toHaveBeenCalled();
  });

  it("cleanup clearInterval au unmount — pas d'appel après démontage", () => {
    const setCurrentVrmaUrl = vi.fn();
    const canvasRef = makeCanvas();
    const catalogue: VrmaAnimationEntry[] = [makeVrma("idle", "/idle.vrma", true)];

    const { unmount } = renderHook(() =>
      useAfkLoops({
        canvasRef,
        playMode: "playing",
        afkLoops: { enabled: true, viewerThreshold: 5, idleSeconds: 1 },
        vrmaCatalogue: catalogue,
        currentViewerCount: 0,
        setCurrentVrmaUrl,
      })
    );

    // Unmount avant le premier poll
    unmount();

    // Avance du temps — ne doit plus déclencher
    act(() => {
      vi.advanceTimersByTime(30_000);
    });

    expect(setCurrentVrmaUrl).not.toHaveBeenCalled();
  });

  it("activité pointermove reset le délai (pas de déclenchement si actif)", () => {
    const setCurrentVrmaUrl = vi.fn();
    const canvasRef = makeCanvas();
    const catalogue: VrmaAnimationEntry[] = [makeVrma("idle", "/idle.vrma", true)];

    renderHook(() =>
      useAfkLoops({
        canvasRef,
        playMode: "playing",
        afkLoops: { enabled: true, viewerThreshold: 5, idleSeconds: 30 },
        vrmaCatalogue: catalogue,
        currentViewerCount: 0,
        setCurrentVrmaUrl,
      })
    );

    // Avance 20s (pas encore AFK)
    act(() => { vi.advanceTimersByTime(20_000); });

    // Simule activité pointermove sur window → reset lastActivityAt
    // (le listener est sur window, pas sur canvasRef.current)
    act(() => {
      window.dispatchEvent(new Event("pointermove"));
    });

    // Avance encore 20s → total 40s, mais depuis l'activité seulement 20s
    act(() => { vi.advanceTimersByTime(20_000); });

    // Pas encore déclenché (20s depuis la dernière activité < 30s idleSeconds)
    expect(setCurrentVrmaUrl).not.toHaveBeenCalled();
  });

  it("activité keydown window reset le délai (pas de déclenchement si actif)", () => {
    const setCurrentVrmaUrl = vi.fn();
    const canvasRef = makeCanvas();
    const catalogue: VrmaAnimationEntry[] = [makeVrma("idle", "/idle.vrma", true)];

    renderHook(() =>
      useAfkLoops({
        canvasRef,
        playMode: "playing",
        afkLoops: { enabled: true, viewerThreshold: 5, idleSeconds: 30 },
        vrmaCatalogue: catalogue,
        currentViewerCount: 0,
        setCurrentVrmaUrl,
      })
    );

    // Avance 25s
    act(() => { vi.advanceTimersByTime(25_000); });

    // Simule keydown sur window
    act(() => {
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "w" }));
    });

    // Avance 15s → 15s depuis keydown (< 30s)
    act(() => { vi.advanceTimersByTime(15_000); });

    expect(setCurrentVrmaUrl).not.toHaveBeenCalled();
  });
});
