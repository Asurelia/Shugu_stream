/**
 * Tests for useAccessibilityPrefs hook (U5 a11y captions toggle)
 *
 * Covers:
 *  1. Default state is captionsEnabled=false (no stored prefs)
 *  2. setCaptionsEnabled(true) updates state and persists to localStorage
 *  3. setCaptionsEnabled(false) updates state and persists to localStorage
 *  4. Hook rehydrates from existing localStorage on mount
 *  5. Handles corrupted localStorage gracefully (defaults to false)
 */
import { describe, it, expect, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useAccessibilityPrefs } from "../useAccessibilityPrefs";

const STORAGE_KEY = "shugu-a11y-prefs";

describe("useAccessibilityPrefs", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  /* ── 1. Default state ──────────────────────────────────────── */

  it("returns captionsEnabled=false by default when nothing is stored", () => {
    const { result } = renderHook(() => useAccessibilityPrefs());
    expect(result.current.captionsEnabled).toBe(false);
  });

  /* ── 2. setCaptionsEnabled(true) ───────────────────────────── */

  it("setCaptionsEnabled(true) updates state to true", () => {
    const { result } = renderHook(() => useAccessibilityPrefs());
    act(() => {
      result.current.setCaptionsEnabled(true);
    });
    expect(result.current.captionsEnabled).toBe(true);
  });

  it("setCaptionsEnabled(true) persists { captionsEnabled: true } to localStorage", () => {
    const { result } = renderHook(() => useAccessibilityPrefs());
    act(() => {
      result.current.setCaptionsEnabled(true);
    });
    const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "{}");
    expect(stored).toEqual({ captionsEnabled: true });
  });

  /* ── 3. setCaptionsEnabled(false) ──────────────────────────── */

  it("setCaptionsEnabled(false) after true reverts state to false", () => {
    const { result } = renderHook(() => useAccessibilityPrefs());
    act(() => { result.current.setCaptionsEnabled(true); });
    act(() => { result.current.setCaptionsEnabled(false); });
    expect(result.current.captionsEnabled).toBe(false);
  });

  it("setCaptionsEnabled(false) persists { captionsEnabled: false } to localStorage", () => {
    const { result } = renderHook(() => useAccessibilityPrefs());
    act(() => { result.current.setCaptionsEnabled(true); });
    act(() => { result.current.setCaptionsEnabled(false); });
    const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "{}");
    expect(stored).toEqual({ captionsEnabled: false });
  });

  /* ── 4. Rehydration from existing localStorage ─────────────── */

  it("rehydrates captionsEnabled=true from existing localStorage entry", () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ captionsEnabled: true }));
    const { result } = renderHook(() => useAccessibilityPrefs());
    // After mount, useEffect runs and reads from localStorage.
    expect(result.current.captionsEnabled).toBe(true);
  });

  it("rehydrates captionsEnabled=false from stored false entry", () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ captionsEnabled: false }));
    const { result } = renderHook(() => useAccessibilityPrefs());
    expect(result.current.captionsEnabled).toBe(false);
  });

  /* ── 5. Corrupted localStorage gracefully defaults to false ─── */

  it("handles invalid JSON in localStorage gracefully (defaults to false)", () => {
    localStorage.setItem(STORAGE_KEY, "not-valid-json{{{");
    const { result } = renderHook(() => useAccessibilityPrefs());
    expect(result.current.captionsEnabled).toBe(false);
  });

  it("handles unexpected shape in localStorage gracefully (defaults to false)", () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ someOtherKey: true }));
    const { result } = renderHook(() => useAccessibilityPrefs());
    expect(result.current.captionsEnabled).toBe(false);
  });
});
