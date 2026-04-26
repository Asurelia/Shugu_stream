/**
 * Tests — `catalogClient` (Phase E5.2).
 *
 * Couverture :
 *   1. getAssetCatalog → GET /api/assets/catalog, retourne AssetCatalogOut.
 *   2. Retour d'un catalogue vide (toutes sections = []).
 *   3. CatalogClientError levée sur 401.
 *   4. CatalogClientError levée sur 500.
 *   5. CatalogClientError.message et .name corrects.
 *
 * Mock : `globalThis.fetch` stubbée.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  getAssetCatalog,
  CatalogClientError,
  type AssetCatalogOut,
} from "../api/catalogClient";

// ─── Fixtures ────────────────────────────────────────────────────────────────

const MOCK_CATALOG: AssetCatalogOut = {
  vrm_avatars: [
    { slug: "shugu", file: "/assets/vrm/shugu.vrm", sidecars: ["/assets/vrma/idle.vrma"] },
  ],
  outfits: [
    { slug: "default", file: "/assets/vrm/outfits/default.png", display_name: "Tenue par défaut" },
  ],
  vrma_animations: [
    { slug: "wave", file: "/assets/vrma/wave.vrma", duration_ms: 2000, loop: false },
    { slug: "idle_loop", file: "/assets/vrma/idle.vrma", duration_ms: null, loop: true },
  ],
  vfx: [{ slug: "sparkle_pink", file: "/assets/vfx/sparkle_pink.json" }],
  scenes: [{ slug: "main_talk", file: "/assets/scenes/main_talk.json" }],
  props_3d: [],
  faces: ["joy", "sad", "surprised"],
  camera_modes: ["close_up", "wide"],
  cached_at: "2026-01-01T12:00:00Z",
};

// ─── Helpers ─────────────────────────────────────────────────────────────────

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

// ─── Tests ───────────────────────────────────────────────────────────────────

beforeEach(() => {
  vi.clearAllMocks();
  // Stub window.location pour intercepter les redirects 401 (httpClient H2).
  Object.defineProperty(window, "location", {
    configurable: true,
    value: { replace: vi.fn(), href: "http://localhost/test" },
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("catalogClient · getAssetCatalog", () => {
  it("GET /api/assets/catalog retourne AssetCatalogOut complet", async () => {
    mockFetch(MOCK_CATALOG);
    const result = await getAssetCatalog();

    expect(fetch).toHaveBeenCalledWith(
      "/api/assets/catalog",
      expect.objectContaining({ credentials: "include" }),
    );
    expect(result.vrm_avatars).toHaveLength(1);
    expect(result.vrm_avatars[0].slug).toBe("shugu");
    expect(result.outfits[0].display_name).toBe("Tenue par défaut");
    expect(result.vrma_animations).toHaveLength(2);
    expect(result.faces).toEqual(["joy", "sad", "surprised"]);
    expect(result.camera_modes).toEqual(["close_up", "wide"]);
    expect(result.cached_at).toBe("2026-01-01T12:00:00Z");
  });

  it("catalogue vide : toutes sections sont des tableaux vides sans throw", async () => {
    const emptyCatalog: AssetCatalogOut = {
      vrm_avatars: [],
      outfits: [],
      vrma_animations: [],
      vfx: [],
      scenes: [],
      props_3d: [],
      faces: [],
      camera_modes: [],
      cached_at: "2026-01-01T00:00:00Z",
    };
    mockFetch(emptyCatalog);
    const result = await getAssetCatalog();
    expect(result.vrm_avatars).toHaveLength(0);
    expect(result.props_3d).toHaveLength(0);
  });

  it("VrmaAnimationEntry avec loop:true est correctement parsée", async () => {
    mockFetch(MOCK_CATALOG);
    const result = await getAssetCatalog();
    const idleAnim = result.vrma_animations.find((a) => a.slug === "idle_loop");
    expect(idleAnim?.loop).toBe(true);
    expect(idleAnim?.duration_ms).toBeNull();
  });
});

describe("catalogClient · HttpError (alias CatalogClientError)", () => {
  it("401 → HttpError(401) + redirect /login (fix H2 mid-session)", async () => {
    mockFetch({ detail: "Unauthorized" }, 401);
    const replaceSpy = (
      window.location as unknown as { replace: ReturnType<typeof vi.fn> }
    ).replace;
    await expect(getAssetCatalog()).rejects.toBeInstanceOf(CatalogClientError);
    // Confirmation H2 : l'opérateur est redirigé vers /login plutôt que coincé
    // avec une UI morte affichant "Erreur 401".
    expect(replaceSpy).toHaveBeenCalledWith("/login");
  });

  it("500 → HttpError avec status=500", async () => {
    mockFetch({ detail: "Internal Server Error" }, 500);
    await expect(getAssetCatalog()).rejects.toBeInstanceOf(CatalogClientError);
  });

  it("HttpError.message contient [status] + detail", () => {
    // CatalogClientError est un alias de HttpError depuis H2.
    const err = new CatalogClientError(404, "Catalog not found", null);
    expect(err.message).toBe("[404] Catalog not found");
    expect(err.name).toBe("HttpError");
  });
});
