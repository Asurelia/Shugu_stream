/**
 * `/[username]/admin` — Live Control Center (App Router migration, Sprint E5).
 *
 * Server shell : exporte `metadata`, délègue le rendu à `AdminHomeClient`.
 * `AdminShell` et `AdminAuthGuard` utilisent `next/navigation` — App Router uniquement.
 */
import type { Metadata } from "next";

import { AdminHomeClient } from "./_client";

export const metadata: Metadata = {
  title: "Live Control — Shugu Admin",
};

export default function AdminHomePage() {
  return <AdminHomeClient />;
}
