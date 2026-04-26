/**
 * catalogue-styles — constantes de styles inline du panneau AssetCatalogue.
 *
 * Responsabilité unique : centraliser tous les styles React.CSSProperties
 * utilisés par AssetCataloguePanel et ses sous-composants.
 * Extraction de AssetCataloguePanel.tsx (Phase E5.3.1 — M2 fix).
 *
 * @module panels/catalogue/catalogue-styles
 */

/** Style du conteneur principal du panneau catalogue. */
export const PANEL_STYLE: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  height: "100%",
  background: "#0d0d14",
  color: "#c8c8d8",
  fontSize: 13,
  fontFamily: "inherit",
  overflowY: "auto",
};

/** Style de l'en-tête du panneau (titre + bouton refresh). */
export const HEADER_STYLE: React.CSSProperties = {
  padding: "8px 12px",
  borderBottom: "1px solid #222230",
  display: "flex",
  alignItems: "center",
  gap: 8,
};

/** Style d'un en-tête de section repliable. */
export const SECTION_HEADER: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 6,
  padding: "6px 12px",
  background: "#111118",
  borderBottom: "1px solid #1a1a28",
  cursor: "pointer",
  userSelect: "none",
};

/** Style d'une entrée de catalogue (non-draggable). */
export const ENTRY_STYLE: React.CSSProperties = {
  padding: "4px 20px",
  borderBottom: "1px solid #0f0f1a",
  fontSize: 12,
  color: "#aaaacc",
  display: "flex",
  alignItems: "center",
  gap: 6,
};

/** Style d'une entrée draggable (hérite de ENTRY_STYLE + cursor grab). */
export const ENTRY_DRAGGABLE_STYLE: React.CSSProperties = {
  ...ENTRY_STYLE,
  cursor: "grab",
  userSelect: "none",
};

/** Style du slug d'un asset (police monospace, couleur discrète). */
export const SLUG_STYLE: React.CSSProperties = {
  fontFamily: "monospace",
  color: "#8899bb",
  fontSize: 11,
};

/** Style du badge count dans l'en-tête de section. */
export const COUNT_BADGE: React.CSSProperties = {
  marginLeft: "auto",
  fontSize: 10,
  color: "#555566",
  background: "#1a1a28",
  padding: "1px 5px",
  borderRadius: 3,
};

/** Style du hint "drag" affiché sur les entrées draggables. */
export const DRAG_HINT_STYLE: React.CSSProperties = {
  fontSize: 9,
  color: "#555566",
  marginLeft: "auto",
  fontStyle: "italic",
};
