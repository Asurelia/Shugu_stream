/**
 * AssetCataloguePanel — exploration du catalogue d'assets avec drag-drop.
 *
 * Responsabilité unique : gérer le state loading/error/catalog, fetcher
 * le catalogue au mount et composer les sections via AssetSection.
 *
 * Extension E5.3 : les assets `props_3d` sont rendus draggables (HTML5
 * native drag-drop). Les autres types (VRM, VRMA, VFX, etc.) ont des
 * sémantiques à définir en E5.4+ et restent en lecture seule.
 *
 * Pattern drag-drop : HTML5 natif (cohérent avec `scene-editor/dnd-context.ts`
 * Phase A). Le payload est encodé en JSON dans `dataTransfer` avec le MIME
 * type `application/x-shugu-prop`. Le canvas viewer (useDragDropTarget) lit
 * ce payload au drop.
 *
 * Visual cue : cursor `grab` au survol, `grabbing` pendant le drag.
 *
 * Données : fetchées via `catalogClient.getAssetCatalog()` au mount.
 * Cache 60s côté serveur — rafraîchi sur demande via bouton ↻.
 *
 * @module panels/AssetCataloguePanel
 */

import { useCallback, useEffect, useState } from "react";
import {
  getAssetCatalog,
  type AssetCatalogOut,
  type Prop3DEntry,
  CatalogClientError,
} from "../api/catalogClient";
import { PROP_DRAG_MIME, type PropDragPayload } from "../viewer/interactions/useDragDropTarget";
import { AssetSection } from "./catalogue/AssetSection";
import {
  PANEL_STYLE,
  HEADER_STYLE,
  ENTRY_STYLE,
  ENTRY_DRAGGABLE_STYLE,
  SLUG_STYLE,
  DRAG_HINT_STYLE,
} from "./catalogue/catalogue-styles";

// ─── Sous-composants locaux ───────────────────────────────────────────────────

/**
 * Carte d'asset draggable pour les props 3D.
 *
 * `draggable={true}` + `onDragStart` encode le payload en JSON
 * dans le dataTransfer avec le MIME type `PROP_DRAG_MIME`.
 * `cursor: grab/grabbing` via inline style dynamique.
 */
function DraggablePropCard({ asset }: { asset: Prop3DEntry }) {
  const [isDragging, setIsDragging] = useState(false);

  const handleDragStart = (e: React.DragEvent<HTMLDivElement>) => {
    setIsDragging(true);
    const payload: PropDragPayload = { kind: "prop_3d", asset };
    e.dataTransfer.setData(PROP_DRAG_MIME, JSON.stringify(payload));
    // Fallback MIME pour compatibilité maximale.
    e.dataTransfer.setData("application/json", JSON.stringify(payload));
    e.dataTransfer.effectAllowed = "copy";
  };

  const handleDragEnd = () => {
    setIsDragging(false);
  };

  return (
    <div
      draggable
      onDragStart={handleDragStart}
      onDragEnd={handleDragEnd}
      style={{
        ...ENTRY_DRAGGABLE_STYLE,
        cursor: isDragging ? "grabbing" : "grab",
        opacity: isDragging ? 0.7 : 1,
        background: isDragging ? "#171724" : undefined,
      }}
      title={`Glisser "${asset.slug}" dans le viewer pour l'ajouter à la scène`}
    >
      <span style={{ color: "#cc7744", fontSize: 10 }}>⬡</span>
      <span style={SLUG_STYLE}>{asset.slug}</span>
      <span style={DRAG_HINT_STYLE}>drag</span>
    </div>
  );
}

// ─── Composant ────────────────────────────────────────────────────────────────

type SectionKey = "vrm" | "outfits" | "anims" | "vfx" | "scenes" | "faces" | "cameras" | "props";

/**
 * Panneau catalogue d'assets.
 *
 * Sections repliables — sections VRM et Animations ouvertes par défaut.
 * Section Props 3D ouverte par défaut si des props sont disponibles.
 */
