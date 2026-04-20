import { EventCard } from "@/features/creator-home/shared";

/**
 * EventCards flottantes gauche — remplace SupportersRail. Valeurs mockées
 * identiques à l'ancien composant pour zéro régression de contenu.
 */
export function FloatingEvents() {
  return (
    <div
      className="hidden lg:flex fixed flex-col pointer-events-none"
      style={{ left: 24, top: 140, gap: 10, maxWidth: 240, zIndex: 3 }}
    >
      <div className="pointer-events-auto">
        <EventCard
          icon="+"
          label="Latest Subscriber"
          value="Nebula_Walker_99"
          accent="primary"
          style={{ minWidth: 220 }}
        />
      </div>
      <div className="pointer-events-auto">
        <EventCard
          icon="$"
          label="Latest Tip"
          value="$50.00 — Anon"
          accent="tertiary"
          style={{ minWidth: 220 }}
        />
      </div>
    </div>
  );
}
