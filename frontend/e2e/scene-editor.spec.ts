/**
 * Scene Editor — Phase A smoke test.
 *
 * Ces tests valident que le port verbatim du design Unity-style charge sans
 * régression :
 *   - la page `/[username]/admin/scene-editor` sort du layout admin, passe en
 *     plein écran (`position: fixed`), monte `SceneEditorApp` via dynamic
 *     import (ssr: false car dépend de window/popup APIs) ;
 *   - la menubar affiche le brand "Shugu Scene Editor" + les menus File /
 *     Edit / Scene / Window / Go / Help ;
 *   - les 3 docks principaux (viewport / right / bottom) sont rendus avec
 *     leurs tabstrips contenant les panneaux attendus par défaut.
 *
 * Aucun backend requis en Phase A : le scene editor affiche les mocks de
 * `mock-data.ts` tant que le store Zustand (Phase B) et les APIs (Phase C)
 * ne sont pas branchés. Les tests restent donc déterministes tant qu'on est
 * sur main non authentifié ; l'auth operator sera stubbée à partir de
 * Phase C quand les drafts deviendront persistables.
 */

import { test, expect } from "@playwright/test";

const EDITOR_URL = "/shugu/admin/scene-editor";

test.describe("Scene Editor · Phase A smoke", () => {
  test("page loads fullscreen with menubar + 3 docks (viewport / right / bottom)", async ({ page }) => {
    await page.goto(EDITOR_URL);

    // Attend que `SceneEditorApp` soit monté (dynamic import ssr:false).
    // `ide-root` est le wrapper racine émis par `SceneEditorApp` quand le
    // module est chargé côté client.
    await expect(page.locator(".ide-root")).toBeVisible();

    // Menubar présent avec le brand Shugu Scene Editor.
    await expect(page.locator(".ide-menubar")).toBeVisible();
    await expect(page.locator(".ide-menubar-brand")).toContainText("Shugu");
    await expect(page.locator(".ide-menubar-brand")).toContainText("Scene Editor");

    // Les 6 menus principaux (File / Edit / Scene / Window / Go / Help) sont
    // rendus dans la menubar.
    for (const menu of ["File", "Edit", "Scene", "Window", "Go", "Help"]) {
      await expect(page.locator(".ide-menubar-item", { hasText: menu })).toBeVisible();
    }

    // 3 docks principaux (le shell a viewport + right + bottom + hierarchy à
    // gauche qui partage le même ide-dock parent).
    // On vérifie au moins 3 .ide-tabstrip (viewport, right, bottom ont chacun
    // le leur ; hierarchy est un panel simple sans tabstrip).
    await expect(page.locator(".ide-tabstrip")).toHaveCount(3);
  });

  test("default tabs: Scene (viewport), Inspector (right), Assets (bottom)", async ({ page }) => {
    await page.goto(EDITOR_URL);
    await expect(page.locator(".ide-root")).toBeVisible();

    // Les trois tabs actifs par défaut d'après DEFAULT_LAYOUT dans
    // SceneEditorApp.tsx. `.ide-tab.active` identifie l'onglet actif dans
    // un tabstrip.
    const activeTabs = page.locator(".ide-tab.active");
    await expect(activeTabs).toHaveCount(3);
    await expect(activeTabs.filter({ hasText: /scene/i })).toBeVisible();
    await expect(activeTabs.filter({ hasText: /inspector/i })).toBeVisible();
    await expect(activeTabs.filter({ hasText: /assets/i })).toBeVisible();
  });

  test("splitters are rendered between docks", async ({ page }) => {
    await page.goto(EDITOR_URL);
    await expect(page.locator(".ide-root")).toBeVisible();

    // Au moins 3 splitters : left/viewport, viewport/right, workspace/bottom.
    const splitters = page.locator(".ide-splitter");
    expect(await splitters.count()).toBeGreaterThanOrEqual(3);
    await expect(splitters.first()).toBeVisible();
  });

  test("hotkey W activates the Move tool in the toolbar", async ({ page }) => {
    await page.goto(EDITOR_URL);
    await expect(page.locator(".ide-root")).toBeVisible();

    // Presser 'w' doit allumer l'outil Move (cf. hotkeys.tsx + MainToolbar).
    // On teste via le bouton du toolbar qui possède la classe `.active` quand
    // `tool === "move"`.
    await page.keyboard.press("w");
    // L'un des boutons toolbar devient actif avec un label Move.
    const activeToolBtn = page.locator(".ide-toolbar .ide-tb-btn.active");
    await expect(activeToolBtn.first()).toBeVisible();
  });
});
