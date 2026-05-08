"use client";

/**
 * Observatory Mesh client — Sprint mos-A, itération 2a.
 *
 * Visualisation force-directed des workers Shugu :
 *   - 1 nœud central `shugu_persona_brain` (`isCenter: true`)
 *   - 6 satellites (les autres `KNOWN_WORKERS`) reliés au centre par des
 *     liens 1-to-many.
 *   - chaque event SSE Observatory met à jour `lastActivityAt` du nœud
 *     correspondant ; `WorkersMesh` affiche un halo pulsant pendant 2s.
 *
 * Fenêtre console : on garde la même console que l'itération 1, sous le
 * mesh, pour que le streamer puisse lire le détail brut des events tout
 * en regardant la viz.
 *
 * `WorkersMesh` est importé via `next/dynamic({ ssr: false })` parce que
 * `react-force-graph-2d` touche `window` à l'import (canvas + d3). Sans ça,
 * `next build` plante au prerender.
 *
 * Cycle de vie EventSource : identique à iter 1 (pas de hook partagé pour
 * un seul consommateur), avec gestion d'erreur explicite et nettoyage au
 * unmount via le return du `useEffect`.
 */

import dynamic from "next/dynamic";
import { useEffect, useMemo, useRef, useState } from "react";

import { AdminShell } from "@/components/admin/AdminShell";
import { GlassPill, GlassSection } from "@/features/liquid-glass/primitives";
import {
  KNOWN_WORKERS,
  openObservatoryStream,
  parseObservatoryEvent,
  type ObservatoryEvent,
} from "@/services/adminObservatoryClient";

import type { WorkerLink, WorkerNode } from "./WorkersMesh";

/** Plafond de lignes retenues dans la console live (parité avec iter 1). */
const MAX_LOG_LINES = 200;

/** Worker placé au centre du mesh — porte la "personnalité" de Shugu. */
const CENTER_WORKER = "shugu_persona_brain";

/** Dimensions hardcodées du canvas mesh (iter 2a — ResizeObserver plus tard). */
const MESH_WIDTH = 720;
const MESH_HEIGHT = 420;

/**
 * Charge `WorkersMesh` côté client uniquement — `react-force-graph-2d` lit
 * `window` au top-level de son module. `loading` rend un placeholder neutre
 * pour éviter le layout shift pendant l'hydratation.
 */
const WorkersMesh = dynamic(
  () => import("./WorkersMesh").then((m) => m.WorkersMesh),
  {
    ssr: false,
    loading: () => (
      <div
        data-testid="observatory-mesh-loading"
        className="rounded-xl border border-white/5 bg-black/40 grid place-items-center text-shugu-cream-dim text-sm"
        style={{ width: MESH_WIDTH, height: MESH_HEIGHT }}
      >
        chargement du mesh…
      </div>
    ),
  },
);

type LogLine = {
  ts: string;
  worker: string;
  type: string;
  raw: string;
};

/**
 * Formatte un event Observatory en ligne console — `HH:MM:SS  worker  type
 * payload-summary`. Calque iter 1 pour cohérence visuelle entre les deux pages.
 */
function formatLogLine(ev: ObservatoryEvent): LogLine {
  let stamp = ev.ts;
  try {
    stamp = new Date(ev.ts).toISOString().slice(11, 19);
  } catch {
    /* keep raw on parse error */
  }
  let payloadStr = "";
  try {
    payloadStr = JSON.stringify(ev.payload);
    if (payloadStr.length > 160) payloadStr = payloadStr.slice(0, 160) + "…";
  } catch {
    payloadStr = "<unserializable>";
  }
  return {
    ts: ev.ts,
    worker: ev.worker,
    type: ev.type,
    raw: `${stamp}  ${ev.worker.padEnd(20)}  ${ev.type.padEnd(20)}  ${payloadStr}`,
  };
}

/**
 * Construit la topologie statique du mesh : 1 centre + N satellites reliés
 * au centre. Memoizé sur `KNOWN_WORKERS` (constant) — calcul stable.
 */
function buildTopology(
  lastSeen: Record<string, number>,
): { nodes: WorkerNode[]; links: WorkerLink[] } {
  const nodes: WorkerNode[] = KNOWN_WORKERS.map((id) => ({
    id,
    isCenter: id === CENTER_WORKER,
    lastActivityAt: lastSeen[id] ?? null,
  }));
  const links: WorkerLink[] = KNOWN_WORKERS
    .filter((id) => id !== CENTER_WORKER)
    .map((id) => ({ source: CENTER_WORKER, target: id }));
  return { nodes, links };
}

