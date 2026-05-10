/**
 * Tests unitaires — `applyScheduleDayDrag` (Schedule DnD jour-only).
 *
 * Stratégie : tester la logique pure sans monter de composant React.
 * `applyScheduleDayDrag` est le seul endroit où les règles métier du drag
 * sont encodées ; `handleDragEnd` dans `_client.tsx` est un simple wrapper
 * de 3 lignes qui appelle cette fonction et passe le résultat à `setEvents`.
 *
 * Cas couverts :
 *   1. Drop sur une colonne différente → met à jour le jour.
 *   2. Drop sur la même colonne → no-op (référence identique).
 *   3. Drop hors zone (overId = null) → no-op.
 *   4. overId sans préfixe `day-` invalide → no-op.
 *   5. overId avec jour invalide → no-op.
 */

import { describe, expect, it } from "vitest";
import { applyScheduleDayDrag } from "../scheduleDndLogic";
import type { ScheduleEvent } from "../types";

const BASE_EVENTS: ScheduleEvent[] = [
  { id: "1", day: "Lun", hour: "20:00", title: "Chill Coding",     category: "IRL",  ritual: true  },
  { id: "2", day: "Mer", hour: "21:00", title: "Baldur's Gate 3",  category: "Game", ritual: false },
  { id: "3", day: "Sam", hour: "18:00", title: "Drawing Aura",     category: "Art",  ritual: true  },
];

describe("applyScheduleDayDrag", () => {
  it("met à jour le jour quand le drop est sur une colonne différente", () => {
    const result = applyScheduleDayDrag(BASE_EVENTS, "1", "day-Jeu");

    // L'évènement 1 doit maintenant être au Jeudi.
    const moved = result.find((e) => e.id === "1");
    expect(moved?.day).toBe("Jeu");

    // Les autres évènements ne bougent pas.
    expect(result.find((e) => e.id === "2")?.day).toBe("Mer");
    expect(result.find((e) => e.id === "3")?.day).toBe("Sam");

    // La liste doit être une nouvelle référence (immutabilité).
    expect(result).not.toBe(BASE_EVENTS);
  });

  it("retourne la même référence si drop sur la même colonne (no-op)", () => {
    // L'évènement 2 est déjà au Mercredi.
    const result = applyScheduleDayDrag(BASE_EVENTS, "2", "day-Mer");

    // Référence identique — pas de re-render inutile.
    expect(result).toBe(BASE_EVENTS);
  });

  it("retourne la même référence si drop hors zone (overId null)", () => {
    const result = applyScheduleDayDrag(BASE_EVENTS, "1", null);
    expect(result).toBe(BASE_EVENTS);
  });

  it("retourne la même référence si overId ne commence pas par 'day-'", () => {
    const result = applyScheduleDayDrag(BASE_EVENTS, "1", "col-Lun");
    expect(result).toBe(BASE_EVENTS);
  });

  it("retourne la même référence si le jour extrait est invalide", () => {
    const result = applyScheduleDayDrag(BASE_EVENTS, "1", "day-INVALID");
    expect(result).toBe(BASE_EVENTS);
  });
});
