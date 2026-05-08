"use client";

/**
 * MissionFilters — barre de filtre par agent + stats header du Kanban.
 *
 * Composant contrôlé : reçoit la liste d'agents distincts (extraite par
 * le parent) et la sélection courante. Émet via `onChange(agent | null)`.
 *
 * Stats : nombre de missions visibles, coût USD cumulé, tokens cumulés.
 * Affichage compact en pills pour rester aligné avec le design Liquid
 * Glass des autres pages admin.
 */

import { GlassPill } from "@/features/liquid-glass/primitives";

type Props = {
  agents: string[];
  selected: string | null;
  onChange: (agent: string | null) => void;
  totalMissions: number;
  totalCostUsd: number;
  totalTokens: number;
};

function formatCostUsd(usd: number): string {
  if (usd === 0) return "$0";
  if (usd < 0.01) return `$${usd.toFixed(4)}`;
  return `$${usd.toFixed(3)}`;
}

function formatTokens(n: number): string {
  if (n === 0) return "0";
  if (n < 1000) return String(n);
  return `${(n / 1000).toFixed(1)}k`;
}

export function MissionFilters({
  agents,
  selected,
  onChange,
  totalMissions,
  totalCostUsd,
  totalTokens,
}: Props) {
  return (
    <div
      data-testid="missions-filters"
      className="flex items-center justify-between gap-3 flex-wrap"
    >
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-[11px] text-shugu-cream-dim font-mono uppercase tracking-[0.14em]">
          Agent
        </span>
        <button
          type="button"
          onClick={() => onChange(null)}
          aria-pressed={selected === null}
          className={[
            "text-[11px] px-2.5 py-1 rounded-full border transition-colors",
            selected === null
              ? "bg-white/[0.08] border-white/20 text-shugu-cream"
              : "border-white/10 text-shugu-cream-dim hover:text-shugu-cream",
          ].join(" ")}
        >
          tous
        </button>
        {agents.map((agent) => (
          <button
            key={agent}
            type="button"
            onClick={() => onChange(agent)}
            aria-pressed={selected === agent}
            data-testid={`mission-filter-${agent}`}
            className={[
              "text-[11px] px-2.5 py-1 rounded-full border font-mono transition-colors",
              selected === agent
                ? "bg-white/[0.08] border-white/20 text-shugu-cream"
                : "border-white/10 text-shugu-cream-dim hover:text-shugu-cream",
            ].join(" ")}
          >
            {agent}
          </button>
        ))}
      </div>

      <div className="flex items-center gap-2 flex-wrap">
        <GlassPill tone="default" data-testid="missions-stat-count">
          {totalMissions} missions
        </GlassPill>
        <GlassPill tone="primary" data-testid="missions-stat-cost">
          {formatCostUsd(totalCostUsd)}
        </GlassPill>
        <GlassPill tone="tertiary" data-testid="missions-stat-tokens">
          {formatTokens(totalTokens)} tokens
        </GlassPill>
      </div>
    </div>
  );
}
