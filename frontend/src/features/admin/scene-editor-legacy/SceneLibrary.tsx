/**
 * SceneLibrary — galerie workshop des scenes.
 *
 * Bande horizontale scrollable de cartes sélectionnables. Chaque carte :
 *   - Thumbnail = background CSS de la scene (gradient mini-préview)
 *   - Nom (display_name) + slug monospace en sub
 *   - Badge actif/inactif (cyan = actif, gris = inactif)
 *   - Bouton contextuel "⋯" qui ouvre un mini-menu (Duplicate / Toggle / Delete)
 *   - Carte highlight violet si sélectionnée
 *
 * Dernière carte = bouton "+" pour créer une nouvelle scene depuis EMPTY_SCENE.
 * Clic ouvre un modal inline qui demande slug + display_name, puis POST admin.
 *
 * Remplace le dropdown natif `<select>` qui était overlayé dans le viewport.
 */
import { useState } from "react";
import type { SceneRow } from "./types";

type Props = {
  scenes: SceneRow[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onCreate: (slug: string, displayName: string) => Promise<void> | void;
  onDuplicate: (id: string) => Promise<void> | void;
  onToggleActive: (id: string) => Promise<void> | void;
  onDelete: (id: string) => Promise<void> | void;
};

export function SceneLibrary({
  scenes, selectedId, onSelect, onCreate, onDuplicate, onToggleActive, onDelete,
}: Props) {
  const [showCreate, setShowCreate] = useState(false);
  const [newSlug, setNewSlug] = useState("");
  const [newDisplayName, setNewDisplayName] = useState("");
  const [menuOpenId, setMenuOpenId] = useState<string | null>(null);

  const handleCreate = async () => {
    if (!newSlug.trim() || !newDisplayName.trim()) return;
    await onCreate(newSlug.trim(), newDisplayName.trim());
    setNewSlug("");
    setNewDisplayName("");
    setShowCreate(false);
  };

  return (
    <div style={{
      background: "rgba(18,18,30,0.6)",
      borderRadius: 12,
      padding: 10,
      boxShadow: "inset 0 0 0 1px rgba(224,142,254,0.18)",
      backdropFilter: "blur(18px)",
    }}>
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        marginBottom: 8,
      }}>
        <div style={{
          fontFamily: "var(--font-display)", fontSize: "0.68rem",
          letterSpacing: "0.16em", textTransform: "uppercase",
          color: "var(--on-surface-variant)", fontWeight: 600,
        }}>
          Scene Library · {scenes.length}
        </div>
      </div>

      <div style={{
        display: "flex",
        gap: 10,
        overflowX: "auto",
        paddingBottom: 4,
      }} className="scroll-inner">
        {scenes.map((s) => {
          const active = s.id === selectedId;
          return (
            <Card
              key={s.id}
              scene={s}
              active={active}
              menuOpen={menuOpenId === s.id}
              onClick={() => onSelect(s.id)}
              onMenuToggle={() => setMenuOpenId((id) => id === s.id ? null : s.id)}
              onDuplicate={() => { setMenuOpenId(null); void onDuplicate(s.id); }}
              onToggleActive={() => { setMenuOpenId(null); void onToggleActive(s.id); }}
              onDelete={() => { setMenuOpenId(null); void onDelete(s.id); }}
            />
          );
        })}

        {/* Carte "+" — create new scene */}
        {!showCreate ? (
          <button
            onClick={() => setShowCreate(true)}
            style={{
              width: 160, minWidth: 160, height: 104,
              background: "transparent",
              border: "2px dashed rgba(224,142,254,0.3)",
              borderRadius: 12,
              cursor: "pointer",
              display: "flex", flexDirection: "column",
              alignItems: "center", justifyContent: "center",
              gap: 6,
              color: "var(--on-surface-variant)",
              fontFamily: "var(--font-display)",
              fontSize: "0.82rem",
              fontWeight: 600,
              transition: "all 0.2s ease",
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.background = "rgba(224,142,254,0.08)";
              e.currentTarget.style.borderColor = "rgba(224,142,254,0.6)";
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.background = "transparent";
              e.currentTarget.style.borderColor = "rgba(224,142,254,0.3)";
            }}
          >
            <span style={{ fontSize: "1.4rem" }}>+</span>
            <span>Nouvelle scene</span>
          </button>
        ) : (
          <div style={{
            width: 240, minWidth: 240,
            background: "rgba(36,36,52,0.8)",
            borderRadius: 12,
            padding: 10,
            display: "flex", flexDirection: "column", gap: 6,
            boxShadow: "inset 0 0 0 1px rgba(224,142,254,0.4)",
          }}>
            <input
              value={newSlug}
              onChange={(e) => setNewSlug(e.target.value)}
              placeholder="slug (my_new_scene)"
              pattern="[a-zA-Z0-9_\-]{1,64}"
              autoFocus
              style={{
                background: "rgba(9,9,18,0.6)",
                border: "none",
                borderRadius: 6,
                padding: "4px 8px",
                color: "var(--on-surface)",
                fontFamily: "var(--font-mono)",
                fontSize: "0.72rem",
                boxShadow: "inset 0 0 0 1px rgba(71,71,84,0.4)",
                outline: "none",
              }}
            />
            <input
              value={newDisplayName}
              onChange={(e) => setNewDisplayName(e.target.value)}
              placeholder="Display name"
              style={{
                background: "rgba(9,9,18,0.6)",
                border: "none",
                borderRadius: 6,
                padding: "4px 8px",
                color: "var(--on-surface)",
                fontFamily: "var(--font-body)",
                fontSize: "0.78rem",
                boxShadow: "inset 0 0 0 1px rgba(71,71,84,0.4)",
                outline: "none",
              }}
            />
            <div style={{ display: "flex", gap: 4, marginTop: 2 }}>
              <button
                onClick={() => { void handleCreate(); }}
                disabled={!newSlug.trim() || !newDisplayName.trim()}
                style={{
                  flex: 1,
                  background: "linear-gradient(135deg, var(--primary), var(--primary-container))",
                  color: "#1a0a24",
                  border: "none",
                  borderRadius: 6,
                  padding: "5px 8px",
                  fontFamily: "var(--font-display)",
                  fontWeight: 700,
                  fontSize: "0.72rem",
                  cursor: "pointer",
                  opacity: (newSlug.trim() && newDisplayName.trim()) ? 1 : 0.4,
                }}
              >
                ✦ Créer
              </button>
              <button
                onClick={() => { setShowCreate(false); setNewSlug(""); setNewDisplayName(""); }}
                style={{
                  background: "transparent",
                  color: "var(--on-surface-muted)",
                  border: "none",
                  borderRadius: 6,
                  padding: "5px 8px",
                  fontFamily: "var(--font-display)",
                  fontSize: "0.72rem",
                  cursor: "pointer",
                  boxShadow: "inset 0 0 0 1px rgba(71,71,84,0.3)",
                }}
              >
                ✕
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Card ──────────────────────────────────────────────────────────────────

function Card({
  scene, active, menuOpen,
  onClick, onMenuToggle, onDuplicate, onToggleActive, onDelete,
}: {
  scene: SceneRow;
  active: boolean;
  menuOpen: boolean;
  onClick: () => void;
  onMenuToggle: () => void;
  onDuplicate: () => void;
  onToggleActive: () => void;
  onDelete: () => void;
}) {
  return (
    <div
      onClick={onClick}
      style={{
        position: "relative",
        width: 180, minWidth: 180, height: 104,
        borderRadius: 12,
        overflow: "hidden",
        cursor: "pointer",
        transition: "all 0.2s ease",
        opacity: scene.is_active ? 1 : 0.5,
        boxShadow: active
          ? "0 0 0 2px var(--primary), 0 10px 30px -10px rgba(224,142,254,0.6)"
          : "inset 0 0 0 1px rgba(71,71,84,0.3)",
      }}
    >
      {/* Thumbnail = background CSS de la scene */}
      <div style={{
        position: "absolute", inset: 0,
        background: scene.payload?.background || "#1a0a24",
      }} />
      {/* Dégradé sombre en bas pour la lisibilité du texte */}
      <div style={{
        position: "absolute", inset: 0,
        background: "linear-gradient(180deg, transparent 40%, rgba(0,0,0,0.75) 100%)",
      }} />

      {/* Badge actif/inactif */}
      <div style={{
        position: "absolute", top: 8, left: 8,
        display: "flex", alignItems: "center", gap: 4,
        padding: "2px 6px",
        borderRadius: 999,
        background: "rgba(9,9,18,0.7)",
        backdropFilter: "blur(10px)",
      }}>
        <span style={{
          width: 5, height: 5, borderRadius: "50%",
          background: scene.is_active ? "var(--tertiary)" : "var(--on-surface-muted)",
          boxShadow: scene.is_active ? "0 0 6px var(--tertiary)" : "none",
        }} />
        <span style={{
          fontFamily: "var(--font-mono)", fontSize: "0.6rem",
          color: scene.is_active ? "var(--tertiary)" : "var(--on-surface-muted)",
          letterSpacing: "0.08em", textTransform: "uppercase",
        }}>
          {scene.is_active ? "live" : "off"}
        </span>
      </div>

      {/* Menu "⋯" top-right */}
      <button
        onClick={(e) => { e.stopPropagation(); onMenuToggle(); }}
        style={{
          position: "absolute", top: 6, right: 6,
          width: 24, height: 24, borderRadius: "50%",
          background: "rgba(9,9,18,0.7)",
          backdropFilter: "blur(10px)",
          border: "none",
          cursor: "pointer",
          color: "var(--on-surface)",
          display: "flex", alignItems: "center", justifyContent: "center",
          fontSize: "1rem",
          lineHeight: 1,
        }}
      >
        ⋯
      </button>

      {menuOpen && (
        <div
          onClick={(e) => e.stopPropagation()}
          style={{
            position: "absolute", top: 34, right: 6,
            zIndex: 10,
            background: "rgba(30,30,45,0.95)",
            backdropFilter: "blur(20px)",
            borderRadius: 8,
            padding: 4,
            minWidth: 130,
            boxShadow: "0 10px 30px -8px rgba(0,0,0,0.6), inset 0 0 0 1px rgba(224,142,254,0.3)",
          }}
        >
          <MenuItem onClick={onDuplicate}>❖ Dupliquer</MenuItem>
          <MenuItem onClick={onToggleActive}>
            {scene.is_active ? "○ Désactiver" : "◉ Activer"}
          </MenuItem>
          <MenuItem onClick={onDelete} danger>✕ Supprimer</MenuItem>
        </div>
      )}

      {/* Nom + slug */}
      <div style={{
        position: "absolute", bottom: 8, left: 10, right: 10,
      }}>
        <div style={{
          fontFamily: "var(--font-display)",
          fontSize: "0.82rem",
          fontWeight: 700,
          color: "#fff",
          letterSpacing: "-0.01em",
          textShadow: "0 1px 6px rgba(0,0,0,0.7)",
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}>
          {scene.display_name}
        </div>
        <div style={{
          fontFamily: "var(--font-mono)",
          fontSize: "0.62rem",
          color: "rgba(255,255,255,0.6)",
          letterSpacing: "0.04em",
        }}>
          {scene.slug}
        </div>
      </div>
    </div>
  );
}

function MenuItem({
  children, onClick, danger,
}: { children: React.ReactNode; onClick: () => void; danger?: boolean }) {
  return (
    <button
      onClick={onClick}
      style={{
        display: "block", width: "100%",
        padding: "6px 10px",
        background: "transparent",
        color: danger ? "var(--danger, #ff6a8a)" : "var(--on-surface)",
        border: "none",
        borderRadius: 6,
        cursor: "pointer",
        fontFamily: "var(--font-display)",
        fontSize: "0.72rem",
        fontWeight: 600,
        textAlign: "left",
        transition: "background 0.15s ease",
      }}
      onMouseEnter={(e) => { e.currentTarget.style.background = "rgba(255,255,255,0.06)"; }}
      onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
    >
      {children}
    </button>
  );
}
