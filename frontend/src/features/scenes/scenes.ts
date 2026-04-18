import * as THREE from "three";

export type SceneName = "just_chatting" | "reading_chat" | "reacting" | "idle_sleepy";

export type SceneConfig = {
  name: SceneName;
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

export const SCENES: Record<SceneName, SceneConfig> = {
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
    avatarRotationY: 0.22,   // ~12° — torso angled toward the chat panel
  },
  reacting: {
    name: "reacting",
    cameraBase: new THREE.Vector3(0, 1.4, 0.78),
    cameraTarget: new THREE.Vector3(0, 1.36, 0),
    fov: 16,
    background: "linear-gradient(135deg, #4C1D5B 0%, #A03469 35%, #FF617F 50%, #A03469 65%, #4C1D5B 100%)",
    idleAnimation: "/animations/idle_excited.fbx",
    avatarPosition: new THREE.Vector3(0, 0, 0.08),  // leaning forward into camera
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

export const DEFAULT_SCENE: SceneName = "just_chatting";

export function isSceneName(value: string): value is SceneName {
  return value in SCENES;
}
