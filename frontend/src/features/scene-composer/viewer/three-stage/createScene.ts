/**
 * createScene — initialise le triplet WebGLRenderer + Scene + éclairage.
 *
 * Responsabilité unique : construire et retourner les objets Three.js de base
 * (renderer, scene, floor) avec un éclairage minimal prêt-à-l'emploi.
 * Aucun React, aucun état global — fonction pure déterministe.
 *
 * Porté depuis `StreamStage.tsx (Figma_mini)` lignes 272-340 — adaptation
 * Scene Composer : on retire les overlays StreamHud/ShotDeck, on conserve le
 * rendu WebGL, les lights et le sol.
 *
 * @module three-stage/createScene
 */

import * as THREE from "three";

// ─── Types ────────────────────────────────────────────────────────────────────

/** Rig Three.js minimal retourné par `createScene`. */
export interface SceneRig {
  renderer: THREE.WebGLRenderer;
  scene: THREE.Scene;
  /** Mesh du sol circulaire (utile pour le dispose). */
  floor: THREE.Mesh;
}

// ─── Constantes de la scène ───────────────────────────────────────────────────

/** Couleur de fond de la scène (noir profond de la charte Shugu). */
const BG_COLOR = 0x05050a;
/** Intensité de la lumière ambiante — suffisamment douce pour ne pas écraser le VRM. */
const AMBIENT_INTENSITY = 0.6;
/** Intensité de la lumière directionnelle principale (key light). */
const DIRECTIONAL_INTENSITY = 1.2;

// ─── Implémentation ────────────────────────────────────────────────────────────

/**
 * Construit un `SceneRig` (renderer + scene + éclairage + sol).
 *
 * @param canvas - L'élément `<canvas>` DOM sur lequel attacher le renderer.
 * @param width  - Largeur initiale du renderer en pixels.
 * @param height - Hauteur initiale du renderer en pixels.
 * @returns Un `SceneRig` prêt à recevoir une caméra et des objets 3D.
 */
export function createScene(
  canvas: HTMLCanvasElement,
  width: number,
  height: number,
): SceneRig {
  // ── Renderer ──────────────────────────────────────────────────────────────
  // `antialias: false` pour les perf streaming ; le VRM reste lisible.
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: false });
  renderer.setSize(width, height);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  // Three.js r152+ : `outputEncoding` removed in favor of `outputColorSpace`.
  // We use the `THREE.SRGBColorSpace` constant which renders the same gamma
  // correction as the legacy `THREE.sRGBEncoding` (3001) did pre-r152.
  renderer.outputColorSpace = THREE.SRGBColorSpace;

  // ── Scene ─────────────────────────────────────────────────────────────────
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(BG_COLOR);

  // ── Éclairage ─────────────────────────────────────────────────────────────
  // Ambient : lumière douce omnidirectionnelle (réduit les ombres trop dures).
  const ambient = new THREE.AmbientLight(0xffffff, AMBIENT_INTENSITY);
  scene.add(ambient);

  // Key light : lumière directionnelle principale (front-top-left).
  const dirLight = new THREE.DirectionalLight(0xffffff, DIRECTIONAL_INTENSITY);
  dirLight.position.set(2, 4, 3);
  scene.add(dirLight);

  // Fill light : lumière d'ambiance froide côté droit (caractéristique VTuber).
  const fillLight = new THREE.PointLight(0x6699ff, 0.5, 8);
  fillLight.position.set(-3, 2, -1);
  scene.add(fillLight);

  // ── Sol ───────────────────────────────────────────────────────────────────
  // Disque circulaire fin — repère visuel de la position du sol.
  const floorGeo = new THREE.CircleGeometry(3, 32);
  const floorMat = new THREE.MeshStandardMaterial({
    color: 0x111118,
    roughness: 0.9,
    metalness: 0.1,
  });
  const floor = new THREE.Mesh(floorGeo, floorMat);
  floor.rotation.x = -Math.PI / 2;
  floor.position.y = 0;
  scene.add(floor);

  return { renderer, scene, floor };
}
