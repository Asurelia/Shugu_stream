/**
 * TransformSection — section d'édition du transform d'un prop 3D sélectionné.
 *
 * Responsabilité unique : afficher et permettre l'édition des axes XYZ
 * pour position, rotation (degrés) et scale d'un prop 3D.
 * Pousse les modifications dans le store via `updateMeshTransform`.
 *
 * Extraction de SceneInspectorPanel.tsx (Phase E5.3.1 — M2 fix).
 *
 * Convention rotation : degrés dans le store (conversion à la frontière
 * gizmo ↔ store, cohérent avec SceneEditorViewer legacy).
 *
 * @module panels/inspector/TransformSection
 */

import { useSceneComposerStore, type ObjectTransform } from "../../store/useSceneComposerStore";
import { AxisSlider } from "./AxisSlider";
import { SECTION_STYLE, SECTION_TITLE_STYLE } from "./inspector-styles";

// ─── Types ────────────────────────────────────────────────────────────────────

export interface TransformSectionProps {
  /** Transform courant de l'instance (depuis le store). */
  transform: ObjectTransform;
  /** ID de l'instance à mettre à jour dans le store. */
  instanceId: string;
}

// ─── Composant ────────────────────────────────────────────────────────────────

/**
 * Section transform d'un prop sélectionné.
 *
 * Affiche les sliders XYZ pour position, rotation (degrés) et scale.
 * Les valeurs sont lues depuis `transform` (du store) et pushées via
 * `store.updateMeshTransform`.
 *
 * @example
 * ```tsx
 * <TransformSection
 *   transform={selectedPropInstance.transform}
 *   instanceId={selectedMeshId}
 * />
 * ```
 */
export function TransformSection({ transform, instanceId }: TransformSectionProps) {
  const updateMeshTransform = useSceneComposerStore((s) => s.updateMeshTransform);

  const updateAxis = (
    field: keyof ObjectTransform,
    axisIndex: 0 | 1 | 2,
    value: number,
  ) => {
    const current = [...transform[field]] as [number, number, number];
    current[axisIndex] = value;
    updateMeshTransform(instanceId, { [field]: current });
  };

  return (
    <div style={SECTION_STYLE}>
      {/* Position */}
      <div style={SECTION_TITLE_STYLE}>Position</div>
      <AxisSlider
        axis="x"
        value={transform.position[0]}
        min={-10}
        max={10}
        step={0.01}
        onChange={(v) => updateAxis("position", 0, v)}
      />
      <AxisSlider
        axis="y"
        value={transform.position[1]}
        min={-2}
        max={5}
        step={0.01}
        onChange={(v) => updateAxis("position", 1, v)}
      />
      <AxisSlider
        axis="z"
        value={transform.position[2]}
        min={-10}
        max={10}
        step={0.01}
        onChange={(v) => updateAxis("position", 2, v)}
      />

      {/* Rotation (degrés) */}
      <div style={{ ...SECTION_TITLE_STYLE, marginTop: 10 }}>Rotation (°)</div>
      <AxisSlider
        axis="x"
        value={transform.rotation[0]}
        min={-180}
        max={180}
        step={0.5}
        onChange={(v) => updateAxis("rotation", 0, v)}
      />
      <AxisSlider
        axis="y"
        value={transform.rotation[1]}
        min={-180}
        max={180}
        step={0.5}
        onChange={(v) => updateAxis("rotation", 1, v)}
      />
      <AxisSlider
        axis="z"
        value={transform.rotation[2]}
        min={-180}
        max={180}
        step={0.5}
        onChange={(v) => updateAxis("rotation", 2, v)}
      />

      {/* Scale */}
      <div style={{ ...SECTION_TITLE_STYLE, marginTop: 10 }}>Scale</div>
      <AxisSlider
        axis="x"
        value={transform.scale[0]}
        min={0.01}
        max={5}
        step={0.01}
        onChange={(v) => updateAxis("scale", 0, v)}
      />
      <AxisSlider
        axis="y"
        value={transform.scale[1]}
        min={0.01}
        max={5}
        step={0.01}
        onChange={(v) => updateAxis("scale", 1, v)}
      />
      <AxisSlider
        axis="z"
        value={transform.scale[2]}
        min={0.01}
        max={5}
        step={0.01}
        onChange={(v) => updateAxis("scale", 2, v)}
      />
    </div>
  );
}
