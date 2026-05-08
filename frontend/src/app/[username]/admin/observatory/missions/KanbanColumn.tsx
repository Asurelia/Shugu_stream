"use client";

/**
 * KanbanColumn — drop zone d'une colonne du Kanban.
 *
 * Utilise `useDroppable` de `@dnd-kit/core` pour accepter les cartes
 * déplacées. L'id du droppable est préfixé par `col-` (ex. `col-IN_PROGRESS`)
 * pour ne pas collisionner avec un id de mission qui aurait la même valeur
 * que le statut (peu probable mais défensif).
 *
 * Highlight `isOver` : la colonne change de bordure quand une carte
 * survole — feedback visuel pour le drop. Style minimal, pas de glow lourd
 * pour rester cohérent avec la viz iter 1 (worker grid).
 */

import { useDroppable } from "@dnd-kit/core";

import type { Mission, MissionStatus } from "@/services/adminObservatoryMissionsClient";

import { MissionCard } from "./MissionCard";

type Props = {
  status: MissionStatus;
  label: string;
  missions: Mission[];
};

export function KanbanColumn({ status, label, missions }: Props) {
  const { isOver, setNodeRef } = useDroppable({ id: `col-${status}` });

  return (
    <div
      ref={setNodeRef}
      data-testid={`kanban-column-${status}`}
      data-kanban-status={status}
      className={[
        "rounded-xl border p-3 flex flex-col gap-2 min-h-[200px]",
        "bg-white/[0.02] transition-colors",
        isOver ? "border-pink-300/40 bg-white/[0.04]" : "border-white/10",
      ].join(" ")}
    >
      <header className="flex items-center justify-between px-1 pb-1 border-b border-white/5">
        <span className="text-[11px] uppercase tracking-[0.16em] text-shugu-cream-dim font-mono">
          {label}
        </span>
        <span
          className="text-[10px] px-1.5 py-0.5 rounded bg-white/5 text-shugu-cream-dim font-mono"
          data-testid={`kanban-column-count-${status}`}
        >
          {missions.length}
        </span>
      </header>

      <div className="flex flex-col gap-2">
        {missions.length === 0 ? (
          <div className="text-[11px] text-shugu-cream-dim/50 italic px-1 py-3 text-center">
            (vide)
          </div>
        ) : (
          missions.map((m) => <MissionCard key={m.id} mission={m} />)
        )}
      </div>
    </div>
  );
}
