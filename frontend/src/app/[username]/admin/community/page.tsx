/**
 * `/[username]/admin/community` — Community (App Router migration, Sprint E5).
 *
 * Server shell : exporte `metadata`, délègue le rendu à `CommunityClient`.
 * `AdminShell` et `AdminAuthGuard` utilisent `next/navigation` — App Router uniquement.
 */
import type { Metadata } from "next";

import { CommunityClient } from "./_client";

export const metadata: Metadata = {
  title: "Community — Shugu Admin",
};

export default function CommunityPage() {
  return <CommunityClient />;
}
