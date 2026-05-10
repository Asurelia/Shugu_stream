/**
 * adminAssetsClient — wrappers fetch pour /api/admin/registry/*.
 *
 * Gated opérateur côté backend (require_operator). Les cookies operator
 * (shugu_access) transitent automatiquement via credentials: "include".
 *
 * Pattern identique à adminUsersClient.ts (AdminError + request helper).
 */

export type RegistryRow = {
  id: string;
  kind: string;
  slug: string;
  display_name: string;
  payload: Record<string, unknown>;
  is_active: boolean;
  created_at: string;
  updated_at: string;
};

export type RegistryList = { items: RegistryRow[] };

export type CreateAssetPayload = {
  kind: string;
  slug: string;
  display_name: string;
  payload: Record<string, unknown>;
};

export class AdminAssetsError extends Error {
  constructor(public status: number, public detail: string) {
    super(`[${status}] ${detail}`);
    this.name = "AdminAssetsError";
  }
}

async function request<T>(path: string, opts: RequestInit = {}): Promise<T> {
  const resp = await fetch(path, {
    credentials: "include",
    headers: { "Content-Type": "application/json", ...(opts.headers ?? {}) },
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
    const detail = (payload && payload.detail) || `HTTP ${resp.status}`;
    throw new AdminAssetsError(resp.status, String(detail));
  }
  return payload as T;
}

export async function listAssets(
  kind: string,
  includeInactive = true,
): Promise<RegistryList> {
  const qs = new URLSearchParams({
    kind,
    include_inactive: String(includeInactive),
  });
  return request<RegistryList>(`/api/admin/registry?${qs.toString()}`);
}

export async function createAsset(data: CreateAssetPayload): Promise<RegistryRow> {
  return request<RegistryRow>("/api/admin/registry", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export async function toggleAsset(id: string, is_active: boolean): Promise<RegistryRow> {
  return request<RegistryRow>(`/api/admin/registry/${id}`, {
    method: "PATCH",
    body: JSON.stringify({ is_active }),
  });
}

export async function deleteAsset(id: string): Promise<void> {
  return request<void>(`/api/admin/registry/${id}`, {
    method: "DELETE",
  });
}
