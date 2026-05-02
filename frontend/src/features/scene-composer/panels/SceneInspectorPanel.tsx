/**
 * SceneInspectorPanel — inspection et édition des éléments de la scène.
 *
 * Responsabilité unique : composer les sous-composants d'inspection,
 * gérer les sélecteurs store et le chargement des métadonnées de scène.
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

import { useEffect, useMemo, useState } from "react";
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
} from "../store/useSceneComposerStore";
import { TransformSection } from "./inspector/TransformSection";
import {
  PANEL_STYLE,
  HEADER_STYLE,
  SECTION_STYLE,
  LABEL_STYLE,
  VALUE_STYLE,
  JSON_STYLE,
} from "./inspector/inspector-styles";

// ─── Sous-composants locaux ───────────────────────────────────────────────────

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
  const propInstanceSelector = useMemo(
    () => (selectedMeshId ? selectPropInstance(selectedMeshId) : () => undefined),
    [selectedMeshId],
  );
  const selectedPropInstance = useSceneComposerStore(propInstanceSelector);

  const [scene, setScene] = useState<AuthoredSceneOut | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Load scène seulement si aucun mesh n'est sélectionné.
  /* eslint-disable react-hooks/set-state-in-effect -- FIXME P5: fetch-on-selection-change pattern, refactor to useReducer when adopting data lib */
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
  /* eslint-enable react-hooks/set-state-in-effect */

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
