/**
 * catalogClient — GET /api/assets/catalog (Phase E5.1).
 *
 * Retourne le catalogue unifié des assets disponibles (VRM, outfits, VRMA,
 * VFX, scenes, props 3D, whitelist faces/camera_modes). Cache 60s côté
 * serveur — le frontend n'a pas besoin de cacher côté client.
 *
 * Pattern : `request<T>` helper identique à `scenesClient.ts`.
 *
 * @module api/catalogClient
 */

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

// ─── Erreur client ────────────────────────────────────────────────────────────

export class CatalogClientError extends Error {
  constructor(
    public status: number,
    public detail: string,
  ) {
    super(`[${status}] ${detail}`);
    this.name = "CatalogClientError";
  }
}

// ─── Helper fetch ─────────────────────────────────────────────────────────────

async function request<T>(path: string, opts: RequestInit = {}): Promise<T> {
  const resp = await fetch(path, {
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(opts.headers ?? {}),
    },
    ...opts,
  });

  const text = await resp.text();
  const payload = text
    ? (() => {
        try {
          return JSON.parse(text);
        } catch {
          return { detail: text };
        }
      })()
    : {};

  if (!resp.ok) {
    const detail =
      (payload as { detail?: string })?.detail ?? `HTTP ${resp.status}`;
    throw new CatalogClientError(resp.status, String(detail));
  }

  return payload as T;
}

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
