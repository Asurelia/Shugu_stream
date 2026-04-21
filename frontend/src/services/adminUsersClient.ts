/**
 * adminUsersClient — wrappers fetch pour /api/admin/users/*.
 *
 * Gated opérateur côté backend (require_operator). Les cookies operator
 * (shugu_access) transitent automatiquement via credentials: "include".
 */

export type AdminUser = {
  id: string;
  username: string;
  email: string;
  display_name: string | null;
  email_verified: boolean;
  vip_active: boolean;
  vip_since: string | null;
  vip_until: string | null;
  created_at: string;
  last_seen_at: string | null;
  is_active: boolean;
};

export type AdminUsersList = { total: number; items: AdminUser[] };

export type VIPAction = "grant" | "revoke";

export type ListParams = {
  role?: "all" | "member" | "vip";
  email_verified?: boolean;
  is_active?: boolean;
  limit?: number;
  offset?: number;
};

export class AdminError extends Error {
  constructor(public status: number, public detail: string) {
    super(`[${status}] ${detail}`);
    this.name = "AdminError";
  }
}

async function request<T>(path: string, opts: RequestInit = {}): Promise<T> {
  const resp = await fetch(path, {
    credentials: "include",
    headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
    ...opts,
  });
  const text = await resp.text();
  const payload = text ? (() => {
    try { return JSON.parse(text); } catch { return { detail: text }; }
  })() : {};
  if (!resp.ok) {
    const detail = (payload && payload.detail) || `HTTP ${resp.status}`;
    throw new AdminError(resp.status, String(detail));
  }
  return payload as T;
}

export async function listUsers(params: ListParams = {}): Promise<AdminUsersList> {
  const qs = new URLSearchParams();
  if (params.role !== undefined) qs.set("role", params.role);
  if (params.email_verified !== undefined) qs.set("email_verified", String(params.email_verified));
  if (params.is_active !== undefined) qs.set("is_active", String(params.is_active));
  if (params.limit !== undefined) qs.set("limit", String(params.limit));
  if (params.offset !== undefined) qs.set("offset", String(params.offset));
  const q = qs.toString();
  return request<AdminUsersList>(`/api/admin/users${q ? `?${q}` : ""}`);
}

export async function setVIP(
  user_id: string,
  action: VIPAction,
  duration_days?: number,
): Promise<AdminUser> {
  return request<AdminUser>(`/api/admin/users/${user_id}/vip`, {
    method: "POST",
    body: JSON.stringify({ action, ...(duration_days !== undefined ? { duration_days } : {}) }),
  });
}

export async function deactivateUser(user_id: string, reason?: string): Promise<AdminUser> {
  return request<AdminUser>(`/api/admin/users/${user_id}/deactivate`, {
    method: "POST",
    body: JSON.stringify({ reason: reason ?? null }),
  });
}
