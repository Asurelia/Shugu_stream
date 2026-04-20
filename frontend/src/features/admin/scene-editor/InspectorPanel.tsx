/**
 * InspectorPanel — contrôles numériques pour éditer une ScenePayload.
 *
 * Sections :
 *   1. Camera  (x/y/z + FOV + look_at x/y/z)
 *   2. Avatar  (x/y/z + rotY)
 *   3. Background CSS (textarea avec preview gradient)
 *   4. Idle animation (URL / slug)
 *
 * Chaque input modifie la `draft` via `onChange(next)`. Le parent lifte le
 * state et pilote le viewer via les mêmes champs. Sync bidirectionnel
 * garanti : quand le viewer bouge le VRM à la souris, il appelle
 * `onAvatarTransformChange` côté parent, qui met à jour `draft`, qui
 * ré-injecte dans les sliders de ce composant.
 */
import type { CSSProperties } from "react";
import type { ScenePayload, GizmoMode } from "./types";

type Props = {
  draft: ScenePayload;
  onChange: (next: ScenePayload) => void;
  gizmoMode: GizmoMode;
  onGizmoModeChange: (mode: GizmoMode) => void;
  /** Si false (mode preview), la section Gizmo est masquée (inutile). */
  showGizmoControls: boolean;
};

export function InspectorPanel({
  draft, onChange, gizmoMode, onGizmoModeChange, showGizmoControls,
}: Props) {
  const patch = (mutator: (p: ScenePayload) => ScenePayload) => onChange(mutator(draft));

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
      {/* Mode gizmo toolbar — visible seulement en mode 3D libre ────── */}
      {showGizmoControls && (
        <Section title="Gizmo mode">
          <div style={{ display: "flex", gap: 6 }}>
            {(["translate", "rotate", "scale"] as const).map((m) => (
              <button
                key={m}
                onClick={() => onGizmoModeChange(m)}
                style={{
                  flex: 1,
                  padding: "6px 10px",
                  borderRadius: 8,
                  border: "none",
                  cursor: "pointer",
                  background: gizmoMode === m
                    ? "linear-gradient(135deg, var(--primary), var(--primary-container))"
                    : "rgba(9,9,18,0.55)",
                  color: gizmoMode === m ? "#1a0a24" : "var(--on-surface-variant)",
                  fontFamily: "var(--font-display)",
                  fontWeight: 700,
                  fontSize: "0.72rem",
                  textTransform: "uppercase",
                  letterSpacing: "0.08em",
                  boxShadow: gizmoMode === m
                    ? "0 6px 18px -8px rgba(224,142,254,0.5)"
                    : "inset 0 0 0 1px rgba(71,71,84,0.3)",
                }}
              >
                {m}
              </button>
            ))}
          </div>
        </Section>
      )}

      {/* Camera ─────────────────────────────────────────────────── */}
      <Section title="Camera (scene)">
        <Vec3Row
          label="pos"
          value={draft.camera}
          onChange={(v) => patch((p) => ({ ...p, camera: v }))}
          step={0.01}
        />
        <Vec3Row
          label="look"
          value={draft.look_at}
          onChange={(v) => patch((p) => ({ ...p, look_at: v }))}
          step={0.01}
        />
        <SliderRow
          label="FOV"
          value={draft.fov}
          min={10} max={80} step={1}
          onChange={(fov) => patch((p) => ({ ...p, fov }))}
          suffix="°"
        />
      </Section>

      {/* Avatar ─────────────────────────────────────────────────── */}
      <Section title="Avatar">
        <Vec3Row
          label="pos"
          value={draft.avatar_position}
          onChange={(v) => patch((p) => ({ ...p, avatar_position: v }))}
          step={0.01}
        />
        <SliderRow
          label="rotY"
          value={draft.avatar_rotation_y}
          min={-Math.PI} max={Math.PI} step={0.01}
          onChange={(rot) => patch((p) => ({ ...p, avatar_rotation_y: rot }))}
          suffix=" rad"
        />
      </Section>

      {/* Background ─────────────────────────────────────────────── */}
      <Section title="Background (CSS)">
        <div style={{
          height: 32,
          borderRadius: 8,
          marginBottom: 6,
          background: draft.background || "#1a0a24",
          boxShadow: "inset 0 0 0 1px rgba(71,71,84,0.3)",
        }} />
        <textarea
          value={draft.background}
          onChange={(e) => patch((p) => ({ ...p, background: e.target.value }))}
          rows={3}
          style={{
            ...fieldStyle,
            fontFamily: "var(--font-mono)",
            fontSize: "0.72rem",
            resize: "vertical",
          }}
        />
      </Section>

      {/* Idle animation ─────────────────────────────────────────── */}
      <Section title="Idle animation">
        <input
          value={draft.idle_animation}
          onChange={(e) => patch((p) => ({ ...p, idle_animation: e.target.value }))}
          placeholder="/idle_loop.vrma  ou  slug"
          style={{ ...fieldStyle, fontFamily: "var(--font-mono)", fontSize: "0.74rem" }}
        />
      </Section>
    </div>
  );
}

