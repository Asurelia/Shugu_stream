/**
 * createCamera — PerspectiveCamera + OrbitControls + presets de vue.
 *
 * Responsabilité unique : créer et configurer la caméra de l'éditeur 3D avec
 * ses OrbitControls. Fournit des presets nommés (free/front/side/top) pour
 * les boutons de vue rapide du SceneComposer.
 *
 * Upgrade vs Figma_mini : on remplace le lerp caméra manuel de StreamStage
 * par OrbitControls standard — plus ergonomique et cohérent avec
 * SceneEditorViewer (legacy).
 *
 * @module three-stage/createCamera
 */

import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";

// ─── Types ────────────────────────────────────────────────────────────────────

/** Identifiants des presets de caméra disponibles dans le Scene Composer. */
export type CameraPreset = "free" | "front" | "side" | "top";

/** Rig caméra retourné par `createCamera`. */
export interface CameraRig {
  camera: THREE.PerspectiveCamera;
  controls: OrbitControls;
  /** Applique un preset nommé (réinitialise position + target). */
  applyPreset: (preset: CameraPreset) => void;
}

// ─── Presets ─────────────────────────────────────────────────────────────────

/** Configuration positionnelle pour chaque preset de caméra. */
interface PresetConfig {
  position: THREE.Vector3;
  target: THREE.Vector3;
}

const PRESETS: Record<CameraPreset, PresetConfig> = {
  free: {
    position: new THREE.Vector3(0, 1.5, 3),
    target: new THREE.Vector3(0, 1.2, 0),
  },
  front: {
    position: new THREE.Vector3(0, 1.2, 2.5),
    target: new THREE.Vector3(0, 1.2, 0),
  },
  side: {
    position: new THREE.Vector3(2.5, 1.2, 0),
    target: new THREE.Vector3(0, 1.2, 0),
  },
  top: {
    position: new THREE.Vector3(0, 4, 0.001),
    target: new THREE.Vector3(0, 0, 0),
  },
};

// ─── Implémentation ────────────────────────────────────────────────────────────

/**
 * Construit un `CameraRig` avec OrbitControls attaché au `domElement`.
 *
 * @param domElement - Le canvas du renderer (pour les events souris OrbitControls).
 * @param aspect     - Ratio largeur/hauteur initial.
 * @param preset     - Preset de vue initial (défaut : "free").
 * @returns Un `CameraRig` prêt à être utilisé dans la boucle RAF.
 */
export function createCamera(
  domElement: HTMLCanvasElement,
  aspect: number,
  preset: CameraPreset = "free",
): CameraRig {
  // FOV 36° — identique à StreamStage Figma_mini, adapté pour les sujets VTuber
  // (moins de distorsion grand-angle, portrait naturel).
  const camera = new THREE.PerspectiveCamera(36, aspect, 0.1, 100);

  const controls = new OrbitControls(camera, domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;
  controls.minDistance = 0.5;
  controls.maxDistance = 15;
  controls.maxPolarAngle = Math.PI * 0.9;

  function applyPreset(p: CameraPreset): void {
    const cfg = PRESETS[p];
    camera.position.copy(cfg.position);
    controls.target.copy(cfg.target);
    controls.update();
  }

  // Appliquer le preset initial.
  applyPreset(preset);

  return { camera, controls, applyPreset };
}
