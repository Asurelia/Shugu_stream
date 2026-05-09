/**
 * Tests — `useViewerToken` hook (Sprint D PR D-8).
 *
 * Hook React mutualisé entre `LiveKitProvider` (audio) et `ViewerEventsProvider`
 * (events WS). Centralise :
 *   - fetch initial via `POST /api/voice/token`
 *   - refresh proactif T-60s avant expiration via `POST /api/voice/token/refresh`
 *   - exposition `{ token, livekitUrl, expiresAt, isLoading, error }`
 *
 * Pourquoi mutualiser ? Sans cela, LiveKitProvider et ViewerEventsProvider
 * fetchent chacun un token, deux refresh timers vivent en parallèle, et la
 * dérive de claim `session_id` peut bloquer le WS sans signal user.
 *
 * Stratégie de test : `vi.useFakeTimers()` pour piloter le refresh à T-60s,
 * `fetch` stubbed pour servir tokens initiaux + refresh successifs.
 *
 * Référence spec : docs/specs/2026-05-08-voice-body-pipeline-design.md §6.3.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render } from "@testing-library/react";
import * as React from "react";
import { useViewerToken } from "../useViewerToken";

// ─── Helpers ────────────────────────────────────────────────────────────────

interface ViewerTokenSnapshot {
  token: string | null;
  livekitUrl: string | null;
  expiresAt: number | null;
  isLoading: boolean;
  error: Error | null;
}

/**
 * Test consumer — expose la valeur du hook via une ref pour assertions.
 *
 * On ne render pas le shape JSON dans le DOM (fragile aux re-renders) :
 * on lit la ref directement après que `act` ait flushé les effets.
 *
 * Le snapshot est mis à jour dans un `useEffect` (pas pendant le render) pour
 * respecter `react-hooks/refs` (no ref mutation during render).
 */
function TestConsumer({
  snapshotRef,
}: {
  snapshotRef: { current: ViewerTokenSnapshot | null };
}): JSX.Element {
  const value = useViewerToken();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  React.useEffect(() => {
    snapshotRef.current = {
      token: value.token,
      livekitUrl: value.livekitUrl,
      expiresAt: value.expiresAt,
      isLoading: value.isLoading,
      error: value.error,
    };
  });
  return <div data-testid="consumer" />;
}

function makeBackendTokenResponse(opts: {
  token?: string;
  expiresInS?: number;
  livekitUrl?: string;
}): { token: string; expires_at: number; livekit_url: string } {
  const nowS = Math.floor(Date.now() / 1000);
  return {
    token: opts.token ?? "tok-initial",
    expires_at: nowS + (opts.expiresInS ?? 300), // 5min default
    livekit_url: opts.livekitUrl ?? "wss://livekit.test",
  };
}

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: false });
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

// ─── Tests ──────────────────────────────────────────────────────────────────

/**
 * Helper — flush les microtasks (résolution des promises) sans toucher aux
 * fake timers. Fait avancer le bootstrap fetch sans déclencher le refresh
 * timer programmé à T-240s.
 */
async function flushMicrotasks(): Promise<void> {
  // Une résolution de Promise est une microtask. On lance un await yield N
  // fois pour s'assurer que la chaîne `fetch().then(...).then(...)` est
  // entièrement résolue (3 microtasks dans notre bootstrap).
  for (let i = 0; i < 5; i++) {
    await Promise.resolve();
  }
}

describe("useViewerToken — fetch initial", () => {
  it("au mount → fetch /api/voice/token et expose token + livekitUrl", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () =>
        Promise.resolve(
          makeBackendTokenResponse({ token: "tok-A", expiresInS: 300 }),
        ),
    });
    vi.stubGlobal("fetch", fetchMock);

    const snapshot = { current: null as ViewerTokenSnapshot | null };
    render(<TestConsumer snapshotRef={snapshot} />);

    await act(async () => {
      await flushMicrotasks();
    });

    expect(snapshot.current?.token).toBe("tok-A");
    expect(snapshot.current?.livekitUrl).toBe("wss://livekit.test");
    expect(snapshot.current?.expiresAt).toBeGreaterThan(0);
    expect(snapshot.current?.isLoading).toBe(false);
    expect(snapshot.current?.error).toBeNull();

    // Vérifie que l'endpoint correct a été frappé.
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const calledUrl = String(fetchMock.mock.calls[0][0]);
    expect(calledUrl).toContain("/api/voice/token");
  });

  it("compat shim : accepte aussi le champ `url` (legacy LiveKitProvider shape)", async () => {
    // Le LiveKitProvider initial D-6 attendait `{token, url, room}`. Le backend
    // expose `livekit_url`. Pour permettre la migration progressive sans casser
    // les tests existants, le hook doit accepter les deux formes.
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () =>
        Promise.resolve({
          token: "tok-legacy",
          url: "wss://livekit.legacy",
          room: "shugu-room",
          expires_at: Math.floor(Date.now() / 1000) + 300,
        }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const snapshot = { current: null as ViewerTokenSnapshot | null };
    render(<TestConsumer snapshotRef={snapshot} />);

    await act(async () => {
      await flushMicrotasks();
    });

    expect(snapshot.current?.token).toBe("tok-legacy");
    expect(snapshot.current?.livekitUrl).toBe("wss://livekit.legacy");
  });

  it("expose error si fetch token échoue (401)", async () => {
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      json: () => Promise.resolve({ detail: "not authenticated" }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const snapshot = { current: null as ViewerTokenSnapshot | null };
    render(<TestConsumer snapshotRef={snapshot} />);

    await act(async () => {
      await flushMicrotasks();
    });

    expect(snapshot.current?.error).not.toBeNull();
    expect(snapshot.current?.token).toBeNull();
    errSpy.mockRestore();
  });
});

