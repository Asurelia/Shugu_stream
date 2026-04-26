/**
 * SceneInspectorPanel — affichage READ-ONLY d'une AuthoredScene sélectionnée.
 *
 * Responsabilité unique : afficher les champs d'une scène authoriée en mode
 * lecture (pas d'édition en E5.2). Les champs complexes (`triggers`,
 * `static_state`, `timeline_keyframes`, `loop_config`) sont affichés en JSON
 * formaté — l'éditeur structuré est prévu pour E5.3+.
 *
 * NOTE : l'affichage JSON pour les champs complexes est intentionnel pour E5.2.
 * Une interface d'édition structurée (discriminated union `TriggerSpec`, etc.)
 * sera implémentée en E5.3 avec les gizmos.
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

// ─── Helpers ──────────────────────────────────────────────────────────────────

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

// ─── Composant ────────────────────────────────────────────────────────────────

/**
 * Panneau d'inspection READ-ONLY de la scène sélectionnée.
 *
 * Affiche les métadonnées et la configuration de la scène. Pas d'édition en
 * E5.2 — voir E5.3 pour l'éditeur structuré des triggers et states.
 */
export function SceneInspectorPanel() {
  const selectedSceneId = useSceneComposerStore(selectSelectedSceneId);

  const [scene, setScene] = useState<AuthoredSceneOut | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
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
  }, [selectedSceneId]);

  if (!selectedSceneId) {
    return (
      <div style={{ ...PANEL_STYLE, alignItems: "center", justifyContent: "center" }}>
        <div style={{ color: "#444455", textAlign: "center", padding: 24 }}>
          Sélectionnez une scène dans la liste.
        </div>
      </div>
    );
  }

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

  const createdAt = new Date(scene.created_at).toLocaleString("fr-FR");
  const updatedAt = new Date(scene.updated_at).toLocaleString("fr-FR");

  return (
    <div style={PANEL_STYLE}>
      <div style={HEADER_STYLE}>Inspecteur</div>

      {/* Métadonnées */}
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

      {/* Configuration (JSON view — E5.3 ajoutera les éditeurs structurés) */}
      <div style={SECTION_STYLE}>
        <JsonField label="Triggers" value={scene.triggers.length > 0 ? scene.triggers : null} />
        <JsonField label="État statique" value={scene.static_state} />
        <JsonField label="Keyframes timeline" value={scene.timeline_keyframes} />
        <JsonField label="Config boucle" value={scene.loop_config} />
      </div>
    </div>
  );
}
