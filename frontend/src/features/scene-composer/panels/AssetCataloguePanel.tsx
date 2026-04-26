/**
 * AssetCataloguePanel — exploration READ-ONLY du catalogue d'assets.
 *
 * Responsabilité unique : afficher le catalogue d'assets disponibles (VRM,
 * outfits, animations VRMA, VFX, scènes background) en mode lecture. Chaque
 * section est repliable. Aucun drag-drop en E5.2 (prévu E5.3).
 *
 * Données : fetchées via `catalogClient.getAssetCatalog()` au mount.
 * Le cache de 60s est géré côté serveur — le panneau rafraîchit seulement
 * sur demande explicite (bouton ↻).
 *
 * @module panels/AssetCataloguePanel
 */

import { useCallback, useEffect, useState } from "react";
import {
  getAssetCatalog,
  type AssetCatalogOut,
  CatalogClientError,
} from "../api/catalogClient";

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
  display: "flex",
  alignItems: "center",
  gap: 8,
};

const SECTION_HEADER: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 6,
  padding: "6px 12px",
  background: "#111118",
  borderBottom: "1px solid #1a1a28",
  cursor: "pointer",
  userSelect: "none",
};

const ENTRY_STYLE: React.CSSProperties = {
  padding: "4px 20px",
  borderBottom: "1px solid #0f0f1a",
  fontSize: 12,
  color: "#aaaacc",
  display: "flex",
  alignItems: "center",
  gap: 6,
};

const SLUG_STYLE: React.CSSProperties = {
  fontFamily: "monospace",
  color: "#8899bb",
  fontSize: 11,
};

const COUNT_BADGE: React.CSSProperties = {
  marginLeft: "auto",
  fontSize: 10,
  color: "#555566",
  background: "#1a1a28",
  padding: "1px 5px",
  borderRadius: 3,
};

// ─── Helpers ──────────────────────────────────────────────────────────────────

function SectionHeader({
  label,
  count,
  open,
  onToggle,
}: {
  label: string;
  count: number;
  open: boolean;
  onToggle: () => void;
}) {
  return (
    <div style={SECTION_HEADER} onClick={onToggle} role="button" tabIndex={0}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") onToggle(); }}>
      <span style={{ color: "#7766cc", fontSize: 10 }}>{open ? "▾" : "▸"}</span>
      <span style={{ fontWeight: 600, fontSize: 11, color: "#9988dd", textTransform: "uppercase", letterSpacing: 0.8 }}>
        {label}
      </span>
      <span style={COUNT_BADGE}>{count}</span>
    </div>
  );
}

// ─── Composant ────────────────────────────────────────────────────────────────

type SectionKey = "vrm" | "outfits" | "anims" | "vfx" | "scenes" | "faces" | "cameras";

/**
 * Panneau catalogue d'assets en lecture seule.
 * Chaque section est repliable pour économiser l'espace vertical.
 */
export function AssetCataloguePanel() {
  const [catalog, setCatalog] = useState<AssetCatalogOut | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [openSections, setOpenSections] = useState<Set<SectionKey>>(
    new Set(["vrm", "anims"]),
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
        <span style={{ fontWeight: 600, fontSize: 11, color: "#7766cc", textTransform: "uppercase", letterSpacing: 1 }}>
          Assets
        </span>
        <button
          style={{ background: "none", border: "none", color: "#7766cc", cursor: "pointer", fontSize: 14, padding: "0 4px", marginLeft: "auto" }}
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
          {/* VRM Avatars */}
          <SectionHeader label="Avatars VRM" count={catalog.vrm_avatars.length} open={openSections.has("vrm")} onToggle={() => toggleSection("vrm")} />
          {openSections.has("vrm") && catalog.vrm_avatars.map((a) => (
            <div key={a.slug} style={ENTRY_STYLE}>
              <span style={SLUG_STYLE}>{a.slug}</span>
              {a.sidecars.length > 0 && (
                <span style={{ fontSize: 10, color: "#444455" }}>+{a.sidecars.length} VRMA</span>
              )}
            </div>
          ))}

          {/* Outfits */}
          <SectionHeader label="Outfits" count={catalog.outfits.length} open={openSections.has("outfits")} onToggle={() => toggleSection("outfits")} />
          {openSections.has("outfits") && catalog.outfits.map((o) => (
            <div key={o.slug} style={ENTRY_STYLE}>
              <span style={SLUG_STYLE}>{o.slug}</span>
              {o.display_name && <span style={{ color: "#8888aa", fontSize: 11 }}>{o.display_name}</span>}
            </div>
          ))}

          {/* Animations VRMA */}
          <SectionHeader label="Animations VRMA" count={catalog.vrma_animations.length} open={openSections.has("anims")} onToggle={() => toggleSection("anims")} />
          {openSections.has("anims") && catalog.vrma_animations.map((a) => (
            <div key={a.slug} style={ENTRY_STYLE}>
              <span style={SLUG_STYLE}>{a.slug}</span>
              {a.loop && <span style={{ fontSize: 10, color: "#7766cc" }}>loop</span>}
              {a.duration_ms != null && (
                <span style={{ fontSize: 10, color: "#555566", marginLeft: "auto" }}>
                  {(a.duration_ms / 1000).toFixed(1)}s
                </span>
              )}
            </div>
          ))}

          {/* VFX */}
          <SectionHeader label="VFX" count={catalog.vfx.length} open={openSections.has("vfx")} onToggle={() => toggleSection("vfx")} />
          {openSections.has("vfx") && catalog.vfx.map((v) => (
            <div key={v.slug} style={ENTRY_STYLE}>
              <span style={SLUG_STYLE}>{v.slug}</span>
            </div>
          ))}

          {/* Scenes background */}
          <SectionHeader label="Scènes background" count={catalog.scenes.length} open={openSections.has("scenes")} onToggle={() => toggleSection("scenes")} />
          {openSections.has("scenes") && catalog.scenes.map((s) => (
            <div key={s.slug} style={ENTRY_STYLE}>
              <span style={SLUG_STYLE}>{s.slug}</span>
            </div>
          ))}

          {/* Faces whitelist */}
          <SectionHeader label="Faces (whitelist)" count={catalog.faces.length} open={openSections.has("faces")} onToggle={() => toggleSection("faces")} />
          {openSections.has("faces") && catalog.faces.map((f) => (
            <div key={f} style={ENTRY_STYLE}>
              <span style={SLUG_STYLE}>{f}</span>
            </div>
          ))}

          {/* Camera modes */}
          <SectionHeader label="Modes caméra" count={catalog.camera_modes.length} open={openSections.has("cameras")} onToggle={() => toggleSection("cameras")} />
          {openSections.has("cameras") && catalog.camera_modes.map((c) => (
            <div key={c} style={ENTRY_STYLE}>
              <span style={SLUG_STYLE}>{c}</span>
            </div>
          ))}

          {/* Cache info */}
          <div style={{ padding: "6px 12px", fontSize: 10, color: "#333344", borderTop: "1px solid #151520" }}>
            Cache serveur : {new Date(catalog.cached_at).toLocaleTimeString("fr-FR")}
          </div>
        </>
      )}
    </div>
  );
}
