/**
 * adminAnalyticsClient — wrappers fetch pour /api/admin/analytics/*.
 *
 * Gated opérateur côté backend (require_operator). Les cookies operator
 * (shugu_access) transitent automatiquement via credentials: "include".
 *
 * 8 endpoints mirroring backend routes/admin_analytics.py :
 *   GET /api/admin/analytics/kpis
 *   GET /api/admin/analytics/timeline
 *   GET /api/admin/analytics/top-routes
 *   GET /api/admin/analytics/top-visitors
 *   GET /api/admin/analytics/heatmap
 *   GET /api/admin/analytics/funnel
 *   GET /api/admin/analytics/performances
 *   GET /api/admin/analytics/performances/{id}
 *   GET /api/admin/analytics/export  (streaming CSV, handled via link)
 */

export type AnalyticsWindow = "1h" | "24h" | "7d" | "30d";

// ── KPIs ──────────────────────────────────────────────────────────────────

export type KPIsResponse = {
  window: AnalyticsWindow;
  visitors_unique: number;
  visitors_unique_delta_pct: number;
  performances_total: number;
  performances_total_delta_pct: number;
  avg_duration_ms: number;
  avg_duration_ms_delta_pct: number;
  moderation_refused_rate: number;
  moderation_refused_rate_delta_pct: number;
  bans_active_count: number;
};

// ── Timeline ──────────────────────────────────────────────────────────────

export type TimelineBucket = {
  bucket: string; // ISO datetime string
  performances: number;
  visitors_unique: number;
};

export type TimelineResponse = {
  window: AnalyticsWindow;
  buckets: TimelineBucket[];
};

// ── Top routes ────────────────────────────────────────────────────────────

export type TopRoute = {
  route: string;
  count: number;
  pct: number;
};

export type TopRoutesResponse = {
  window: string;
  total: number;
  items: TopRoute[];
};

// ── Top visitors ──────────────────────────────────────────────────────────

export type TopVisitor = {
  ip_hash_truncated: string; // 12 first chars only
  msg_count_window: number;
  first_seen: string; // ISO datetime
  last_seen: string;
  is_banned: boolean;
};

export type TopVisitorsResponse = {
  items: TopVisitor[];
};

// ── Heatmap ───────────────────────────────────────────────────────────────

export type HeatmapBucket = {
  hour: number; // 0..23 UTC
  count: number;
};

export type HeatmapResponse = {
  window: string;
  buckets: HeatmapBucket[]; // always 24 entries
  max_count: number;
};

// ── Funnel ────────────────────────────────────────────────────────────────

export type FunnelResponse = {
  visitors_unique_total: number;
  members_total: number;
  vips_total: number;
  visitor_to_member_pct: number;
  member_to_vip_pct: number;
};

// ── Performances list ─────────────────────────────────────────────────────

export type PerformanceListItem = {
  performance_id: string;
  author_role: string;
  author_ip_hash_truncated: string | null;
  route: string;
  duration_ms: number | null;
  has_moderation_refusal: boolean;
  created_at: string; // ISO datetime
  played_at: string | null;
  input_text_excerpt: string;
  output_text_excerpt: string | null;
};

export type PerformanceListResponse = {
  total: number;
  items: PerformanceListItem[];
};

export type PerformancesParams = {
  author_role?: string;
  route?: string;
  since?: string; // ISO datetime
  limit?: number;
  offset?: number;
};

// ── Performance detail ────────────────────────────────────────────────────

export type PerformanceDetail = {
  performance_id: string;
  author_role: string;
  author_ip_hash_truncated: string | null;
  route: string;
  duration_ms: number | null;
  input_text: string;
  output_text: string | null;
  moderation_ingress: Record<string, unknown> | null;
  moderation_egress: Record<string, unknown> | null;
  created_at: string;
  played_at: string | null;
};

// ── Error class ───────────────────────────────────────────────────────────

export class AdminError extends Error {
  constructor(
    public status: number,
    public detail: string,
  ) {
    super(`[${status}] ${detail}`);
    this.name = "AdminError";
  }
}

// ── Internal fetch helper ─────────────────────────────────────────────────

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
    throw new AdminError(resp.status, String(detail));
  }
  return payload as T;
}

// ── Public API ────────────────────────────────────────────────────────────

export async function getKpis(
  window: AnalyticsWindow = "24h",
): Promise<KPIsResponse> {
  return request<KPIsResponse>(
    `/api/admin/analytics/kpis?window=${window}`,
  );
}

export async function getTimeline(
  window: AnalyticsWindow = "24h",
): Promise<TimelineResponse> {
  return request<TimelineResponse>(
    `/api/admin/analytics/timeline?window=${window}`,
  );
}

export async function getTopRoutes(
  window: AnalyticsWindow = "24h",
  limit = 5,
): Promise<TopRoutesResponse> {
  return request<TopRoutesResponse>(
    `/api/admin/analytics/top-routes?window=${window}&limit=${limit}`,
  );
}

export async function getTopVisitors(
  window: AnalyticsWindow = "24h",
  limit = 5,
): Promise<TopVisitorsResponse> {
  return request<TopVisitorsResponse>(
    `/api/admin/analytics/top-visitors?window=${window}&limit=${limit}`,
  );
}

export async function getHeatmap(
  window: AnalyticsWindow = "24h",
): Promise<HeatmapResponse> {
  return request<HeatmapResponse>(
    `/api/admin/analytics/heatmap?window=${window}`,
  );
}

export async function getFunnel(): Promise<FunnelResponse> {
  return request<FunnelResponse>(`/api/admin/analytics/funnel`);
}

export async function listPerformances(
  params: PerformancesParams = {},
): Promise<PerformanceListResponse> {
  const qs = new URLSearchParams();
  if (params.author_role) qs.set("author_role", params.author_role);
  if (params.route) qs.set("route", params.route);
  if (params.since) qs.set("since", params.since);
  if (params.limit !== undefined) qs.set("limit", String(params.limit));
  if (params.offset !== undefined) qs.set("offset", String(params.offset));
  const q = qs.toString();
  return request<PerformanceListResponse>(
    `/api/admin/analytics/performances${q ? `?${q}` : ""}`,
  );
}

export async function getPerformance(
  performance_id: string,
): Promise<PerformanceDetail> {
  return request<PerformanceDetail>(
    `/api/admin/analytics/performances/${encodeURIComponent(performance_id)}`,
  );
}

/**
 * Trigger CSV export as browser download.
 *
 * Uses window.location.href so the browser handles cookies + download dialog.
 * Call this only after confirming the export size won't exceed 10k rows
 * (the backend will return 413 if it does — but since it's a navigation,
 * you won't get a nice error; check count via a separate KPI call if needed).
 *
 * For the 413 case we recommend showing a toast and reducing the window.
 */
export function triggerCsvExport(params: {
  since: string; // ISO datetime
  until: string; // ISO datetime
  author_role?: string;
  route?: string;
}): void {
  const qs = new URLSearchParams({
    type: "performances",
    since: params.since,
    until: params.until,
  });
  if (params.author_role) qs.set("author_role", params.author_role);
  if (params.route) qs.set("route", params.route);
  window.location.href = `/api/admin/analytics/export?${qs.toString()}`;
}
