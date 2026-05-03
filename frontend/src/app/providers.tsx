"use client";

/**
 * Client-side providers boundary for App Router.
 *
 * Isolates the client boundary so `app/layout.tsx` (a Server Component,
 * free to use `metadata` exports) can mount it safely. Add other client-only
 * providers here as needed (e.g. theme provider, error boundary, query client).
 */
import type { ReactNode } from "react";

export function ClientProviders({ children }: { children: ReactNode }) {
  return <>{children}</>;
}
