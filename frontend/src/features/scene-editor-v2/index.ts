/**
 * Scene Editor v2 — barrel export.
 * Phase 1 = shell uniquement (3 workspaces vides + palette + hotkeys).
 */

export { SceneEditorV2App } from "./app/SceneEditorV2App";
export { ErrorBoundary as SceneEditorV2ErrorBoundary } from "./app/ErrorBoundary";
export { useSceneEditorStore, __resetSceneEditorStoreForTest } from "./store/useSceneEditorStore";
export { WORKSPACES, DEFAULT_WORKSPACE, isWorkspaceId } from "./app/workspace-types";
export type { WorkspaceId, WorkspaceDef } from "./app/workspace-types";
export { useHotkeys } from "./hooks/useHotkeys";
export type { Binding as HotkeyBinding } from "./hooks/useHotkeys";
