"use client";

/**
 * Observatory client — Sprint mos-A, itération 1.
 *
 * Visualise les workers Shugu en live :
 *   - grille placeholder de 6 cartes (pulsing dot quand actif)
 *   - console scrollable connectée à `/api/admin/observatory/events` (SSE)
 *
 * Itération 2 (séparée) : remplacer la grille par un mesh force-directed
 * (react-force-graph), ajouter un kanban d'actions Director, et un éditeur
 * de mémoire. Cette itération pose UNIQUEMENT les fondations.
 *
 * Le composant gère lui-même le cycle de vie EventSource — pas de hook
 * partagé pour le moment (un seul consommateur). Les events reçus
 * marquent le worker correspondant comme "actif" pendant 4s, ce qui rend
 * la pulsation visible sans qu'elle ne reste verrouillée si un worker est
 * silencieux.
 */

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

import { AdminShell } from "@/components/admin/AdminShell";
import {
  GlassSection,
  GlassPill,
} from "@/features/liquid-glass/primitives";
import {
  KNOWN_WORKERS,
  openObservatoryStream,
  parseObservatoryEvent,
  type ObservatoryEvent,
} from "@/services/adminObservatoryClient";

const MAX_LOG_LINES = 200;

/**
 * Fenêtre d'inactivité après laquelle un worker repasse en idle (cercle
 * statique). 4s = un compromis : assez court pour que la viz soit vivante,
 * assez long pour que l'œil voie la pulsation entre deux events rapprochés.
 */
const ACTIVE_WINDOW_MS = 4000;

type WorkerCardProps = {
  name: string;
  active: boolean;
  lastEventType: string | null;
};

function WorkerCard({ name, active, lastEventType }: WorkerCardProps) {
  return (
    <div
      data-testid={`observatory-worker-card-${name}`}
      className="rounded-xl border border-white/10 bg-white/[0.03] px-4 py-3 flex items-center gap-3"
    >
      <span
        className={
          "w-2.5 h-2.5 rounded-full shrink-0 " +
          (active ? "bg-emerald-400 animate-pulse" : "bg-white/20")
        }
        aria-label={active ? "actif" : "idle"}
      />
      <div className="min-w-0 flex-1">
        <div className="font-mono text-[12px] text-shugu-cream truncate">
          {name}
        </div>
        <div className="text-[10px] text-shugu-cream-dim truncate">
          {lastEventType ?? "—"}
        </div>
      </div>
    </div>
  );
}

type LogLine = {
  ts: string;
  worker: string;
  type: string;
  raw: string;
};

/**
 * Formatte un event Observatory en une ligne unique pour la console — on
 * affiche `HH:MM:SS  worker  type  payload-summary`.
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

export function ObservatoryClient() {
  // Les hrefs des boutons "Mesh →" / "Missions →" sont construits en absolu
  // via `useParams`. Un href relatif (ex: "./missions") sur l'URL parent
  // `/[username]/admin/observatory` (sans trailing slash) résolverait vers
  // `/[username]/admin/missions` côté navigateur (sémantique URL standard
  // — le dernier segment est remplacé) → 404. L'absolu est défensif.
  const params = useParams<{ username?: string | string[] }>();
  const rawUsername = params?.username;
  const username = Array.isArray(rawUsername) ? rawUsername[0] : rawUsername;
  const meshHref = username
    ? `/${encodeURIComponent(username)}/admin/observatory/mesh`
    : "#";
  const missionsHref = username
    ? `/${encodeURIComponent(username)}/admin/observatory/missions`
    : "#";

  const [logs, setLogs] = useState<LogLine[]>([]);
  const [connected, setConnected] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  // worker → timestamp(ms) du dernier event reçu pour ce worker.
  const [lastSeen, setLastSeen] = useState<Record<string, number>>({});
  const [lastTypeByWorker, setLastTypeByWorker] = useState<Record<string, string>>({});
  // `now` est state-driven (pas Date.now() lu en render) — react-hooks/purity
  // interdit les fonctions impures pendant le render. Le tick à 1s rafraîchit
  // cette valeur, ce qui fait vieillir les "actives" sans couplage au stream.
  const [now, setNow] = useState<number>(() => Date.now());
  const consoleRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    // Le helper (`adminObservatoryClient.ts`) construit l'EventSource sur
    // l'URL canonique. `vi.stubGlobal('EventSource', ...)` intercepte
    // toujours le constructeur global, donc le test reste découplé.
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
      setLastTypeByWorker((prev) => ({ ...prev, [ev.worker]: ev.type }));
    };
    es.onerror = () => {
      // EventSource va auto-retry — on signale juste l'état pour l'UI.
      setConnected(false);
      setErrorMsg("Connexion SSE perdue (retry auto)");
    };

    return () => {
      es.close();
    };
  }, []);

  // Tick à 1s pour faire vieillir les "actives". Pas couplé au stream
  // — un worker silencieux repasse idle même si rien ne publie.
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  // Auto-scroll vers le bas à chaque nouveau log.
  useEffect(() => {
    if (consoleRef.current) {
      consoleRef.current.scrollTop = consoleRef.current.scrollHeight;
    }
  }, [logs]);

  const isActive = (name: string): boolean => {
    const t = lastSeen[name];
    return typeof t === "number" && now - t < ACTIVE_WINDOW_MS;
  };

  const activeCount = useMemo(
    () => KNOWN_WORKERS.filter((w) => {
      const t = lastSeen[w];
      return typeof t === "number" && now - t < ACTIVE_WINDOW_MS;
    }).length,
    [lastSeen, now],
  );

  return (
    <AdminShell
      active="observatory"
      title="Observatory"
      subtitle="Live mesh of Shugu workers"
      headerRight={
        <div className="flex items-center gap-3">
          <GlassPill tone={connected ? "primary" : "warn"} dot>
            {connected ? `${activeCount}/${KNOWN_WORKERS.length} actifs` : "déconnecté"}
          </GlassPill>
          <Link
            href={meshHref}
            data-testid="observatory-mesh-link"
            className="lgb lgb-subtle lgb-sm"
            style={{ textDecoration: "none" }}
          >
            <span>⊛</span><span>View mesh →</span>
          </Link>
          <Link
            href={missionsHref}
            data-testid="observatory-missions-link"
            className="lgb lgb-subtle lgb-sm"
            style={{ textDecoration: "none" }}
          >
            <span>▦</span><span>Missions →</span>
          </Link>
        </div>
      }
    >
      <section className="flex flex-col gap-5">
        {errorMsg && (
          <div
            data-testid="observatory-error"
            className="p-3 rounded-xl bg-amber-500/10 border border-amber-500/30 text-sm text-amber-100"
          >
            {errorMsg}
          </div>
        )}

        <GlassSection
          title="Workers"
          subtitle="Pulsation = event reçu dans les 4 dernières secondes."
        >
          <div
            data-testid="observatory-worker-grid"
            className="grid grid-cols-2 md:grid-cols-3 gap-3"
          >
            {KNOWN_WORKERS.map((name) => (
              <WorkerCard
                key={name}
                name={name}
                active={isActive(name)}
                lastEventType={lastTypeByWorker[name] ?? null}
              />
            ))}
          </div>
        </GlassSection>

        <GlassSection
          title="Live console"
          subtitle={`Stream SSE — ${logs.length}/${MAX_LOG_LINES} lignes retenues.`}
        >
          <div
            ref={consoleRef}
            data-testid="observatory-console"
            className="h-[280px] overflow-auto font-mono text-[11px] leading-relaxed text-shugu-cream-dim bg-black/30 border border-white/5 rounded-xl p-3"
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
