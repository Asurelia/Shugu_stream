"use client";

/**
 * Asset Registry client island.
 *
 * Migration Pages Router → App Router (Sprint E5) :
 *   - `<Meta>` supprimé — métadonnées déclarées côté Server (`page.tsx`).
 *   - `AdminShell` migré vers `next/navigation` ; fonctionne uniquement App Router.
 *   - `export default` renommé en `export function AssetsClient`.
 */
import { useCallback, useEffect, useState, type FormEvent } from "react";

import { AdminShell } from "@/components/admin/AdminShell";

type RegistryRow = {
  id: string;
  kind: string;
  slug: string;
  display_name: string;
  payload: Record<string, unknown>;
  is_active: boolean;
  created_at: string;
  updated_at: string;
};

type KindKey = "gesture" | "scene" | "emote" | "shot" | "expression" | "mood";

type KindDef = {
  key: KindKey;
  label: string;
  summary: string;
  fields: FormField[];
  buildPayload: (values: Record<string, string>) => Record<string, unknown>;
  renderRow: (p: Record<string, unknown>) => string;
};

type FormField = {
  name: string;
  label: string;
  placeholder?: string;
  type?: "text" | "select" | "number" | "textarea";
  options?: string[];
  required?: boolean;
  help?: string;
};

// ─── Config par kind (déclaratif — ajouter un kind = une entrée) ──────────

const KINDS: KindDef[] = [
  {
    key: "gesture",
    label: "Gestures",
    summary: "Animations une-shot (FBX Mixamo ou VRMA natif).",
    fields: [
      { name: "url", label: "URL", placeholder: "/animations/wave.fbx", required: true },
      { name: "source", label: "Source", type: "select", options: ["fbx", "vrma"], required: true },
    ],
    buildPayload: (v) => ({ url: v.url, source: v.source || "fbx" }),
    renderRow: (p) => String(p.url ?? ""),
  },
  {
    key: "scene",
    label: "Scenes",
    summary: "Cadrages caméra + background + idle animation.",
    fields: [
      { name: "bg", label: "Background CSS", placeholder: "linear-gradient(135deg, …)", required: true },
      { name: "idle", label: "Idle animation (URL)", placeholder: "/animations/idle_loop.vrma", required: true },
      { name: "cx", label: "Caméra X", type: "number", placeholder: "0" },
      { name: "cy", label: "Caméra Y", type: "number", placeholder: "1.35" },
      { name: "cz", label: "Caméra Z", type: "number", placeholder: "1.2" },
      { name: "fov", label: "FOV", type: "number", placeholder: "20" },
    ],
    buildPayload: (v) => ({
      camera: { x: numOr(v.cx, 0), y: numOr(v.cy, 1.35), z: numOr(v.cz, 1.2) },
      look_at: { x: 0, y: numOr(v.cy, 1.3) - 0.05, z: 0 },
      fov: numOr(v.fov, 20),
      background: v.bg,
      idle_animation: v.idle,
      avatar_position: { x: 0, y: 0, z: 0 },
      avatar_rotation_y: 0,
    }),
    renderRow: (p) => {
      const cam = p.camera as { x?: number; y?: number; z?: number } | undefined;
      const fov = typeof p.fov === "number" ? p.fov : "-";
      return `cam(${cam?.x ?? 0}, ${cam?.y ?? 0}, ${cam?.z ?? 0}) · FOV ${fov}`;
    },
  },
  {
    key: "emote",
    label: "Emotes",
    summary: "Pop-up emoji par-dessus le stream.",
    fields: [
      { name: "emoji", label: "Emoji", placeholder: "♡", required: true },
      { name: "hue", label: "Teinte CSS", placeholder: "#FF6B8A" },
    ],
    buildPayload: (v) => ({ emoji: v.emoji, ...(v.hue ? { hue: v.hue } : {}) }),
    renderRow: (p) => `${p.emoji ?? ""}  ${p.hue ?? ""}`,
  },
  {
    key: "shot",
    label: "Shots",
    summary: "Cadrages caméra nommés (wide/medium/close/…).",
    fields: [
      { name: "fov", label: "FOV", type: "number", placeholder: "22", required: true },
      { name: "offset_y", label: "Offset Y", type: "number", placeholder: "0" },
    ],
    buildPayload: (v) => ({
      fov: numOr(v.fov, 22),
      ...(v.offset_y ? { offset_y: numOr(v.offset_y, 0) } : {}),
    }),
    renderRow: (p) => `FOV ${p.fov ?? "-"} · ΔY ${p.offset_y ?? 0}`,
  },
  {
    key: "expression",
    label: "Expressions",
    summary: "Blendshapes VRM faciaux (contrainte par le modèle).",
    fields: [
      { name: "vrm_blendshape", label: "Blendshape VRM", placeholder: "happy", required: true,
        help: "Doit correspondre à un blendshape réel du modèle VRM chargé." },
    ],
    buildPayload: (v) => ({ vrm_blendshape: v.vrm_blendshape }),
    renderRow: (p) => String(p.vrm_blendshape ?? ""),
  },
  {
    key: "mood",
    label: "Moods",
    summary: "États ambiant (Markov chain). Payload actuellement décoratif.",
    fields: [
      { name: "color_tint", label: "Teinte CSS (optionnel)", placeholder: "#e08efe" },
    ],
    buildPayload: (v) => (v.color_tint ? { color_tint: v.color_tint } : {}),
    renderRow: (p) => (typeof p.color_tint === "string" ? p.color_tint : "—"),
  },
];

