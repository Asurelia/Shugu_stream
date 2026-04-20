/**
 * SceneEditorToolbar — barre d'action Save / Preview / Revert.
 *
 * `dirty` reflète si `draft` diverge de `original`. Quand dirty=false, Save
 * et Revert sont greyed out. Le status affiche l'état courant (saved / dirty
 * / preview actif / erreur).
 */

type Status =
  | { kind: "idle" }
  | { kind: "dirty" }
  | { kind: "saving" }
  | { kind: "saved" }
  | { kind: "preview" }
  | { kind: "error"; message: string };

export type ViewMode = "preview" | "edit";

type Props = {
  dirty: boolean;
  status: Status;
  viewMode: ViewMode;
  onViewModeChange: (mode: ViewMode) => void;
  onSave: () => void;
  onPreview: () => void;
  onRevert: () => void;
};

export function SceneEditorToolbar({
  dirty, status, viewMode, onViewModeChange,
  onSave, onPreview, onRevert,
}: Props) {
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 10,
      padding: "10px 14px",
      background: "rgba(18,18,30,0.75)",
      borderRadius: 12,
      boxShadow: "inset 0 0 0 1px rgba(224,142,254,0.22)",
      backdropFilter: "blur(20px)",
    }}>
      {/* View mode segmented — la brique UX clé : par défaut WYSIWYG */}
      <div style={{
        display: "flex", gap: 2,
        padding: 3,
        background: "rgba(9,9,18,0.6)",
        borderRadius: 999,
        boxShadow: "inset 0 0 0 1px rgba(71,71,84,0.3)",
      }}>
        <SegBtn label="✦ Live View" active={viewMode === "preview"} onClick={() => onViewModeChange("preview")} />
        <SegBtn label="◈ Edit 3D"    active={viewMode === "edit"}    onClick={() => onViewModeChange("edit")} />
      </div>

      <div style={{ width: 1, height: 24, background: "rgba(71,71,84,0.4)", margin: "0 4px" }} />

      <button
        onClick={onSave}
        disabled={!dirty || status.kind === "saving"}
        style={{
          ...btnBase,
          background: dirty
            ? "linear-gradient(135deg, var(--primary), var(--primary-container))"
            : "rgba(36,36,52,0.6)",
          color: dirty ? "#1a0a24" : "var(--on-surface-muted)",
          cursor: dirty ? "pointer" : "not-allowed",
          boxShadow: dirty ? "0 10px 30px -10px rgba(224,142,254,0.6)" : "none",
        }}
      >
        {status.kind === "saving" ? "…" : "✦ Save"}
      </button>

      <button
        onClick={onPreview}
        style={{
          ...btnBase,
          background: "linear-gradient(135deg, var(--tertiary), var(--tertiary-dim))",
          color: "#0d0d18",
          cursor: "pointer",
        }}
        title="Broadcast aux viewers connectés — ils voient la config live sans que ce soit sauvegardé"
      >
        ◉ Push Live
      </button>

      <button
        onClick={onRevert}
        disabled={!dirty}
        style={{
          ...btnBase,
          background: "transparent",
          color: dirty ? "var(--on-surface-variant)" : "var(--on-surface-muted)",
          cursor: dirty ? "pointer" : "not-allowed",
          boxShadow: "inset 0 0 0 1px rgba(71,71,84,0.3)",
        }}
      >
        ↶ Revert
      </button>

      <div style={{ flex: 1 }} />

      <StatusBadge status={status} />
    </div>
  );
}

function SegBtn({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      style={{
        padding: "5px 12px",
        borderRadius: 999,
        border: "none",
        cursor: "pointer",
        background: active
          ? "linear-gradient(135deg, var(--primary), var(--primary-container))"
          : "transparent",
        color: active ? "#1a0a24" : "var(--on-surface-variant)",
        fontFamily: "var(--font-display)",
        fontWeight: 700,
        fontSize: "0.72rem",
        letterSpacing: "0.04em",
        transition: "all 0.2s ease",
      }}
    >
      {label}
    </button>
  );
}

function StatusBadge({ status }: { status: Status }) {
  const [label, color] = (() => {
    switch (status.kind) {
      case "idle":    return ["untouched",   "var(--on-surface-muted)"];
      case "dirty":   return ["unsaved",     "var(--warn, #ffcf6b)"];
      case "saving":  return ["saving…",     "var(--on-surface-variant)"];
      case "saved":   return ["saved ✓",     "var(--success, #8aefc7)"];
      case "preview": return ["preview live", "var(--tertiary)"];
      case "error":   return [status.message, "var(--danger, #ff6a8a)"];
    }
  })();
  return (
    <span style={{
      fontFamily: "var(--font-mono)",
      fontSize: "0.68rem",
      color,
      letterSpacing: "0.08em",
      textTransform: "uppercase",
      maxWidth: 240,
      overflow: "hidden",
      textOverflow: "ellipsis",
      whiteSpace: "nowrap",
    }}>
      {label}
    </span>
  );
}

const btnBase: React.CSSProperties = {
  border: "none",
  borderRadius: 10,
  padding: "7px 14px",
  fontFamily: "var(--font-display)",
  fontWeight: 700,
  fontSize: "0.76rem",
  letterSpacing: "0.04em",
  textTransform: "uppercase",
  transition: "all 0.2s ease",
};

export type { Status };
