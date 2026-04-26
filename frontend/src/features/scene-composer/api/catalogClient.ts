/**
 * catalogClient — GET /api/assets/catalog (Phase E5.1).
 *
 * Retourne le catalogue unifié des assets disponibles (VRM, outfits, VRMA,
 * VFX, scenes, props 3D, whitelist faces/camera_modes). Cache 60s côté
 * serveur — le frontend n'a pas besoin de cacher côté client.
 *
 * Pattern fetch : module partagé `httpClient.ts` (mêmes garanties que
 * `scenesClient` : credentials cookies, redirect 401 → /login, HttpError
 * unifiée). Plus de logique fetch dupliquée ici.
 *
 * @module api/catalogClient
 */

import { HttpError, request } from "./httpClient";

// Re-export pour ne pas casser les imports existants côté call-sites.
export { HttpError } from "./httpClient";

// ─── Types miroirs (AssetCatalogOut) ─────────────────────────────────────────
// (miroirs de `backend/shugu/domain/assets_catalog_schemas.py`)

export interface VrmAvatarEntry {
  slug: string;
  file: string;
  sidecars: string[];
}

export interface OutfitEntry {
  slug: string;
  file: string;
  display_name: string | null;
}

export interface VrmaAnimationEntry {
  slug: string;
  file: string;
  duration_ms: number | null;
  loop: boolean;
}

export interface VfxEntry {
  slug: string;
  file: string;
}

export interface SceneEntry {
  slug: string;
  file: string;
}

export interface Prop3DEntry {
  slug: string;
  file: string;
}

export interface AssetCatalogOut {
  vrm_avatars: VrmAvatarEntry[];
  outfits: OutfitEntry[];
  vrma_animations: VrmaAnimationEntry[];
  vfx: VfxEntry[];
  scenes: SceneEntry[];
  props_3d: Prop3DEntry[];
  faces: string[];
  camera_modes: string[];
  cached_at: string;
}

// ─── Compat — alias historique de HttpError ──────────────────────────────────

/**
 * @deprecated Utiliser `HttpError` (depuis `./httpClient`).
 *
 * Conservé comme alias pour compat des call-sites existants. `instanceof`
 * checks continuent de fonctionner car `CatalogClientError === HttpError`.
 */
export const CatalogClientError = HttpError;
/** @deprecated Utiliser `HttpError` (depuis `./httpClient`). */
export type CatalogClientError = HttpError;

// ─── API ─────────────────────────────────────────────────────────────────────

/**
 * Récupère le catalogue unifié des assets.
 *
 * Cache 60s côté serveur — appeler au boot du Scene Composer puis à la demande
 * (bouton "Rafraîchir" dans AssetCataloguePanel).
 */
export async function getAssetCatalog(): Promise<AssetCatalogOut> {
  return request<AssetCatalogOut>("/api/assets/catalog");
}
