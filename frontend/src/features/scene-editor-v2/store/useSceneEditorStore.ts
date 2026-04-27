/**
 * Store Zustand global du Scene Editor v2 — Phase 1 foundation.
 *
 * Phase 1 = shell uniquement, donc le store contient :
 * - currentWorkspace : workspace actif
 * - paletteOpen     : Command Palette ouverte ou non
 * - sceneName       : nom affiché dans la topbar (renommable inline plus tard)
 * - dirty           : flag "modifications non sauvées"
 * - splitRatios     : map id → ratio [0..1] persisté localStorage par splittable layout
 *
 * Phase 2+ ajoutera : selection 3D, hierarchy, transform mode, gizmo state, etc.
 *
 * Persistance : on garde le store volontairement simple pour Phase 1 (pas de
 * `persist` middleware) — seul `splitRatios` lit/écrit localStorage à la
 * volée via les helpers exportés. Évite les soucis de SSR hydration Next.js.
 */

import { create } from "zustand";
import { DEFAULT_WORKSPACE, type WorkspaceId, isWorkspaceId } from "../app/workspace-types";

const SPLIT_STORAGE_PREFIX = "scene-editor-v2:split:";
const WORKSPACE_STORAGE_KEY = "scene-editor-v2:workspace";

type SceneEditorState = {
  currentWorkspace: WorkspaceId;
  paletteOpen: boolean;
  sceneName: string;
  dirty: boolean;
  splitRatios: Record<string, number>;

  setWorkspace: (id: WorkspaceId) => void;
  openPalette: () => void;
  closePalette: () => void;
  togglePalette: () => void;
  setSceneName: (name: string) => void;
  markDirty: () => void;
  markClean: () => void;
  setSplitRatio: (id: string, ratio: number) => void;
};

function readPersistedWorkspace(): WorkspaceId {
  if (typeof window === "undefined") return DEFAULT_WORKSPACE;
  try {
    const raw = window.localStorage.getItem(WORKSPACE_STORAGE_KEY);
    return isWorkspaceId(raw) ? raw : DEFAULT_WORKSPACE;
  } catch {
    return DEFAULT_WORKSPACE;
  }
}

function readPersistedRatio(id: string): number | undefined {
  if (typeof window === "undefined") return undefined;
  try {
    const raw = window.localStorage.getItem(SPLIT_STORAGE_PREFIX + id);
    if (raw === null) return undefined;
    const n = Number.parseFloat(raw);
    return Number.isFinite(n) && n > 0 && n < 1 ? n : undefined;
  } catch {
    return undefined;
  }
}

export const useSceneEditorStore = create<SceneEditorState>((set) => ({
  currentWorkspace: readPersistedWorkspace(),
  paletteOpen: false,
  sceneName: "untitled scene",
  dirty: false,
  splitRatios: {},

  setWorkspace: (id) => {
    set({ currentWorkspace: id });
    if (typeof window !== "undefined") {
      try { window.localStorage.setItem(WORKSPACE_STORAGE_KEY, id); } catch { /* quota */ }
    }
  },
  openPalette: () => set({ paletteOpen: true }),
  closePalette: () => set({ paletteOpen: false }),
  togglePalette: () => set((s) => ({ paletteOpen: !s.paletteOpen })),
  setSceneName: (name) => set({ sceneName: name, dirty: true }),
  markDirty: () => set({ dirty: true }),
  markClean: () => set({ dirty: false }),
  setSplitRatio: (id, ratio) => {
    const clamped = Math.min(0.95, Math.max(0.05, ratio));
    set((s) => ({ splitRatios: { ...s.splitRatios, [id]: clamped } }));
    if (typeof window !== "undefined") {
      try { window.localStorage.setItem(SPLIT_STORAGE_PREFIX + id, String(clamped)); } catch { /* quota */ }
    }
  },
}));

/** Helper pour SplitLayout : ratio initial via store puis fallback localStorage puis default. */
export function readSplitRatio(id: string, defaultRatio: number): number {
  const fromStore = useSceneEditorStore.getState().splitRatios[id];
  if (fromStore !== undefined) return fromStore;
  const fromStorage = readPersistedRatio(id);
  return fromStorage ?? defaultRatio;
}

/**
 * Reset complet pour les tests Vitest.
 * Zustand garde le state au niveau module, donc sans reset les tests partagent
 * le state. À appeler dans beforeEach des suites qui mutent le store.
 */
export function __resetSceneEditorStoreForTest(): void {
  useSceneEditorStore.setState({
    currentWorkspace: DEFAULT_WORKSPACE,
    paletteOpen: false,
    sceneName: "untitled scene",
    dirty: false,
    splitRatios: {},
  });
  if (typeof window !== "undefined") {
    try {
      window.localStorage.removeItem(WORKSPACE_STORAGE_KEY);
      const keysToRemove: string[] = [];
      for (let i = 0; i < window.localStorage.length; i++) {
        const k = window.localStorage.key(i);
        if (k && k.startsWith(SPLIT_STORAGE_PREFIX)) keysToRemove.push(k);
      }
      keysToRemove.forEach((k) => window.localStorage.removeItem(k));
    } catch { /* quota / opaque */ }
  }
}
