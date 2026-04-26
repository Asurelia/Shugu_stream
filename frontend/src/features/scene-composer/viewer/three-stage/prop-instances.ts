/**
 * prop-instances — instanciation d'objets 3D depuis les métadonnées du catalogue.
 *
 * Responsabilité unique : créer et disposer des Object3D representant des props
 * droppés dans la scène. Fonction pure, testable en isolation.
 *
 * MVP E5.3 : les props sont représentés par des BoxGeometry colorées (placeholder
 * visuel). Le chargement glTF réel via GLTFLoader est prévu pour E5.4+ une fois
 * que les assets `props_3d` auront des fichiers `.glb` dans le catalogue serveur.
 *
 * Convention des noms Three.js : chaque prop reçoit le nom de son `instanceId`
 * avec le préfixe `__prop_` pour être identifiable dans le raycaster et la scène
 * (`userData.instanceId` est aussi posé pour la sélection rapide sans string split).
 *
 * Dispose pattern (Phase F lesson M2) : `disposePropInstance` traverse l'Object3D
 * et dispose explicitement geometry + materials + textures pour libérer la VRAM.
 *
 * @module three-stage/prop-instances
 */

import * as THREE from "three";
import type { Prop3DEntry } from "../../api/catalogClient";

// ─── Types ────────────────────────────────────────────────────────────────────

/**
 * Alias de `Prop3DEntry` — utilisé dans ce module pour la clarté sémantique.
 *
 * @see catalogClient.Prop3DEntry
 */
export type PropAsset = Prop3DEntry;

/** Options de création d'un prop. */
export interface CreatePropOptions {
  /**
   * Rotation initiale en radians (Euler XYZ).
   * Défaut : [0, 0, 0].
   */
  initialRotation?: THREE.Euler;
  /**
   * Scale initial.
   * Défaut : [1, 1, 1].
   */
  initialScale?: THREE.Vector3;
}

// ─── Constantes ───────────────────────────────────────────────────────────────

/** Dimensions de la BoxGeometry placeholder (env. taille d'un objet de scène type). */
const PLACEHOLDER_SIZE = { width: 0.3, height: 0.3, depth: 0.3 };

/**
 * Palette de couleurs pour les props placeholder — distinguer visuellement les types.
 * Hash simple du slug → index dans la palette.
 */
const PROP_COLORS = [
  0x7766cc, // violet Shugu
  0x44aacc, // bleu clair
  0xcc7744, // orange
  0x44cc77, // vert
  0xcc4466, // rose
  0x88ccaa, // vert pâle
  0xccaa44, // jaune
  0x6688cc, // bleu violet
];

// ─── Helpers ─────────────────────────────────────────────────────────────────

/**
 * Hash simple d'une chaîne → index entier dans [0, mod).
 * Utilisé pour assigner une couleur déterministe par slug d'asset.
 */
function hashStringToIndex(str: string, mod: number): number {
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    hash = (hash * 31 + str.charCodeAt(i)) | 0;
  }
  return Math.abs(hash) % mod;
}

// ─── Implémentation ────────────────────────────────────────────────────────────

/**
 * Instancie un Object3D depuis les métadonnées d'un asset prop.
 *
 * MVP E5.3 : BoxGeometry colorée avec `MeshStandardMaterial` semi-transparent
 * pour donner une indication visuelle du placement. Phase E5.4+ remplacera
 * cette implémentation par un chargement glTF réel.
 *
 * Nommage Three.js :
 *   - `object.name = "__prop_${instanceId}"`
 *   - `object.userData.instanceId = instanceId`
 *   - `object.userData.assetSlug = asset.slug`
 *   - `object.userData.selectable = true`
 *
 * @param asset      - Métadonnées de l'asset (slug + file).
 * @param position   - Position mondiale initiale (ground plane Y=0 recommandé).
 * @param instanceId - Identifiant unique de l'instance (UUID-like du store).
 * @param options    - Rotation et scale initiaux optionnels.
 * @returns Un `THREE.Mesh` prêt à être ajouté à la scène.
 */
export function createPropInstance(
  asset: PropAsset,
  position: THREE.Vector3,
  instanceId: string,
  options?: CreatePropOptions,
): THREE.Object3D {
  const colorIndex = hashStringToIndex(asset.slug, PROP_COLORS.length);
  const color = PROP_COLORS[colorIndex];

  const geometry = new THREE.BoxGeometry(
    PLACEHOLDER_SIZE.width,
    PLACEHOLDER_SIZE.height,
    PLACEHOLDER_SIZE.depth,
  );

  const material = new THREE.MeshStandardMaterial({
    color,
    roughness: 0.7,
    metalness: 0.1,
    transparent: true,
    opacity: 0.85,
  });

  const mesh = new THREE.Mesh(geometry, material);

  // Nommage et userData pour identification dans le raycaster.
  mesh.name = `__prop_${instanceId}`;
  mesh.userData["instanceId"] = instanceId;
  mesh.userData["assetSlug"] = asset.slug;
  mesh.userData["selectable"] = true;

  // Position initiale.
  mesh.position.copy(position);

  // Rotation initiale (optionnelle).
  if (options?.initialRotation) {
    mesh.rotation.copy(options.initialRotation);
  }

  // Scale initial (optionnel).
  if (options?.initialScale) {
    mesh.scale.copy(options.initialScale);
  }

  return mesh;
}

/**
 * Dispose un Object3D instancié via `createPropInstance`.
 *
 * Traverse l'objet et libère geometry + materials + textures.
 * À appeler AVANT `scene.remove(obj)` n'est pas strict, mais doit
 * être appelé AVANT `renderer.dispose()`.
 *
 * @param obj - L'Object3D à disposer.
 */
export function disposePropInstance(obj: THREE.Object3D): void {
  obj.traverse((child) => {
    const mesh = child as THREE.Mesh;
    if (!mesh.isMesh) return;

    mesh.geometry?.dispose();

    const mats = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
    for (const mat of mats) {
      if (!mat) continue;
      mat.dispose();
      // Dispose les textures pour libérer la VRAM (Phase F lesson M2).
      const m = mat as THREE.MeshStandardMaterial;
      m.map?.dispose();
      m.normalMap?.dispose();
      m.roughnessMap?.dispose();
      m.metalnessMap?.dispose();
      m.emissiveMap?.dispose();
    }
  });
}
