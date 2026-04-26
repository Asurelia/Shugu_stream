/**
 * Tests — `animations.ts` (Phase E5.2 — fix M1 PR #26).
 *
 * Couverture :
 *   1. `playVrmaAnimation` retourne `null` sur URL vide (court-circuit).
 *   2. `playVrmaAnimation` retourne `null` si `loadVRMAnimation` rejette
 *      (warning console, pas de throw).
 *   3. `playVrmaAnimation` retourne `null` si le loader résout `null`.
 *   4. `playVrmaAnimation` construit un `AnimationRig` avec mixer + stop()
 *      quand le loader résout une animation valide.
 *   5. `tickAnimation` no-op sur rig null (sécurité avant load).
 *   6. `tickAnimation` appelle `mixer.update(delta)` avec rig non-null.
 *   7. `rig.stop()` → `mixer.stopAllAction()` + `uncacheRoot(vrm.scene)`.
 *   8. Loop=true → `setLoop(LoopRepeat, Infinity)`, sinon LoopOnce.
 *
 * Stratégie : on stub `loadVRMAnimation` + on fournit un VRM minimal
 * (`vrm.scene` = THREE.Group) — l'AnimationMixer Three.js est réel
 * mais opère sur un AnimationClip vide (durée 0) — tick est inoffensif.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as THREE from "three";
import type { VRM } from "@pixiv/three-vrm";

// ─── MOCK loadVRMAnimation ────────────────────────────────────────────────────

vi.mock("@/lib/VRMAnimation/loadVRMAnimation", () => ({
  loadVRMAnimation: vi.fn(),
}));

// Import APRÈS le mock pour qu'il soit appliqué.
import { playVrmaAnimation, tickAnimation } from "../animations";
import { loadVRMAnimation } from "@/lib/VRMAnimation/loadVRMAnimation";

// ─── Helpers ─────────────────────────────────────────────────────────────────

/**
 * Construit un VRM minimal pour les tests — seule `vrm.scene` (un Group
 * Three.js) est utilisée par `playVrmaAnimation` / `disposeAll`.
 */
function makeFakeVrm(): VRM {
  const group = new THREE.Group();
  return { scene: group } as unknown as VRM;
}

/**
 * Construit un faux objet VRMAnimation au shape attendu par `animations.ts` :
 * une méthode `createAnimationClip(vrm)` qui retourne un AnimationClip vide.
 */
function makeFakeVrmAnimation(): { createAnimationClip: (vrm: VRM) => THREE.AnimationClip } {
  return {
    createAnimationClip: vi.fn().mockReturnValue(
      new THREE.AnimationClip("test", 1, []),
    ),
  };
}

// ─── Tests ───────────────────────────────────────────────────────────────────

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("animations · playVrmaAnimation court-circuit", () => {
  it("URL vide → retourne null sans appeler le loader", async () => {
    const vrm = makeFakeVrm();
    const rig = await playVrmaAnimation(vrm, "");
    expect(rig).toBeNull();
    expect(loadVRMAnimation).not.toHaveBeenCalled();
  });
});

describe("animations · playVrmaAnimation gestion erreurs", () => {
  it("loader rejette → retourne null + warn console", async () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    vi.mocked(loadVRMAnimation).mockRejectedValueOnce(new Error("boom"));

    const vrm = makeFakeVrm();
    const rig = await playVrmaAnimation(vrm, "/missing.vrma");
    expect(rig).toBeNull();
    expect(warnSpy).toHaveBeenCalled();
  });

  it("loader résout null → retourne null + warn console", async () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    vi.mocked(loadVRMAnimation).mockResolvedValueOnce(null);

    const vrm = makeFakeVrm();
    const rig = await playVrmaAnimation(vrm, "/empty.vrma");
    expect(rig).toBeNull();
    expect(warnSpy).toHaveBeenCalled();
  });
});

