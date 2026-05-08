"use client";

/**
 * WorkersMesh — visualisation force-directed des workers Shugu (Sprint mos-A iter 2).
 *
 * Rend un graphe radial : 1 nœud central (`shugu_persona_brain`) connecté à 6
 * nœuds satellites. Les arêtes sont des liens 1-to-many. L'animation force-graph
 * (d3-force) équilibre les positions automatiquement.
 *
 * Halo pulsant :
 *   - chaque nœud porte un timestamp `lastActivityAt` (ms epoch).
 *   - on dessine en `nodeCanvasObject` un halo dont l'alpha décroît sur 2s.
 *   - mode `'after'` : on rend par-dessus le draw par défaut, donc on garde
 *     le cercle natif + on ajoute la pulsation. Plus simple à raisonner que
 *     `'replace'` (qui force à redessiner cercle + label).
 *
 * Le composant est `dynamic({ ssr: false })` côté `_client.tsx` — `ForceGraph2D`
 * touche `window` à l'import. Ici on import direct : ce module sera lui-même
 * importé via dynamic, donc jamais résolu côté server.
 *
 * Limites connues (acceptables pour iter 2) :
 *   - dimensions hardcodées via prop `width`/`height` ; si l'utilisateur
 *     redimensionne la fenêtre, le graphe ne s'adapte pas. Itération suivante
 *     branchera un ResizeObserver.
 *   - pas d'interactivité (click/drag) : on désactive `enableNodeDrag` pour
 *     que le mesh garde sa forme radiale prévisible.
 */

import { useMemo, useRef } from "react";
import ForceGraph2D, {
  type ForceGraphMethods,
  type NodeObject,
} from "react-force-graph-2d";

/** Durée du halo (ms) — au-delà, l'alpha = 0 et l'effet disparaît. */
export const HALO_DURATION_MS = 2000;

/**
 * Forme d'un nœud worker. `id` est l'identifiant unique passé au force-graph
 * (on utilise le nom du worker — il est unique dans le set affiché).
 *
 * `lastActivityAt` est mis à jour par le parent dès qu'un event SSE matche
 * ce worker. `null` = aucun event encore reçu pour ce worker.
 */
export type WorkerNode = {
  id: string;
  isCenter: boolean;
  lastActivityAt: number | null;
};

export type WorkerLink = {
  source: string;
  target: string;
};

export type WorkersMeshProps = {
  nodes: WorkerNode[];
  links: WorkerLink[];
  /** Heure courante (ms epoch) — passée par le parent pour driver les halos sans setState pendant render. */
  now: number;
  width: number;
  height: number;
};

/** Couleurs harmonisées avec le thème admin (saumon = accent, cream = idle). */
const COLOR_CENTER = "#E07A5F";
const COLOR_SATELLITE = "#F5F0E6";
const COLOR_HALO = "rgba(224, 122, 95, ${a})";
const COLOR_LINK = "rgba(245, 240, 230, 0.18)";

/**
 * Dessine un halo concentrique pulsant autour du nœud. L'alpha décroît
 * linéairement de 0.55 → 0 sur `HALO_DURATION_MS`. Le rayon croît de
 * 1.6× → 3.0× la taille du nœud pour l'effet "ondulation".
 *
 * Appelé par force-graph dans le système de coordonnées graph (pas screen),
 * d'où le multiplicateur `globalScale` négligé ici (le rayon en unités graph
 * reste cohérent quel que soit le zoom).
 */
function paintHalo(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  baseRadius: number,
  ageMs: number,
): void {
  if (ageMs >= HALO_DURATION_MS) return;
  const progress = ageMs / HALO_DURATION_MS; // 0 → 1
  const alpha = 0.55 * (1 - progress);
  const radius = baseRadius * (1.6 + 1.4 * progress);
  ctx.beginPath();
  ctx.arc(x, y, radius, 0, 2 * Math.PI, false);
  ctx.strokeStyle = COLOR_HALO.replace("${a}", alpha.toFixed(3));
  ctx.lineWidth = 1.5;
  ctx.stroke();
}

export function WorkersMesh({ nodes, links, now, width, height }: WorkersMeshProps) {
  const graphRef = useRef<ForceGraphMethods<WorkerNode, WorkerLink>>();

  // Le force-graph mute le tableau qu'on lui passe (assigne `x`, `y`, `vx`,
  // `vy`). Pour éviter que React détecte de la "mutation contrôlée" et
  // réagisse en boucle, on stabilise la référence des données : tant que la
  // liste de noms ne change pas, on ne remet pas un nouveau tableau.
  const nodesKey = nodes.map((n) => n.id).join(",");
  const linksKey = links.map((l) => `${l.source}->${l.target}`).join(",");
  const graphData = useMemo(
    () => ({
      nodes: nodes.map((n) => ({ ...n })),
      links: links.map((l) => ({ ...l })),
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [nodesKey, linksKey],
  );

  return (
    <div
      data-testid="observatory-mesh-canvas-wrap"
      style={{ width, height }}
      className="relative rounded-xl overflow-hidden border border-white/5 bg-black/40"
    >
      <ForceGraph2D<WorkerNode, WorkerLink>
        ref={graphRef}
        graphData={graphData}
        width={width}
        height={height}
        backgroundColor="rgba(0,0,0,0)"
        nodeRelSize={6}
        nodeColor={(n) => (n.isCenter ? COLOR_CENTER : COLOR_SATELLITE)}
        nodeLabel={(n) => n.id}
        nodeVal={(n) => (n.isCenter ? 4 : 2)}
        linkColor={() => COLOR_LINK}
        linkWidth={1}
        enableNodeDrag={false}
        enableZoomInteraction={false}
        enablePanInteraction={false}
        cooldownTicks={120}
        nodeCanvasObjectMode={() => "after"}
        nodeCanvasObject={(node: NodeObject<WorkerNode>, ctx) => {
          // Label sous le nœud — petit + monospace pour cohérence console.
          const x = node.x ?? 0;
          const y = node.y ?? 0;
          ctx.font = "10px JetBrains Mono, ui-monospace, monospace";
          ctx.textAlign = "center";
          ctx.textBaseline = "top";
          ctx.fillStyle = "rgba(245, 240, 230, 0.8)";
          ctx.fillText(node.id, x, y + (node.isCenter ? 14 : 10));
          // Halo si event récent.
          if (node.lastActivityAt !== null && node.lastActivityAt !== undefined) {
            const ageMs = now - node.lastActivityAt;
            if (ageMs >= 0 && ageMs < HALO_DURATION_MS) {
              const baseRadius = node.isCenter ? 12 : 8;
              paintHalo(ctx, x, y, baseRadius, ageMs);
            }
          }
        }}
      />
    </div>
  );
}
