import * as THREE from "three";
import { getItems, invalidate as invalidateRegistry, type RegistryItem } from "../registry/registryClient";

export type SceneName = string;

export type SceneConfig = {
  name: string;
  cameraBase: THREE.Vector3;
  cameraTarget: THREE.Vector3;
  fov: number;
  background: string;
  idleAnimation: string;
  /** World-space offset applied to the avatar (vrm.scene.position). */
  avatarPosition: THREE.Vector3;
  /** Yaw (Y-axis rotation, radians). 0 = facing camera. */
  avatarRotationY: number;
};

// ─── Fallback statique (seed garantit zéro régression) ─────────────────────
const FALLBACK_CONFIGS: Record<string, SceneConfig> = {
  just_chatting: {
    name: "just_chatting",
    cameraBase: new THREE.Vector3(0, 1.35, 1.2),
    cameraTarget: new THREE.Vector3(0, 1.3, 0),
    fov: 20,
    background: "linear-gradient(135deg, #1A0A20 0%, #3B1E4E 35%, #4C1D5B 50%, #3B1E4E 65%, #1A0A20 100%)",
    idleAnimation: "/idle_loop.vrma",
    avatarPosition: new THREE.Vector3(0, 0, 0),
    avatarRotationY: 0,
  },
  reading_chat: {
    name: "reading_chat",
    cameraBase: new THREE.Vector3(-0.32, 1.38, 0.95),
    cameraTarget: new THREE.Vector3(-0.15, 1.34, 0),
    fov: 18,
    background: "linear-gradient(135deg, #1E1B3A 0%, #2B1E50 35%, #3B2969 50%, #2B1E50 65%, #1E1B3A 100%)",
    idleAnimation: "/animations/idle_attentive.fbx",
    avatarPosition: new THREE.Vector3(-0.15, 0, 0),
    avatarRotationY: 0.22,
  },
  reacting: {
    name: "reacting",
    cameraBase: new THREE.Vector3(0, 1.4, 0.78),
    cameraTarget: new THREE.Vector3(0, 1.36, 0),
    fov: 16,
    background: "linear-gradient(135deg, #4C1D5B 0%, #A03469 35%, #FF617F 50%, #A03469 65%, #4C1D5B 100%)",
    idleAnimation: "/animations/idle_excited.fbx",
    avatarPosition: new THREE.Vector3(0, 0, 0.08),
    avatarRotationY: 0,
  },
  idle_sleepy: {
    name: "idle_sleepy",
    cameraBase: new THREE.Vector3(0.08, 1.32, 1.4),
    cameraTarget: new THREE.Vector3(0, 1.3, 0),
    fov: 22,
    background: "linear-gradient(135deg, #07040F 0%, #14102A 35%, #1E1740 50%, #14102A 65%, #07040F 100%)",
    idleAnimation: "/animations/idle_sleepy.fbx",
    avatarPosition: new THREE.Vector3(0.1, 0, -0.05),
    avatarRotationY: -0.12,
  },
};

/**
 * Registre "hot" qui commence avec les fallbacks et est enrichi au boot
 * par fetch `/api/registry/scene`. Reste la source de vérité pour
 * `SceneManager.requestScene()`. Toute mutation passe par
 * `refreshScenes()` — pas d'accès direct depuis l'extérieur.
 */
export const SCENES: Record<string, SceneConfig> = { ...FALLBACK_CONFIGS };
export const DEFAULT_SCENE: SceneName = "just_chatting";

export function isSceneName(value: string): boolean {
  return value in SCENES;
}

// ─── Conversion payload JSON registry → SceneConfig ────────────────────────

type Vec3Json = { x?: number; y?: number; z?: number } | undefined;
type ScenePayload = {
  camera?: Vec3Json;
  look_at?: Vec3Json;
  fov?: number;
  background?: string;
  idle_animation?: string;
  avatar_position?: Vec3Json;
  avatar_rotation_y?: number;
};

function vec3(v: Vec3Json, fallback: THREE.Vector3): THREE.Vector3 {
  if (!v) return fallback.clone();
  return new THREE.Vector3(v.x ?? 0, v.y ?? 0, v.z ?? 0);
}

function payloadToConfig(slug: string, p: ScenePayload, fb?: SceneConfig): SceneConfig {
  const baseFb = fb ?? FALLBACK_CONFIGS.just_chatting;
  return {
    name: slug,
    cameraBase: vec3(p.camera, baseFb.cameraBase),
    cameraTarget: vec3(p.look_at, baseFb.cameraTarget),
    fov: typeof p.fov === "number" ? p.fov : baseFb.fov,
    background: typeof p.background === "string" && p.background ? p.background : baseFb.background,
    idleAnimation: typeof p.idle_animation === "string" && p.idle_animation ? p.idle_animation : baseFb.idleAnimation,
    avatarPosition: vec3(p.avatar_position, baseFb.avatarPosition),
    avatarRotationY: typeof p.avatar_rotation_y === "number" ? p.avatar_rotation_y : baseFb.avatarRotationY,
  };
}

// ─── Public API (fetch + merge) ────────────────────────────────────────────

/**
 * Recharge les scenes depuis `/api/registry/scene` et merge dans SCENES.
 * Les slugs fallback sont conservés si absents de la DB (zéro régression
 * si le registry est vide). À appeler au boot + sur WS invalidation.
 */
export async function refreshScenes(): Promise<void> {
  invalidateRegistry("scene");
  const items = (await getItems("scene")) as RegistryItem[];
  // Repart de zero sur les fallbacks puis surcharge avec les rows DB actives.
  for (const key of Object.keys(SCENES)) delete SCENES[key];
  for (const [slug, cfg] of Object.entries(FALLBACK_CONFIGS)) {
    SCENES[slug] = cfg;
  }
  for (const item of items) {
    if (!item.is_active) continue;
    SCENES[item.slug] = payloadToConfig(
      item.slug,
      item.payload as ScenePayload,
      FALLBACK_CONFIGS[item.slug],
    );
  }
}
