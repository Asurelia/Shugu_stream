"use client";

/**
 * `/[username]/admin/analytics` — Harmonized Stream Pulse client island.
 *
 * Sub-project B/4 : migration mock → dashboard prod-ready branché sur
 * /api/admin/analytics/* (8 routes, polling 60 s).
 *
 * Layout §7.1 spec :
 *   - KPI band (4 MetricTile avec delta)
 *   - Window tabs (1h | 24h | 7d | 30d)
 *   - Grid 2 col (lg:[1fr_320px])
 *     - Col principale : Timeline bars, Heatmap horaire, Filtres,
 *       Liste Performances (paginée, click → modal détail), CSV export
 *     - Rail droit : Top routes, Top visiteurs, Funnel
 */
import { useCallback, useEffect, useState } from "react";

import { AdminShell } from "@/components/admin/AdminShell";
import {
  GlassButton,
  GlassModal,
  GlassPill,
  GlassSection,
  GlassRow,
  GlassTabs,
  useToast,
} from "@/features/liquid-glass/primitives";
import { BarList, Heatmap, MetricTile } from "@/features/liquid-glass/dataviz";
import {
  AdminError,
  AnalyticsWindow,
  FunnelResponse,
  HeatmapResponse,
  KPIsResponse,
  PerformanceDetail,
  PerformanceListItem,
  PerformanceListResponse,
  TimelineResponse,
  TopRoutesResponse,
  TopVisitorsResponse,
  getFunnel,
  getHeatmap,
  getKpis,
  getPerformance,
  getTimeline,
  getTopRoutes,
  getTopVisitors,
  listPerformances,
  triggerCsvExport,
} from "@/services/adminAnalyticsClient";

// ── Constants ──────────────────────────────────────────────────────────────

const PAGE_SIZE = 25;
const POLL_MS = 60_000;

const ROLE_OPTIONS = ["visitor", "member", "vip", "operator"] as const;
const ROUTE_OPTIONS = ["visitor_ws", "viewer", "operator_ws"] as const;

// ── Helpers ────────────────────────────────────────────────────────────────

function fmtDelta(pct: number): string {
  const sign = pct >= 0 ? "+" : "";
  return `${sign}${pct.toFixed(1)} %`;
}