describe("useViewerToken — refresh proactif T-60s", () => {
  it("schedule un refresh à T-60s avant expiration", async () => {
    const nowS = Math.floor(Date.now() / 1000);
    const initialResp = {
      token: "tok-initial",
      expires_at: nowS + 300, // 5 min
      livekit_url: "wss://livekit.test",
    };
    const refreshResp = {
      token: "tok-refreshed",
      expires_at: nowS + 600, // refresh étend de 5min
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: () => Promise.resolve(initialResp),
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: () => Promise.resolve(refreshResp),
      });
    vi.stubGlobal("fetch", fetchMock);

    const snapshot = { current: null as ViewerTokenSnapshot | null };
    render(<TestConsumer snapshotRef={snapshot} />);

    await act(async () => {
      await flushMicrotasks();
    });
    expect(snapshot.current?.token).toBe("tok-initial");
    expect(fetchMock).toHaveBeenCalledTimes(1);

    // Avance jusqu'à T-60s avant exp = T+240s (de l'instant initial).
    // `advanceTimersByTimeAsync` flush aussi les microtasks générées par
    // les callbacks de timer fired pendant l'avance (on a besoin que
    // `doRefresh` complete `fetch().json()` pour que setState soit appelé).
    await act(async () => {
      await vi.advanceTimersByTimeAsync(241_000);
      await flushMicrotasks();
    });

    expect(snapshot.current?.token).toBe("tok-refreshed");

    // 2e fetch = endpoint refresh.
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const refreshUrl = String(fetchMock.mock.calls[1][0]);
    expect(refreshUrl).toContain("/api/voice/token/refresh");
    // Vérifie qu'on envoie bien le Bearer token initial.
    const refreshOpts = fetchMock.mock.calls[1][1] as RequestInit;
    expect((refreshOpts.headers as Record<string, string>).Authorization).toBe(
      "Bearer tok-initial",
    );
  });

  it("si refresh échoue → garde l'ancien token + log warn (pas de crash)", async () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const nowS = Math.floor(Date.now() / 1000);
    const initialResp = {
      token: "tok-initial",
      expires_at: nowS + 300,
      livekit_url: "wss://livekit.test",
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: () => Promise.resolve(initialResp),
      })
      .mockResolvedValueOnce({
        ok: false,
        status: 500,
        json: () => Promise.resolve({ detail: "server error" }),
      });
    vi.stubGlobal("fetch", fetchMock);

    const snapshot = { current: null as ViewerTokenSnapshot | null };
    render(<TestConsumer snapshotRef={snapshot} />);

    await act(async () => {
      await flushMicrotasks();
    });
    expect(snapshot.current?.token).toBe("tok-initial");

    // Trigger refresh à T-60s.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(241_000);
      await flushMicrotasks();
    });

    // Le token initial reste exposé même si refresh fail.
    expect(snapshot.current?.token).toBe("tok-initial");
    expect(warnSpy).toHaveBeenCalled();
  });

  it("expiresAt déjà passé au mount → refresh fire immédiat, pas de boucle infinie", async () => {
    // Edge case : si le serveur retourne un token dont `expires_at` est dans
    // le passé (clock skew, bug backend), refreshAt deviendrait <0. Le hook
    // doit clamp à 0 et fire un seul refresh — pas une boucle.
    const nowS = Math.floor(Date.now() / 1000);
    const initialResp = {
      token: "tok-stale",
      expires_at: nowS - 100, // déjà expiré
      livekit_url: "wss://livekit.test",
    };
    const refreshResp = {
      token: "tok-fresh",
      expires_at: nowS + 300,
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: () => Promise.resolve(initialResp),
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: () => Promise.resolve(refreshResp),
      });
    vi.stubGlobal("fetch", fetchMock);

    const snapshot = { current: null as ViewerTokenSnapshot | null };
    render(<TestConsumer snapshotRef={snapshot} />);

    await act(async () => {
      await flushMicrotasks();
    });
    // À ce stade : token-stale exposé, setTimeout 0ms armé pour refresh.

    // Avance d'1ms pour fire le setTimeout(0).
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
      await flushMicrotasks();
    });

    // Refresh a fire → tok-fresh exposé.
    expect(snapshot.current?.token).toBe("tok-fresh");
    // Pas de boucle : exactly 2 fetch calls.
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});

