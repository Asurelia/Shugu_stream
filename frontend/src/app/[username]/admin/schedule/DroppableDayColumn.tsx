"use client";

/**
 * DroppableDayColumn — colonne jour de la grille semaine, zone de drop DnD.
 *
 * Utilise `useDroppable` de `@dnd-kit/core`. L'id est préfixé `day-` pour
 * éviter toute collision avec un id d'évènement (pattern identique aux
 * colonnes Kanban du module Observatory/Missions).
 *
 * Highlight `isOver` : bordure légère pour indiquer qu'un drop est possible
 * ici — style cohérent avec le Liquid Glass de l'app.
 */

import { useDroppable } from "@dnd-kit/core";

import type { ScheduleEvent, WeekDay } from "./types";

import { DraggableEventCard } from "./DraggableEventCard";

type Props = {
  day: WeekDay;
  events: ScheduleEvent[];
};

export function DroppableDayColumn({ day, events }: Props) {
  const { isOver, setNodeRef } = useDroppable({ id: `day-${day}` });

  return (
    <div className="flex flex-col">
      <div className="font-mono text-[10px] text-shugu-cream-dim uppercase tracking-[0.16em] text-center py-2">
        {day}
      </div>
      <div
        ref={setNodeRef}
        data-testid={`schedule-day-column-${day}`}
        className={[
          "flex-1 min-h-[160px] rounded-xl p-2 flex flex-col gap-1.5 transition-colors",
          isOver
            ? "border border-pink-300/30 bg-white/[0.04]"
            : "border border-transparent",
        ].join(" ")}
        style={
          isOver
            ? undefined
            : { background: "rgba(255,255,255,0.02)", boxShadow: "inset 0 0 0 1px rgba(255,255,255,0.05)" }
        }
      >
        {events.map((e) => (
          <DraggableEventCard key={e.id} event={e} />
        ))}
      </div>
    </div>
  );
}
