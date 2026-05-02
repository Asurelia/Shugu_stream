"use client";

/**
 * Client-side providers wrapper for App Router.
 *
 * `DesktopProvider` uses `useReducer` + `useContext` → cannot be a Server
 * Component. We isolate the client boundary here so `app/layout.tsx` (which
 * is a Server Component, free to use `metadata` exports) can mount it safely.
 *
 * Add other client-only providers here as Phase 2 progresses (e.g. theme
 * provider, error boundary, query client) — this keeps the boundary tight
 * and the server tree as small as possible.
 */
import type { ReactNode } from "react";

import { DesktopProvider } from "@/features/desktop/desktopState";

export function ClientProviders({ children }: { children: ReactNode }) {
  return <DesktopProvider>{children}</DesktopProvider>;
}