const KIND_MAP: Record<KindKey, KindDef> = Object.fromEntries(KINDS.map((k) => [k.key, k])) as Record<KindKey, KindDef>;

function numOr(s: string | undefined, fallback: number): number {
  if (!s) return fallback;
  const n = Number(s);
  return Number.isFinite(n) ? n : fallback;
}

// ─── Page component ───────────────────────────────────────────────────────

export function AssetsClient() {
  const [activeKind, setActiveKind] = useState<KindKey>("gesture");
  const [rows, setRows] = useState<RegistryRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [flash, setFlash] = useState<string | null>(null);

  const kindDef = KIND_MAP[activeKind];

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(
        `/api/admin/registry?kind=${encodeURIComponent(activeKind)}&include_inactive=true`,
        { credentials: "include" },
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = (await res.json()) as { items: RegistryRow[] };
      setRows(data.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : "fetch failed");
    } finally {
      setLoading(false);
    }
  }, [activeKind]);

  /* eslint-disable react-hooks/set-state-in-effect -- FIXME P5: fetch-on-mount pattern, refactor to useReducer when adopting data lib */
  useEffect(() => { void load(); }, [load]);
  /* eslint-enable react-hooks/set-state-in-effect */

  const handleToggle = async (row: RegistryRow) => {
    try {
      const res = await fetch(`/api/admin/registry/${row.id}`, {
        method: "PATCH",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ is_active: !row.is_active }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      void load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "patch failed");
    }
  };

  const handleDelete = async (row: RegistryRow) => {
    if (!confirm(`Désactiver ${row.slug} ?`)) return;
    try {
      const res = await fetch(`/api/admin/registry/${row.id}`, {
        method: "DELETE",
        credentials: "include",
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      void load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "delete failed");
    }
  };

  return (
    <AdminShell
      active="assets"
      title="Asset Registry"
      subtitle="Données-fiées : Hermes voit toute addition au prochain appel, sans redéploiement."
    >
      {/* Tabs kinds ──────────────────────────────────────────────── */}
      <div style={{ display: "flex", gap: 6, marginBottom: 20, flexWrap: "wrap" }}>
        {KINDS.map((k) => (
          <button
            key={k.key}
            onClick={() => setActiveKind(k.key)}
            style={{
              background: activeKind === k.key
                ? "linear-gradient(135deg, var(--primary), var(--primary-container))"
                : "rgba(36,36,52,0.45)",
              color: activeKind === k.key ? "#1a0a24" : "var(--on-surface-variant)",
              border: "none",
              borderRadius: 999,
              padding: "8px 16px",
              fontFamily: "var(--font-display)",
              fontWeight: 700,
              fontSize: "0.78rem",
              letterSpacing: "0.04em",
              textTransform: "uppercase",
              cursor: "pointer",
              boxShadow: activeKind === k.key
                ? "0 10px 30px -10px rgba(224,142,254,0.6)"
                : "inset 0 0 0 1px rgba(71,71,84,0.25)",
              transition: "all 0.2s ease",
            }}
          >
            {k.label}
          </button>
        ))}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 360px", gap: 24, alignItems: "flex-start" }}>
        {/* Table ──────────────────────────────────────────────── */}
        <section
          style={{
            background: "rgba(36,36,52,0.45)",
            borderRadius: 16,
            padding: 20,
            boxShadow: "inset 0 0 0 1px rgba(71,71,84,0.25)",
            minHeight: 360,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 6 }}>
            <div style={{
              fontFamily: "var(--font-display)", letterSpacing: "0.14em",
              textTransform: "uppercase", color: "var(--on-surface-variant)",
              fontSize: "0.72rem", fontWeight: 600,
            }}>
              {kindDef.label} · {rows.filter((r) => r.is_active).length} actifs / {rows.length} total
            </div>
            <button
              onClick={() => void load()}
              style={{
                background: "transparent", border: "none", cursor: "pointer",
                color: "var(--on-surface-variant)", fontFamily: "var(--font-mono)", fontSize: "0.72rem",
              }}
            >↻ refresh</button>
          </div>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: "0.68rem", color: "var(--on-surface-muted)", marginBottom: 12 }}>
            {kindDef.summary}
          </div>

          {loading && <div style={{ color: "var(--on-surface-muted)", padding: 12 }}>chargement…</div>}
          {error && (
            <div style={{
              background: "rgba(255,106,138,0.12)",
              color: "var(--danger, #ff6a8a)",
              borderRadius: 8, padding: 10, marginBottom: 12, fontSize: "0.8rem",
            }}>
              ✕ {error}
            </div>
          )}

          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {rows.map((r) => (
              <div
                key={r.id}
                style={{
                  display: "grid",
                  gridTemplateColumns: "auto 1fr 1.4fr auto auto",
                  alignItems: "center",
                  gap: 12, padding: "8px 10px",
                  background: r.is_active ? "rgba(9,9,18,0.4)" : "rgba(9,9,18,0.15)",
                  opacity: r.is_active ? 1 : 0.55,
                  borderRadius: 8,
                  boxShadow: "inset 0 0 0 1px rgba(71,71,84,0.18)",
                }}
              >
                <span style={{
                  width: 6, height: 6, borderRadius: "50%",
                  background: r.is_active ? "var(--tertiary)" : "var(--on-surface-muted)",
                }} />
                <span style={{
                  fontFamily: "var(--font-display)", fontWeight: 700,
                  fontSize: "0.82rem", color: "var(--on-surface)",
                }}>
                  {r.slug}
                </span>
                <span style={{
                  fontFamily: "var(--font-mono)", fontSize: "0.72rem",
                  color: "var(--on-surface-variant)",
                  overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                }}>
                  {kindDef.renderRow(r.payload)}
                </span>
                <button
                  onClick={() => void handleToggle(r)}
                  style={{
                    background: "transparent", border: "none", cursor: "pointer",
                    color: "var(--on-surface-variant)",
                    fontFamily: "var(--font-mono)", fontSize: "0.7rem",
                    padding: "4px 8px",
                  }}
                >
                  {r.is_active ? "désactiver" : "activer"}
                </button>
                <button
                  onClick={() => void handleDelete(r)}
                  style={{
                    background: "transparent", border: "none", cursor: "pointer",
                    color: "var(--danger, #ff6a8a)",
                    fontFamily: "var(--font-mono)", fontSize: "0.7rem",
                    padding: "4px 8px",
                  }}
                  disabled={!r.is_active}
                >✕</button>
              </div>
            ))}
            {!loading && rows.length === 0 && (
              <div style={{ color: "var(--on-surface-muted)", padding: 16, textAlign: "center" }}>
                Aucun {kindDef.label.toLowerCase().slice(0, -1)} — utilise le formulaire à droite.
              </div>
            )}
          </div>
        </section>

        {/* Formulaire ──────────────────────────────────────────── */}
        <DynamicForm
          key={kindDef.key}
          kindDef={kindDef}
          onCreated={() => { setFlash(`✓ ${kindDef.label.slice(0, -1)} ajouté`); void load(); }}
          onError={setError}
          flash={flash}
          clearFlash={() => setFlash(null)}
        />
      </div>
    </AdminShell>
  );
}

