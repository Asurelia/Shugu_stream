/**
 * Tests — Panneaux Scene Composer (Phase E5.2).
 *
 * Couverture :
 *   ScenesListPanel :
 *     1. Affiche "Chargement…" au mount.
 *     2. Affiche la liste des scènes après fetch réussi.
 *     3. Affiche "Aucune scène" quand la liste est vide.
 *     4. Affiche l'erreur réseau.
 *     5. Filtre par nom.
 *     6. Clic sur une scène → setSelectedSceneId.
 *
 *   SceneInspectorPanel :
 *     7. Affiche "Sélectionnez une scène" quand selectedSceneId = null.
 *     8. Affiche les métadonnées de la scène sélectionnée.
 *     9. Affiche l'erreur si getScene échoue.
 *
 *   AssetCataloguePanel :
 *    10. Affiche "Chargement…" au mount.
 *    11. Affiche les sections avec leur count.
 *    12. Affiche l'erreur si le catalog fetch échoue.
 *
 * Mocks : fetch stubbé pour les clients API. Store réinitialisé entre les tests.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { AuthoredSceneOut } from "../api/scenesClient";
import type { AssetCatalogOut } from "../api/catalogClient";
import { useSceneComposerStore } from "../store/useSceneComposerStore";

// ─── Fixtures ─────────────────────────────────────────────────────────────────

const MOCK_SCENE: AuthoredSceneOut = {
  id: "scene-abc",
  name: "idle_default",
  description: "Scène par défaut",
  type: "static",
  triggers: [],
  static_state: null,
  timeline_keyframes: null,
  loop_config: null,
  owner_username: "shugu",
  enabled: true,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

const MOCK_CATALOG: AssetCatalogOut = {
  vrm_avatars: [{ slug: "shugu", file: "/assets/vrm/shugu.vrm", sidecars: [] }],
  outfits: [],
  vrma_animations: [
    { slug: "wave", file: "/assets/vrma/wave.vrma", duration_ms: 2000, loop: false },
  ],
  vfx: [],
  scenes: [],
  props_3d: [],
  faces: ["joy"],
  camera_modes: ["close_up"],
  cached_at: "2026-01-01T12:00:00Z",
};

// ─── Helpers fetch mock ────────────────────────────────────────────────────────

function mockFetch(body: unknown, status = 200): void {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: status >= 200 && status < 300,
      status,
      text: () => Promise.resolve(JSON.stringify(body)),
    }),
  );
}

function mockFetchReject(message = "Network error"): void {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockRejectedValue(new Error(message)),
  );
}

// ─── Setup / Teardown ─────────────────────────────────────────────────────────

beforeEach(() => {
  useSceneComposerStore.getState().resetUI();
  vi.clearAllMocks();
  cleanup();
});

afterEach(() => {
  vi.unstubAllGlobals();
  cleanup();
});

// ─── ScenesListPanel ──────────────────────────────────────────────────────────

// Import tardif pour que les mocks vi.mock soient hoistés correctement.
const { ScenesListPanel } = await import("../panels/ScenesListPanel");

describe("ScenesListPanel", () => {
  it("affiche 'Chargement…' immédiatement au mount", () => {
    // Fetch qui ne résout jamais → état loading visible.
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => {})));
    render(<ScenesListPanel />);
    expect(screen.getByText(/chargement/i)).toBeTruthy();
  });

  it("affiche la liste des scènes après fetch réussi", async () => {
    mockFetch([MOCK_SCENE]);
    render(<ScenesListPanel />);
    await waitFor(() => {
      expect(screen.getByText("idle_default")).toBeTruthy();
    });
  });

  it("affiche 'Aucune scène configurée' quand la liste est vide", async () => {
    mockFetch([]);
    render(<ScenesListPanel />);
    await waitFor(() => {
      expect(screen.getByText(/aucune scène configurée/i)).toBeTruthy();
    });
  });

  it("affiche l'erreur réseau sur fetch qui échoue", async () => {
    mockFetch({ detail: "Internal Server Error" }, 500);
    render(<ScenesListPanel />);
    await waitFor(() => {
      expect(screen.getByText(/erreur 500/i)).toBeTruthy();
    });
  });

  it("filtre les scènes par nom", async () => {
    const scenes = [
      { ...MOCK_SCENE, id: "s1", name: "idle_default" },
      { ...MOCK_SCENE, id: "s2", name: "gaming_hype" },
    ];
    mockFetch(scenes);
    render(<ScenesListPanel />);
    await waitFor(() => {
      expect(screen.getByText("idle_default")).toBeTruthy();
    });

    const input = screen.getByPlaceholderText(/filtrer/i);
    act(() => {
      fireEvent.change(input, { target: { value: "gaming" } });
    });

    expect(screen.getByText("gaming_hype")).toBeTruthy();
    expect(screen.queryByText("idle_default")).toBeNull();
  });

  it("clic sur une scène → setSelectedSceneId dans le store", async () => {
    mockFetch([MOCK_SCENE]);
    render(<ScenesListPanel />);
    await waitFor(() => {
      expect(screen.getByText("idle_default")).toBeTruthy();
    });

    await act(async () => {
      screen.getByText("idle_default").click();
    });

    expect(
      useSceneComposerStore.getState().selectedSceneId,
    ).toBe("scene-abc");
  });
});

// ─── SceneInspectorPanel ──────────────────────────────────────────────────────

const { SceneInspectorPanel } = await import("../panels/SceneInspectorPanel");

describe("SceneInspectorPanel", () => {
  it("affiche 'Sélectionnez une scène' quand selectedSceneId est null", () => {
    render(<SceneInspectorPanel />);
    expect(screen.getByText(/sélectionnez une scène/i)).toBeTruthy();
  });

  it("affiche les métadonnées de la scène sélectionnée", async () => {
    mockFetch(MOCK_SCENE);
    act(() => {
      useSceneComposerStore.getState().setSelectedSceneId("scene-abc");
    });
    render(<SceneInspectorPanel />);
    await waitFor(() => {
      expect(screen.getByText("idle_default")).toBeTruthy();
    });
    expect(screen.getByText("static")).toBeTruthy();
    expect(screen.getByText("shugu")).toBeTruthy();
  });

  it("affiche l'erreur si getScene échoue (404)", async () => {
    mockFetch({ detail: "Scene introuvable" }, 404);
    act(() => {
      useSceneComposerStore.getState().setSelectedSceneId("bad-id");
    });
    render(<SceneInspectorPanel />);
    await waitFor(() => {
      expect(screen.getByText(/erreur 404/i)).toBeTruthy();
    });
  });
});

// ─── AssetCataloguePanel ──────────────────────────────────────────────────────

const { AssetCataloguePanel } = await import("../panels/AssetCataloguePanel");

describe("AssetCataloguePanel", () => {
  it("affiche 'Chargement…' immédiatement au mount", () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => {})));
    render(<AssetCataloguePanel />);
    expect(screen.getByText(/chargement/i)).toBeTruthy();
  });

  it("affiche les sections avec leur count après fetch réussi", async () => {
    mockFetch(MOCK_CATALOG);
    render(<AssetCataloguePanel />);
    await waitFor(() => {
      // Section "Avatars VRM" avec count=1 est visible.
      expect(screen.getByText("Avatars VRM")).toBeTruthy();
    });
    // Le slug "shugu" est visible dans la section ouverte par défaut.
    expect(screen.getByText("shugu")).toBeTruthy();
  });

  it("affiche l'erreur si le catalog fetch échoue", async () => {
    mockFetch({ detail: "Unauthorized" }, 401);
    render(<AssetCataloguePanel />);
    await waitFor(() => {
      expect(screen.getByText(/erreur 401/i)).toBeTruthy();
    });
  });
});
