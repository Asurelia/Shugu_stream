/**
 * Tests — `scenesClient` (Phase E5.2).
 *
 * Couverture :
 *   1. listScenes → GET /api/scene-composer/scenes, retourne le tableau.
 *   2. getScene → GET /api/scene-composer/scenes/:id.
 *   3. createScene → POST, retourne la scène créée.
 *   4. updateScene → PUT, retourne la scène mise à jour.
 *   5. deleteScene → DELETE 204, retourne null (httpClient unifié H2).
 *   6. playScene → POST /play, retourne { ok: true }.
 *   7. HttpError levée sur 4xx (alias `ScenesClientError` toujours valide).
 *   8. HttpError levée sur 5xx.
 *   9. `encodeURIComponent` protège les IDs avec caractères spéciaux.
 *
 * Mock : `globalThis.fetch` stubbée via `vi.stubGlobal` pour contrôler les
 * réponses sans appels réseau réels. `window.location.replace` stub pour
 * éviter le redirect réel sur 401.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  listScenes,
  getScene,
  createScene,
  updateScene,
  deleteScene,
  playScene,
  ScenesClientError,
  type AuthoredSceneOut,
} from "../api/scenesClient";

// ─── Fixtures ────────────────────────────────────────────────────────────────

const MOCK_SCENE: AuthoredSceneOut = {
  id: "scene-abc-123",
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

// ─── Helpers ─────────────────────────────────────────────────────────────────

function mockFetch(body: unknown, status = 200): void {
  const text =
    status === 204 ? "" : JSON.stringify(body);
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: status >= 200 && status < 300,
      status,
      text: () => Promise.resolve(text),
    }),
  );
}

// ─── Tests ───────────────────────────────────────────────────────────────────

beforeEach(() => {
  vi.clearAllMocks();
  // Stub window.location pour intercepter les redirects 401 sans navigation réelle.
  Object.defineProperty(window, "location", {
    configurable: true,
    value: { replace: vi.fn(), href: "http://localhost/test" },
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("scenesClient · listScenes", () => {
  it("GET /api/scene-composer/scenes retourne un tableau de scènes", async () => {
    mockFetch([MOCK_SCENE]);
    const result = await listScenes();
    expect(result).toHaveLength(1);
    expect(result[0].id).toBe("scene-abc-123");
    expect(fetch).toHaveBeenCalledWith(
      "/api/scene-composer/scenes",
      expect.objectContaining({ credentials: "include" }),
    );
  });

  it("retourne un tableau vide si le backend retourne []", async () => {
    mockFetch([]);
    const result = await listScenes();
    expect(result).toEqual([]);
  });
});

describe("scenesClient · getScene", () => {
  it("GET /api/scene-composer/scenes/:id retourne la scène", async () => {
    mockFetch(MOCK_SCENE);
    const result = await getScene("scene-abc-123");
    expect(result.name).toBe("idle_default");
    expect(fetch).toHaveBeenCalledWith(
      "/api/scene-composer/scenes/scene-abc-123",
      expect.objectContaining({ credentials: "include" }),
    );
  });

  it("encodeURIComponent protège les IDs avec slash", async () => {
    mockFetch(MOCK_SCENE);
    await getScene("bad/id");
    expect(fetch).toHaveBeenCalledWith(
      "/api/scene-composer/scenes/bad%2Fid",
      expect.anything(),
    );
  });
});

describe("scenesClient · createScene", () => {
  it("POST /api/scene-composer/scenes retourne la scène créée", async () => {
    mockFetch(MOCK_SCENE, 201);
    const result = await createScene({
      name: "idle_default",
      type: "static",
    });
    expect(result.id).toBe("scene-abc-123");
    expect(fetch).toHaveBeenCalledWith(
      "/api/scene-composer/scenes",
      expect.objectContaining({ method: "POST" }),
    );
  });
});

describe("scenesClient · updateScene", () => {
  it("PUT /api/scene-composer/scenes/:id retourne la scène mise à jour", async () => {
    mockFetch({ ...MOCK_SCENE, description: "Mise à jour" });
    const result = await updateScene("scene-abc-123", {
      description: "Mise à jour",
    });
    expect(result.description).toBe("Mise à jour");
    expect(fetch).toHaveBeenCalledWith(
      "/api/scene-composer/scenes/scene-abc-123",
      expect.objectContaining({ method: "PUT" }),
    );
  });
});

describe("scenesClient · deleteScene", () => {
  it("DELETE 204 résout sans throw (null via httpClient unifié H2)", async () => {
    mockFetch(null, 204);
    // `deleteScene` retourne `Promise<void>` côté API ; httpClient résout
    // `null as void` en interne — on vérifie juste l'absence de throw + le
    // bon endpoint/method.
    await expect(deleteScene("scene-abc-123")).resolves.not.toThrow();
    expect(fetch).toHaveBeenCalledWith(
      "/api/scene-composer/scenes/scene-abc-123",
      expect.objectContaining({ method: "DELETE" }),
    );
  });
});

describe("scenesClient · playScene", () => {
  it("POST /play retourne { ok: true }", async () => {
    mockFetch({ ok: true });
    const result = await playScene("scene-abc-123");
    expect(result.ok).toBe(true);
    expect(fetch).toHaveBeenCalledWith(
      "/api/scene-composer/scenes/scene-abc-123/play",
      expect.objectContaining({ method: "POST" }),
    );
  });
});

describe("scenesClient · HttpError (alias ScenesClientError)", () => {
  it("404 → HttpError avec status=404", async () => {
    mockFetch({ detail: "Scene non trouvée" }, 404);
    await expect(getScene("inexistant")).rejects.toBeInstanceOf(
      ScenesClientError,
    );
    try {
      await getScene("inexistant");
    } catch (err) {
      if (err instanceof ScenesClientError) {
        expect(err.status).toBe(404);
        expect(err.detail).toContain("Scene non trouvée");
      }
    }
  });

  it("500 → HttpError avec status=500", async () => {
    mockFetch({ detail: "Erreur interne" }, 500);
    await expect(listScenes()).rejects.toBeInstanceOf(ScenesClientError);
  });

  it("HttpError.message contient [status] + detail", () => {
    // ScenesClientError est un alias de HttpError depuis H2 (1 module = 1 resp).
    const err = new ScenesClientError(403, "Accès refusé", null);
    expect(err.message).toBe("[403] Accès refusé");
    expect(err.name).toBe("HttpError");
  });

  it("401 mid-session → redirect /login + HttpError(401) levée", async () => {
    mockFetch({ detail: "Cookie expiré" }, 401);
    const replaceSpy = (
      window.location as unknown as { replace: ReturnType<typeof vi.fn> }
    ).replace;
    await expect(listScenes()).rejects.toBeInstanceOf(ScenesClientError);
    expect(replaceSpy).toHaveBeenCalledWith("/login");
  });
});
