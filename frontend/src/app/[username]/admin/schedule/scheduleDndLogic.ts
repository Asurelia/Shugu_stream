/**
 * scheduleDndLogic — logique pure du drag-and-drop jour Schedule.
 *
 * Séparé du composant React pour pouvoir être testé en isolation (Vitest)
 * sans jsdom ni composant monté. `handleDragEnd` dans `_client.tsx` est un
 * simple wrapper qui appelle `applyScheduleDayDrag` et passe le résultat à
 * `setEvents`.
 *
 * Pattern identique au handler Kanban du module Observatory/Missions mais
 * adapté à la granularité "jour" plutôt que "statut".
 */

import { WEEK_DAYS } from "./types";
import type { ScheduleEvent, WeekDay } from "./types";

const DAY_PREFIX = "day-";

/**
 * Applique un déplacement jour-only depuis un drag-end @dnd-kit.
 *
 * @param events  Liste courante des évènements.
 * @param activeId  `event.active.id` — id de l'évènement déplacé.
 * @param overId  `event.over?.id` (null si drop hors zone).
 * @returns  Nouvelle liste avec le jour mis à jour, ou la liste originale
 *           si le drop est invalide / sur le même jour.
 */
export function applyScheduleDayDrag(
  events: ScheduleEvent[],
  activeId: string,
  overId: string | null,
): ScheduleEvent[] {
  // Drop hors zone droppable → no-op.
  if (overId === null) return events;

  // L'id de la colonne doit commencer par le préfixe attendu.
  if (!overId.startsWith(DAY_PREFIX)) return events;

  const targetDay = overId.slice(DAY_PREFIX.length) as WeekDay;

  // Valider que le jour cible est un jour de semaine connu.
  if (!(WEEK_DAYS as readonly string[]).includes(targetDay)) return events;

  const sourceEvent = events.find((e) => e.id === activeId);
  if (!sourceEvent) return events;

  // Drop sur la même colonne → no-op (référence stable, pas de re-render).
  if (sourceEvent.day === targetDay) return events;

  return events.map((e) =>
    e.id === activeId ? { ...e, day: targetDay } : e,
  );
}
