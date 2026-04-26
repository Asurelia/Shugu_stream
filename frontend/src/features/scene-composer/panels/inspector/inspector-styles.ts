/**
 * inspector-styles — constantes de styles inline du panneau Inspector.
 *
 * Responsabilité unique : centraliser tous les styles React.CSSProperties
 * utilisés par SceneInspectorPanel et ses sous-composants.
 * Extraction de SceneInspectorPanel.tsx (Phase E5.3.1 — M2 fix).
 *
 * @module panels/inspector/inspector-styles
 */

/** Style du conteneur principal du panneau. */
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

/** Style de l'en-tête du panneau. */
export const HEADER_STYLE: React.CSSProperties = {
  padding: "8px 12px",
  borderBottom: "1px solid #222230",
  fontWeight: 600,
  fontSize: 11,
  color: "#7766cc",
  textTransform: "uppercase",
  letterSpacing: 1,
};

/** Style des sections du panneau. */
export const SECTION_STYLE: React.CSSProperties = {
  padding: "8px 12px",
  borderBottom: "1px solid #151520",
};

/** Style du titre de chaque section. */
export const SECTION_TITLE_STYLE: React.CSSProperties = {
  fontSize: 10,
  color: "#7766cc",
  textTransform: "uppercase",
  letterSpacing: 0.8,
  fontWeight: 600,
  marginBottom: 8,
};

/** Style des labels de champs. */
export const LABEL_STYLE: React.CSSProperties = {
  fontSize: 10,
  color: "#666688",
  textTransform: "uppercase",
  letterSpacing: 0.8,
  marginBottom: 2,
};

/** Style des valeurs de champs. */
export const VALUE_STYLE: React.CSSProperties = {
  color: "#c0c0d8",
  wordBreak: "break-all",
};

/** Style des blocs JSON pré-formatés. */
export const JSON_STYLE: React.CSSProperties = {
  background: "#101018",
  borderRadius: 4,
  padding: "6px 8px",
  fontSize: 11,
  color: "#99aacc",
  whiteSpace: "pre-wrap",
  overflowX: "auto",
  fontFamily: "monospace",
  maxHeight: 200,
  overflowY: "auto",
};

/** Style de la ligne de slider (grille label + range + number). */
export const SLIDER_ROW_STYLE: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "20px 1fr 55px",
  alignItems: "center",
  gap: 6,
  marginBottom: 4,
};

/** Style du label d'axe coloré selon l'axe (X rouge, Y vert, Z bleu). */
export const AXIS_LABEL_STYLE = (axis: "x" | "y" | "z"): React.CSSProperties => ({
  fontSize: 10,
  fontWeight: 700,
  color: axis === "x" ? "#cc4455" : axis === "y" ? "#44cc66" : "#4488cc",
  fontFamily: "monospace",
});

/** Style de l'input range. */
export const SLIDER_STYLE: React.CSSProperties = {
  width: "100%",
  accentColor: "#7766cc",
  cursor: "pointer",
};

/** Style de l'input number synchronisé avec le slider. */
export const NUMBER_INPUT_STYLE: React.CSSProperties = {
  background: "#101018",
  border: "1px solid #2a2a40",
  borderRadius: 3,
  color: "#c0c0d8",
  fontSize: 11,
  fontFamily: "monospace",
  padding: "2px 4px",
  width: "100%",
  textAlign: "right",
};

/**
 * Objet groupé pour import unique depuis les sous-composants.
 *
 * @example
 * ```tsx
 * import { inspectorStyles } from "./inspector-styles";
 * // Puis : style={inspectorStyles.PANEL_STYLE}
 * ```
 */
export const inspectorStyles = {
  PANEL_STYLE,
  HEADER_STYLE,
  SECTION_STYLE,
  SECTION_TITLE_STYLE,
  LABEL_STYLE,
  VALUE_STYLE,
  JSON_STYLE,
  SLIDER_ROW_STYLE,
  AXIS_LABEL_STYLE,
  SLIDER_STYLE,
  NUMBER_INPUT_STYLE,
} as const;
