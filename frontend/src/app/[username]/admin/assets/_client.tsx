"use client";

/**
 * Asset Registry client island.
 *
 * Migration Pages Router → App Router (Sprint E5) :
 *   - `<Meta>` supprimé — métadonnées déclarées côté Server (`page.tsx`).
 *   - `AdminShell` migré vers `next/navigation` ; fonctionne uniquement App Router.
 *   - `export default` renommé en `export function AssetsClient`.
 *
 * Refonte design system (audit UX P0) :
 *   - Tous les inline-styles remplacés par Glass primitives.
 *   - confirm() natif → GlassModal de confirmation.
 *   - setError() → useToast().error().
 *   - flash → toast.success().
 *   - Skeleton loading + empty state cohérents.
 */
import { useCallback, useEffect, useState, type FormEvent } from "react";

import { AdminShell } from "@/components/admin/AdminShell";
import {
  GlassSection,
  GlassCard,
  GlassRow,
  GlassPill,
  GlassButton,
  GlassInput,
  GlassTabs,
  GlassModal,
  useToast,
} from "@/features/liquid-glass/primitives";
import {
  listAssets,
  createAsset,
  toggleAsset,
  deleteAsset,
  AdminAssetsError,
  type RegistryRow,
} from "@/services/adminAssetsClient";

// ─── Re-export type for external consumers ────────────────────────────────────
export type { RegistryRow };

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
      {
        name: "vrm_blendshape",
        label: "Blendshape VRM",
        placeholder: "happy",
        required: true,
        help: "Doit correspondre à un blendshape réel du modèle VRM chargé.",
      },
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

const KIND_MAP: Record<KindKey, KindDef> = Object.fromEntries(
  KINDS.map((k) => [k.key, k]),
) as Record<KindKey, KindDef>;

function numOr(s: string | undefined, fallback: number): number {
  if (!s) return fallback;
  const n = Number(s);
  return Number.isFinite(n) ? n : fallback;
}

// ─── Page component ───────────────────────────────────────────────────────

export function AssetsClient() {
  const toast = useToast();
  const [activeKind, setActiveKind] = useState<KindKey>("gesture");
  const [rows, setRows] = useState<RegistryRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [pendingDelete, setPendingDelete] = useState<RegistryRow | null>(null);
  const [deleting, setDeleting] = useState(false);

  const kindDef = KIND_MAP[activeKind];

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listAssets(activeKind);
      setRows(data.items);
    } catch (err) {
      const detail =
        err instanceof AdminAssetsError ? err.detail : "Erreur réseau";
      toast.error("Chargement échoué", { description: detail });
    } finally {
      setLoading(false);
    }
  }, [activeKind, toast]);

  /* eslint-disable react-hooks/set-state-in-effect -- FIXME P5: fetch-on-mount pattern, refactor to useReducer when adopting data lib */
  useEffect(() => { void load(); }, [load]);
  /* eslint-enable react-hooks/set-state-in-effect */

  const handleToggle = async (row: RegistryRow) => {
    try {
      await toggleAsset(row.id, !row.is_active);
      void load();
    } catch (err) {
      const detail =
        err instanceof AdminAssetsError ? err.detail : "Erreur réseau";
      toast.error("Action échouée", { description: detail });
    }
  };

  const handleConfirmDelete = async () => {
    if (!pendingDelete) return;
    setDeleting(true);
    try {
      await deleteAsset(pendingDelete.id);
      setPendingDelete(null);
      toast.success("Asset désactivé", { description: pendingDelete.slug });
      void load();
    } catch (err) {
      const detail =
        err instanceof AdminAssetsError ? err.detail : "Erreur réseau";
      toast.error("Action échouée", { description: detail });
    } finally {
      setDeleting(false);
    }
  };

  const handleCreated = (slug: string) => {
    toast.success("Asset créé", { description: slug });
    void load();
  };

  const KINDS_TABS = KINDS.map((k) => ({ value: k.key, label: k.label }));

  return (
    <AdminShell
      active="assets"
      title="Asset Registry"
      subtitle="Données-fiées : le LLM voit toute addition au prochain appel, sans redéploiement."
      headerRight={
        <GlassPill tone="primary" dot>
          {rows.filter((r) => r.is_active).length} actifs / {rows.length} total
        </GlassPill>
      }
    >
      <section className="flex flex-col gap-5">
        {/* Tabs kinds */}
        <GlassTabs
          aria-label="Catégorie d'asset"
          tabs={KINDS_TABS}
          value={activeKind}
          onChange={(v) => setActiveKind(v as KindKey)}
        />

        <div className="grid grid-cols-1 lg:grid-cols-[1fr_360px] gap-6 items-start">
          {/* Liste assets */}
          <GlassSection
            title={kindDef.label}
            subtitle={kindDef.summary}
            right={
              <GlassButton variant="ghost" size="sm" onClick={() => void load()}>
                {loading ? "…" : "Rafraîchir"}
              </GlassButton>
            }
          >
            {loading ? (
              <GlassCard>
                <div className="py-6 text-center text-sm opacity-60">Chargement…</div>
              </GlassCard>
            ) : rows.length === 0 ? (
              <GlassCard>
                <div className="py-6 text-center text-sm opacity-60">
                  Aucun {kindDef.label.toLowerCase().slice(0, -1)} — utilise le formulaire à droite.
                </div>
              </GlassCard>
            ) : (
              rows.map((r) => (
                <GlassRow
                  key={r.id}
                  label={
                    <span className="flex items-center gap-2">
                      <span className="font-semibold">{r.slug}</span>
                      <GlassPill tone={r.is_active ? "tertiary" : "default"} dot>
                        {r.is_active ? "actif" : "inactif"}
                      </GlassPill>
                    </span>
                  }
                  sub={
                    <span className="font-mono text-[11px] opacity-65 truncate block">
                      {kindDef.renderRow(r.payload)}
                    </span>
                  }
                  trailing={
                    <div className="flex items-center gap-2 shrink-0">
                      <GlassButton
                        variant="ghost"
                        size="sm"
                        onClick={() => void handleToggle(r)}
                      >
                        {r.is_active ? "Désactiver" : "Activer"}
                      </GlassButton>
                      <GlassButton
                        variant="danger"
                        size="sm"
                        onClick={() => setPendingDelete(r)}
                        disabled={!r.is_active}
                      >
                        Désactiver
                      </GlassButton>
                    </div>
                  }
                />
              ))
            )}
          </GlassSection>

          {/* Formulaire */}
          <DynamicForm
            key={kindDef.key}
            kindDef={kindDef}
            onCreated={handleCreated}
          />
        </div>
      </section>

      {/* Modal de confirmation désactivation */}
      <GlassModal
        open={pendingDelete !== null}
        onClose={() => { if (!deleting) setPendingDelete(null); }}
        title="Désactiver l'asset"
        footer={
          <>
            <GlassButton
              variant="ghost"
              size="sm"
              onClick={() => setPendingDelete(null)}
              disabled={deleting}
            >
              Annuler
            </GlassButton>
            <GlassButton
              variant="danger"
              size="sm"
              onClick={() => void handleConfirmDelete()}
              disabled={deleting}
            >
              {deleting ? "…" : "Désactiver"}
            </GlassButton>
          </>
        }
      >
        <p className="text-sm opacity-80">
          Désactiver{" "}
          <strong>&quot;{pendingDelete?.slug}&quot;</strong> ?
          <br />
          <span className="opacity-60 text-xs">L&apos;asset reste en base et peut être réactivé via le bouton de bascule.</span>
        </p>
      </GlassModal>
    </AdminShell>
  );
}