function fmtDuration(ms: number | null): string {
  if (ms === null) return "—";
  if (ms < 1000) return `${ms} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}

function relTime(iso: string): string {
  const d = (Date.now() - new Date(iso).getTime()) / 1000;
  if (d < 60) return `il y a ${Math.floor(d)}s`;
  if (d < 3600) return `il y a ${Math.floor(d / 60)}m`;
  if (d < 86400) return `il y a ${Math.floor(d / 3600)}h`;
  return `il y a ${Math.floor(d / 86400)}j`;
}

function roleTone(
  role: string,
): "primary" | "warn" | "danger" | "default" | "secondary" {
  if (role === "operator") return "danger";
  if (role === "vip") return "primary";
  if (role === "member") return "secondary";
  return "default";
}

// ── Timeline bars — inline mini component ─────────────────────────────────
// The existing Sparkline/BarList primitives don't directly render a vertical-
// bar timeline with dual series. We build a lightweight SVG here to stay zero-
// dependency and consistent with the dataviz philosophy.

function TimelineBars({ data }: { data: TimelineResponse["buckets"] }) {
  if (data.length === 0) {
    return (
      <div className="p-4 text-sm opacity-60">aucune donnée sur la période</div>
    );
  }
  const maxPerf = Math.max(...data.map((b) => b.performances)) || 1;
  const WIDTH = 600;
  const HEIGHT = 80;
  const barW = Math.max(2, (WIDTH / data.length) * 0.6);
  const gap = WIDTH / data.length;

  return (
    <div className="overflow-x-auto">
      <svg
        width={WIDTH}
        height={HEIGHT + 20}
        viewBox={`0 0 ${WIDTH} ${HEIGHT + 20}`}
        aria-label="Timeline des performances"
        style={{ maxWidth: "100%" }}
      >
        {data.map((b, i) => {
          const x = i * gap + gap / 2;
          const h = (b.performances / maxPerf) * HEIGHT;
          return (
            <g key={i}>
              <rect
                x={x - barW / 2}
                y={HEIGHT - h}
                width={barW}
                height={h}
                rx={2}
                fill="#e08efe"
                fillOpacity={0.75}
              />
            </g>
          );
        })}
        {/* Axis labels — first, middle, last */}
        {[0, Math.floor(data.length / 2), data.length - 1].map((i) => {
          if (i < 0 || i >= data.length) return null;
          const x = i * gap + gap / 2;
          const label = new Date(data[i].bucket).toLocaleTimeString("fr-FR", {
            hour: "2-digit",
            minute: "2-digit",
            month: data.length > 48 ? "short" : undefined,
            day: data.length > 48 ? "numeric" : undefined,
          });
          return (
            <text
              key={i}
              x={x}
              y={HEIGHT + 14}
              textAnchor="middle"
              fontSize={9}
              fill="rgba(255,255,255,0.4)"
              fontFamily="monospace"
            >
              {label}
            </text>
          );
        })}
      </svg>
    </div>
  );
}

// ── Performance detail modal ───────────────────────────────────────────────

function PerformanceModal({
  performanceId,
  onClose,
}: {
  performanceId: string;
  onClose: () => void;
}) {
  const toast = useToast();
  const [detail, setDetail] = useState<PerformanceDetail | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const d = await getPerformance(performanceId);
        if (!cancelled) setDetail(d);
      } catch (err) {
        if (!cancelled) {
          const msg = err instanceof AdminError ? err.detail : "erreur réseau";
          toast.error("Chargement échoué", { description: msg });
          onClose();
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [performanceId, onClose, toast]);

  return (
    <GlassModal open onClose={onClose}>
      <div className="p-5 space-y-4 max-h-[80vh] overflow-y-auto">
        {loading || !detail ? (
          <div className="text-sm opacity-60 p-4">chargement…</div>
        ) : (
          <>
            <div className="flex items-center gap-2">
              <h3 className="text-base font-light text-shugu-cream flex-1">
                Performance{" "}
                <code className="text-[11px] opacity-60">
                  {detail.performance_id}
                </code>
              </h3>
              <GlassPill tone={roleTone(detail.author_role)}>
                {detail.author_role}
              </GlassPill>
              <GlassPill>{detail.route}</GlassPill>
            </div>

            <div className="grid grid-cols-2 gap-3 text-[12px]">
              <div>
                <span className="opacity-50 block">Durée</span>
                <span className="text-shugu-cream">
                  {fmtDuration(detail.duration_ms)}
                </span>
              </div>
              <div>
                <span className="opacity-50 block">Créée</span>
                <span className="text-shugu-cream">{relTime(detail.created_at)}</span>
              </div>
              {detail.author_ip_hash_truncated && (
                <div>
                  <span className="opacity-50 block">IP (tronquée)</span>
                  <code className="text-shugu-cream">
                    {detail.author_ip_hash_truncated}…
                  </code>
                </div>
              )}
              <div>
                <span className="opacity-50 block">Modération</span>
                <span
                  className={
                    detail.moderation_ingress || detail.moderation_egress
                      ? "text-red-400"
                      : "opacity-50"
                  }
                >
                  {detail.moderation_ingress || detail.moderation_egress
                    ? "refusée"
                    : "ok"}
                </span>
              </div>
            </div>

            <div>
              <span className="text-[11px] opacity-50 uppercase tracking-widest">
                Input
              </span>
              <pre className="mt-1 p-3 rounded bg-white/5 text-[12px] text-shugu-cream whitespace-pre-wrap break-words max-h-40 overflow-y-auto">
                {detail.input_text || "—"}
              </pre>
            </div>

            {detail.output_text && (
              <div>
                <span className="text-[11px] opacity-50 uppercase tracking-widest">
                  Output
                </span>
                <pre className="mt-1 p-3 rounded bg-white/5 text-[12px] text-shugu-cream whitespace-pre-wrap break-words max-h-40 overflow-y-auto">
                  {detail.output_text}
                </pre>
              </div>
            )}

            {(detail.moderation_ingress || detail.moderation_egress) && (
              <div>
                <span className="text-[11px] opacity-50 uppercase tracking-widest">
                  Modération JSON
                </span>
                <pre className="mt-1 p-3 rounded bg-red-900/20 text-[11px] text-red-300 whitespace-pre-wrap break-all max-h-32 overflow-y-auto">
                  {JSON.stringify(
                    {
                      ingress: detail.moderation_ingress,
                      egress: detail.moderation_egress,
                    },
                    null,
                    2,
                  )}
                </pre>
              </div>
            )}

            <div className="flex justify-end pt-2">
              <GlassButton variant="ghost" size="sm" onClick={onClose}>
                Fermer
              </GlassButton>
            </div>
          </>
        )}
      </div>
    </GlassModal>
  );
}

// ── Main client ────────────────────────────────────────────────────────────

export function AnalyticsClient() {
  const toast = useToast();

  // Window + filters
  const [analyticsWindow, setAnalyticsWindow] =
    useState<AnalyticsWindow>("24h");
  const [roleFilter, setRoleFilter] = useState<string | undefined>(undefined);
  const [routeFilter, setRouteFilter] = useState<string | undefined>(undefined);
  const [page, setPage] = useState(0);

  // Data state
  const [kpis, setKpis] = useState<KPIsResponse | null>(null);
  const [timeline, setTimeline] = useState<TimelineResponse | null>(null);
  const [topRoutes, setTopRoutes] = useState<TopRoutesResponse | null>(null);
  const [topVisitors, setTopVisitors] = useState<TopVisitorsResponse | null>(
    null,
  );
  const [heatmap, setHeatmap] = useState<HeatmapResponse | null>(null);
  const [funnel, setFunnel] = useState<FunnelResponse | null>(null);
  const [performances, setPerformances] =
    useState<PerformanceListResponse | null>(null);
  const [loading, setLoading] = useState(true);

  // Modal
  const [selectedPerfId, setSelectedPerfId] = useState<string | null>(null);

  const offset = page * PAGE_SIZE;

  const load = useCallback(async () => {
    try {
      const [k, tl, tr, tv, hm, fn, perfs] = await Promise.all([
        getKpis(analyticsWindow),
        getTimeline(analyticsWindow),
        getTopRoutes(analyticsWindow, 5),
        getTopVisitors(analyticsWindow, 5),
        getHeatmap(analyticsWindow),
        getFunnel(),
        listPerformances({
          author_role: roleFilter,
          route: routeFilter,
          limit: PAGE_SIZE,
          offset,
        }),
      ]);
      setKpis(k);
      setTimeline(tl);
      setTopRoutes(tr);
      setTopVisitors(tv);
      setHeatmap(hm);
      setFunnel(fn);
      setPerformances(perfs);
    } catch (err) {
      if (err instanceof AdminError) {
        toast.error("Chargement échoué", { description: err.detail });
      } else {
        toast.error("Chargement échoué", { description: "Erreur réseau" });
      }
    } finally {
      setLoading(false);
    }
  }, [analyticsWindow, roleFilter, routeFilter, offset, toast]);

  /* eslint-disable react-hooks/set-state-in-effect -- fetch-on-mount + filter deps */
  useEffect(() => {
    const tid = setTimeout(() => void load(), 0);
    const id = setInterval(() => void load(), POLL_MS);
    return () => {
      clearTimeout(tid);
      clearInterval(id);
    };
  }, [load]);
  /* eslint-enable react-hooks/set-state-in-effect */

  const handleExport = () => {
    const now = new Date();
    const windowMs: { [K in AnalyticsWindow]: number } = {
      "1h": 3_600_000,
      "24h": 86_400_000,
      "7d": 7 * 86_400_000,
      "30d": 30 * 86_400_000,
    };
    const since = new Date(now.getTime() - windowMs[analyticsWindow as AnalyticsWindow]);
    triggerCsvExport({
      since: since.toISOString(),
      until: now.toISOString(),
      author_role: roleFilter,
      route: routeFilter,
    });
    toast.info("Export lancé", {
      description:
        "Si le fichier ne se télécharge pas, réduisez la fenêtre temporelle.",
    });
  };

  // Convert heatmap 1D buckets → 1×24 matrix for Heatmap component
  const heatmapMatrix: number[][] = heatmap
    ? [heatmap.buckets.map((b) => b.count)]
    : [Array<number>(24).fill(0)];

  const perfTotal = performances?.total ?? 0;

  return (
    <AdminShell
      active="analytics"
      title="Analytics"
      subtitle="Métriques pipeline IA — performances, visiteurs, modération."
      headerRight={
        <GlassPill tone="primary" dot>
          {kpis?.visitors_unique ?? "…"} visiteurs{" "}
          {analyticsWindow}
        </GlassPill>
      }
    >
      <div className="flex flex-col gap-5">
        {/* KPI band */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <MetricTile
            label="Visiteurs uniques"
            value={String(kpis?.visitors_unique ?? "…")}
            delta={
              kpis ? fmtDelta(kpis.visitors_unique_delta_pct) : undefined
            }
            color="#e08efe"
          />
          <MetricTile
            label="Performances"
            value={String(kpis?.performances_total ?? "…")}
            delta={
              kpis
                ? fmtDelta(kpis.performances_total_delta_pct)
                : undefined
            }
            color="#81ecff"
          />
          <MetricTile
            label="Durée moy"
            value={fmtDuration(kpis?.avg_duration_ms ?? null)}
            delta={
              kpis ? fmtDelta(kpis.avg_duration_ms_delta_pct) : undefined
            }
            color="#ffcf6b"
          />
          <MetricTile
            label="Bans actifs"
            value={String(kpis?.bans_active_count ?? "…")}
            color="#fd6c9c"
          />
        </div>

        {/* Window + refresh */}
        <div className="flex items-center gap-3 flex-wrap">
          <GlassTabs
            aria-label="Fenêtre temporelle"
            value={analyticsWindow}
            onChange={(v) => {
              setAnalyticsWindow(v as AnalyticsWindow);
              setPage(0);
            }}
            tabs={[
              { value: "1h", label: "1h" },
              { value: "24h", label: "24h" },
              { value: "7d", label: "7j" },
              { value: "30d", label: "30j" },
            ]}
          />
          <div className="ml-auto">
            <GlassButton
              variant="ghost"
              size="sm"
              onClick={() => void load()}
            >
              {loading ? "…" : "Rafraîchir"}
            </GlassButton>
          </div>
        </div>

        {/* Main grid */}
        <div className="grid grid-cols-1 lg:grid-cols-[1fr_320px] gap-5">
          {/* Colonne principale */}
          <section className="flex flex-col gap-5">
            {/* Timeline */}
            <GlassSection
              title="Timeline"
              subtitle={`Performances par bucket — fenêtre ${analyticsWindow}.`}
            >
              <TimelineBars data={timeline?.buckets ?? []} />
            </GlassSection>

            {/* Heatmap horaire */}
            <GlassSection
              title="Heatmap horaire"
              subtitle="Distribution par heure du jour UTC (0–23)."
            >
              <Heatmap data={heatmapMatrix} color="#e08efe" />
              {heatmap && (
                <div className="mt-2 text-[11px] font-mono opacity-40">
                  pic : {heatmap.max_count} perf
                </div>
              )}
            </GlassSection>

            {/* Filtres */}
            <GlassSection
              title="Filtres"
              subtitle="Affine la liste des performances."
            >
              <div className="flex flex-wrap items-center gap-3">
                <div className="flex items-center gap-2">
                  <span className="text-[11px] opacity-50">Rôle</span>
                  <GlassButton
                    variant={roleFilter === undefined ? "secondary" : "ghost"}
                    size="sm"
                    onClick={() => {
                      setRoleFilter(undefined);
                      setPage(0);
                    }}
                  >
                    Tous
                  </GlassButton>
                  {ROLE_OPTIONS.map((r) => (
                    <GlassButton
                      key={r}
                      variant={roleFilter === r ? "secondary" : "ghost"}
                      size="sm"
                      onClick={() => {
                        setRoleFilter(r);
                        setPage(0);
                      }}
                    >
                      {r}
                    </GlassButton>
                  ))}
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-[11px] opacity-50">Route</span>
                  <GlassButton
                    variant={routeFilter === undefined ? "secondary" : "ghost"}
                    size="sm"
                    onClick={() => {
                      setRouteFilter(undefined);
                      setPage(0);
                    }}
                  >
                    Toutes
                  </GlassButton>
                  {ROUTE_OPTIONS.map((rt) => (
                    <GlassButton
                      key={rt}
                      variant={routeFilter === rt ? "secondary" : "ghost"}
                      size="sm"
                      onClick={() => {
                        setRouteFilter(rt);
                        setPage(0);
                      }}
                    >
                      {rt}
                    </GlassButton>
                  ))}
                </div>
              </div>
            </GlassSection>

            {/* Performances list */}
            <GlassSection
              title="Performances"
              subtitle={`${perfTotal} total · page ${page + 1}/${Math.max(1, Math.ceil(perfTotal / PAGE_SIZE))}`}
            >
              {loading && !performances ? (
                <div className="p-4 text-sm opacity-60">chargement…</div>
              ) : performances?.items.length === 0 ? (
                <div className="p-4 text-sm opacity-60">
                  aucune performance sur cette période
                </div>
              ) : (
                performances?.items.map((p: PerformanceListItem) => (
                  <GlassRow
                    key={p.performance_id}
                    label={
                      <span className="flex items-center gap-2 flex-wrap">
                        <GlassPill tone={roleTone(p.author_role)}>
                          {p.author_role}
                        </GlassPill>
                        <GlassPill>{p.route}</GlassPill>
                        {p.has_moderation_refusal && (
                          <GlassPill tone="danger">refusée</GlassPill>
                        )}
                        <span className="text-shugu-cream text-[12px] truncate max-w-[240px]">
                          {p.input_text_excerpt}
                        </span>
                      </span>
                    }
                    sub={
                      <span className="block text-[11px] opacity-50">
                        {relTime(p.created_at)} ·{" "}
                        {fmtDuration(p.duration_ms)}
                        {p.author_ip_hash_truncated &&
                          ` · ${p.author_ip_hash_truncated}…`}
                      </span>
                    }
                    trailing={
                      <GlassButton
                        variant="subtle"
                        size="sm"
                        onClick={() => setSelectedPerfId(p.performance_id)}
                      >
                        Détail
                      </GlassButton>
                    }
                  />
                ))
              )}

              {perfTotal > PAGE_SIZE && (
                <div className="flex items-center justify-between gap-3 pt-4">
                  <GlassButton
                    variant="ghost"
                    size="sm"
                    disabled={page === 0}
                    onClick={() => setPage((p) => Math.max(0, p - 1))}
                  >
                    ← Précédent
                  </GlassButton>
                  <span className="text-[12px] opacity-60">
                    {offset + 1}–
                    {Math.min(
                      offset + (performances?.items.length ?? 0),
                      perfTotal,
                    )}{" "}
                    sur {perfTotal}
                  </span>
                  <GlassButton
                    variant="ghost"
                    size="sm"
                    disabled={
                      offset + (performances?.items.length ?? 0) >= perfTotal
                    }
                    onClick={() => setPage((p) => p + 1)}
                  >
                    Suivant →
                  </GlassButton>
                </div>
              )}
            </GlassSection>

            {/* CSV export */}
            <div className="flex justify-end">
              <GlassButton variant="secondary" size="sm" onClick={handleExport}>
                Exporter CSV ({analyticsWindow})
              </GlassButton>
            </div>
          </section>

          {/* Rail droit */}
          <aside className="flex flex-col gap-4">
            {/* Top routes */}
            <GlassSection
              title="Top routes"
              subtitle={`Fenêtre ${analyticsWindow}.`}
            >
              {topRoutes?.items.length ? (
                <BarList
                  color="#81ecff"
                  rows={topRoutes.items.map((r) => ({
                    label: r.route,
                    value: r.count,
                    sub: `${r.pct.toFixed(1)} %`,
                  }))}
                />
              ) : (
                <div className="p-3 text-sm opacity-60">aucune donnée</div>
              )}
            </GlassSection>

            {/* Top visiteurs */}
            <GlassSection
              title="Top visiteurs"
              subtitle={`Par msg count — fenêtre ${analyticsWindow}.`}
            >
              {topVisitors?.items.length ? (
                topVisitors.items.map((v) => (
                  <GlassRow
                    key={v.ip_hash_truncated}
                    label={
                      <span className="flex items-center gap-2">
                        <code className="font-mono text-[12px] text-shugu-cream">
                          {v.ip_hash_truncated}…
                        </code>
                        {v.is_banned && (
                          <GlassPill tone="danger">banni</GlassPill>
                        )}
                      </span>
                    }
                    sub={`premier : ${relTime(v.first_seen)}`}
                    trailing={
                      <span className="font-mono text-[11px] text-shugu-cream-dim">
                        {v.msg_count_window} msg
                      </span>
                    }
                  />
                ))
              ) : (
                <div className="p-3 text-sm opacity-60">aucune donnée</div>
              )}
            </GlassSection>

            {/* Funnel */}
            <GlassSection
              title="Funnel conversion"
              subtitle="All-time visitors → members → VIPs."
            >
              {funnel ? (
                <div className="flex flex-col gap-3">
                  <div className="flex items-center justify-between text-[12px]">
                    <span className="opacity-70">Visiteurs uniques</span>
                    <span className="font-mono text-shugu-cream">
                      {funnel.visitors_unique_total.toLocaleString("fr-FR")}
                    </span>
                  </div>
                  <div className="flex items-center justify-between text-[12px]">
                    <span className="opacity-70">Members</span>
                    <span className="flex items-center gap-2 font-mono text-shugu-cream">
                      {funnel.members_total.toLocaleString("fr-FR")}
                      <GlassPill tone="secondary">
                        {funnel.visitor_to_member_pct.toFixed(1)} %
                      </GlassPill>
                    </span>
                  </div>
                  <div className="flex items-center justify-between text-[12px]">
                    <span className="opacity-70">VIPs</span>
                    <span className="flex items-center gap-2 font-mono text-shugu-cream">
                      {funnel.vips_total.toLocaleString("fr-FR")}
                      <GlassPill tone="primary">
                        {funnel.member_to_vip_pct.toFixed(1)} %
                      </GlassPill>
                    </span>
                  </div>
                  {/* Funnel bar */}
                  {funnel.visitors_unique_total > 0 && (
                    <div className="mt-1 flex flex-col gap-1">
                      {[
                        {
                          label: "Visiteurs",
                          pct: 100,
                          color: "#e08efe",
                        },
                        {
                          label: "Members",
                          pct: funnel.visitor_to_member_pct,
                          color: "#81ecff",
                        },
                        {
                          label: "VIPs",
                          pct:
                            (funnel.vips_total /
                              funnel.visitors_unique_total) *
                            100,
                          color: "#ffd98c",
                        },
                      ].map((step) => (
                        <div key={step.label} className="flex items-center gap-2">
                          <span className="text-[10px] w-16 opacity-50">
                            {step.label}
                          </span>
                          <div
                            className="flex-1 h-2 rounded-full overflow-hidden"
                            style={{ background: "rgba(255,255,255,0.05)" }}
                          >
                            <div
                              style={{
                                width: `${Math.min(100, step.pct)}%`,
                                height: "100%",
                                background: `linear-gradient(90deg, ${step.color}, ${step.color}cc)`,
                                boxShadow: `0 0 8px -2px ${step.color}90`,
                                borderRadius: 999,
                              }}
                            />
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ) : (
                <div className="p-3 text-sm opacity-60">chargement…</div>
              )}
            </GlassSection>
          </aside>
        </div>
      </div>

      {/* Performance detail modal */}
      {selectedPerfId && (
        <PerformanceModal
          performanceId={selectedPerfId}
          onClose={() => setSelectedPerfId(null)}
        />
      )}
    </AdminShell>
  );
}
