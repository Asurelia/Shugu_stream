/**
 * /lg-preview — App Router migration (Sprint E3).
 *
 * Server Component shell that exports `metadata` for SEO. The actual smoke-test
 * markup lives in `_client.tsx` (Client Component) because it uses `useState`
 * for modal / tab / switch state.
 */
import type { Metadata } from "next";

import { LgPreviewClient } from "./_client";

export const metadata: Metadata = {
  title: "LG Preview — Shugu",
};

export default function LgPreviewPage() {
  return <LgPreviewClient />;
}