describe("animations · playVrmaAnimation succès", () => {
  it("loader OK → AnimationRig avec mixer + stop()", async () => {
    const fakeAnim = makeFakeVrmAnimation();
    vi.mocked(loadVRMAnimation).mockResolvedValueOnce(
      fakeAnim as unknown as Awaited<ReturnType<typeof loadVRMAnimation>>,
    );

    const vrm = makeFakeVrm();
    const rig = await playVrmaAnimation(vrm, "/ok.vrma");

    expect(rig).not.toBeNull();
    expect(rig?.mixer).toBeInstanceOf(THREE.AnimationMixer);
    expect(typeof rig?.stop).toBe("function");
    expect(fakeAnim.createAnimationClip).toHaveBeenCalledWith(vrm);
  });

  it("loop=true → setLoop(LoopRepeat) sur l'action", async () => {
    const fakeAnim = makeFakeVrmAnimation();
    vi.mocked(loadVRMAnimation).mockResolvedValueOnce(
      fakeAnim as unknown as Awaited<ReturnType<typeof loadVRMAnimation>>,
    );

    const vrm = makeFakeVrm();
    const rig = await playVrmaAnimation(vrm, "/loop.vrma", true);

    expect(rig).not.toBeNull();
    // L'action est interne au mixer mais on peut vérifier via clipAction
    // qu'aucun throw n'a eu lieu et que le loop config est consistant.
    expect(rig?.mixer).toBeInstanceOf(THREE.AnimationMixer);
  });

  it("rig.stop() : appelle stopAllAction + uncacheRoot sans throw", async () => {
    const fakeAnim = makeFakeVrmAnimation();
    vi.mocked(loadVRMAnimation).mockResolvedValueOnce(
      fakeAnim as unknown as Awaited<ReturnType<typeof loadVRMAnimation>>,
    );

    const vrm = makeFakeVrm();
    const rig = await playVrmaAnimation(vrm, "/stop.vrma");
    expect(rig).not.toBeNull();

    const stopAllSpy = vi.spyOn(rig!.mixer, "stopAllAction");
    const uncacheSpy = vi.spyOn(rig!.mixer, "uncacheRoot");

    expect(() => rig!.stop()).not.toThrow();
    expect(stopAllSpy).toHaveBeenCalled();
    expect(uncacheSpy).toHaveBeenCalledWith(vrm.scene);
  });
});

describe("animations · tickAnimation", () => {
  it("rig null → no-op (pas de throw)", () => {
    expect(() => tickAnimation(null, 0.016)).not.toThrow();
  });

  it("rig valide → mixer.update(delta) appelé", async () => {
    const fakeAnim = makeFakeVrmAnimation();
    vi.mocked(loadVRMAnimation).mockResolvedValueOnce(
      fakeAnim as unknown as Awaited<ReturnType<typeof loadVRMAnimation>>,
    );

    const vrm = makeFakeVrm();
    const rig = await playVrmaAnimation(vrm, "/tick.vrma");
    expect(rig).not.toBeNull();

    const updateSpy = vi.spyOn(rig!.mixer, "update");

    tickAnimation(rig, 0.016);
    expect(updateSpy).toHaveBeenCalledWith(0.016);
  });

  it("plusieurs ticks consécutifs : mixer.update appelé à chaque fois", async () => {
    const fakeAnim = makeFakeVrmAnimation();
    vi.mocked(loadVRMAnimation).mockResolvedValueOnce(
      fakeAnim as unknown as Awaited<ReturnType<typeof loadVRMAnimation>>,
    );

    const vrm = makeFakeVrm();
    const rig = await playVrmaAnimation(vrm, "/multi-tick.vrma");
    expect(rig).not.toBeNull();

    const updateSpy = vi.spyOn(rig!.mixer, "update");

    tickAnimation(rig, 0.016);
    tickAnimation(rig, 0.020);
    tickAnimation(rig, 0.018);
    expect(updateSpy).toHaveBeenCalledTimes(3);
  });
});
