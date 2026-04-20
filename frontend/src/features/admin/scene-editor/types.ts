/**
 * Types partagés entre les composants du scene editor.
 *
 * La forme `ScenePayload` correspond **exactement** au JSONB servi par
 * `GET /api/registry/scene` (côté backend `_validate_scene_payload` dans
 * `routes/registry_api.py`). Garder les deux alignés en cas de refonte —
 * pas encore de codegen Pydantic→TS (Phase 6).
 */

export type Vec3 = { x: number; y: number; z: number };

export type ScenePayload = {
  camera: Vec3;
  look_at: Vec3;
  fov: number;
  background: string;
  idle_animation: string;
  avatar_position: Vec3;
  avatar_rotation_y: number;
};

export type SceneRow = {
  id: string;
  kind: "scene";
  slug: string;
  display_name: string;
  payload: ScenePayload;
  is_active: boolean;
  created_at: string;
  updated_at: string;
};

export type GizmoMode = "translate" | "rotate" | "scale";

/** Valeur par défaut — utilisée quand aucune scene n'est sélectionnée. */
export const EMPTY_SCENE: ScenePayload = {
  camera: { x: 0, y: 1.35, z: 1.2 },
  look_at: { x: 0, y: 1.3, z: 0 },
  fov: 20,
  background: "linear-gradient(135deg, #1A0A20 0%, #3B1E4E 50%, #1A0A20 100%)",
  idle_animation: "/idle_loop.vrma",
  avatar_position: { x: 0, y: 0, z: 0 },
  avatar_rotation_y: 0,
};
