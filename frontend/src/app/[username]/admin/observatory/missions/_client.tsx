"use client";

/**
 * MissionsClient — Sprint mos-A, itération 2b (Kanban).
 *
 * Affiche les missions récentes des workers Shugu sous forme de Kanban
 * 4 colonnes (BACKLOG / TO_DO / IN_PROGRESS / DONE). Drag-and-drop via
 * `@dnd-kit/core` pour déplacer une carte d'une colonne à l'autre.
 *
 * # État local-only
 *
 * Le drop ne persiste pas côté backend (iter 2b = mock-only). Le déplacement
 * met à jour `useState<Mission[]>` localement — un refresh de page restaure
 * l'état serveur. L'iter 3 wirera un `PATCH /api/admin/observatory/missions/
 * {id}` pour persister.
 *
 * # Decoupage modules
 *
 * - `MissionCard.tsx` : carte draggable + halo IN_PROGRESS pulsant
 * - `KanbanColumn.tsx` : drop zone d'une colonne + header count
 * - `MissionFilters.tsx` : barre de filtre par agent + stats header
 * - `_client.tsx` (ici) : orchestration `DndContext` + état + fetch
 *
 * Découpage justifié par la règle modulaire ≤400 lignes/fichier (CLAUDE
 * memory `feedback_modular_architecture`). Chaque module a une seule
 * responsabilité.
 */

import { DndContext, type DragEndEvent, PointerSensor, useSensor, useSensors } from "@dnd-kit/core";
import { useEffect, useMemo, useState } from "react";

import { AdminShell } from "@/components/admin/AdminShell";
import { GlassPill } from "@/features/liquid-glass/primitives";
import {
  fetchMissions,
  MISSION_STATUSES,
  type Mission,
  type MissionStatus,
} from "@/services/adminObservatoryMissionsClient";

import { KanbanColumn } from "./KanbanColumn";
import { MissionFilters } from "./MissionFilters";

const COLUMN_LABELS: Record<MissionStatus, string> = {
  BACKLOG: "Backlog",
  TO_DO: "À faire",
  IN_PROGRESS: "En cours",
  DONE: "Terminé",
};

/** Filtre = nom d'agent ou `null` pour tout afficher. */
type AgentFilter = string | null;

export function MissionsClient() {
  const [missions, setMissions] = useState<Mission[]>([]);
  const [agentFilter, setAgentFilter] = useState<AgentFilter>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isMock, setIsMock] = useState(true);

  // PointerSensor avec activationConstraint=8px : un simple click sur la
  // carte n'amorce pas un drag (utile si on rajoute un onClick navigation
  // vers un détail mission en iter 3).
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 8 } }),
  );

  useEffect(() => {
    // `loading=true` et `error=null` sont déjà l'état initial via `useState` —
    // on n'écrit pas ces valeurs synchrones dans l'effect (règle
    // react-hooks/set-state-in-effect). Si en iter 3 on rajoute un refetch
    // manuel, on les set côté handler de l'utilisateur (pas ici).
    let cancelled = false;
    fetchMissions()
      .then((resp) => {
        if (cancelled) return;
        setMissions(resp.items);
        setIsMock(resp.mock);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        const msg = err instanceof Error ? err.message : "erreur inconnue";
        setError(msg);
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Liste des agents distincts (extraite des missions reçues) — alimente
  // le dropdown de filtre. Triée alpha pour stabilité visuelle.
  const agents = useMemo(() => {
    const set = new Set(missions.map((m) => m.agent));
    return Array.from(set).sort();
  }, [missions]);

  // Missions affichées = filtrées par `agentFilter` si non null.
  const visibleMissions = useMemo(
    () => (agentFilter === null ? missions : missions.filter((m) => m.agent === agentFilter)),
    [missions, agentFilter],
  );

  // Map status → missions de cette colonne, déjà filtrées.
  const missionsByStatus = useMemo(() => {
    const map: Record<MissionStatus, Mission[]> = {
      BACKLOG: [],
      TO_DO: [],
      IN_PROGRESS: [],
      DONE: [],
    };
    for (const m of visibleMissions) {
      map[m.status].push(m);
    }
    return map;
  }, [visibleMissions]);

  const totalCost = useMemo(
    () => visibleMissions.reduce((acc, m) => acc + m.cost_usd, 0),
    [visibleMissions],
  );
  const totalTokens = useMemo(
    () => visibleMissions.reduce((acc, m) => acc + m.tokens_in + m.tokens_out, 0),
    [visibleMissions],
  );

  /**
   * Handler `onDragEnd` — met à jour le statut de la mission déplacée.
   *
   * `event.active.id` est l'id de la mission, `event.over.id` est l'id
   * de la colonne (préfixé par `col-` pour éviter une collision si une
   * mission a le même id qu'un statut). Si `over` est null (drop hors
   * zone), on no-op.
   */
  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    if (over === null) return;
    const missionId = String(active.id);
    const overId = String(over.id);
    if (!overId.startsWith("col-")) return;
    const target = overId.slice("col-".length) as MissionStatus;
    if (!(MISSION_STATUSES as readonly string[]).includes(target)) return;
    setMissions((prev) =>
      prev.map((m) => (m.id === missionId ? { ...m, status: target } : m)),
    );
  };

  return (
    <AdminShell
      active="observatory-missions"
      title="Missions Kanban"
      subtitle="Drag-and-drop des missions récentes des workers Shugu."
      headerRight={
        <GlassPill tone={isMock ? "warn" : "primary"} dot>
          {isMock ? "données mock" : "live"}
        </GlassPill>
      }
    >
      <section className="flex flex-col gap-5">
        {error !== null && (
          <div
            data-testid="missions-error"
            className="p-3 rounded-xl bg-rose-500/10 border border-rose-500/30 text-sm text-rose-100"
          >
            Erreur de chargement : {error}
          </div>
        )}

        <MissionFilters
          agents={agents}
          selected={agentFilter}
          onChange={setAgentFilter}
          totalMissions={visibleMissions.length}
          totalCostUsd={totalCost}
          totalTokens={totalTokens}
        />

        {loading ? (
          <div className="text-shugu-cream-dim text-sm py-10 text-center">
            chargement des missions…
          </div>
        ) : (
          <DndContext sensors={sensors} onDragEnd={handleDragEnd}>
            <div
              data-testid="missions-kanban-board"
              className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-3"
            >
              {MISSION_STATUSES.map((status) => (
                <KanbanColumn
                  key={status}
                  status={status}
                  label={COLUMN_LABELS[status]}
                  missions={missionsByStatus[status]}
                />
              ))}
            </div>
          </DndContext>
        )}
      </section>
    </AdminShell>
  );
}
