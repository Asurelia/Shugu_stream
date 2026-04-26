/**
 * PlayModeToolbar — barre de contrôle Play/Stop du Scene Composer.
 *
 * Responsabilité unique : exposer les contrôles de lecture (play/stop),
 * le badge viewerMode, la configuration AFK Loops (activation + sliders)
 * et l'indicateur de statut AFK actif.
 *
 * Positionnement : bande horizontale fixe entre le header Composer et le
 * viewer canvas. Doit être rendue par le composant parent (SceneComposerPage)
 * au-dessus de <SceneComposerViewer />.
 *
 * Données :
 *   - Lit `playMode`, `viewerMode`, `afkLoops` depuis `useSceneComposerStore`.
 *   - Actions : `setPlayMode`, `setAfkLoops`.
 *   - `afkActive` : prop optionnelle booléenne indiquant si une AFK loop tourne
 *     activement (mis à jour par useAfkLoops et propagé par SceneComposerPage).
 *
 * Styles : inline uniquement, cohérents avec la palette `#0d0d14` / `#7766cc`
 * du reste du scene-composer (cf. inspector-styles + catalogue-styles).
 *
 * @module panels/PlayModeToolbar
 */

import React from "react";
import {
  useSceneComposerStore,
  selectPlayMode,
  selectViewerMode,
  selectAfkLoops,
} from "../store/useSceneComposerStore";

// ─── Types ────────────────────────────────────────────────────────────────────

export interface PlayModeToolbarProps {
  /**
   * Indique si une boucle AFK est actuellement active (animation idle en cours).
   *
   * Calculé par useAfkLoops et propagé par SceneComposerPage — lecture seule ici.
   * Affiche un badge informatif dans la toolbar.
   */
  afkActive?: boolean;
  /**
   * Nombre de viewers actuellement connectés.
   *
   * Affiché à titre informatif. Source réelle câblée dans une phase ultérieure.
   * Défaut : 0 (mode solo / AFK probable).
   */
  currentViewerCount?: number;
}

// ─── Styles locaux ────────────────────────────────────────────────────────────
// Palette cohérente avec inspector-styles et catalogue-styles.

const TOOLBAR_STYLE: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 12,
  padding: "6px 14px",
  background: "#0a0a11",
  borderBottom: "1px solid #1a1a2a",
  flexShrink: 0,
  flexWrap: "wrap",
  minHeight: 40,
};

const PLAY_BTN_BASE: React.CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 5,
  padding: "4px 12px",
  border: "1px solid",
  borderRadius: 4,
  fontSize: 12,
  fontWeight: 600,
  cursor: "pointer",
  letterSpacing: 0.5,
  transition: "background 0.15s, border-color 0.15s",
  fontFamily: "inherit",
};

const PLAY_BTN_PLAYING: React.CSSProperties = {
  ...PLAY_BTN_BASE,
  background: "#1e0a0a",
  borderColor: "#cc4455",
  color: "#ff6677",
};

const PLAY_BTN_STOPPED: React.CSSProperties = {
  ...PLAY_BTN_BASE,
  background: "#0a1e14",
  borderColor: "#44cc88",
  color: "#55ee99",
};

const BADGE_STYLE_EDIT: React.CSSProperties = {
  fontSize: 10,
  fontWeight: 700,
  letterSpacing: 1,
  padding: "2px 7px",
  borderRadius: 3,
  border: "1px solid #333366",
  background: "#111128",
  color: "#7766cc",
  textTransform: "uppercase" as const,
};

const BADGE_STYLE_PREVIEW: React.CSSProperties = {
  ...BADGE_STYLE_EDIT,
  border: "1px solid #447755",
  background: "#0d1a12",
  color: "#55cc88",
};

const DIVIDER: React.CSSProperties = {
  width: 1,
  height: 22,
  background: "#222234",
  flexShrink: 0,
};

const LABEL_STYLE: React.CSSProperties = {
  fontSize: 11,
  color: "#666688",
  textTransform: "uppercase" as const,
  letterSpacing: 0.6,
};

const CHECKBOX_ROW: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 6,
  cursor: "pointer",
};

const AFK_ACTIVE_BADGE: React.CSSProperties = {
  fontSize: 10,
  color: "#cc8844",
  background: "#1a1204",
  border: "1px solid #554422",
  borderRadius: 3,
  padding: "2px 7px",
  fontStyle: "italic",
};

const SLIDER_ROW: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 6,
};

const SLIDER_STYLE: React.CSSProperties = {
  width: 90,
  accentColor: "#7766cc",
  cursor: "pointer",
};

const VALUE_LABEL: React.CSSProperties = {
  fontSize: 10,
  color: "#aaaacc",
  fontFamily: "monospace",
  minWidth: 28,
  textAlign: "right" as const,
};

// ─── Composant ────────────────────────────────────────────────────────────────

