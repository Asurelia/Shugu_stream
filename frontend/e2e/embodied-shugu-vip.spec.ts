/**
 * Phase E4 — North Star Demo : VIP arrival triggers Embodied Shugu transformation.
 *
 * Scénario end-to-end :
 *   1. L'operator ouvre le Scene Editor.
 *   2. Un VIP (Spoukie) arrive — déclenché via POST /api/test/director/trigger.
 *   3. Le Director (Soul/Shell) réagit en < 5s : outfit, VFX, anim, face.
 *   4. Les data-attributes du viewer-adapter reflètent le changement.
 *
 * # Prérequis backend
 *
 * Ce test nécessite un backend FastAPI lancé avec :
 *   SHUGU_DIRECTOR_ENABLED=true
 *   SHUGU_TEST_TRIGGERS_ENABLED=true
 *   SHUGU_MINIMAX_API_KEY=... (ou autre provider configuré)
 *
 * Si `SHUGU_MINIMAX_API_KEY` est absent, le test est skippé proprement.
 * Si le backend est absent (pas de PLAYWRIGHT_BACKEND_URL), les steps API
 * sont skippées et le test passe en mode "frontend-only" (vérifie juste que
 * la page charge).
 *
 * # Data-attributes observés
 *
 * Le `<ViewerAdapter>` expose (Phase E4) :
 *   - `data-current-outfit`    : slug du dernier outfit appliqué.
 *   - `data-current-face`      : slug de la dernière expression faciale.
 *   - `data-active-vfx-count`  : nb de VFX reçus depuis le boot.
 *   - `data-current-scene`     : slug de la scène active.
 *
 * # Gating
 *
 * `SHUGU_MINIMAX_API_KEY` est utilisé comme proxy "le LLM est disponible en CI".
 * Sans LLM, le Director fait un fallback `[say_emotion:neutral]` qui ne mute
 * pas l'outfit → le test de changement d'outfit ne peut pas passer.
 *
 * Le test est donc skipé proprement (`test.skip`) si la clé est absente,
 * plutôt que de flaquer ou crasher.
 */

import { test, expect } from "@playwright/test";

const EDITOR_URL = "/shugu/admin/scene-editor";

/**
 * URL du backend API pour les routes Director test.
 * Peut être overridée via PLAYWRIGHT_BACKEND_URL (pour CI cross-origin).
 * Défaut : même origine que le frontend (proxy Next.js).
 */
const BACKEND_URL = process.env.PLAYWRIGHT_BACKEND_URL || "";

/**
 * Intercepte `/auth/me` pour simuler un operator connecté.
 * Pattern hérité des tests Phase A/B/D — sans ce stub, `AdminAuthGuard`
 * redirige vers `/login` avant que la page soit montée.
 */
async function stubAuth(page: import("@playwright/test").Page, username = "shugu") {
  await page.route("**/auth/me", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ username }),
    });
  });
}

/**
 * Stub WS /ws/editor pour éviter les erreurs de connexion WebSocket
 * quand le backend réel n'est pas disponible.
 */
async function stubEditorWs(page: import("@playwright/test").Page) {
  // On ne peut pas stubber un WebSocket natif en Playwright — on stub
  // simplement l'API REST qui pré-charge les scènes. Le WS s'échouera
  // silencieusement (le hook gère les erreurs de connexion gracieusement).
  await page.route("**/api/scene-editor/**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ items: [], total: 0 }),
    });
  });
}

