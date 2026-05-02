/**
 * `/[username]/admin/analytics` — Harmonized Stream Pulse (App Router migration, Sprint E5).
 *
 * Server shell : exporte `metadata`, délègue le rendu à `AnalyticsClient`.
 * `AdminShell` et `AdminAuthGuard` utilisent `next/navigation` — App Router uniquement.
 */
import type { Metadata } from "next";

import { AnalyticsClient } from "./_client";

export const metadata: Metadata = {
  title: "Harmonized Stream Pulse — Shugu Admin",
};

export default function AnalyticsPage() {
  return <AnalyticsClient />;
}
