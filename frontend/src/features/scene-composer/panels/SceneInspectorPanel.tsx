/**
 * SceneInspectorPanel — inspection et édition des éléments de la scène.
 *
 * Responsabilité unique : afficher et permettre l'édition des propriétés
 * d'un élément sélectionné (scène authoriée ou prop 3D instancié).
 *
 * Extension E5.3 : passe de READ-ONLY (E5.2) à édition complète :
 *   - Aucune sélection → placeholder "sélectionnez"
 *   - Prop 3D sélectionné (`selectedMeshId` non-null) → TransformSection
 *     avec sliders XYZ position/rotation/scale → store.updateMeshTransform
 *   - Scène sélectionnée (`selectedSceneId` non-null, pas de mesh) → affichage
 *     READ-ONLY de la scène (comportement E5.2 conservé)
 *
 * Bidirectionnel : les sliders poussent dans le store via `updateMeshTransform`,
 * qui alimente le sync store → Three.js dans SceneComposerViewer. Le gizmo
 * pousse dans le même store → les sliders reflètent la pose du gizmo.
 *
 * Sous-composants :
 *   - `<TransformSection />` : sliders XYZ pour position, rotation, scale
 *   - `<SceneMetadataSection />` : affichage READ-ONLY metadata scène (E5.2)
 *
 * @module panels/SceneInspectorPanel
 */

import { useEffect, useState } from "react";
import {
  getScene,
  type AuthoredSceneOut,
  ScenesClientError,
} from "../api/scenesClient";
import {
  useSceneComposerStore,
  selectSelectedSceneId,
  selectSelectedMeshId,
  selectPropInstance,
  type ObjectTransform,
} from "../store/useSceneComposerStore";

// ─── Styles ───────────────────────────────────────────────────────────────────

const PANEL_STYLE: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  height: "100%",
  background: "#0d0d14",
  color: "#c8c8d8",
  fontSize: 13,
  fontFamily: "inherit",
  overflowY: "auto",
};

const HEADER_STYLE: React.CSSProperties = {
  padding: "8px 12px",
  borderBottom: "1px solid #222230",
  fontWeight: 600,
  fontSize: 11,
  color: "#7766cc",
  textTransform: "uppercase",
  letterSpacing: 1,
};

const SECTION_STYLE: React.CSSProperties = {
  padding: "8px 12px",
  borderBottom: "1px solid #151520",
};

const SECTION_TITLE_STYLE: React.CSSProperties = {
  fontSize: 10,
  color: "#7766cc",
  textTransform: "uppercase",
  letterSpacing: 0.8,
  fontWeight: 600,
  marginBottom: 8,
};

const LABEL_STYLE: React.CSSProperties = {
  fontSize: 10,
  color: "#666688",
  textTransform: "uppercase",
  letterSpacing: 0.8,
  marginBottom: 2,
};

const VALUE_STYLE: React.CSSProperties = {
  color: "#c0c0d8",
  wordBreak: "break-all",
};

const JSON_STYLE: React.CSSProperties = {
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

const SLIDER_ROW_STYLE: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "20px 1fr 55px",
  alignItems: "center",
  gap: 6,
  marginBottom: 4,
};

const AXIS_LABEL_STYLE = (axis: "x" | "y" | "z"): React.CSSProperties => ({
  fontSize: 10,
  fontWeight: 700,
  color: axis === "x" ? "#cc4455" : axis === "y" ? "#44cc66" : "#4488cc",
  fontFamily: "monospace",
});

const SLIDER_STYLE: React.CSSProperties = {
  width: "100%",
  accentColor: "#7766cc",
  cursor: "pointer",
};

const NUMBER_INPUT_STYLE: React.CSSProperties = {
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

// ─── Sous-composants ──────────────────────────────────────────────────────────

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div style={{ marginBottom: 8 }}>
      <div style={LABEL_STYLE}>{label}</div>
      <div style={VALUE_STYLE}>{children}</div>
    </div>
  );
}

function JsonField({ label, value }: { label: string; value: unknown }) {
  if (value === null || value === undefined) {
    return (
      <div style={{ marginBottom: 8 }}>
        <div style={LABEL_STYLE}>{label}</div>
        <div style={{ ...VALUE_STYLE, color: "#444455" }}>—</div>
      </div>
    );
  }
  return (
    <div style={{ marginBottom: 8 }}>
      <div style={LABEL_STYLE}>{label}</div>
      <pre style={JSON_STYLE}>{JSON.stringify(value, null, 2)}</pre>
    </div>
  );
}

/**
 * Ligne de slider pour un axe XYZ.
 *
 * Affiche un label coloré par axe, un input range et un input number
 * synchronisés. `onChange` est appelé à chaque modification.
 */
