import { useEffect, useState } from "react";

const STORAGE_KEY = "shugu-a11y-prefs";

type A11yPrefs = {
  captionsEnabled: boolean;
};

function readPrefs(): A11yPrefs {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return { captionsEnabled: false };
    const parsed = JSON.parse(raw) as unknown;
    if (typeof parsed === "object" && parsed !== null && "captionsEnabled" in parsed) {
      return { captionsEnabled: !!(parsed as Record<string, unknown>).captionsEnabled };
    }
  } catch {
    // ignore parse/access errors
  }
  return { captionsEnabled: false };
}

function writePrefs(prefs: A11yPrefs): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs));
  } catch {
    // ignore storage errors (private mode, quota exceeded, etc.)
  }
}

/**
 * Accessibility preferences — persisted in localStorage under `shugu-a11y-prefs`.
 *
 * `captionsEnabled` controls whether anonymous visitors see Shugu's assistant
 * messages in the chat feed (off by default to preserve the current engagement
 * model; visitors opt-in via the HUD toggle).
 *
 * SSR-safe: the localStorage read happens in a useEffect, never during render,
 * so there is no hydration mismatch. First paint always returns { captionsEnabled: false }.
 */
export function useAccessibilityPrefs(): {
  captionsEnabled: boolean;
  setCaptionsEnabled: (v: boolean) => void;
} {
  const [captionsEnabled, setCaptionsEnabledState] = useState(false);

  // Hydrate from localStorage after mount (SSR-safe).
  // P2: setState in effect is intentional — we're syncing from an external
  // system (localStorage). Same pattern as debugCaptions in _client.tsx.
  useEffect(() => {
    const stored = readPrefs();
    if (stored.captionsEnabled) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setCaptionsEnabledState(true);
    }
  }, []);

  const setCaptionsEnabled = (v: boolean) => {
    setCaptionsEnabledState(v);
    writePrefs({ captionsEnabled: v });
  };

  return { captionsEnabled, setCaptionsEnabled };
}