// ─── DynamicForm (une instance par kind) ───────────────────────────────────

function DynamicForm({
  kindDef, onCreated, onError, flash, clearFlash,
}: {
  kindDef: KindDef;
  onCreated: () => void;
  onError: (msg: string) => void;
  flash: string | null;
  clearFlash: () => void;
}) {
  const [slug, setSlug] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [values, setValues] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);

  // Reset form quand le kind change — géré par key={kindDef.key} sur <DynamicForm />.

  const update = (name: string, value: string) =>
    setValues((prev) => ({ ...prev, [name]: value }));

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!slug || !displayName) return;
    setSubmitting(true);
    clearFlash();
    try {
      const res = await fetch("/api/admin/registry", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          kind: kindDef.key,
          slug: slug.trim(),
          display_name: displayName.trim(),
          payload: kindDef.buildPayload(values),
        }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `HTTP ${res.status}`);
      }
      setSlug("");
      setDisplayName("");
      setValues({});
      onCreated();
    } catch (err) {
      onError(err instanceof Error ? err.message : "create failed");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <aside
      style={{
        background: "rgba(18,18,30,0.75)",
        borderRadius: 16, padding: 20,
        boxShadow: "inset 0 0 0 1px rgba(224,142,254,0.28)",
        backdropFilter: "blur(20px)",
      }}
    >
      <div style={{
        fontFamily: "var(--font-display)", letterSpacing: "0.14em",
        textTransform: "uppercase", color: "var(--on-surface-variant)",
        fontSize: "0.72rem", fontWeight: 600, marginBottom: 14,
      }}>
        Nouveau {kindDef.label.slice(0, -1).toLowerCase()}
      </div>

      <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <Field label="Slug">
          <input
            value={slug}
            onChange={(e) => setSlug(e.target.value)}
            placeholder="my_new_item"
            pattern="[a-zA-Z0-9_\-]{1,64}"
            required
            style={fieldStyle}
          />
        </Field>
        <Field label="Display name">
          <input
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            placeholder="My new item"
            required
            style={fieldStyle}
          />
        </Field>

        {kindDef.fields.map((f) => (
          <Field key={f.name} label={f.label} help={f.help}>
            {f.type === "select" ? (
              <select
                value={values[f.name] ?? (f.options?.[0] ?? "")}
                onChange={(e) => update(f.name, e.target.value)}
                style={{ ...fieldStyle, cursor: "pointer" }}
              >
                {(f.options ?? []).map((o) => <option key={o} value={o}>{o}</option>)}
              </select>
            ) : f.type === "textarea" ? (
              <textarea
                value={values[f.name] ?? ""}
                onChange={(e) => update(f.name, e.target.value)}
                placeholder={f.placeholder}
                required={f.required}
                rows={3}
                style={{ ...fieldStyle, resize: "vertical" }}
              />
            ) : (
              <input
                type={f.type === "number" ? "number" : "text"}
                step={f.type === "number" ? "any" : undefined}
                value={values[f.name] ?? ""}
                onChange={(e) => update(f.name, e.target.value)}
                placeholder={f.placeholder}
                required={f.required}
                style={fieldStyle}
              />
            )}
          </Field>
        ))}

        {flash && (
          <div style={{
            background: "rgba(129,236,255,0.12)",
            color: "var(--tertiary)",
            borderRadius: 8, padding: 8, fontSize: "0.75rem",
          }}>
            {flash}
          </div>
        )}

        <button
          type="submit"
          disabled={submitting || !slug || !displayName}
          style={{
            background: "linear-gradient(135deg, var(--primary), var(--primary-container))",
            color: "#1a0a24", border: "none", borderRadius: 12,
            padding: "10px 16px",
            fontFamily: "var(--font-display)", fontWeight: 700,
            fontSize: "0.82rem", letterSpacing: "0.02em",
            cursor: submitting ? "wait" : "pointer",
            opacity: submitting ? 0.7 : 1, marginTop: 4,
            boxShadow: "0 10px 30px -10px rgba(224,142,254,0.6)",
          }}
        >
          {submitting ? "…" : "✦ Ajouter"}
        </button>
      </form>
    </aside>
  );
}

function Field({ label, children, help }: { label: string; children: React.ReactNode; help?: string }) {
  return (
    <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <span style={{
        fontFamily: "var(--font-display)", fontSize: "0.68rem",
        letterSpacing: "0.08em", textTransform: "uppercase",
        color: "var(--on-surface-muted)",
      }}>{label}</span>
      {children}
      {help && (
        <span style={{
          fontFamily: "var(--font-mono)", fontSize: "0.62rem",
          color: "var(--on-surface-muted)", marginTop: 2,
        }}>{help}</span>
      )}
    </label>
  );
}

const fieldStyle: React.CSSProperties = {
  background: "rgba(9,9,18,0.55)",
  border: "none", borderRadius: 10,
  padding: "8px 10px",
  color: "var(--on-surface)",
  fontFamily: "var(--font-body)", fontSize: "0.82rem",
  outline: "none",
  boxShadow: "inset 0 0 0 1px rgba(71,71,84,0.3)",
  width: "100%",
};
