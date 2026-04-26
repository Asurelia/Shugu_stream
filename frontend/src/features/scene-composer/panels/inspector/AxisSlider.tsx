/**
 * AxisSlider — ligne de slider pour un axe XYZ.
 *
 * Responsabilité unique : afficher un label coloré par axe (X/Y/Z),
 * un input range et un input number synchronisés. Appelle `onChange`
 * à chaque modification de l'un ou l'autre contrôle.
 *
 * Extraction de SceneInspectorPanel.tsx (Phase E5.3.1 — M2 fix).
 *
 * @module panels/inspector/AxisSlider
 */

import {
  SLIDER_ROW_STYLE,
  AXIS_LABEL_STYLE,
  SLIDER_STYLE,
  NUMBER_INPUT_STYLE,
} from "./inspector-styles";

// ─── Types ────────────────────────────────────────────────────────────────────

export interface AxisSliderProps {
  /** Axe à afficher — détermine la couleur du label (X rouge, Y vert, Z bleu). */
  axis: "x" | "y" | "z";
  /** Valeur courante du slider. */
  value: number;
  /** Valeur minimale. */
  min: number;
  /** Valeur maximale. */
  max: number;
  /** Pas d'incrémentation. */
  step: number;
  /** Appelé avec la nouvelle valeur à chaque changement. */
  onChange: (v: number) => void;
}

// ─── Composant ────────────────────────────────────────────────────────────────

/**
 * Ligne de slider pour un axe XYZ.
 *
 * Affiche un label coloré par axe, un input range et un input number
 * synchronisés. `onChange` est appelé à chaque modification.
 *
 * @example
 * ```tsx
 * <AxisSlider
 *   axis="x"
 *   value={position[0]}
 *   min={-10} max={10} step={0.01}
 *   onChange={(v) => updateAxis("position", 0, v)}
 * />
 * ```
 */
export function AxisSlider({
  axis,
  value,
  min,
  max,
  step,
  onChange,
}: AxisSliderProps) {
  const label = axis.toUpperCase();
  return (
    <div style={SLIDER_ROW_STYLE}>
      <span style={AXIS_LABEL_STYLE(axis)}>{label}</span>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        style={SLIDER_STYLE}
        onChange={(e) => onChange(parseFloat(e.target.value))}
      />
      <input
        type="number"
        min={min}
        max={max}
        step={step}
        value={Number.isFinite(value) ? parseFloat(value.toFixed(3)) : 0}
        style={NUMBER_INPUT_STYLE}
        onChange={(e) => {
          const v = parseFloat(e.target.value);
          if (Number.isFinite(v)) onChange(v);
        }}
      />
    </div>
  );
}
