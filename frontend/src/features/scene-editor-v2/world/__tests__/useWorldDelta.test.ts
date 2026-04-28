import {
  describe,
  it,
  expect,
  vi,
  beforeEach,
  afterEach,
  type MockInstance,
} from "vitest";
import { renderHook } from "@testing-library/react";
import { useWorldDelta } from "../useWorldDelta";
import { useWorldStateStore, __resetWorldStateStoreForTest } from "../useWorldStateStore";

// ─── WebSocket mock factory ───────────────────────────────────────────────────

type WSInstance = {
  onopen: ((ev: Event) => void) | null;
  onmessage: ((ev: MessageEvent) => void) | null;
  onclose: ((ev: CloseEvent) => void) | null;
  onerror: ((ev: Event) => void) | null;
  close: MockInstance;
  readyState: number;
  url: string;
};

let mockInstances: WSInstance[] = [];

function createMockWS(url: string): WSInstance {
  const inst: WSInstance = {
    onopen: null,
    onmessage: null,
    onclose: null,
    onerror: null,
    close: vi.fn(),
    readyState: WebSocket.CONNECTING,
    url,
  };
  mockInstances.push(inst);
  return inst;
}

beforeEach(() => {
  mockInstances = [];
  __resetWorldStateStoreForTest();
  vi.useFakeTimers();
  vi.stubGlobal("WebSocket", vi.fn((url: string) => createMockWS(url)));
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

// ─── Tests ────────────────────────────────────────────────────────────────────

describe("useWorldDelta — connection lifecycle", () => {
  it("opens a WebSocket to /ws/world on mount", () => {
    renderHook(() => useWorldDelta());
    expect(mockInstances).toHaveLength(1);
    expect(mockInstances[0].url).toContain("/ws/world");
  });

  it("closes the WebSocket on unmount", () => {
    const { unmount } = renderHook(() => useWorldDelta());
    unmount();
    expect(mockInstances[0].close).toHaveBeenCalled();
  });
});

describe("useWorldDelta — applyDelta on message", () => {
  it("calls applyDelta with parsed JSON when a message is received", () => {
    renderHook(() => useWorldDelta());
    const ws = mockInstances[0];

    // Simulate open + message
    ws.onopen?.(new Event("open"));
    ws.onmessage?.(
      new MessageEvent("message", { data: JSON.stringify({ avatar_pose: "wave" }) })
    );

    const { state } = useWorldStateStore.getState();
    expect(state.avatar_pose).toBe("wave");
  });

  it("applies multiple deltas sequentially", () => {
    renderHook(() => useWorldDelta());
    const ws = mockInstances[0];
    ws.onopen?.(new Event("open"));

    ws.onmessage?.(
      new MessageEvent("message", { data: JSON.stringify({ mood: "happy" }) })
    );
    ws.onmessage?.(
      new MessageEvent("message", { data: JSON.stringify({ clock_ms: 500 }) })
    );

    const { state } = useWorldStateStore.getState();
    expect(state.mood).toBe("happy");
    expect(state.clock_ms).toBe(500);
  });

  it("ignores malformed JSON without throwing", () => {
    renderHook(() => useWorldDelta());
    const ws = mockInstances[0];
    ws.onopen?.(new Event("open"));

    // Should not throw
    expect(() =>
      ws.onmessage?.(new MessageEvent("message", { data: "not-json{{{" }))
    ).not.toThrow();

    // Store unchanged
    expect(useWorldStateStore.getState().state.avatar_pose).toBe("idle");
  });
});

describe("useWorldDelta — reconnect backoff", () => {
  it("reconnects after close with initial 1s backoff", () => {
    renderHook(() => useWorldDelta());
    expect(mockInstances).toHaveLength(1);

    // Simulate close
    mockInstances[0].onclose?.(new CloseEvent("close"));

    // Before timer fires — no new instance
    expect(mockInstances).toHaveLength(1);

    // Advance 1 second
    vi.advanceTimersByTime(1000);
    expect(mockInstances).toHaveLength(2);
  });

  it("doubles backoff on consecutive closes (exponential)", () => {
    renderHook(() => useWorldDelta());

    // First close → reconnect after 1s
    mockInstances[0].onclose?.(new CloseEvent("close"));
    vi.advanceTimersByTime(1000);
    expect(mockInstances).toHaveLength(2);

    // Second close → reconnect after 2s
    mockInstances[1].onclose?.(new CloseEvent("close"));
    vi.advanceTimersByTime(1000);
    expect(mockInstances).toHaveLength(2); // not yet

    vi.advanceTimersByTime(1000); // total 2s
    expect(mockInstances).toHaveLength(3);
  });

  it("stops reconnecting after unmount (cancelled token)", () => {
    const { unmount } = renderHook(() => useWorldDelta());
    unmount();

    mockInstances[0].onclose?.(new CloseEvent("close"));
    vi.advanceTimersByTime(5000);

    // Should NOT have created a second instance
    expect(mockInstances).toHaveLength(1);
  });
});