export function ObservatoryMeshClient() {
  const [logs, setLogs] = useState<LogLine[]>([]);
  const [connected, setConnected] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  // worker → timestamp(ms) du dernier event SSE reçu pour ce worker.
  const [lastSeen, setLastSeen] = useState<Record<string, number>>({});
  // `now` state-driven (pas Date.now() en render) — tick à 250ms pour que
  // l'animation halo (2s) soit fluide sans solliciter le force-graph.
  const [now, setNow] = useState<number>(() => Date.now());
  const consoleRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const es = openObservatoryStream();

    es.onopen = () => {
      setConnected(true);
      setErrorMsg(null);
    };
    es.onmessage = (msg: MessageEvent<string>) => {
      const ev = parseObservatoryEvent(msg.data);
      if (ev === null) return;
      const line = formatLogLine(ev);
      setLogs((prev) => {
        const next = [...prev, line];
        if (next.length > MAX_LOG_LINES) next.splice(0, next.length - MAX_LOG_LINES);
        return next;
      });
      setLastSeen((prev) => ({ ...prev, [ev.worker]: Date.now() }));
    };
    es.onerror = () => {
      // EventSource auto-retry — on signale l'état pour l'UI.
      setConnected(false);
      setErrorMsg("Connexion SSE perdue (retry auto)");
    };

    return () => {
      es.close();
    };
  }, []);

  // Tick rapide pour driver l'animation halo (durée 2s, ~8fps suffit visuel).
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(id);
  }, []);

  // Auto-scroll console à chaque nouveau log.
  useEffect(() => {
    if (consoleRef.current) {
      consoleRef.current.scrollTop = consoleRef.current.scrollHeight;
    }
  }, [logs]);

  const topology = useMemo(() => buildTopology(lastSeen), [lastSeen]);

  // Compte des workers actifs dans la fenêtre halo (cohérent avec ce qu'on
  // voit pulser à l'écran). On réutilise HALO_DURATION_MS de WorkersMesh
  // implicitement (2s) — un peu plus serré qu'iter 1 (4s) car la viz mesh
  // a sa propre animation, on évite les doubles-comptages.
  const activeCount = useMemo(
    () => KNOWN_WORKERS.filter((w) => {
      const t = lastSeen[w];
      return typeof t === "number" && now - t < 2000;
    }).length,
    [lastSeen, now],
  );

  return (
    <AdminShell
      active="observatory-mesh"
      title="Observatory · Mesh"
      subtitle="Force-directed view of Shugu workers"
      headerRight={
        <GlassPill tone={connected ? "primary" : "warn"} dot>
          {connected ? `${activeCount}/${KNOWN_WORKERS.length} actifs` : "déconnecté"}
        </GlassPill>
      }
    >
      <section className="flex flex-col gap-5">
        {errorMsg && (
          <div
            data-testid="observatory-mesh-error"
            className="p-3 rounded-xl bg-amber-500/10 border border-amber-500/30 text-sm text-amber-100"
          >
            {errorMsg}
          </div>
        )}

        <GlassSection
          title="Mesh"
          subtitle="Halo pulsant sur chaque event SSE (2s)."
        >
          <div data-testid="observatory-mesh-container" className="flex justify-center">
            <WorkersMesh
              nodes={topology.nodes}
              links={topology.links}
              now={now}
              width={MESH_WIDTH}
              height={MESH_HEIGHT}
            />
          </div>
        </GlassSection>

        <GlassSection
          title="Live console"
          subtitle={`Stream SSE — ${logs.length}/${MAX_LOG_LINES} lignes retenues.`}
        >
          <div
            ref={consoleRef}
            data-testid="observatory-mesh-console"
            className="h-[240px] overflow-auto font-mono text-[11px] leading-relaxed text-shugu-cream-dim bg-black/30 border border-white/5 rounded-xl p-3"
          >
            {logs.length === 0 ? (
              <div className="opacity-50">en attente d&apos;events…</div>
            ) : (
              logs.map((line, i) => (
                <div key={`${line.ts}-${i}`} className="whitespace-pre">
                  {line.raw}
                </div>
              ))
            )}
          </div>
        </GlassSection>
      </section>
    </AdminShell>
  );
}
