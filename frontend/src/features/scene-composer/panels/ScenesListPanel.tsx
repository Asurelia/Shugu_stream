/**
 * ScenesListPanel — liste + filtre + sélection des AuthoredScenes.
 *
 * Responsabilité unique : afficher la liste des scènes authoriées disponibles,
 * permettre la recherche par nom, et mettre à jour `selectedSceneId` dans le
 * store Scene Composer au clic.
 *
 * Données : fetchées via `scenesClient.listScenes()` au mount + bouton refresh.
 * Sélection : propagée via `useSceneComposerStore.setSelectedSceneId`.
 *
 * OUT OF SCOPE E5.2 : bouton "Créer scène" (E5.3), drag-drop (E5.3).
 *
 * @module panels/ScenesListPanel
 */

import { useCallback, useEffect, useState } from "react";
import {
  listScenes,
  type AuthoredSceneOut,
  ScenesClientError,
} from "../api/scenesClient";
import {
  useSceneComposerStore,
  selectSelectedSceneId,
} from "../store/useSceneComposerStore";

// ─── Styles inline (pas de module CSS pour E5.2 — charte cohérente avec
//     SceneEditorApp qui utilise des styles globals) ─────────────────────────

const PANEL_STYLE: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  height: "100%",
  background: "#0d0d14",
  color: "#c8c8d8",
  fontSize: 13,
  fontFamily: "inherit",
};

const HEADER_STYLE: React.CSSProperties = {
  padding: "8px 12px",
  borderBottom: "1px solid #222230",
  display: "flex",
  alignItems: "center",
  gap: 8,
};

const SEARCH_STYLE: React.CSSProperties = {
  flex: 1,
  background: "#1a1a28",
  border: "1px solid #333344",
  borderRadius: 4,
  padding: "4px 8px",
  color: "#c8c8d8",
  fontSize: 12,
  outline: "none",
};

const LIST_STYLE: React.CSSProperties = {
  flex: 1,
  overflowY: "auto",
  padding: "4px 0",
};

const ITEM_BASE: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  padding: "6px 12px",
  cursor: "pointer",
  borderLeft: "2px solid transparent",
  gap: 2,
};

const ITEM_SELECTED: React.CSSProperties = {
  ...ITEM_BASE,
  background: "#1a1a30",
  borderLeftColor: "#6655ee",
};

const ITEM_HOVER: React.CSSProperties = {
  ...ITEM_BASE,
  background: "#15151f",
};

const TAG_STYLE: React.CSSProperties = {
  display: "inline-block",
  fontSize: 10,
  padding: "1px 5px",
  borderRadius: 3,
  background: "#2a2a40",
  color: "#8888aa",
};

// ─── Composant ────────────────────────────────────────────────────────────────

/**
 * Panneau liste des scènes authoriées avec filtre texte et sélection.
 */
export function ScenesListPanel() {
  const selectedSceneId = useSceneComposerStore(selectSelectedSceneId);
  const setSelectedSceneId = useSceneComposerStore(
    (s) => s.setSelectedSceneId,
  );

  const [scenes, setScenes] = useState<AuthoredSceneOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const [hoveredId, setHoveredId] = useState<string | null>(null);

  const fetchScenes = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await listScenes();
      setScenes(data);
    } catch (err) {
      if (err instanceof ScenesClientError) {
        setError(`Erreur ${err.status} : ${err.detail}`);
      } else {
        setError("Erreur réseau inattendue.");
      }
    } finally {
      setLoading(false);
    }
  }, []);

  /* eslint-disable react-hooks/set-state-in-effect -- FIXME P5: fetch-on-mount pattern, refactor to useReducer when adopting data lib */
  useEffect(() => {
    void fetchScenes();
  }, [fetchScenes]);
  /* eslint-enable react-hooks/set-state-in-effect */

  const filtered = scenes.filter((s) =>
    s.name.toLowerCase().includes(filter.toLowerCase()),
  );

  return (
    <div style={PANEL_STYLE}>
      {/* En-tête */}
      <div style={HEADER_STYLE}>
        <span style={{ fontWeight: 600, fontSize: 11, color: "#7766cc", textTransform: "uppercase", letterSpacing: 1 }}>
          Scènes
        </span>
        <input
          style={SEARCH_STYLE}
          placeholder="Filtrer…"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          aria-label="Filtrer les scènes"
        />
        <button
          style={{
            background: "none",
            border: "none",
            color: "#7766cc",
            cursor: "pointer",
            fontSize: 14,
            padding: "0 4px",
          }}
          onClick={() => void fetchScenes()}
          title="Rafraîchir"
          aria-label="Rafraîchir la liste des scènes"
        >
          ↻
        </button>
      </div>

      {/* Corps */}
      <div style={LIST_STYLE} role="listbox" aria-label="Scènes">
        {loading && (
          <div style={{ padding: "12px", color: "#555566", textAlign: "center" }}>
            Chargement…
          </div>
        )}

        {!loading && error && (
          <div style={{ padding: "12px", color: "#cc4444", fontSize: 12 }}>
            {error}
          </div>
        )}

        {!loading && !error && filtered.length === 0 && (
          <div style={{ padding: "12px", color: "#555566", textAlign: "center" }}>
            {filter ? "Aucune scène correspondante." : "Aucune scène configurée."}
          </div>
        )}

        {!loading && !error &&
          filtered.map((scene) => {
            const isSelected = scene.id === selectedSceneId;
            const isHovered = scene.id === hoveredId;
            const itemStyle = isSelected
              ? ITEM_SELECTED
              : isHovered
              ? ITEM_HOVER
              : ITEM_BASE;

            return (
              <div
                key={scene.id}
                style={itemStyle}
                onClick={() => setSelectedSceneId(scene.id)}
                onMouseEnter={() => setHoveredId(scene.id)}
                onMouseLeave={() => setHoveredId(null)}
                role="option"
                tabIndex={-1}
                aria-selected={isSelected}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    setSelectedSceneId(scene.id);
                  }
                }}
              >
                <span style={{ fontWeight: isSelected ? 600 : 400 }}>
                  {scene.name}
                </span>
                <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
                  <span style={TAG_STYLE}>{scene.type}</span>
                  {!scene.enabled && (
                    <span style={{ ...TAG_STYLE, color: "#cc6644" }}>
                      désactivée
                    </span>
                  )}
                </div>
              </div>
            );
          })}
      </div>
    </div>
  );
}
