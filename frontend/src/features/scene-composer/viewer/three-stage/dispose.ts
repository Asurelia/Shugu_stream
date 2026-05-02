/**
 * dispose — nettoyage complet du rig Three.js au unmount.
 *
 * Responsabilité unique : libérer toutes les ressources GPU/CPU créées par
 * les autres modules three-stage (renderer, scene, camera, vrm, controls).
 *
 * Porté depuis `StreamStage.tsx (Figma_mini)` lignes 613-626 (`disposeRig` +
 * `disposeObject`). Adapté pour le Scene Composer (pas de gizmo TransformControls
 * en E5.2 — ajouté E5.3).
 *
 * Contrat : appeler `disposeAll` UNE seule fois au unmount React. Après
 * l'appel, toutes les refs pointent vers des objets libérés — ne pas les
 * réutiliser.
 *
 * @module three-stage/dispose
 */

import * as THREE from "three";
import type { VRM } from "@pixiv/three-vrm";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import type { HelperSet } from "./helpers";
import type { AnimationRig } from "./animations";

// ─── Types ────────────────────────────────────────────────────────────────────

/** Arguments passés à `disposeAll` — tous les champs sont optionnels car
 *  certains peuvent ne pas avoir été créés (ex: VRM pas encore chargé). */
export interface DisposeArgs {
  renderer?: THREE.WebGLRenderer | null;
  scene?: THREE.Scene | null;
  floor?: THREE.Mesh | null;
  controls?: OrbitControls | null;
  vrm?: VRM | null;
  helpers?: HelperSet | null;
  animRig?: AnimationRig | null;
}

// ─── Helpers internes ─────────────────────────────────────────────────────────

/**
 * Traverse un `Object3D` et dispose la geometry + les materials de chaque Mesh.
 * Pattern identique à `disposeObject` dans Figma_mini.
 */
function disposeObject(obj: THREE.Object3D): void {
  obj.traverse((child) => {
    const mesh = child as THREE.Mesh;
    if (!mesh.isMesh) return;

    mesh.geometry?.dispose();

    if (Array.isArray(mesh.material)) {
      mesh.material.forEach((m) => {
        disposeMaterial(m);
      });
    } else if (mesh.material) {
      disposeMaterial(mesh.material);
    }
  });
}

/** Dispose un material et ses textures éventuelles. */
function disposeMaterial(mat: THREE.Material): void {
  mat.dispose();
  // Dispose les textures pour libérer la VRAM.
  const m = mat as THREE.MeshStandardMaterial;
  m.map?.dispose();
  m.normalMap?.dispose();
  m.roughnessMap?.dispose();
  m.metalnessMap?.dispose();
  m.emissiveMap?.dispose();
}

// ─── Implémentation ────────────────────────────────────────────────────────────

/**
 * Libère toutes les ressources Three.js du Scene Composer.
 *
 * Ordre : animation → VRM → helpers → sol → controls → renderer.
 * (Du plus dépendant au moins dépendant pour éviter les accès à des objets
 * déjà libérés.)
 */
export function disposeAll({
  renderer,
  scene,
  floor,
  controls,
  vrm,
  helpers,
  animRig,
}: DisposeArgs): void {
  // 1. Animation — stopper avant de détruire le VRM.
  animRig?.stop();

  // 2. VRM — traverser et disposer tous les meshes.
  if (vrm) {
    scene?.remove(vrm.scene);
    disposeObject(vrm.scene);
  }

  // 3. Helpers (Grid + Axes) — chaque helper a geometry + material à libérer.
  if (helpers && scene) {
    helpers.dispose(scene);
  }

  // 4. Sol.
  if (floor && scene) {
    scene.remove(floor);
    floor.geometry.dispose();
    if (Array.isArray(floor.material)) {
      floor.material.forEach((m) => m.dispose());
    } else {
      (floor.material as THREE.Material)?.dispose();
    }
  }

  // 5. OrbitControls — retire les event listeners DOM.
  controls?.dispose();

  // 6. Renderer — libère le contexte WebGL.
  renderer?.dispose();
}
