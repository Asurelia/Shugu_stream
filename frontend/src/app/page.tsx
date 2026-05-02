/**
 * Root route `/` — App Router migration (Sprint E6).
 *
 * Server Component shell that exports `metadata` for SEO. The viewer hub
 * logic lives in `_client.tsx` (Client Component) because it uses hooks,
 * WebSocket, and Three.js.
 *
 * Font variables (--font-quicksand, --font-comfortaa, --font-display,
 * --font-body, --font-mono) are already injected on <html> by app/layout.tsx
 * — no re-declaration needed here.
 */
import type { Metadata } from "next";

import { HomeClient } from "./_client";

export const metadata: Metadata = {
  title: "Shugu ♡ AI VTuber live",
};

export default function HomePage() {
  return <HomeClient />;
}
