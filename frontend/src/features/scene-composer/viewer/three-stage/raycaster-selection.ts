/**
 * raycaster-selection — sélection click-to-pick de meshes dans la scène.
 *
 * Responsabilité unique : gérer le raycasting sur `pointerdown` pour
 * identifier le mesh sélectionné dans la scène. Le listener est attaché
 * au `domElement` du renderer et doit être nettoyé via `dispose()`.
 *
 * Filtrage des objets non-sélectionnables :
 *   - Helpers Three.js (GridHelper, AxesHelper, CameraHelper) — prefixe de nom configurable
 *   - Objets marqués `userData.selectable === false`
 *   - Le sol/fond (non-interactif)
 *
 * @module three-stage/raycaster-selection
 */

import * as THREE from "three";

// ─── Types ────────────────────────────────────────────────────────────────────

/** Options de configuration du raycaster de sélection. */
export interface RaycasterSelectionOptions {
  /**
   * Préfixes de noms d'objets à ignorer lors du raycast.
   *
   * Défaut : `["__helper_", "__gizmo_", "__floor_"]` pour filtrer les
   * helpers internes du Scene Composer.
   */
  ignoreNamePrefixes?: string[];
  /**
   * Noms d'objets exacts à ignorer (en plus des préfixes).
   * Utile pour exclure le sol circulaire ou le VRM avatar.
   */
  ignoreNames?: string[];
}

/** Handle retourné par `setupRaycasterSelection`. */
export interface RaycasterSelectionHandle {
  /**
   * Libère le listener pointerdown attaché au domElement.
   *
   * À appeler au unmount React avant de disposer le renderer.
   */
  dispose: () => void;
}

// ─── Constantes ───────────────────────────────────────────────────────────────

/** Préfixes de noms d'objets ignorés par défaut (helpers internes). */
const DEFAULT_IGNORE_PREFIXES = ["__helper_", "__gizmo_", "__floor_"];

// ─── Helpers ─────────────────────────────────────────────────────────────────

/**
 * Vérifie si un Object3D doit être ignoré lors du raycast.
 *
 * Critères d'exclusion :
 *   - `userData.selectable === false`
 *   - Nom commençant par un préfixe ignoré
 *   - Nom exact dans la liste des noms ignorés
 */
function isIgnored(
  obj: THREE.Object3D,
  ignorePrefixes: string[],
  ignoreNames: string[],
): boolean {
  if (obj.userData["selectable"] === false) return true;
  if (ignoreNames.includes(obj.name)) return true;
  return ignorePrefixes.some((prefix) => obj.name.startsWith(prefix));
}

// ─── Implémentation ────────────────────────────────────────────────────────────

/**
 * Attache un listener `pointerdown` sur `domElement` pour sélectionner
 * les meshes intersectés par un ray depuis la caméra.
 *
 * Le callback `onSelect` reçoit :
 *   - `Object3D` : le mesh cliqué (son Object3D racine dans la scène)
 *   - `null` : clic dans le vide (désélection)
 *
 * Pour déterminer la racine de l'objet (utile quand l'objet est un enfant
 * d'un groupe prop), on remonte les parents jusqu'à trouver celui dont le
 * parent direct est la scène (`object.parent === scene`).
 *
 * @param scene      - Scène Three.js contenant les objets intersectables.
 * @param camera     - Caméra active pour calculer les coordonnées du ray.
 * @param domElement - Canvas du renderer (cible du listener pointerdown).
 * @param onSelect   - Callback appelé avec le mesh sélectionné ou null.
 * @param options    - Filtres d'objets à ignorer.
 * @returns Handle avec `dispose()` pour retirer le listener.
 */
export function setupRaycasterSelection(
  scene: THREE.Scene,
  camera: THREE.PerspectiveCamera,
  domElement: HTMLElement,
  onSelect: (mesh: THREE.Object3D | null) => void,
  options?: RaycasterSelectionOptions,
): RaycasterSelectionHandle {
  const ignorePrefixes = options?.ignoreNamePrefixes ?? DEFAULT_IGNORE_PREFIXES;
  const ignoreNames = options?.ignoreNames ?? [];

  const raycaster = new THREE.Raycaster();
  const pointer = new THREE.Vector2();

  const onPointerDown = (event: PointerEvent) => {
    // Calcule les coordonnées normalisées (-1 à 1) dans le canvas.
    const rect = domElement.getBoundingClientRect();
    pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;

    raycaster.setFromCamera(pointer, camera);

    // Intersecte tous les descendants de la scène.
    const intersects = raycaster.intersectObjects(scene.children, true);

    // Filtre : on prend le premier intersect dont l'objet n'est pas ignoré.
    for (const intersect of intersects) {
      let obj: THREE.Object3D = intersect.object;

      // Vérification de l'objet lui-même et de ses parents directs.
      if (isIgnored(obj, ignorePrefixes, ignoreNames)) continue;

      // Remonte jusqu'à la racine dans la scène pour sélectionner l'entité
      // complète (ex: tout un groupe prop, pas juste un sous-mesh).
      while (obj.parent && obj.parent !== scene) {
        obj = obj.parent;
      }

      // Vérifie aussi la racine trouvée.
      if (isIgnored(obj, ignorePrefixes, ignoreNames)) continue;

      onSelect(obj);
      return;
    }

    // Aucun mesh valide → désélection.
    onSelect(null);
  };

  domElement.addEventListener("pointerdown", onPointerDown);

  return {
    dispose(): void {
      domElement.removeEventListener("pointerdown", onPointerDown);
    },
  };
}
