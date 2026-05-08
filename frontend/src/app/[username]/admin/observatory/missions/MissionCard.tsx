"use client";

/**
 * MissionCard — carte draggable d'une mission Kanban.
 *
 * Utilise `useDraggable` de `@dnd-kit/core`. Le handle de drag est l'icône
 * `≡` à droite de la carte ; le reste de la zone est aussi listener pour
 * UX "grab partout" (comme Trello). Le PointerSensor a une activation
 * distance de 8px (cf. `_client.tsx`) pour ne pas confondre click et drag.
 *
 * Halo IN_PROGRESS : ring saumon pulsant (`animate-pulse` Tailwind +
 * `ring-pink-300/40`). C'est notre "saumon halo" du spec — couleur Shugu
 * brand secondary (`#fd6c9c`) déclinée en ring.
 */

import { useDraggable } from "@dnd-kit/core";
import { CSS } from "@dnd-kit/utilities";

import type { Mission } from "@/services/adminObservatoryMissionsClient";

type Props = {
  mission: Mission;
};

/** Formatte un coût USD en string compact (ex. `$0.0042`). */
function formatCost(usd: number): string {
  if (usd === 0) return "—";
  if (usd < 0.01) return `$${usd.toFixed(4)}`;
  return `$${usd.toFixed(3)}`;
}

/** Formatte un nombre de tokens en compact (ex. `1.2k`). */
function formatTokens(n: number): string {
  if (n === 0) return "0";
  if (n < 1000) return String(n);
  return `${(n / 1000).toFixed(1)}k`;
}

export function MissionCard({ mission }: Props) {
  const { attributes, listeners, setNodeRef, transform, isDragging } =
    useDraggable({ id: mission.id });

  const inProgress = mission.status === "IN_PROGRESS";

  const style: React.CSSProperties = {
    transform: CSS.Translate.toString(transform),
    opacity: isDragging ? 0.5 : 1,
    cursor: isDragging ? "grabbing" : "grab",
  };

  const totalTokens = mission.tokens_in + mission.tokens_out;

  return (
    <div
      ref={setNodeRef}
      style={style}
      {...listeners}
      {...attributes}
      data-testid={`mission-card-${mission.id}`}
      data-mission-status={mission.status}
      className={[
        "rounded-xl border bg-white/[0.03] p-3 flex flex-col gap-2",
        "border-white/10 hover:border-white/20 transition-colors",
        inProgress
          ? "ring-2 ring-pink-300/40 ring-offset-0 animate-pulse"
          : "",
      ].join(" ")}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="text-[12px] text-shugu-cream font-medium leading-snug min-w-0 flex-1">
          {mission.title}
        </div>
        <span
          aria-hidden
          className="text-shugu-cream-dim text-base shrink-0 select-none"
          title="Glisser pour déplacer"
        >
          ≡
        </span>
      </div>

      <div className="flex items-center gap-1.5 flex-wrap">
        <span
          className="font-mono text-[10px] px-1.5 py-0.5 rounded bg-white/5 text-shugu-cream-dim border border-white/10"
          data-testid={`mission-agent-${mission.id}`}
        >
          {mission.agent}
        </span>
      </div>

      <div className="flex items-center justify-between text-[10px] text-shugu-cream-dim font-mono">
        <span title="Coût LLM cumulé">{formatCost(mission.cost_usd)}</span>
        <span title="Tokens (in + out)">{formatTokens(totalTokens)} tk</span>
      </div>
    </div>
  );
}