test.describe("Phase E4 — Embodied Shugu VIP north star demo", () => {
  test.beforeEach(async ({ page }) => {
    await stubAuth(page);
    await stubEditorWs(page);
  });

  test("Scene Editor charge avec le viewer-adapter et ses data-attributes", async ({ page }) => {
    // Test de smoke Phase E4 : vérifie que la page charge correctement
    // et que les data-attributes Phase E4 sont présents avec des valeurs par défaut.
    await page.goto(EDITOR_URL);

    // Attendre que SceneEditorApp soit monté (dynamic import ssr:false).
    await expect(page.locator(".ide-root")).toBeVisible({ timeout: 30_000 });

    // Le scene-viewer-canvas est dans le dock viewport.
    await expect(page.locator('[data-testid="scene-viewer-canvas"]')).toBeVisible({
      timeout: 10_000,
    });

    // Vérifier que les data-attributes Phase E4 sont présents sur le viewer-adapter.
    const adapter = page.locator('[data-testid="scene-viewer-adapter"]');
    await expect(adapter).toBeVisible();

    // Les valeurs initiales sont les défauts du store.
    await expect(adapter).toHaveAttribute("data-current-outfit", "default");
    await expect(adapter).toHaveAttribute("data-current-face", "neutral");
    await expect(adapter).toHaveAttribute("data-current-scene", "main_talk");
    await expect(adapter).toHaveAttribute("data-active-vfx-count", "0");
  });

  test(
    "VIP arrival triggers Embodied Shugu transformation in <5s",
    async ({ page, request }) => {
      // Ce test nécessite une clé LLM en CI pour que le Director produise
      // des tags réels (outfit/vfx/face) — sans clé, le fallback est
      // [say_emotion:neutral] qui ne change pas l'outfit.
      test.skip(
        !process.env.SHUGU_MINIMAX_API_KEY && !process.env.ANTHROPIC_API_KEY,
        "Aucune clé LLM disponible (SHUGU_MINIMAX_API_KEY / ANTHROPIC_API_KEY absent) — test skippé en CI sans LLM.",
      );

      // Le backend doit être disponible et configuré avec les flags Director.
      test.skip(
        !process.env.SHUGU_DIRECTOR_ENABLED || process.env.SHUGU_DIRECTOR_ENABLED !== "true",
        "SHUGU_DIRECTOR_ENABLED != true — backend Director non configuré pour ce test.",
      );

      await page.goto(EDITOR_URL);
      await expect(page.locator(".ide-root")).toBeVisible({ timeout: 30_000 });
      await expect(page.locator('[data-testid="scene-viewer-canvas"]')).toBeVisible({
        timeout: 10_000,
      });

      const adapter = page.locator('[data-testid="scene-viewer-adapter"]');
      await expect(adapter).toBeVisible();

      // Capturer l'état initial.
      const initialOutfit = await adapter.getAttribute("data-current-outfit");

      // Déclencher l'arrivée VIP via la route de test Director.
      const triggerUrl = BACKEND_URL
        ? `${BACKEND_URL}/api/test/director/trigger`
        : "/api/test/director/trigger";

      const triggerResponse = await request.post(triggerUrl, {
        data: {
          kind: "vip_arrival",
          payload: { sender: "spoukie" },
        },
        headers: {
          // Le cookie operator doit être transmis pour l'auth.
          // En CI, le backend est lancé avec credentials de test.
        },
      });

      // 202 Accepted = trigger publié sur le bus (orchestration asynchrone).
      // 404 = test_triggers_enabled=False → fail explicite.
      // 503 = director_enabled=False → fail explicite.
      expect(triggerResponse.status(), "La route /api/test/director/trigger doit retourner 202").toBe(202);

      // Attendre que l'outfit change (le Director a eu le temps de LLM + workers).
      // Budget : 5s avec retry toutes les 250ms (typique < 3s sur MiniMax).
      await expect.poll(
        async () => {
          return adapter.getAttribute("data-current-outfit");
        },
        {
          timeout: 5_000,
          intervals: [250, 500, 1_000],
          message: `L'outfit n'a pas changé depuis "${initialOutfit}" après le trigger VIP vip_arrival Spoukie`,
        },
      ).not.toBe(initialOutfit);

      // Vérifier que des VFX ont été activés.
      const vfxCount = await adapter.getAttribute("data-active-vfx-count");
      expect(
        parseInt(vfxCount ?? "0", 10),
        "Au moins 1 VFX doit avoir été déclenché par le Director",
      ).toBeGreaterThan(0);
    },
  );

  test(
    "Route test director retourne 404 quand SHUGU_TEST_TRIGGERS_ENABLED est absent",
    async ({ request }) => {
      // Ce test vérifie le comportement de fail-closed de la route.
      // On suppose que le backend de test n'a PAS le flag activé
      // (comportement par défaut sécurisé).
      test.skip(
        !!process.env.SHUGU_TEST_TRIGGERS_ENABLED,
        "SHUGU_TEST_TRIGGERS_ENABLED activé — skip le test de fail-closed.",
      );

      const triggerUrl = BACKEND_URL
        ? `${BACKEND_URL}/api/test/director/trigger`
        : "/api/test/director/trigger";

      // Sans cookie d'auth → 401 (correct).
      // Avec cookie mais sans flag → 404 (correct).
      // On vérifie juste que la route ne retourne jamais 200 sans le flag.
      const response = await request.post(triggerUrl, {
        data: { kind: "vip_arrival", payload: {} },
        failOnStatusCode: false,
      });

      // 401 (pas d'auth) ou 404 (flag absent) sont tous deux acceptables.
      expect(
        [401, 404],
        `La route doit retourner 401 ou 404 sans les conditions requises (reçu: ${response.status()})`,
      ).toContain(response.status());
    },
  );
});