function AxisSlider({
  axis,
  value,
  min,
  max,
  step,
  onChange,
}: {
  axis: "x" | "y" | "z";
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (v: number) => void;
}) {
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

/**
 * Section transform d'un prop sélectionné.
 *
 * Affiche les sliders XYZ pour position, rotation (degrés) et scale.
 * Les valeurs sont lues depuis `transform` (du store) et pushées via
 * `onUpdate` → `store.updateMeshTransform`.
 *
 * Convention rotation : degrés dans le store (conversion à la frontière
 * gizmo ↔ store, cohérent avec SceneEditorViewer legacy).
 */
function TransformSection({
  transform,
  instanceId,
}: {
  transform: ObjectTransform;
  instanceId: string;
}) {
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

/**
 * Section metadata scène (READ-ONLY — comportement E5.2 conservé).
 */
function SceneMetadataSection({ scene }: { scene: AuthoredSceneOut }) {
  const createdAt = new Date(scene.created_at).toLocaleString("fr-FR");
  const updatedAt = new Date(scene.updated_at).toLocaleString("fr-FR");

  return (
    <>
      <div style={SECTION_STYLE}>
        <Field label="Nom">{scene.name}</Field>
        <Field label="Type">{scene.type}</Field>
        <Field label="Activée">{scene.enabled ? "Oui" : "Non"}</Field>
        {scene.description && (
          <Field label="Description">{scene.description}</Field>
        )}
        <Field label="Propriétaire">{scene.owner_username}</Field>
        <Field label="ID">{scene.id}</Field>
        <Field label="Créée">{createdAt}</Field>
        <Field label="Mise à jour">{updatedAt}</Field>
      </div>

      <div style={SECTION_STYLE}>
        <JsonField label="Triggers" value={scene.triggers.length > 0 ? scene.triggers : null} />
        <JsonField label="État statique" value={scene.static_state} />
        <JsonField label="Keyframes timeline" value={scene.timeline_keyframes} />
        <JsonField label="Config boucle" value={scene.loop_config} />
      </div>
    </>
  );
}

// ─── Composant principal ──────────────────────────────────────────────────────

/**
 * Panneau d'inspection et d'édition du Scene Composer.
 *
 * Priorité de sélection :
 *   1. Mesh 3D sélectionné (`selectedMeshId`) → TransformSection éditable
 *   2. Scène sélectionnée (`selectedSceneId`) → métadonnées READ-ONLY
 *   3. Aucune sélection → placeholder
 */
export function SceneInspectorPanel() {
  const selectedSceneId = useSceneComposerStore(selectSelectedSceneId);
  const selectedMeshId = useSceneComposerStore(selectSelectedMeshId);

  // Sélecteur dynamique pour l'instance de prop sélectionnée.
  const selectedPropInstance = useSceneComposerStore(
    selectedMeshId ? selectPropInstance(selectedMeshId) : () => undefined,
  );

  const [scene, setScene] = useState<AuthoredSceneOut | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Load scène seulement si aucun mesh n'est sélectionné.
  useEffect(() => {
    if (selectedMeshId) {
      // Mesh sélectionné — pas besoin de charger la scène.
      setScene(null);
      setError(null);
      return;
    }

    if (!selectedSceneId) {
      setScene(null);
      setError(null);
      return;
    }

    setLoading(true);
    setError(null);

    getScene(selectedSceneId)
      .then((data) => {
        setScene(data);
      })
      .catch((err) => {
        if (err instanceof ScenesClientError) {
          setError(`Erreur ${err.status} : ${err.detail}`);
        } else {
          setError("Erreur réseau inattendue.");
        }
        setScene(null);
      })
      .finally(() => {
        setLoading(false);
      });
  }, [selectedSceneId, selectedMeshId]);

  // ── Cas 1 : Mesh 3D sélectionné ─────────────────────────────────────────
  if (selectedMeshId && selectedPropInstance) {
    return (
      <div style={PANEL_STYLE}>
        <div style={HEADER_STYLE}>Inspecteur — Prop 3D</div>
        <div style={SECTION_STYLE}>
          <Field label="ID">{selectedMeshId}</Field>
          <Field label="Asset">{selectedPropInstance.assetSlug}</Field>
        </div>
        <TransformSection
          transform={selectedPropInstance.transform}
          instanceId={selectedMeshId}
        />
      </div>
    );
  }

  // ── Cas 2 : Aucune sélection ─────────────────────────────────────────────
  if (!selectedSceneId && !selectedMeshId) {
    return (
      <div style={{ ...PANEL_STYLE, alignItems: "center", justifyContent: "center" }}>
        <div style={{ color: "#444455", textAlign: "center", padding: 24 }}>
          Sélectionnez une scène dans la liste<br />ou un prop 3D dans le viewer.
        </div>
      </div>
    );
  }

  // ── Cas 3 : Chargement de la scène ───────────────────────────────────────
  if (loading) {
    return (
      <div style={{ ...PANEL_STYLE, alignItems: "center", justifyContent: "center" }}>
        <div style={{ color: "#555566" }}>Chargement…</div>
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ ...PANEL_STYLE, padding: 16 }}>
        <div style={{ color: "#cc4444" }}>{error}</div>
      </div>
    );
  }

  if (!scene) return null;

  // ── Cas 4 : Scène sélectionnée (READ-ONLY) ───────────────────────────────
  return (
    <div style={PANEL_STYLE}>
      <div style={HEADER_STYLE}>Inspecteur</div>
      <SceneMetadataSection scene={scene} />
    </div>
  );
}
