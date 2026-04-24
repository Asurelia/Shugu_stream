/**
 * Vitest configuration — Shugu_stream frontend.
 *
 * Phase B (store Zustand du Scene Editor) introduit les premiers tests
 * unitaires front du repo. On cible `src/stores/__tests__/` et
 * `src/features/scene-editor/__tests__/` avec l'environnement jsdom pour
 * simuler `window.localStorage` et DOM APIs (BroadcastChannel stub).
 *
 * Les tests E2E Playwright restent sous `e2e/` avec leur propre harness —
 * Vitest ignore ce dossier pour éviter la double-exécution.
 */

import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    include: [
      "src/**/*.test.{ts,tsx}",
      "src/**/__tests__/**/*.{ts,tsx}",
    ],
    exclude: ["node_modules", "e2e", ".next", ".archive"],
    setupFiles: ["./vitest.setup.ts"],
    // Reset modules and mocks between tests — critique pour Zustand stores
    // qui persistent sinon entre tests (shared module state).
    clearMocks: true,
    restoreMocks: true,
  },
});