describe("useViewerToken — enabled flip (login mid-session)", () => {
  /**
   * Test review #3 critique D-8 : le pattern central "wrap inconditionnel +
   * prop enabled" est load-bearing. Sans test du flip false→true, une
   * régression sur les deps de useEffect rend le bootstrap silencieux et
   * l'avatar n'aura jamais de token.
   */

  function FlipConsumer({
    enabled,
    snapshotRef,
  }: {
    enabled: boolean;
    snapshotRef: { current: ViewerTokenSnapshot | null };
  }): JSX.Element {
    const value = useViewerToken({ enabled });
    // eslint-disable-next-line react-hooks/exhaustive-deps
    React.useEffect(() => {
      snapshotRef.current = {
        token: value.token,
        livekitUrl: value.livekitUrl,
        expiresAt: value.expiresAt,
        isLoading: value.isLoading,
        error: value.error,
      };
    });
    return <div data-testid="flip-consumer" />;
  }

  it("enabled=false au mount → aucun fetch ; flip true → bootstrap fetch fire", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(makeBackendTokenResponse({})),
    });
    vi.stubGlobal("fetch", fetchMock);

    const snapshot = { current: null as ViewerTokenSnapshot | null };
    const { rerender } = render(
      <FlipConsumer enabled={false} snapshotRef={snapshot} />,
    );

    await act(async () => {
      await flushMicrotasks();
    });

    // Aucun fetch tant que enabled=false (pas de bootstrap, pas de timer).
    expect(fetchMock).toHaveBeenCalledTimes(0);
    expect(snapshot.current?.token).toBeNull();

    // Flip enabled=true → bootstrap doit fire.
    rerender(<FlipConsumer enabled={true} snapshotRef={snapshot} />);
    await act(async () => {
      await flushMicrotasks();
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(snapshot.current?.token).toBe("tok-initial");
    expect(snapshot.current?.livekitUrl).toBe("wss://livekit.test");
  });

  it("enabled=true → false → cleanup token (cancel refresh timer pending)", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(makeBackendTokenResponse({ expiresInS: 300 })),
    });
    vi.stubGlobal("fetch", fetchMock);

    const snapshot = { current: null as ViewerTokenSnapshot | null };
    const { rerender } = render(
      <FlipConsumer enabled={true} snapshotRef={snapshot} />,
    );

    await act(async () => {
      await flushMicrotasks();
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(snapshot.current?.token).toBe("tok-initial");

    // Flip enabled=false (logout mid-session par exemple).
    rerender(<FlipConsumer enabled={false} snapshotRef={snapshot} />);
    await act(async () => {
      await flushMicrotasks();
    });

    // Avance au-delà du refresh point — aucun nouveau fetch (timer cancellé).
    await act(async () => {
      await vi.advanceTimersByTimeAsync(500_000);
      await flushMicrotasks();
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});

describe("useViewerToken — refresh 401 surface error (review fix #1)", () => {
  /**
   * Spec §6.1 : "Si refresh échoue (auth invalide) → notification user
   * 'session expirée, reload'." Test review fix critique #1 : 401/403
   * doit set state.error pour que le caller puisse afficher l'UI.
   */
  it("refresh retourne 401 → state.error set 'session-expired'", async () => {
    const nowS = Math.floor(Date.now() / 1000);
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        // bootstrap initial — token expire dans 65s pour fire le refresh à T-60s rapide.
        ok: true,
        status: 200,
        json: () =>
          Promise.resolve({
            token: "tok-A",
            expires_at: nowS + 65,
            livekit_url: "wss://livekit.test",
          }),
      })
      .mockResolvedValueOnce({
        // refresh : 401 auth invalid.
        ok: false,
        status: 401,
        json: () => Promise.resolve({ detail: "viewer token expired" }),
      });
    vi.stubGlobal("fetch", fetchMock);

    const snapshot = { current: null as ViewerTokenSnapshot | null };
    render(<TestConsumer snapshotRef={snapshot} />);

    await act(async () => {
      await flushMicrotasks();
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);

    // Avance jusqu'au refresh (à T-60s = T+5s).
    await act(async () => {
      await vi.advanceTimersByTimeAsync(6_000);
      await flushMicrotasks();
    });

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(snapshot.current?.error).not.toBeNull();
    expect(snapshot.current?.error?.message).toMatch(/session-expired/);
    // Old token reste exposé (le caller peut décider de reload).
    expect(snapshot.current?.token).toBe("tok-A");
  });
});

describe("useViewerToken — cleanup", () => {
  it("unmount cancel le timer de refresh (pas de fetch après unmount)", async () => {
    const nowS = Math.floor(Date.now() / 1000);
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () =>
        Promise.resolve({
          token: "tok-A",
          expires_at: nowS + 300,
          livekit_url: "wss://livekit.test",
        }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const snapshot = { current: null as ViewerTokenSnapshot | null };
    const { unmount } = render(<TestConsumer snapshotRef={snapshot} />);

    await act(async () => {
      await flushMicrotasks();
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);

    unmount();

    // Avance bien au-delà du refresh point — aucun fetch ne doit fire.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(500_000);
      await flushMicrotasks();
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
