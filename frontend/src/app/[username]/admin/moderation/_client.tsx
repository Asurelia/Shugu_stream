"use client";

/**
 * Moderation Hub — dashboard pipeline IA agent.
 *
 * Source de données : table `moderation_events` (refus persistés par
 * LoggingModeration) + bans Redis. Refresh auto toutes les 30 s.
 *
 * Endpoint backend gated `require_operator`.
 */
import { useCallback, useEffect, useMemo, useState } from "react";

import { AdminShell } from "@/components/admin/AdminShell";
import {
  GlassSection,
  GlassRow,
  GlassPill,
  GlassButton,
  GlassTabs,
  GlassModal,
  useToast,
} from "@/features/liquid-glass/primitives";
import { MetricTile } from "@/features/liquid-glass/dataviz";
import {
  listEvents,
  getStats,
  listBans,
  clearBan,
  AdminError,
  type ModerationEvent,
  type ModerationStats,
  type BanItem,
  type ModerationPhase,
} from "@/services/adminModerationClient";

const PAGE_SIZE = 25;
const POLL_MS = 30_000;

type PhaseFilter = "all" | ModerationPhase;
type WindowFilter = "1h" | "24h" | "7d";

function relTime(iso: string): string {
  const d = (Date.now() - new Date(iso).getTime()) / 1000;
  if (d < 60) return `il y a ${Math.floor(d)}s`;
  if (d < 3600) return `il y a ${Math.floor(d / 60)}m`;
  if (d < 86400) return `il y a ${Math.floor(d / 3600)}h`;
  return `il y a ${Math.floor(d / 86400)}j`;
}

function formatTTL(s: number): string {
  if (s < 0) return "permanent";
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  return `${Math.floor(s / 3600)}h`;
}

function detectorTone(
  d: string,
): "primary" | "warn" | "danger" | "default" {
  if (d === "profanity" || d === "injection") return "danger";
  if (d === "rate_limit" || d === "ban") return "warn";
  if (d === "length" || d === "egress_length") return "default";
  return "primary";
}

