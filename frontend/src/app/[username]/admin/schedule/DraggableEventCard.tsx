"use client";

/**
 * DraggableEventCard — carte d'évènement draggable dans la grille semaine.
 *
 * Utilise `useDraggable` de `@dnd-kit/core`. ActivationConstraint 8 px :
 * un simple survol ou micro-mouvement ne déclenche pas le drag (compatible
 * avec un futur onClick sur la carte pour l'édition).
 *
 * Le composant est aussi utilisé en mode statique (`dragging=false`, sans
 * les bindings dnd) dans le `DragOverlay` pour la copie qui suit le curseur.
 */

import { useDraggable } from "@dnd-kit/core";
import { CSS } from "@dnd-kit/utilities";

import type { ScheduleEvent } from "./types";

type Props = {
  event: ScheduleEvent;
};

/** Card rendue en mode statique dans le DragOverlay (pas de bindings dnd). */
export function EventCardStatic({ event }: Props) {
  return (
    <div
      className="rounded-lg px-2 py-1.5"
      style={{
        background: event.ritual
          ? "linear-gradient(135deg, rgba(224,142,254,0.18), rgba(253,108,156,0.14))"
          : "rgba(18,14,30,0.6)",
        boxShadow: event.ritual
          ? "inset 0 0 0 1px rgba(224,142,254,0.35)"
          : "inset 0 0 0 1px rgba(255,255,255,0.06)",
      }}
    >
      <div className="font-mono text-[9px] text-shugu-cream-dim">{event.hour}</div>
      <div className="text-[11px] text-shugu-cream font-semibold leading-tight">{event.title}</div>
      <div className="font-mono text-[9px] text-shugu-pink-soft">
        {event.category}
        {event.ritual ? " · ♺" : ""}
      </div>
    </div>
  );
}

/** Card draggable — lie `useDraggable` et expose le transform/isDragging. */
export function DraggableEventCard({ event }: Props) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: event.id,
    data: { day: event.day },
  });

  const style: React.CSSProperties = {
    transform: CSS.Translate.toString(transform),
    opacity: isDragging ? 0.35 : 1,
    cursor: isDragging ? "grabbing" : "grab",
  };

  return (
    <div
      ref={setNodeRef}
      style={style}
      {...listeners}
      {...attributes}
      data-testid={`schedule-event-card-${event.id}`}
    >
      <EventCardStatic event={event} />
    </div>
  );
}
