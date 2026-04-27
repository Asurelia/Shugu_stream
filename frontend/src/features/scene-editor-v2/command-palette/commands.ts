/**
 * Registry des commandes de la Command Palette.
 *
 * Phase 1 = navigation + visibilité workspace seulement. Phase 2-7 ajoutera
 * Insert / Edit / View / Stream / Help / etc.
 *
 * Une commande = label, optionnel hint clavier, action callback. Le store
 * fournit les hooks (setWorkspace, openPalette, etc.) à connecter au moment
 * de l'instanciation.
 */

import type { useSceneEditorStore } from "../store/useSceneEditorStore";

export type Command = {
  id: string;
  label: string;
  category: "Workspace" | "View" | "Edit" | "File" | "Help";
  hint?: string;
  keywords?: string[];
  run: () => void;
};

type StoreApi = ReturnType<typeof useSceneEditorStore.getState>;

export function buildCommands(store: StoreApi): Command[] {
  return [
    {
      id: "workspace.scene3d",
      label: "Switch to Scene 3D",
      category: "Workspace",
      hint: "1",
      keywords: ["3d", "scene", "viewer", "world"],
      run: () => store.setWorkspace("3d"),
    },
    {
      id: "workspace.overlays",
      label: "Switch to Overlays 2D",
      category: "Workspace",
      hint: "2",
      keywords: ["2d", "overlay", "alert", "subgoal"],
      run: () => store.setWorkspace("2d"),
    },
    {
      id: "workspace.show",
      label: "Switch to Show / Preview",
      category: "Workspace",
      hint: "3",
      keywords: ["show", "preview", "live", "compositing", "stream"],
      run: () => store.setWorkspace("show"),
    },
    {
      id: "view.help",
      label: "Show keyboard shortcuts",
      category: "Help",
      hint: "?",
      keywords: ["shortcuts", "help", "keys", "cheatsheet"],
      run: () => {
        // Phase 1 : log seulement (Phase 7 ajoutera la cheat-sheet modale).
        if (typeof window !== "undefined") {
          window.dispatchEvent(new CustomEvent("scene-editor-v2:show-shortcuts"));
        }
      },
    },
  ];
}

/** Filtrage fuzzy simple : matche si le query (lowercased) est sous-séquence du label/keywords. */
export function filterCommands(commands: Command[], query: string): Command[] {
  const q = query.trim().toLowerCase();
  if (!q) return commands;
  const matches = (text: string) => {
    const t = text.toLowerCase();
    let i = 0;
    for (const ch of t) {
      if (ch === q[i]) i += 1;
      if (i === q.length) return true;
    }
    return false;
  };
  return commands.filter((c) => {
    if (matches(c.label)) return true;
    if (c.category && matches(c.category)) return true;
    if (c.keywords?.some((k) => matches(k))) return true;
    return false;
  });
}
