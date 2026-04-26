/**
 * loadVrm — chargement async d'un avatar VRM dans la scène.
 *
 * Responsabilité unique : charger un fichier `.vrm` via GLTFLoader +
 * VRMLoaderPlugin, normaliser la racine VRM, et gérer l'annulation
 * si le composant est démonté avant la fin du chargement.
 *
 * Porté depuis `StreamStage.tsx (Figma_mini)` lignes 482-583 :
 * - `loadVrmIntoRig` → `loadVrm`
 * - `normalizeVrmRoot` → inlinée (trop petite pour un fichier séparé)
 * - `cacheVrmBones` / `cacheTintableMaterials` → supprimées (Scene Composer
 *   E5.2 n'a pas de gizmos ni de tint outfit — ces features sont E5.3).
 * - `unloadVrm` → dans `dispose.ts`
 *
 * Pattern d'annulation : le caller crée un objet `{ cancelled: false }` et
 * le passe en argument. Si `cancelled` est true quand le loader résout,
 * le VRM est immédiatement libéré sans être ajouté à la scène.
 *
 * @module three-stage/loadVrm
 */

import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader";
import { VRMLoaderPlugin } from "@pixiv/three-vrm";
import type { VRM } from "@pixiv/three-vrm";

// ─── Types ────────────────────────────────────────────────────────────────────

/** Token d'annulation partagé entre l'appelant et le callback du loader. */
export interface CancelToken {
  cancelled: boolean;
}

// ─── Singleton loader ─────────────────────────────────────────────────────────

// Un loader partagé par module (pattern Figma_mini) — évite de recréer
// l'objet à chaque appel et partage le cache interne de GLTFLoader.
const _loader = new GLTFLoader();
_loader.register((parser) => new VRMLoaderPlugin(parser));

// ─── Helpers ─────────────────────────────────────────────────────────────────

/**
 * Normalise la racine du VRM pour le centrer à Y=0 (plancher).
 * Le VRM spec v0 peut exporter avec un offset vertical non-nul.
 *
 * @param vrm - Le VRM chargé à normaliser.
 */
function normalizeVrmRoot(vrm: VRM): void {
  const root = vrm.scene;
  // Recalcule la bounding box du VRM pour trouver la base réelle.
  const box = new THREE.Box3().setFromObject(root);
  const minY = box.min.y;
  if (Math.abs(minY) > 0.001) {
    root.position.y -= minY;
  }
}

// ─── Implémentation ────────────────────────────────────────────────────────────

/**
 * Charge un avatar VRM depuis `url` et l'ajoute à `scene`.
 *
 * @param url    - URL relative du fichier VRM (ex: `/assets/vrm/shugu.vrm`).
 * @param scene  - La scène Three.js dans laquelle ajouter le VRM.
 * @param token  - Token d'annulation. Poser `token.cancelled = true` avant
 *                 la résolution pour que le VRM soit libéré sans mount.
 * @returns La référence VRM montée, ou `null` si chargement annulé.
 */
export async function loadVrm(
  url: string,
  scene: THREE.Scene,
  token: CancelToken,
): Promise<VRM | null> {
  // Bypass en environnement E2E / test — le fichier 28 MB n'est jamais
  // téléchargé dans jsdom ni Playwright.
  if (!url || process.env.NEXT_PUBLIC_E2E === "1") {
    return null;
  }

  let gltf: Awaited<ReturnType<GLTFLoader["loadAsync"]>>;
  try {
    gltf = await _loader.loadAsync(url);
  } catch (err) {
    if (token.cancelled) return null;
    throw err;
  }

  if (token.cancelled) {
    // Libérer le VRM s'il a été chargé mais que le composant est démonté.
    const vrm: VRM | undefined = gltf.userData?.vrm;
    if (vrm) {
      scene.remove(vrm.scene);
      vrm.scene.traverse((obj) => {
        if ((obj as THREE.Mesh).isMesh) {
          const mesh = obj as THREE.Mesh;
          mesh.geometry?.dispose();
          if (Array.isArray(mesh.material)) {
            mesh.material.forEach((m) => m.dispose());
          } else {
            mesh.material?.dispose();
          }
        }
      });
    }
    return null;
  }

  const vrm: VRM = gltf.userData.vrm;
  if (!vrm) {
    console.warn("[loadVrm] Fichier GLTF chargé mais userData.vrm absent — url:", url);
    return null;
  }

  normalizeVrmRoot(vrm);

  // Retourner le miroir (avatar VRM orienté vers la caméra par défaut).
  vrm.scene.rotation.y = Math.PI;

  scene.add(vrm.scene);
  return vrm;
}
