/**
 * `/[username]/admin/scene-editor` — éditeur 3D Unity-like pour les scenes.
 *
 * Layout (2-col) :
 *   ┌───────────────── toolbar (Save/Preview/Revert + status) ─────────────┐
 *   ├─────────────────────────────────┬────────────────────────────────────┤
 *   │                                 │ Scene selector dropdown            │
 *   │  Mini-viewer Three.js           │ Inspector (gizmo mode, camera,     │
 *   │  (VRM + gizmo + grid + axes +   │  avatar, background, idle anim)    │
 *   │   camera frustum helper)        │                                    │
 *   │                                 │                                    │
 *   └─────────────────────────────────┴────────────────────────────────────┘
 *
 * Flow :
 *   1. Fetch `/api/admin/registry?kind=scene&include_inactive=true` au mount
 *   2. Sélection d'une scene → charge son payload dans `draft` + `original`
 *   3. Modifications via gizmo OU inspector → sync bidirectionnel via `draft`
 *   4. Save → PATCH /api/admin/registry/{id} → bust registry → ok
 *   5. Preview → POST /api/admin/registry/{id}/preview avec payload du draft
 *   6. Revert → draft := original (pas de PATCH DB)
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/router";
import { Meta } from "@/components/meta";
import { AdminShell } from "@/components/admin/AdminShell";
import { fetchAuthStatus } from "@/services/shuguClient";
import { buildUrl } from "@/utils/buildUrl";
import { SceneEditorViewer, type ViewMode } from "@/features/admin/scene-editor/SceneEditorViewer";
import { InspectorPanel } from "@/features/admin/scene-editor/InspectorPanel";
import { SceneEditorToolbar, type Status } from "@/features/admin/scene-editor/SceneEditorToolbar";
import { SceneLibrary } from "@/features/admin/scene-editor/SceneLibrary";
import {
  EMPTY_SCENE, type GizmoMode, type SceneRow, type ScenePayload, type Vec3,
} from "@/features/admin/scene-editor/types";

export default function SceneEditorPage() {
  const router = useRouter();
  const rawUsername = router.query.username;
  const urlUsername = Array.isArray(rawUsername) ? rawUsername[0] : rawUsername;
  // `?preview=1` — mode démo sans auth pour itérer visuellement.
  const previewMode = router.query.preview === "1";
  const [operator, setOperator] = useState<{ username: string } | null>(null);
  const [authChecked, setAuthChecked] = useState(false);

  const [scenes, setScenes] = useState<SceneRow[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [draft, setDraft] = useState<ScenePayload>(EMPTY_SCENE);
  const [original, setOriginal] = useState<ScenePayload>(EMPTY_SCENE);
  const [gizmoMode, setGizmoMode] = useState<GizmoMode>("translate");
  const [viewMode, setViewMode] = useState<ViewMode>("preview");
  const [status, setStatus] = useState<Status>({ kind: "idle" });

  // Auth guard (bypass en previewMode pour iter visuellement)
  useEffect(() => {
    if (previewMode) { setAuthChecked(true); return; }
    let cancelled = false;
    fetchAuthStatus().then((me) => {
      if (cancelled) return;
      setOperator(me);
      setAuthChecked(true);
    });
    return () => { cancelled = true; };
  }, [previewMode]);

  useEffect(() => {
    if (previewMode) return;
    if (!authChecked || !urlUsername) return;
    if (!operator) { router.replace("/login"); return; }
    if (operator.username.toLowerCase() !== urlUsername.toLowerCase()) {
      router.replace(`/${encodeURIComponent(operator.username)}/admin/scene-editor`);
    }
  }, [previewMode, authChecked, operator, urlUsername, router]);

  // Load scenes list
  const loadScenes = useCallback(async () => {
    const res = await fetch("/api/admin/registry?kind=scene&include_inactive=true", {
      credentials: "include",
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = (await res.json()) as { items: SceneRow[] };
    setScenes(data.items);
    // Auto-select première scene active
    if (data.items.length > 0 && !selectedId) {
      const first = data.items.find((s) => s.is_active) ?? data.items[0];
      setSelectedId(first.id);
      setDraft(first.payload);
      setOriginal(first.payload);
      setStatus({ kind: "idle" });
    }
  }, [selectedId]);

  useEffect(() => {
    if (!authChecked) return;
    if (!operator && !previewMode) return;
    // En previewMode (sans auth), on peut quand même tenter le fetch — si
    // le backend refuse (401), on reste avec scenes=[] et c'est OK visuellement.
    void loadScenes().catch((e) => {
      if (previewMode) {
        // En démo, on injecte une scene factice pour voir le rendu.
        setScenes([{
          id: "preview-fake-id",
          kind: "scene",
          slug: "just_chatting",
          display_name: "Just Chatting (demo)",
          payload: EMPTY_SCENE,
          is_active: true,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        }]);
        setSelectedId("preview-fake-id");
        setDraft(EMPTY_SCENE);
        setOriginal(EMPTY_SCENE);
      } else {
        setStatus({ kind: "error", message: String(e) });
      }
    });
  }, [authChecked, operator, previewMode, loadScenes]);

  // Sélection manuelle depuis le dropdown
  const handleSelectScene = (id: string) => {
    const row = scenes.find((s) => s.id === id);
    if (!row) return;
    setSelectedId(id);
    setDraft(row.payload);
    setOriginal(row.payload);
    setStatus({ kind: "idle" });
  };

  // Dirty detection — shallow JSON comparison (assez pour des payloads simples)
  const dirty = useMemo(() => JSON.stringify(draft) !== JSON.stringify(original), [draft, original]);
  useEffect(() => {
    if (status.kind === "saving" || status.kind === "saved" || status.kind === "preview") return;
    setStatus({ kind: dirty ? "dirty" : "idle" });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dirty]);

  // Callback viewer → inspector (quand l'admin drag le gizmo)
  const handleAvatarTransform = useCallback((pos: Vec3, rotY: number) => {
    setDraft((d) => {
      // Evite re-render si valeurs identiques (le gizmo fire "change" à chaque frame)
      if (d.avatar_position.x === pos.x && d.avatar_position.y === pos.y &&
          d.avatar_position.z === pos.z && d.avatar_rotation_y === rotY) {
        return d;
      }
      return { ...d, avatar_position: pos, avatar_rotation_y: rotY };
    });
  }, []);

  // Actions
  const handleSave = async () => {
    if (!selectedId) return;
    if (previewMode || selectedId === "preview-fake-id") {
      setStatus({ kind: "error", message: "Mode démo — connecte-toi pour persister" });
      return;
    }
    setStatus({ kind: "saving" });
    try {
      const res = await fetch(`/api/admin/registry/${selectedId}`, {
        method: "PATCH",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ payload: draft }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({} as { detail?: string }));
        const msg = body.detail || `HTTP ${res.status} ${res.statusText}`;
        throw new Error(msg);
      }
      setOriginal(draft);
      setStatus({ kind: "saved" });
      setTimeout(() => setStatus({ kind: "idle" }), 1800);
      void loadScenes();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "save failed";
      console.error("[scene-editor] save failed:", err);
      setStatus({ kind: "error", message: msg });
    }
  };

  // ─── Library actions (create / duplicate / toggle / delete) ────────
  const handleCreateScene = async (slug: string, displayName: string) => {
    if (previewMode) {
      setStatus({ kind: "error", message: "Mode démo — connecte-toi pour créer" });
      return;
    }
    try {
      const res = await fetch("/api/admin/registry", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          kind: "scene", slug, display_name: displayName,
          payload: EMPTY_SCENE,
        }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({} as { detail?: string }));
        throw new Error(body.detail || `HTTP ${res.status}`);
      }
      const row = (await res.json()) as SceneRow;
      await loadScenes();
      setSelectedId(row.id);
      setDraft(row.payload);
      setOriginal(row.payload);
      setStatus({ kind: "saved" });
      setTimeout(() => setStatus({ kind: "idle" }), 1800);
    } catch (err) {
      setStatus({ kind: "error", message: err instanceof Error ? err.message : "create failed" });
    }
  };

  const handleDuplicateScene = async (id: string) => {
    if (previewMode) {
      setStatus({ kind: "error", message: "Mode démo — connecte-toi pour dupliquer" });
      return;
    }
    const source = scenes.find((s) => s.id === id);
    if (!source) return;
    // Trouve un slug disponible {source.slug}_copy_N
    let n = 1;
    let candidate = `${source.slug}_copy`;
    const slugs = new Set(scenes.map((s) => s.slug));
    while (slugs.has(candidate)) {
      n += 1;
      candidate = `${source.slug}_copy_${n}`;
    }
    try {
      const res = await fetch("/api/admin/registry", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          kind: "scene",
          slug: candidate,
          display_name: `${source.display_name} (copie)`,
          payload: source.payload,
        }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({} as { detail?: string }));
        throw new Error(body.detail || `HTTP ${res.status}`);
      }
      const row = (await res.json()) as SceneRow;
      await loadScenes();
      setSelectedId(row.id);
      setDraft(row.payload);
      setOriginal(row.payload);
    } catch (err) {
      setStatus({ kind: "error", message: err instanceof Error ? err.message : "duplicate failed" });
    }
  };

  const handleToggleActive = async (id: string) => {
    if (previewMode) return;
    const row = scenes.find((s) => s.id === id);
    if (!row) return;
    try {
      await fetch(`/api/admin/registry/${id}`, {
        method: "PATCH",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ is_active: !row.is_active }),
      });
      void loadScenes();
    } catch (err) {
      setStatus({ kind: "error", message: err instanceof Error ? err.message : "toggle failed" });
    }
  };

  const handleDeleteScene = async (id: string) => {
    if (previewMode) return;
    if (!confirm("Soft-delete cette scene ?")) return;
    try {
      await fetch(`/api/admin/registry/${id}`, { method: "DELETE", credentials: "include" });
      void loadScenes();
    } catch (err) {
      setStatus({ kind: "error", message: err instanceof Error ? err.message : "delete failed" });
    }
  };

  const handlePreview = async () => {
    if (!selectedId) return;
    try {
      const res = await fetch(`/api/admin/registry/${selectedId}/preview`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ payload: draft }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `HTTP ${res.status}`);
      }
      setStatus({ kind: "preview" });
      setTimeout(() => setStatus({ kind: dirty ? "dirty" : "idle" }), 2500);
    } catch (err) {
      setStatus({ kind: "error", message: err instanceof Error ? err.message : "preview failed" });
    }
  };

  const handleRevert = () => {
    setDraft(original);
    setStatus({ kind: "idle" });
  };

  return (
    <>
      <Meta />
      <AdminShell
        active="scene-editor"
        title="Scene Editor"
        subtitle="Edit camera, avatar et décor d'une scene. Preview live avant de sauvegarder."
      >
        {authChecked && (operator || previewMode) ? (
          <div style={{ display: "flex", flexDirection: "column", gap: 12, height: "calc(100vh - 180px)" }}>
            <SceneEditorToolbar
              dirty={dirty}
              status={status}
              viewMode={viewMode}
              onViewModeChange={setViewMode}
              onSave={handleSave}
              onPreview={handlePreview}
              onRevert={handleRevert}
            />

            {/* Library workshop — bande horizontale scrollable de cartes */}
            <SceneLibrary
              scenes={scenes}
              selectedId={selectedId}
              onSelect={handleSelectScene}
              onCreate={handleCreateScene}
              onDuplicate={handleDuplicateScene}
              onToggleActive={handleToggleActive}
              onDelete={handleDeleteScene}
            />

            <div style={{
              display: "grid",
              gridTemplateColumns: "1fr 360px",
              gap: 14,
              flex: 1,
              minHeight: 0,
            }}>
              {/* Viewport 3D (plus de dropdown overlay — remplacé par la library) */}
              <div style={{
                position: "relative",
                borderRadius: 16,
                overflow: "hidden",
                background: draft.background || "#0d0d18",
                boxShadow: "inset 0 0 0 1px rgba(71,71,84,0.3)",
                minHeight: 0,
              }}>
                <SceneEditorViewer
                  vrmUrl={buildUrl("/shugu_avatar.vrm")}
                  viewMode={viewMode}
                  gizmoMode={gizmoMode}
                  avatarPosition={draft.avatar_position}
                  avatarRotationY={draft.avatar_rotation_y}
                  sceneCamera={draft.camera}
                  sceneLookAt={draft.look_at}
                  sceneFov={draft.fov}
                  onAvatarTransformChange={handleAvatarTransform}
                />
              </div>

              {/* Inspector */}
              <aside style={{
                background: "rgba(18,18,30,0.75)",
                borderRadius: 16,
                padding: 18,
                overflowY: "auto",
                boxShadow: "inset 0 0 0 1px rgba(224,142,254,0.18)",
                backdropFilter: "blur(20px)",
                minHeight: 0,
              }}>
                <InspectorPanel
                  draft={draft}
                  onChange={setDraft}
                  gizmoMode={gizmoMode}
                  onGizmoModeChange={setGizmoMode}
                  showGizmoControls={viewMode === "edit"}
                />
              </aside>
            </div>
          </div>
        ) : (
          <div style={{ color: "var(--on-surface-muted)", padding: 40, textAlign: "center" }}>
            chargement…
          </div>
        )}
      </AdminShell>
    </>
  );
}
