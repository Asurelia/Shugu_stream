/**
 * Smoke test page for App Router bootstrap (Sprint E1).
 *
 * Purpose : validate that the new `app/` tree is reachable, fonts/styles
 * apply, and the client `DesktopProvider` boundary mounts without error.
 *
 * Phase 2 sprints E2-E6 will migrate real pages from `pages/` to `app/`,
 * at which point this smoke route can be deleted (or kept as a permanent
 * health-check page — TBD).
 *
 * Server Component by default — no `"use client"` directive needed since
 * we render plain JSX without hooks. Demonstrates that the layout works
 * for both Server and Client Components.
 */
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Smoke · App Router · Shugu",
};

export default function SmokePage() {
  return (
    <main
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        minHeight: "100vh",
        padding: "2rem",
        gap: "1rem",
      }}
    >
      <h1 style={{ fontFamily: "var(--font-display)", fontSize: "2rem" }}>
        App Router OK
      </h1>
      <p style={{ fontFamily: "var(--font-body)", opacity: 0.8 }}>
        Sprint E1 bootstrap — fonts + layout chargent correctement.
      </p>
      <p
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: "0.85rem",
          opacity: 0.6,
        }}
      >
        /smoke · server component · {new Date().toISOString()}
      </p>
    </main>
  );
}
