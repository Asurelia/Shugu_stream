/**
 * Playwright configuration — Shugu_stream frontend.
 *
 * Phase A (port du Scene Editor Unity-style) introduit le premier harnais E2E
 * du repo. Les tests vivent sous `frontend/e2e/` et ciblent le dev server
 * Next.js tel qu'exposé localement (port 3005 par défaut, cf. scripts
 * `dev`/`start` de `package.json`).
 *
 * Stratégie :
 *  - `webServer` boote `npm run dev` automatiquement, sauf si un serveur
 *    tourne déjà (pratique pour dev local).
 *  - `trace: "retain-on-failure"` garde les traces uniquement sur échec,
 *    pour garder `test-results/` léger.
 *  - En CI, `reuseExistingServer: false` force un boot propre.
 */

import { defineConfig } from "@playwright/test";

const PORT = Number(process.env.PORT || 3005);
const BASE_URL = process.env.PLAYWRIGHT_BASE_URL || `http://localhost:${PORT}`;

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  expect: { timeout: 5_000 },
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: BASE_URL,
    headless: true,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
    viewport: { width: 1440, height: 900 },
  },
  webServer: {
    command: `npm run dev`,
    url: BASE_URL,
    timeout: 180_000,
    reuseExistingServer: !process.env.CI,
    stdout: "pipe",
    stderr: "pipe",
  },
});
