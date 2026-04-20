/**
 * VRMA/FBX clip paths for one-shot actions.
 *
 * **Phase POC** : la liste est maintenant chargée depuis le backend
 * (`GET /api/registry/gesture`) au premier appel, avec un cache mémoire
 * 30 s. Si le fetch échoue ou retourne vide, on retombe sur le fallback
 * statique `FALLBACK_CLIPS` — ça évite que le stream casse si la DB est
 * indisponible.
 *
 * Conversion pipeline Mixamo FBX → VRMA :
 *   1. Download FBX from Mixamo
 *   2. `frontend/public/animations/<slug>.fbx`
 *   3. POST /api/admin/registry { kind: "gesture", slug, display_name,
 *      payload: { url: "/animations/<slug>.fbx", source: "fbx" } }
 *   4. Hermes le voit au prochain appel LLM (sans redéploiement)
 *
 * Appeler `invalidateActionClipsCache()` après une mutation admin pour
 * forcer un refresh immédiat (sinon TTL 30 s).
 */

// ─── Fallback statique (zéro régression si /api/registry indisponible) ───
const FALLBACK_CLIPS: Record<string, string> = {
  wave: "/animations/wave.fbx",
  nod: "/animations/nod.fbx",
  shake_head: "/animations/shake_head.fbx",
  think: "/animations/think.fbx",
  laugh: "/animations/laugh.fbx",
  shrug: "/animations/shrug.fbx",
  point: "/animations/point.fbx",
  bow: "/animations/bow.fbx",
  clap: "/animations/clap.fbx",
  peace: "/animations/peace.fbx",
  heart: "/animations/heart_pose.fbx",
  peek: "/animations/peek.fbx",
  stretch: "/animations/stretch.fbx",
  dance_light: "/animations/dance_light.fbx",
  idle_variant: "/animations/idle_variant.fbx",
};

// Exposé pour la rétrocompat : certains call sites read ACTION_CLIPS
// directement. Il reflète le snapshot cache courant + fallback.
export let ACTION_CLIPS: Record<string, string> = { ...FALLBACK_CLIPS };

export type ActionName = string;

export function isActionName(name: string): boolean {
  return name in ACTION_CLIPS;
}

// ─── Cache + fetch registry ────────────────────────────────────────────

const CACHE_TTL_MS = 30_000;
let _cacheAt = 0;
let _inflight: Promise<Record<string, string>> | null = null;

type RegistryItem = {
  id: string;
  kind: string;
  slug: string;
  display_name: string;
  payload: { url?: string; source?: string; duration_ms?: number };
  is_active: boolean;
};

/**
 * Retourne la liste à jour des clips (merge registry + fallback).
 * Cache 30 s en mémoire — les call sites peuvent appeler librement.
 */
export async function getActionClips(): Promise<Record<string, string>> {
  const now = Date.now();
  if (now - _cacheAt < CACHE_TTL_MS) return ACTION_CLIPS;
  if (_inflight) return _inflight;

  _inflight = (async () => {
    try {
      const res = await fetch("/api/registry/gesture", { credentials: "include" });
      if (!res.ok) throw new Error(`registry fetch ${res.status}`);
      const data = (await res.json()) as { items: RegistryItem[] };
      const clips: Record<string, string> = { ...FALLBACK_CLIPS };
      for (const item of data.items) {
        if (item.payload?.url) clips[item.slug] = item.payload.url;
      }
      ACTION_CLIPS = clips;
      _cacheAt = now;
      return clips;
    } catch (err) {
      console.warn("[animationPack] registry fetch failed, using fallback:", err);
      _cacheAt = now;
      return ACTION_CLIPS;
    } finally {
      _inflight = null;
    }
  })();
  return _inflight;
}

/**
 * Force un rechargement au prochain getActionClips(). À appeler depuis les
 * routes admin (après un POST /api/admin/registry) ou au reçu d'un event
 * `registry.invalidated` sur le WS stage.
 */
export function invalidateActionClipsCache(): void {
  _cacheAt = 0;
}
