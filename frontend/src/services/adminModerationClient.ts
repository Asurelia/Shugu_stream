/**
 * adminModerationClient — wrappers fetch pour /api/admin/moderation/*.
 *
 * Gated opérateur côté backend (require_operator). Les cookies operator
 * (shugu_access) transitent automatiquement via credentials: "include".
 */

export type ModerationPhase = "ingress" | "egress";

export type ModerationEvent = {
  id: number;
  phase: ModerationPhase;
  detector: string;
  verdict: string;
  reason: string | null;
  identity_kind: string | null;
  ip_hash: string | null;
  text_excerpt: string | null;
  text_len: number | null;
  created_at: string;
};

export type EventListResponse = { total: number; items: ModerationEvent[] };

export type BucketCount = { bucket: string; count: number };

export type ModerationStats = {
  window: "1h" | "24h" | "7d";
  total_refused: number;
  by_detector: Record<string, number>;
  by_phase: Record<ModerationPhase, number>;
  timeline: BucketCount[];
};

export type BanItem = { ip_hash: string; ttl_seconds: number };
export type BanListResponse = { total: number; items: BanItem[] };

export type ListEventsParams = {
  phase?: ModerationPhase;
  detector?: string;
  since?: string;
  limit?: number;
  offset?: number;
};

export class AdminError extends Error {
  constructor(
    public status: number,
    public detail: string,
  ) {
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
    throw new AdminError(resp.status, String(detail));
  }
  return payload as T;
}

export async function listEvents(
  params: ListEventsParams = {},
): Promise<EventListResponse> {
  const qs = new URLSearchParams();
  if (params.phase) qs.set("phase", params.phase);
  if (params.detector) qs.set("detector", params.detector);
  if (params.since) qs.set("since", params.since);
  if (params.limit !== undefined) qs.set("limit", String(params.limit));
  if (params.offset !== undefined) qs.set("offset", String(params.offset));
  const q = qs.toString();
  return request<EventListResponse>(
    `/api/admin/moderation/events${q ? `?${q}` : ""}`,
  );
}

export async function getStats(
  window: "1h" | "24h" | "7d" = "24h",
): Promise<ModerationStats> {
  return request<ModerationStats>(
    `/api/admin/moderation/stats?window=${window}`,
  );
}

export async function listBans(): Promise<BanListResponse> {
  return request<BanListResponse>(`/api/admin/moderation/bans`);
}

export async function clearBan(ip_hash: string): Promise<void> {
  await request<void>(
    `/api/admin/moderation/bans/${encodeURIComponent(ip_hash)}`,
    { method: "DELETE" },
  );
}
