/**
 * Registry client — fetch les items `asset_registry` actifs par kind.
 *
 * Utilisé par les features frontend (scenes, animations, emotes, etc.) pour
 * charger dynamiquement leur vocabulaire au boot et se rafraîchir sur le
 * message WS `registry.invalidated`.
 *
 * Cache par kind avec TTL 30 s + dedup inflight.
 */

export type RegistryItem = {
  id: string;
  kind: string;
  slug: string;
  display_name: string;
  payload: Record<string, unknown>;
  is_active: boolean;
};

const CACHE_TTL_MS = 30_000;

type KindCache = {
  at: number;
  items: RegistryItem[];
};

const _caches = new Map<string, KindCache>();
const _inflight = new Map<string, Promise<RegistryItem[]>>();

/**
 * Retourne les items actifs du kind. Cache 30 s. Dedup inflight.
 */
export async function getItems(kind: string): Promise<RegistryItem[]> {
  const now = Date.now();
  const cached = _caches.get(kind);
  if (cached && now - cached.at < CACHE_TTL_MS) return cached.items;
  const existing = _inflight.get(kind);
  if (existing) return existing;

  const p = (async () => {
    try {
      const res = await fetch(`/api/registry/${encodeURIComponent(kind)}`, { credentials: "include" });
      if (!res.ok) throw new Error(`registry fetch ${kind}: ${res.status}`);
      const data = (await res.json()) as { items: RegistryItem[] };
      _caches.set(kind, { at: now, items: data.items });
      return data.items;
    } catch (err) {
      // String constante pour éviter tout format-specifier injection via
      // `kind` (semgrep CWE-134). `kind` + `err` passés comme args séparés.
      console.warn("[registryClient] fetch failed", kind, err);
      // Conserve l'ancien cache si disponible, sinon tableau vide.
      return cached?.items ?? [];
    } finally {
      _inflight.delete(kind);
    }
  })();
  _inflight.set(kind, p);
  return p;
}

/**
 * Retourne l'item actif correspondant à (kind, slug) ou undefined.
 */
export async function getItem(kind: string, slug: string): Promise<RegistryItem | undefined> {
  const items = await getItems(kind);
  return items.find((i) => i.slug === slug);
}

/**
 * Flush le cache pour un kind (ou tous). Le prochain getItems/getItem
 * refetchera. À appeler sur `registry.invalidated` WS event ou après un
 * POST/PATCH/DELETE admin depuis le frontend.
 */
export function invalidate(kind?: string): void {
  if (kind) _caches.delete(kind);
  else _caches.clear();
}
