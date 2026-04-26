/**
 * AssetSection — section repliable générique du catalogue d'assets.
 *
 * Responsabilité unique : afficher un en-tête repliable avec count badge
 * et mapper les items via un `renderEntry` fourni par le parent.
 * Le parent reste responsable du rendu spécifique par type d'asset
 * (chaque type a des champs différents : sidecars, duration, loop, etc.).
 *
 * Extraction de AssetCataloguePanel.tsx (Phase E5.3.1 — M2 fix).
 * Pattern `renderEntry` : évite une prop union complexe tout en restant
 * typé et extensible pour les types futurs (E5.4+).
 *
 * @module panels/catalogue/AssetSection
 */

import type { ReactNode } from "react";
import {
  SECTION_HEADER,
  COUNT_BADGE,
} from "./catalogue-styles";

// ─── Types ────────────────────────────────────────────────────────────────────

export interface AssetSectionProps<T> {
  /** Titre affiché dans l'en-tête de section. */
  title: string;
  /** Items à afficher dans la section. */
  items: T[];
  /** Si `true`, la section est ouverte (contenu visible). */
  open: boolean;
  /** Appelé lors d'un clic sur l'en-tête pour toggler la section. */
  onToggle: () => void;
  /**
   * Fonction de rendu d'une entrée individuelle.
   * Le parent fournit le JSX adapté à son type d'asset.
   *
   * @example
   * ```tsx
   * renderEntry={(anim) => (
   *   <div key={anim.slug} style={ENTRY_STYLE}>
   *     <span style={SLUG_STYLE}>{anim.slug}</span>
   *     {anim.loop && <span>loop</span>}
   *   </div>
   * )}
   * ```
   */
  renderEntry: (item: T, index: number) => ReactNode;
}

// ─── Composant ────────────────────────────────────────────────────────────────

/**
 * Section repliable générique pour le catalogue d'assets.
 *
 * Gère l'affichage de l'en-tête (titre + count badge + chevron toggle)
 * et la liste des entrées via `renderEntry`. Ne connaît pas la structure
 * interne des items — délègue au parent via le pattern render prop.
 *
 * @example
 * ```tsx
 * <AssetSection
 *   title="Animations VRMA"
 *   items={catalog.vrma_animations}
 *   open={openSections.has("anims")}
 *   onToggle={() => toggleSection("anims")}
 *   renderEntry={(anim) => (
 *     <div key={anim.slug} style={ENTRY_STYLE}>
 *       <span style={SLUG_STYLE}>{anim.slug}</span>
 *     </div>
 *   )}
 * />
 * ```
 */
export function AssetSection<T>({
  title,
  items,
  open,
  onToggle,
  renderEntry,
}: AssetSectionProps<T>) {
  return (
    <>
      <div
        style={SECTION_HEADER}
        onClick={onToggle}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") onToggle();
        }}
      >
        <span style={{ color: "#7766cc", fontSize: 10 }}>{open ? "▾" : "▸"}</span>
        <span
          style={{
            fontWeight: 600,
            fontSize: 11,
            color: "#9988dd",
            textTransform: "uppercase",
            letterSpacing: 0.8,
          }}
        >
          {title}
        </span>
        <span style={COUNT_BADGE}>{items.length}</span>
      </div>
      {open && items.map((item, index) => renderEntry(item, index))}
    </>
  );
}