// ─── Sous-composants ──────────────────────────────────────────────────────

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <div style={{
        fontFamily: "var(--font-display)", fontSize: "0.68rem",
        letterSpacing: "0.14em", textTransform: "uppercase",
        color: "var(--on-surface-variant)", marginBottom: 8, fontWeight: 600,
      }}>
        {title}
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>{children}</div>
    </div>
  );
}

function Vec3Row({
  label, value, onChange, step = 0.01,
}: {
  label: string;
  value: { x: number; y: number; z: number };
  onChange: (v: { x: number; y: number; z: number }) => void;
  step?: number;
}) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "40px 1fr 1fr 1fr", gap: 6, alignItems: "center" }}>
      <span style={{
        fontFamily: "var(--font-mono)", fontSize: "0.68rem",
        color: "var(--on-surface-muted)", textTransform: "uppercase",
      }}>{label}</span>
      <NumInput value={value.x} step={step} onChange={(x) => onChange({ ...value, x })} axis="x" />
      <NumInput value={value.y} step={step} onChange={(y) => onChange({ ...value, y })} axis="y" />
      <NumInput value={value.z} step={step} onChange={(z) => onChange({ ...value, z })} axis="z" />
    </div>
  );
}

function NumInput({
  value, step, onChange, axis,
}: {
  value: number;
  step: number;
  onChange: (v: number) => void;
  axis?: "x" | "y" | "z";
}) {
  const borderColor = axis === "x" ? "rgba(253,108,156,0.4)"
    : axis === "y" ? "rgba(129,236,255,0.4)"
    : "rgba(224,142,254,0.4)";
  return (
    <input
      type="number"
      step={step}
      value={Number.isFinite(value) ? Number(value.toFixed(3)) : 0}
      onChange={(e) => {
        const n = Number(e.target.value);
        if (Number.isFinite(n)) onChange(n);
      }}
      style={{
        ...fieldStyle,
        fontFamily: "var(--font-mono)",
        fontSize: "0.72rem",
        padding: "5px 7px",
        boxShadow: `inset 0 0 0 1px ${borderColor}`,
      }}
    />
  );
}

function SliderRow({
  label, value, min, max, step, onChange, suffix,
}: {
  label: string;
  value: number;
  min: number; max: number; step: number;
  onChange: (v: number) => void;
  suffix?: string;
}) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "40px 1fr 72px", gap: 6, alignItems: "center" }}>
      <span style={{
        fontFamily: "var(--font-mono)", fontSize: "0.68rem",
        color: "var(--on-surface-muted)", textTransform: "uppercase",
      }}>{label}</span>
      <input
        type="range"
        min={min} max={max} step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        style={{ accentColor: "var(--primary)", width: "100%" }}
      />
      <input
        type="number"
        min={min} max={max} step={step}
        value={Number.isFinite(value) ? Number(value.toFixed(3)) : 0}
        onChange={(e) => {
          const n = Number(e.target.value);
          if (Number.isFinite(n)) onChange(n);
        }}
        style={{
          ...fieldStyle,
          fontFamily: "var(--font-mono)",
          fontSize: "0.72rem",
          padding: "5px 7px",
          textAlign: "right",
        }}
        title={suffix}
      />
    </div>
  );
}

const fieldStyle: CSSProperties = {
  background: "rgba(9,9,18,0.55)",
  border: "none",
  borderRadius: 8,
  padding: "6px 8px",
  color: "var(--on-surface)",
  fontFamily: "var(--font-body)",
  fontSize: "0.82rem",
  outline: "none",
  boxShadow: "inset 0 0 0 1px rgba(71,71,84,0.3)",
  width: "100%",
  minWidth: 0,
};