export function AssetCataloguePanel() {
  const [catalog, setCatalog] = useState<AssetCatalogOut | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [openSections, setOpenSections] = useState<Set<SectionKey>>(
    new Set(["vrm", "anims", "props"]),
  );

  const fetchCatalog = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getAssetCatalog();
      setCatalog(data);
    } catch (err) {
      if (err instanceof CatalogClientError) {
        setError(`Erreur ${err.status} : ${err.detail}`);
      } else {
        setError("Erreur réseau inattendue.");
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchCatalog();
  }, [fetchCatalog]);

  function toggleSection(key: SectionKey) {
    setOpenSections((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  }

  return (
    <div style={PANEL_STYLE}>
      {/* En-tête */}
      <div style={HEADER_STYLE}>
        <span
          style={{
            fontWeight: 600,
            fontSize: 11,
            color: "#7766cc",
            textTransform: "uppercase",
            letterSpacing: 1,
          }}
        >
          Assets
        </span>
        <button
          style={{
            background: "none",
            border: "none",
            color: "#7766cc",
            cursor: "pointer",
            fontSize: 14,
            padding: "0 4px",
            marginLeft: "auto",
          }}
          onClick={() => void fetchCatalog()}
          title="Rafraîchir le catalogue"
          aria-label="Rafraîchir le catalogue d'assets"
        >
          ↻
        </button>
      </div>

      {loading && (
        <div style={{ padding: 12, color: "#555566", textAlign: "center" }}>
          Chargement…
        </div>
      )}

      {!loading && error && (
        <div style={{ padding: 12, color: "#cc4444", fontSize: 12 }}>{error}</div>
      )}

      {!loading && !error && catalog && (
        <>
          {/* Props 3D — DRAGGABLES (E5.3) */}
          {catalog.props_3d.length > 0 && (
            <AssetSection
              title="Props 3D"
              items={catalog.props_3d}
              open={openSections.has("props")}
              onToggle={() => toggleSection("props")}
              renderEntry={(p) => <DraggablePropCard key={p.slug} asset={p} />}
            />
          )}

          {/* VRM Avatars */}
          <AssetSection
            title="Avatars VRM"
            items={catalog.vrm_avatars}
            open={openSections.has("vrm")}
            onToggle={() => toggleSection("vrm")}
            renderEntry={(a) => (
              <div key={a.slug} style={ENTRY_STYLE}>
                <span style={SLUG_STYLE}>{a.slug}</span>
                {a.sidecars.length > 0 && (
                  <span style={{ fontSize: 10, color: "#444455" }}>
                    +{a.sidecars.length} VRMA
                  </span>
                )}
              </div>
            )}
          />

          {/* Outfits */}
          <AssetSection
            title="Outfits"
            items={catalog.outfits}
            open={openSections.has("outfits")}
            onToggle={() => toggleSection("outfits")}
            renderEntry={(o) => (
              <div key={o.slug} style={ENTRY_STYLE}>
                <span style={SLUG_STYLE}>{o.slug}</span>
                {o.display_name && (
                  <span style={{ color: "#8888aa", fontSize: 11 }}>{o.display_name}</span>
                )}
              </div>
            )}
          />

          {/* Animations VRMA */}
          <AssetSection
            title="Animations VRMA"
            items={catalog.vrma_animations}
            open={openSections.has("anims")}
            onToggle={() => toggleSection("anims")}
            renderEntry={(a) => (
              <div key={a.slug} style={ENTRY_STYLE}>
                <span style={SLUG_STYLE}>{a.slug}</span>
                {a.loop && <span style={{ fontSize: 10, color: "#7766cc" }}>loop</span>}
                {a.duration_ms != null && (
                  <span style={{ fontSize: 10, color: "#555566", marginLeft: "auto" }}>
                    {(a.duration_ms / 1000).toFixed(1)}s
                  </span>
                )}
              </div>
            )}
          />

          {/* VFX */}
          <AssetSection
            title="VFX"
            items={catalog.vfx}
            open={openSections.has("vfx")}
            onToggle={() => toggleSection("vfx")}
            renderEntry={(v) => (
              <div key={v.slug} style={ENTRY_STYLE}>
                <span style={SLUG_STYLE}>{v.slug}</span>
              </div>
            )}
          />

          {/* Scenes background */}
          <AssetSection
            title="Scènes background"
            items={catalog.scenes}
            open={openSections.has("scenes")}
            onToggle={() => toggleSection("scenes")}
            renderEntry={(s) => (
              <div key={s.slug} style={ENTRY_STYLE}>
                <span style={SLUG_STYLE}>{s.slug}</span>
              </div>
            )}
          />

          {/* Faces whitelist */}
          <AssetSection
            title="Faces (whitelist)"
            items={catalog.faces}
            open={openSections.has("faces")}
            onToggle={() => toggleSection("faces")}
            renderEntry={(f) => (
              <div key={f} style={ENTRY_STYLE}>
                <span style={SLUG_STYLE}>{f}</span>
              </div>
            )}
          />

          {/* Camera modes */}
          <AssetSection
            title="Modes caméra"
            items={catalog.camera_modes}
            open={openSections.has("cameras")}
            onToggle={() => toggleSection("cameras")}
            renderEntry={(c) => (
              <div key={c} style={ENTRY_STYLE}>
                <span style={SLUG_STYLE}>{c}</span>
              </div>
            )}
          />

          {/* Cache info */}
          <div
            style={{
              padding: "6px 12px",
              fontSize: 10,
              color: "#333344",
              borderTop: "1px solid #151520",
            }}
          >
            Cache serveur : {new Date(catalog.cached_at).toLocaleTimeString("fr-FR")}
          </div>
        </>
      )}
    </div>
  );
}
