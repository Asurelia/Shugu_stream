/**
 * Tests — `httpClient` (Phase E5.2 — fix H2 PR #26).
 *
 * Couverture :
 *   1. 200 → JSON parsé typé.
 *   2. 204 → null (pas de parse, pas de throw).
 *   3. 401 → redirect /login + HttpError(401) thrown.
 *   4. 4xx avec {detail} → HttpError(status, detail, raw).
 *   5. 4xx sans body → HttpError(status, statusText|`HTTP ${status}`).
 *   6. Body non-JSON → HttpError avec rawText conservé.
 *   7. credentials: "include" toujours injecté.
 *   8. Content-Type: application/json mergé avec headers appelant.
 *
 * Mock : `globalThis.fetch` + `window.location.replace` stubs vi.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { HttpError, request, redirectToLogin } from "../api/httpClient";

// ─── Helpers fetch mock ──────────────────────────────────────────────────────

interface MockFetchOpts {
  status?: number;
  body?: unknown;
  /** Si true, body est renvoyé en text() sans JSON.stringify. */
  rawText?: boolean;
  statusText?: string;
}

function mockFetch({
  status = 200,
  body,
  rawText = false,
  statusText = "",
}: MockFetchOpts = {}): void {
  const text =
    status === 204 || body === undefined
      ? ""
      : rawText
        ? String(body)
        : JSON.stringify(body);
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: status >= 200 && status < 300,
      status,
      statusText,
      text: () => Promise.resolve(text),
    }),
  );
}

// ─── window.location.replace mock ────────────────────────────────────────────
//
// jsdom expose un vrai `window.location` non-mockable directement par
// `vi.stubGlobal`. On stub la méthode `replace` via Object.defineProperty.

let replaceSpy: ReturnType<typeof vi.fn>;

beforeEach(() => {
  replaceSpy = vi.fn();
  Object.defineProperty(window, "location", {
    configurable: true,
    value: { replace: replaceSpy, href: "http://localhost/test" },
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

// ─── Tests ───────────────────────────────────────────────────────────────────

describe("httpClient · request 200", () => {
  it("parse le body JSON et retourne le type T", async () => {
    mockFetch({ body: { hello: "world" } });
    const res = await request<{ hello: string }>("/api/test");
    expect(res.hello).toBe("world");
  });

  it("injecte credentials: 'include' par défaut", async () => {
    mockFetch({ body: {} });
    await request("/api/test");
    expect(fetch).toHaveBeenCalledWith(
      "/api/test",
      expect.objectContaining({ credentials: "include" }),
    );
  });

  it("merge Content-Type: application/json avec les headers appelant", async () => {
    mockFetch({ body: {} });
    await request("/api/test", { headers: { "X-Custom": "abc" } });
    const callArgs = (fetch as unknown as { mock: { calls: unknown[][] } }).mock
      .calls[0];
    const init = callArgs[1] as RequestInit;
    expect(init.headers).toMatchObject({
      "Content-Type": "application/json",
      "X-Custom": "abc",
    });
  });
});

describe("httpClient · request 204 No Content", () => {
  it("retourne null sans tenter de parser le body", async () => {
    mockFetch({ status: 204 });
    const res = await request<void>("/api/delete", { method: "DELETE" });
    expect(res).toBeNull();
  });
});

describe("httpClient · request 401 (cookie expiré)", () => {
  it("appelle window.location.replace('/login') AVANT throw", async () => {
    mockFetch({ status: 401, body: { detail: "Unauthorized" } });
    await expect(request("/api/protected")).rejects.toThrow(HttpError);
    expect(replaceSpy).toHaveBeenCalledWith("/login");
  });

  it("HttpError levé a status=401", async () => {
    mockFetch({ status: 401, body: { detail: "Unauthorized" } });
    try {
      await request("/api/protected");
      expect.fail("devait throw");
    } catch (err) {
      expect(err).toBeInstanceOf(HttpError);
      if (err instanceof HttpError) {
        expect(err.status).toBe(401);
        expect(err.detail).toContain("Session expirée");
      }
    }
  });

  it("redirectToLogin() appelable indépendamment", () => {
    redirectToLogin();
    expect(replaceSpy).toHaveBeenCalledWith("/login");
  });
});

describe("httpClient · request 4xx/5xx", () => {
  it("404 avec {detail} → HttpError(404, detail, raw)", async () => {
    mockFetch({ status: 404, body: { detail: "Scene non trouvée" } });
    try {
      await request("/api/scenes/missing");
      expect.fail("devait throw");
    } catch (err) {
      expect(err).toBeInstanceOf(HttpError);
      if (err instanceof HttpError) {
        expect(err.status).toBe(404);
        expect(err.detail).toBe("Scene non trouvée");
        expect(err.raw).toEqual({ detail: "Scene non trouvée" });
      }
    }
  });

  it("500 sans body parsable → HttpError avec statusText fallback", async () => {
    mockFetch({ status: 500, statusText: "Internal Server Error" });
    try {
      await request("/api/boom");
      expect.fail("devait throw");
    } catch (err) {
      expect(err).toBeInstanceOf(HttpError);
      if (err instanceof HttpError) {
        expect(err.status).toBe(500);
        expect(err.detail).toBe("Internal Server Error");
      }
    }
  });

  it("body non-JSON → conservé dans raw.rawText", async () => {
    mockFetch({ status: 502, body: "<html>bad gateway</html>", rawText: true });
    try {
      await request("/api/proxy");
      expect.fail("devait throw");
    } catch (err) {
      if (err instanceof HttpError) {
        expect(err.status).toBe(502);
        expect(err.detail).toBe("<html>bad gateway</html>");
        expect(err.raw).toEqual({ rawText: "<html>bad gateway</html>" });
      }
    }
  });
});

describe("httpClient · HttpError shape", () => {
  it("message format = '[status] detail'", () => {
    const err = new HttpError(403, "Accès refusé", null);
    expect(err.message).toBe("[403] Accès refusé");
    expect(err.name).toBe("HttpError");
  });
});