/**
 * Barre de contrôle Play/Stop et AFK Loops du Scene Composer.
 *
 * Composition :
 * - Bouton Play/Stop (bascule playMode + force viewerMode cohérent)
 * - Badge viewerMode (READ-ONLY — résultat de setPlayMode)
 * - Toggle AFK Loops (checkbox enabled)
 * - Sliders viewerThreshold (1–50) et idleSeconds (10–300)
 * - Badge "AFK actif" si afkActive=true
 * - Compteur viewers (informatif)
 */
export function PlayModeToolbar({
  afkActive = false,
  currentViewerCount = 0,
}: PlayModeToolbarProps) {
  const playMode = useSceneComposerStore(selectPlayMode);
  const viewerMode = useSceneComposerStore(selectViewerMode);
  const afkLoops = useSceneComposerStore(selectAfkLoops);
  const setPlayMode = useSceneComposerStore((s) => s.setPlayMode);
  const setAfkLoops = useSceneComposerStore((s) => s.setAfkLoops);

  const isPlaying = playMode === "playing";

  function handlePlayStop() {
    setPlayMode(isPlaying ? "stopped" : "playing");
  }

  return (
    <div style={TOOLBAR_STYLE} role="toolbar" aria-label="Contrôles lecture scène">

      {/* ── Bouton Play/Stop ─────────────────────────────────────────────── */}
      <button
        style={isPlaying ? PLAY_BTN_PLAYING : PLAY_BTN_STOPPED}
        onClick={handlePlayStop}
        aria-pressed={isPlaying}
        aria-label={isPlaying ? "Arrêter la lecture" : "Lancer la lecture"}
        title={isPlaying ? "Arrêter (mode édition)" : "Lancer (mode preview)"}
      >
        <span aria-hidden="true">{isPlaying ? "⏹" : "▶"}</span>
        {isPlaying ? "Stop" : "Play"}
      </button>

      {/* ── Badge viewerMode (résultat de cohérence) ─────────────────────── */}
      <span
        style={viewerMode === "edit" ? BADGE_STYLE_EDIT : BADGE_STYLE_PREVIEW}
        title="Mode viewer actuel (contrôlé par Play/Stop)"
        aria-label={`Mode viewer : ${viewerMode}`}
      >
        {viewerMode === "edit" ? "EDIT" : "PREVIEW"}
      </span>

      <div style={DIVIDER} />

      {/* ── AFK Loops toggle ─────────────────────────────────────────────── */}
      <label style={CHECKBOX_ROW} title="Activer/désactiver les boucles AFK déterministes">
        <input
          type="checkbox"
          checked={afkLoops.enabled}
          onChange={(e) => setAfkLoops({ enabled: e.target.checked })}
          style={{ accentColor: "#7766cc", cursor: "pointer" }}
          aria-label="Activer les boucles AFK"
        />
        <span style={LABEL_STYLE}>AFK Loops</span>
      </label>

      {/* ── Slider viewerThreshold (visible si AFK enabled) ──────────────── */}
      {afkLoops.enabled && (
        <div style={SLIDER_ROW} title="Seuil de viewers pour déclencher les AFK loops">
          <span style={LABEL_STYLE}>viewers&lt;</span>
          <input
            type="range"
            min={1}
            max={50}
            step={1}
            value={afkLoops.viewerThreshold}
            onChange={(e) => setAfkLoops({ viewerThreshold: Number(e.target.value) })}
            style={SLIDER_STYLE}
            aria-label={`Seuil viewers : ${afkLoops.viewerThreshold}`}
          />
          <span style={VALUE_LABEL}>{afkLoops.viewerThreshold}</span>
        </div>
      )}

      {/* ── Slider idleSeconds (visible si AFK enabled) ──────────────────── */}
      {afkLoops.enabled && (
        <div style={SLIDER_ROW} title="Délai d'inactivité avant déclenchement AFK">
          <span style={LABEL_STYLE}>idle</span>
          <input
            type="range"
            min={10}
            max={300}
            step={5}
            value={afkLoops.idleSeconds}
            onChange={(e) => setAfkLoops({ idleSeconds: Number(e.target.value) })}
            style={SLIDER_STYLE}
            aria-label={`Délai inactivité : ${afkLoops.idleSeconds}s`}
          />
          <span style={VALUE_LABEL}>{afkLoops.idleSeconds}s</span>
        </div>
      )}

      <div style={DIVIDER} />

      {/* ── Viewers connectés (informatif) ───────────────────────────────── */}
      <span
        style={{ ...LABEL_STYLE, gap: 4 }}
        title="Nombre de viewers connectés (source : phase ultérieure)"
        aria-label={`${currentViewerCount} viewers`}
      >
        {currentViewerCount} viewer{currentViewerCount !== 1 ? "s" : ""}
      </span>

      {/* ── Badge AFK actif (debug) ───────────────────────────────────────── */}
      {afkActive && (
        <span
          style={AFK_ACTIVE_BADGE}
          role="status"
          aria-live="polite"
          title="Une boucle AFK est en cours de lecture"
        >
          AFK actif
        </span>
      )}
    </div>
  );
}