export function ModerationClient() {
  const toast = useToast();
  const [events, setEvents] = useState<ModerationEvent[]>([]);
  const [eventsTotal, setEventsTotal] = useState(0);
  const [stats, setStats] = useState<ModerationStats | null>(null);
  const [bans, setBans] = useState<BanItem[]>([]);
  const [loading, setLoading] = useState(true);

  const [phaseFilter, setPhaseFilter] = useState<PhaseFilter>("all");
  const [detectorFilter, setDetectorFilter] = useState<string | undefined>(
    undefined,
  );
  const [windowFilter, setWindowFilter] = useState<WindowFilter>("24h");
  const [page, setPage] = useState(0);

  const [pendingClearBan, setPendingClearBan] = useState<BanItem | null>(null);
  const [mutating, setMutating] = useState(false);

  const offset = page * PAGE_SIZE;

  const load = useCallback(async () => {
    try {
      const [evs, sts, bns] = await Promise.all([
        listEvents({
          phase: phaseFilter === "all" ? undefined : phaseFilter,
          detector: detectorFilter,
          limit: PAGE_SIZE,
          offset,
        }),
        getStats(windowFilter),
        listBans(),
      ]);
      setEvents(evs.items);
      setEventsTotal(evs.total);
      setStats(sts);
      setBans(bns.items);
    } catch (err) {
      if (err instanceof AdminError) {
        toast.error("Chargement échoué", { description: err.detail });
      }
    } finally {
      setLoading(false);
    }
  }, [phaseFilter, detectorFilter, windowFilter, offset, toast]);

  useEffect(() => {
    void load();
    const id = setInterval(() => void load(), POLL_MS);
    return () => clearInterval(id);
  }, [load]);

  const topDetector = useMemo(() => {
    if (!stats) return "—";
    const entries = Object.entries(stats.by_detector);
    if (entries.length === 0) return "—";
    return entries.sort((a, b) => b[1] - a[1])[0][0];
  }, [stats]);

  const phaseRatio = useMemo(() => {
    if (!stats) return "—";
    const ig = stats.by_phase.ingress ?? 0;
    const eg = stats.by_phase.egress ?? 0;
    return `${ig} / ${eg}`;
  }, [stats]);

  const detectors = useMemo(
    () => Object.keys(stats?.by_detector ?? {}),
    [stats],
  );

  const onClearBanConfirm = async () => {
    if (!pendingClearBan) return;
    setMutating(true);
    try {
      await clearBan(pendingClearBan.ip_hash);
      toast.success("Ban levé", {
        description: pendingClearBan.ip_hash.slice(0, 12),
      });
      setPendingClearBan(null);
      await load();
    } catch (err) {
      const msg = err instanceof AdminError ? err.detail : "erreur réseau";
      toast.error("Échec lever ban", { description: msg });
    } finally {
      setMutating(false);
    }
  };

  return (
    <AdminShell
      active="moderation"
      title="Pipeline Moderation"
      subtitle="Dashboard des refus pipeline IA (ingress/egress) + bans actifs."
      headerRight={
        <GlassPill tone="primary" dot>
          {stats?.total_refused ?? 0} refus {windowFilter}
        </GlassPill>
      }
    >
      <section className="flex flex-col gap-5">
        {/* KPIs */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <MetricTile
            label={`Refus ${windowFilter}`}
            value={String(stats?.total_refused ?? 0)}
            color="#e08efe"
          />
          <MetricTile label="Top detector" value={topDetector} color="#fd6c9c" />
          <MetricTile
            label="Ingress / Egress"
            value={phaseRatio}
            color="#ffcf6b"
          />
          <MetricTile
            label="Bans actifs"
            value={String(bans.length)}
            color="#81ecff"
          />
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-[1fr_320px] gap-5">
          {/* Colonne principale */}
          <section className="flex flex-col gap-5">
            {/* Filtres */}
            <GlassSection
              title="Filtres"
              subtitle="Affine la liste des refus affichés."
            >
              <div className="flex flex-wrap items-center gap-3">
                <GlassTabs
                  value={phaseFilter}
                  onChange={(v) => {
                    setPhaseFilter(v as PhaseFilter);
                    setPage(0);
                  }}
                  tabs={[
                    { value: "all", label: "Tous" },
                    { value: "ingress", label: "Ingress" },
                    { value: "egress", label: "Egress" },
                  ]}
                />
                <GlassTabs
                  value={windowFilter}
                  onChange={(v) => setWindowFilter(v as WindowFilter)}
                  tabs={[
                    { value: "1h", label: "1h" },
                    { value: "24h", label: "24h" },
                    { value: "7d", label: "7j" },
                  ]}
                />
                <div className="flex items-center gap-2">
                  <GlassButton
                    variant={
                      detectorFilter === undefined ? "secondary" : "ghost"
                    }
                    size="sm"
                    onClick={() => {
                      setDetectorFilter(undefined);
                      setPage(0);
                    }}
                  >
                    Tous detectors
                  </GlassButton>
                  {detectors.map((d) => (
                    <GlassButton
                      key={d}
                      variant={detectorFilter === d ? "secondary" : "ghost"}
                      size="sm"
                      onClick={() => {
                        setDetectorFilter(d);
                        setPage(0);
                      }}
                    >
                      {d}
                    </GlassButton>
                  ))}
                </div>
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
            </GlassSection>

            {/* Events */}
            <GlassSection
              title="Events refusés"
              subtitle={`${eventsTotal} total · page ${page + 1}/${Math.max(1, Math.ceil(eventsTotal / PAGE_SIZE))}`}
            >
              {loading && events.length === 0 ? (
                <div className="p-4 text-sm opacity-60">chargement…</div>
              ) : events.length === 0 ? (
                <div className="p-4 text-sm opacity-60">
                  aucun refus sur la période
                </div>
              ) : (
                events.map((e) => (
                  <GlassRow
                    key={e.id}
                    label={
                      <span className="flex items-center gap-2">
                        <GlassPill
                          tone={
                            e.phase === "ingress" ? "secondary" : "tertiary"
                          }
                        >
                          {e.phase}
                        </GlassPill>
                        <GlassPill tone={detectorTone(e.detector)}>
                          {e.detector}
                        </GlassPill>
                        <span className="text-shugu-cream">
                          {e.reason ?? "—"}
                        </span>
                      </span>
                    }
                    sub={
                      <span className="block text-[12px] opacity-65">
                        {relTime(e.created_at)} · &quot;
                        {e.text_excerpt ?? "—"}&quot; ({e.text_len ?? 0} chars)
                      </span>
                    }
                    trailing={
                      <span className="text-[11px] opacity-50">
                        {new Date(e.created_at).toLocaleTimeString("fr-FR")}
                      </span>
                    }
                  />
                ))
              )}

              {eventsTotal > PAGE_SIZE && (
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
                    {offset + 1}–{Math.min(offset + events.length, eventsTotal)}{" "}
                    sur {eventsTotal}
                  </span>
                  <GlassButton
                    variant="ghost"
                    size="sm"
                    disabled={offset + events.length >= eventsTotal}
                    onClick={() => setPage((p) => p + 1)}
                  >
                    Suivant →
                  </GlassButton>
                </div>
              )}
            </GlassSection>
          </section>

          {/* Rail droit */}
          <aside className="flex flex-col gap-4">
            <GlassSection
              title="Stats / detector"
              subtitle={`Fenêtre ${windowFilter}`}
            >
              {stats && Object.entries(stats.by_detector).length > 0 ? (
                Object.entries(stats.by_detector)
                  .sort((a, b) => b[1] - a[1])
                  .map(([d, c]) => (
                    <GlassRow
                      key={d}
                      label={
                        <span className="text-shugu-cream">{d}</span>
                      }
                      trailing={
                        <GlassPill tone={detectorTone(d)}>{c}</GlassPill>
                      }
                    />
                  ))
              ) : (
                <div className="p-3 text-sm opacity-60">aucune donnée</div>
              )}
            </GlassSection>

            <GlassSection
              title="Bans actifs"
              subtitle={`${bans.length} keys Redis`}
            >
              {bans.length === 0 ? (
                <div className="p-3 text-sm opacity-60">aucun ban actif</div>
              ) : (
                bans.map((b) => (
                  <GlassRow
                    key={b.ip_hash}
                    label={
                      <span className="font-mono text-shugu-cream">
                        {b.ip_hash.slice(0, 12)}…
                      </span>
                    }
                    sub={`TTL ${formatTTL(b.ttl_seconds)}`}
                    trailing={
                      <GlassButton
                        variant="danger"
                        size="sm"
                        onClick={() => setPendingClearBan(b)}
                      >
                        Lever
                      </GlassButton>
                    }
                  />
                ))
              )}
            </GlassSection>
          </aside>
        </div>
      </section>

      {/* Modal confirmation lever ban */}
      {pendingClearBan && (
        <GlassModal
          open
          onClose={() => !mutating && setPendingClearBan(null)}
        >
          <div className="p-5 space-y-4">
            <h3 className="text-lg font-light text-shugu-cream">
              Lever le ban{" "}
              <code>{pendingClearBan.ip_hash.slice(0, 12)}…</code> ?
            </h3>
            <p className="text-sm opacity-70">
              Le visiteur correspondant pourra à nouveau interagir avec
              l&apos;agent IA. TTL actuel :{" "}
              {formatTTL(pendingClearBan.ttl_seconds)}.
            </p>
            <div className="flex items-center justify-end gap-2 pt-2">
              <GlassButton
                variant="ghost"
                size="sm"
                onClick={() => setPendingClearBan(null)}
                disabled={mutating}
              >
                Annuler
              </GlassButton>
              <GlassButton
                variant="danger"
                size="sm"
                onClick={() => void onClearBanConfirm()}
                disabled={mutating}
              >
                {mutating ? "…" : "Lever le ban"}
              </GlassButton>
            </div>
          </div>
        </GlassModal>
      )}
    </AdminShell>
  );
}
