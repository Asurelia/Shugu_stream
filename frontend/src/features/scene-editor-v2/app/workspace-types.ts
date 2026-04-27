/**
 * Types et constantes des workspaces du Scene Editor v2.
 *
 * 3 workspaces (cf. docs/scene-editor-v2/DESIGN.md §1) :
 * - `3d`  : monde 3D Shugu (décor, perso, vêtements, props, anims, VFX, lumières, caméra)
 * - `2d`  : overlays stream (sub goal, lower third, alerts, status, ticker)
 * - `show`: compositing temps réel 3D + 2D (preview live)
 */

export type WorkspaceId = "3d" | "2d" | "show";

export type WorkspaceDef = {
  id: WorkspaceId;
  label: string;
  hotkey: "1" | "2" | "3";
  icon: string;
  description: string;
};

export const WORKSPACES: readonly WorkspaceDef[] = [
  { id: "3d",   label: "Scene 3D",  hotkey: "1", icon: "◈", description: "Décor, personnage, props, animations." },
  { id: "2d",   label: "Overlays",  hotkey: "2", icon: "▦", description: "Sub goal, alerts, lower third." },
  { id: "show", label: "Show",      hotkey: "3", icon: "◉", description: "Compositing temps réel 3D + 2D." },
] as const;

export const DEFAULT_WORKSPACE: WorkspaceId = "3d";

export function isWorkspaceId(value: unknown): value is WorkspaceId {
  return value === "3d" || value === "2d" || value === "show";
}