// ─── DynamicForm (une instance par kind) ───────────────────────────────────

function DynamicForm({
  kindDef,
  onCreated,
}: {
  kindDef: KindDef;
  onCreated: (slug: string) => void;
}) {
  const toast = useToast();
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
    try {
      await createAsset({
        kind: kindDef.key,
        slug: slug.trim(),
        display_name: displayName.trim(),
        payload: kindDef.buildPayload(values),
      });
      setSlug("");
      setDisplayName("");
      setValues({});
      onCreated(slug.trim());
    } catch (err) {
      const detail =
        err instanceof AdminAssetsError ? err.detail : "create failed";
      toast.error("Création échouée", { description: detail });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <GlassCard as="aside">
      <div className="flex flex-col gap-4">
        <div className="text-xs font-semibold tracking-widest uppercase opacity-70">
          Nouveau {kindDef.label.slice(0, -1).toLowerCase()}
        </div>

        <form onSubmit={(e) => void handleSubmit(e)} className="flex flex-col gap-3">
          <GlassInput
            label="Slug"
            value={slug}
            onChange={(e) => setSlug(e.target.value)}
            placeholder="my_new_item"
            pattern="[a-zA-Z0-9_\-]{1,64}"
            required
          />
          <GlassInput
            label="Display name"
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            placeholder="My new item"
            required
          />

          {kindDef.fields.map((f) => (
            <div key={f.name} className="flex flex-col gap-1">
              {f.type === "select" ? (
                <div className="lgi-group">
                  <label className="lgi-label">{f.label}</label>
                  <select
                    value={values[f.name] ?? (f.options?.[0] ?? "")}
                    onChange={(e) => update(f.name, e.target.value)}
                    className="lgi lgi-select lg-focus-ring"
                  >
                    {(f.options ?? []).map((o) => (
                      <option key={o} value={o}>
                        {o}
                      </option>
                    ))}
                  </select>
                </div>
              ) : f.type === "textarea" ? (
                /* textarea fallback — no GlassTextarea primitive exists yet */
                <div className="lgi-group">
                  <label className="lgi-label">{f.label}</label>
                  <textarea
                    value={values[f.name] ?? ""}
                    onChange={(e) => update(f.name, e.target.value)}
                    placeholder={f.placeholder}
                    required={f.required}
                    rows={3}
                    className="lgi lg-focus-ring resize-y"
                  />
                </div>
              ) : (
                <GlassInput
                  label={f.label}
                  type={f.type === "number" ? "number" : "text"}
                  step={f.type === "number" ? "any" : undefined}
                  value={values[f.name] ?? ""}
                  onChange={(e) => update(f.name, e.target.value)}
                  placeholder={f.placeholder}
                  required={f.required}
                  hint={f.help}
                />
              )}
            </div>
          ))}

          <GlassButton
            type="submit"
            variant="primary"
            size="md"
            block
            disabled={submitting || !slug || !displayName}
          >
            {submitting ? "…" : "✦ Ajouter"}
          </GlassButton>
        </form>
      </div>
    </GlassCard>
  );
}
