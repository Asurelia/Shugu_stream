/**
 * helpers — GridHelper + AxesHelper avec dispose explicite.
 *
 * Responsabilité unique : créer les helpers visuels de l'éditeur (grille,
 * axes) et fournir une fonction `disposeHelpers` qui libère correctement
 * `.geometry` et `.material` de chaque helper.
 *
 * Leçon Phase F : `scene.remove(helper)` seul NE libère PAS la mémoire GPU.
 * Il faut appeler explicitement `helper.geometry.dispose()` et
 * `helper.material.dispose()` (ou parcourir un tableau de materials). Ce
 * module centralise ce pattern pour éviter les leaks dans le Composer.
 *
 * @module three-stage/helpers
 */

import * as THREE from "three";

// ─── Types ────────────────────────────────────────────────────────────────────

/** Ensemble des helpers visuels créés pour la scène d'édition. */
export interface HelperSet {
  grid: THREE.GridHelper;
  axes: THREE.AxesHelper;
  /** Libère geometry + material de tous les helpers et les retire de la scène. */
  dispose: (scene: THREE.Scene) => void;
}

// ─── Implémentation ────────────────────────────────────────────────────────────

/**
 * Crée et ajoute GridHelper + AxesHelper à la scène.
 *
 * @param scene  - La scène Three.js dans laquelle ajouter les helpers.
 * @returns Un `HelperSet` incluant les helpers et leur fonction dispose.
 */
export function createHelpers(scene: THREE.Scene): HelperSet {
  // Grille 6×6m, divisions de 0.5m — cohérent avec la taille du sol circulaire.
  const grid = new THREE.GridHelper(6, 12, 0x333344, 0x222233);
  scene.add(grid);

  // Axes XYZ (rouge/vert/bleu) de 0.5m — repère d'orientation minimal.
  const axes = new THREE.AxesHelper(0.5);
  scene.add(axes);

  function dispose(s: THREE.Scene): void {
    // GridHelper ───────────────────────────────────────────────────────────
    s.remove(grid);
    grid.geometry.dispose();
    // material peut être un scalaire ou un tableau selon Three.js version.
    if (Array.isArray(grid.material)) {
      grid.material.forEach((m) => m.dispose());
    } else {
      grid.material.dispose();
    }

    // AxesHelper ──────────────────────────────────────────────────────────
    s.remove(axes);
    axes.geometry.dispose();
    if (Array.isArray(axes.material)) {
      axes.material.forEach((m) => m.dispose());
    } else {
      axes.material.dispose();
    }
  }

  return { grid, axes, dispose };
}
