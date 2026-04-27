/**
 * Scene Editor — drag & drop context partagé.
 *
 * Deux types de drags cohabitent : les assets (depuis le panel Assets vers
 * le viewport) et les tabs (d'un dock à l'autre). Un seul payload actif à
 * la fois. Vit dans un module dédié pour éviter les imports circulaires
 * entre l'app shell et les panels.
 */

import { createContext, useContext } from "react";
import type { AssetItem, DockablePanelKey } from "@/features/editor-shared";

export type DockId = "viewport" | "right" | "bottom";

// dnd-context.ts (legacy) — re-exporté depuis editor-shared pendant la transition.
// Phase 6 supprimera ce fichier et ses consumers legacy.
export type { DockablePanelKey, PanelKey } from "@/features/editor-shared";

export type DragPayload =
  | { kind: "asset"; asset: AssetItem }
  | { kind: "tab"; panel: DockablePanelKey; fromDock: DockId };

export type DragDropCtx = {
  payload: DragPayload | null;
  setPayload: (p: DragPayload | null) => void;
  /** Last asset dropped on the viewport — for optimistic display. */
  droppedAsset: AssetItem | null;
  setDroppedAsset: (a: AssetItem | null) => void;
  /** Toast callback (wired in SceneEditorApp). */
  toast: (msg: string) => void;
};

export const DragDropContext = createContext<DragDropCtx>({
  payload: null,
  setPayload: () => {},
  droppedAsset: null,
  setDroppedAsset: () => {},
  toast: () => {},
});

export const useDragDrop = () => useContext(DragDropContext);
