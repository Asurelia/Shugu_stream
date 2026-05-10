/**
 * Types partagés du module Schedule.
 *
 * Extraits de `_client.tsx` pour être réutilisés par les sous-composants
 * DnD (`DraggableEventCard`, `DroppableDayColumn`) et les tests unitaires
 * du helper `applyScheduleDayDrag`.
 */

export const WEEK_DAYS = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"] as const;

export type WeekDay = (typeof WEEK_DAYS)[number];

export type ScheduleEvent = {
  id: string;
  day: WeekDay;
  hour: string;
  title: string;
  category: string;
  ritual: boolean;
};
