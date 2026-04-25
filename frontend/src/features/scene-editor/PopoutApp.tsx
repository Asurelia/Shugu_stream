/**
 * Scene Editor — shell minimal "popout" pour un panel isolé (Phase G).
 *
 * Monté par la route Next.js `/shugu/admin/scene-editor-popout?panel=xxx`
 * (cf. `pages/shugu/admin/scene-editor-popout.tsx`). Responsabilités :
 *
 *  1. lire le `panelKey` dans `router.query.panel`,
 *  2. sélectionner le bon composant panel depuis le registry
 *     (`PANEL_COMPONENTS`), connecté au store Zustand commun,
 *  3. signaler `popout-ready` au parent au mount → le parent répond avec
 *     un snapshot `state-sync` qui initialise le store local,
 *  4. écouter les `state-sync` venant du parent pour appliquer les
 *     mutations,
 *  5. observer le store Zustand local et republier les mutations vers le
 *     parent (evite les boucles via `applyingRemoteRef`),
 *  6. signaler `popout-closed` sur `beforeunload` pour un cleanup propre
 *     côté parent.
 *
 * Le store Zustand est importé en direct : comme la popout tourne dans une
 * autre window, son module est ré-évalué → elle a son propre store isolé
 * du parent. C'est précisément pourquoi on a besoin du BroadcastChannel.
 * Les deux stores convergent via `state-sync` sur les quelques champs
 * partagés (`selectedId`, `tool`, `layoutPreset`, `currentScene`).
 */

import { useRouter } from "next/router";
import { useEffect, useMemo, useRef, type ReactNode } from "react";
import {
  LAYOUT_PRESETS,
  useSceneEditorStore,
  type LayoutPreset,
  type Tool,
} from "@/stores/useSceneEditorStore";
import {
  flushPopout,
  POPOUT_NONCE_QUERY_PARAM,
  publishPopout,
  setPopoutNonce,
  subscribePopout,
  type PopoutMessage,
} from "@/lib/editorPopout";
import { CtxMenuProvider } from "./primitives";
import {
  GameViewPanel,
  HierarchyPanel,
  InspectorPanel,
  SceneViewPanel,
} from "./panels-main";
import {
  AssetsPanel,
  FXPanel,
  MixerPanel,
  PatternsPanel,
  PerfPanel,
  StreamPanel,
  TimelinePanel,
} from "./panels-aux";

/**
 * Liste des panelKeys qu'on autorise à ouvrir en popout. Si `router.query.panel`
 * ne matche pas, on affiche un message plutôt que de crasher.
 */
const KNOWN_PANELS = [
  "scene",
  "live",
  "hierarchy",
  "inspector",
  "effects",
  "stream",
  "perf",
  "assets",
  "timeline",
  "patterns",
  "mixer",
] as const;

type KnownPanel = (typeof KNOWN_PANELS)[number];

function isKnownPanel(v: unknown): v is KnownPanel {
  return typeof v === "string" && (KNOWN_PANELS as readonly string[]).includes(v);
}

/**
 * Renderer par panelKey. Identique au `renderPanel` du shell parent mais
 * sans prop `onPopout` (on est déjà dans le popout — re-popping out
 * reviendrait à ouvrir une pop-à-pop, out-of-scope Phase G).
 *
 * Les props `selectedId` / `onSelect` viennent du store (pour que le
 * popout puisse interagir avec la sélection partagée).
 */
function renderPanelStandalone(
  key: KnownPanel,
  selectedId: string | null,
  onSelect: (id: string | null) => void,
): ReactNode {
  switch (key) {
    case "scene":
      return <SceneViewPanel selectedId={selectedId} onSelect={onSelect} />;
    case "live":
      return <GameViewPanel />;
    case "hierarchy":
      // HierarchyPanel utilise `useCtxMenu()` qui throw hors d'un
      // `<CtxMenuProvider>` — d'où le wrap au render root du popout (cf.
      // SceneEditorPopoutApp.return). `onSelect` accepte (id: string | null)
      // côté store mais HierarchyPanel attend (id: string) ; on ne refilte
      // PAS le null — le clic Treeview fournit toujours un id non-null.
      return (
        <HierarchyPanel
          selectedId={selectedId}
          onSelect={(id) => onSelect(id)}
        />
      );
    case "inspector":
      return <InspectorPanel selectedId={selectedId} />;
    case "effects":
      return <FXPanel />;
    case "stream":
      return <StreamPanel />;
    case "perf":
      return <PerfPanel />;
    case "assets":
      return <AssetsPanel />;
    case "timeline":
      return <TimelinePanel />;
    case "patterns":
      return <PatternsPanel />;
    case "mixer":
      return <MixerPanel />;
  }
}

export function SceneEditorPopoutApp() {
  const router = useRouter();
  const rawPanel = router.query.panel;
  const rawNonce = router.query[POPOUT_NONCE_QUERY_PARAM];
  const panelKey = useMemo<KnownPanel | null>(() => {
    const v = Array.isArray(rawPanel) ? rawPanel[0] : rawPanel;
    return isKnownPanel(v) ? v : null;
  }, [rawPanel]);
  const nonce = useMemo<string | null>(() => {
    const v = Array.isArray(rawNonce) ? rawNonce[0] : rawNonce;
    return typeof v === "string" && v.length > 0 ? v : null;
  }, [rawNonce]);

  // ─── Install le nonce de session AVANT toute opération publish/subscribe.
  // Indispensable côté popout : les subscribers parent rejettent tout
  // message dont senderNonce ne matche pas. On installe via `useMemo`
  // synchronisé sur `nonce` — ça garantit que dès que router.query devient
  // populé (1er render after `router.isReady`), le nonce est posé module-
  // level avant que les useEffect ci-dessous ne s'exécutent (les effects
  // tournent toujours APRÈS render, donc après ce useMemo).
  useMemo(() => {
    if (nonce !== null) setPopoutNonce(nonce);
    // Pas de retour : useMemo est utilisé ici comme "synchronous side
    // effect" — c'est techniquement un anti-pattern React, mais c'est
    // idempotent (setPopoutNonce écrit la même valeur module-scoped à
    // chaque appel) et ça nous donne la garantie d'ordering qu'un
    // useEffect ne donnerait pas.
    return undefined;
  }, [nonce]);

  // Sélecteurs stables : on lit les 4 champs synced avec le parent.
  const selectedId = useSceneEditorStore((s) => s.selectedId);
  const setSelectedId = useSceneEditorStore((s) => s.setSelectedId);

  // Flag anti-echo : quand on applique un remote sync, on skip l'outbound
  // publish qui serait émis par le store.subscribe (sinon boucle).
  const applyingRemoteRef = useRef(false);

  // ─── Subscribe : reçoit les state-sync du parent ─────────────────────
  // On gate sur `nonce` aussi : sans nonce, les messages du parent seraient
  // tous droppés par notre subscriber — autant ne pas s'abonner.
  useEffect(() => {
    if (!panelKey || nonce === null) return;
    const unsub = subscribePopout(panelKey, (msg: PopoutMessage) => {
      // On ignore les messages venant de nous-même (un popout ne doit pas
      // se re-traiter). Seuls les messages `origin: 'parent'` nous
      // intéressent côté popout.
      if (msg.origin !== "parent") return;
      if (msg.type !== "state-sync") return;
      const payload = msg.payload;
      if (!payload || typeof payload !== "object") return;
      const p = payload as Partial<{
        selectedId: string | null;
        tool: Tool;
        layoutPreset: LayoutPreset;
        currentScene: string;
      }>;
      applyingRemoteRef.current = true;
      try {
        const store = useSceneEditorStore.getState();
        if (p.selectedId !== undefined && p.selectedId !== store.selectedId) {
          store.setSelectedId(p.selectedId);
        }
        if (p.tool !== undefined && p.tool !== store.tool) {
          store.setTool(p.tool);
        }
        if (
          p.layoutPreset !== undefined &&
          LAYOUT_PRESETS.includes(p.layoutPreset) &&
          p.layoutPreset !== store.layoutPreset
        ) {
          store.setLayoutPreset(p.layoutPreset);
        }
        if (
          p.currentScene !== undefined &&
          p.currentScene !== store.currentScene
        ) {
          store.setCurrentScene(p.currentScene);
        }
      } finally {
        queueMicrotask(() => {
          applyingRemoteRef.current = false;
        });
      }
    });
    return unsub;
  }, [panelKey, nonce]);

  // ─── Signale popout-ready au mount + popout-closed au unload ────────
  // Gate aussi sur `nonce` : envoyer popout-ready avant que le nonce ne
  // soit installé serait un message dont senderNonce serait soit absent
  // soit auto-généré (et donc différent du nonce parent) → drop côté parent.
  useEffect(() => {
    if (!panelKey || nonce === null) return;
    // Au mount : on annonce au parent qu'on est prêt à recevoir l'état initial.
    publishPopout({
      type: "popout-ready",
      origin: "popout",
      panelKey,
    });
    const onBeforeUnload = () => {
      publishPopout({
        type: "popout-closed",
        origin: "popout",
        panelKey,
      });
      // Flush immédiat : beforeunload est la dernière opportunité de sortir
      // un message avant que la window ne meure.
      flushPopout();
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => {
      window.removeEventListener("beforeunload", onBeforeUnload);
    };
  }, [panelKey, nonce]);

  // ─── Republie les mutations locales vers le parent ──────────────────
  useEffect(() => {
    if (!panelKey || nonce === null) return;
    const unsub = useSceneEditorStore.subscribe((state, prev) => {
      if (applyingRemoteRef.current) return;
      const changed =
        state.selectedId !== prev.selectedId ||
        state.tool !== prev.tool ||
        state.layoutPreset !== prev.layoutPreset ||
        state.currentScene !== prev.currentScene;
      if (!changed) return;
      publishPopout({
        type: "state-sync",
        origin: "popout",
        panelKey,
        payload: {
          selectedId: state.selectedId,
          tool: state.tool,
          layoutPreset: state.layoutPreset,
          currentScene: state.currentScene,
        },
      });
    });
    return unsub;
  }, [panelKey, nonce]);

  // ─── Cleanup global : flush le dernier debounce avant unmount ───────
  useEffect(() => {
    return () => {
      flushPopout();
    };
  }, []);

  if (!router.isReady) {
    return (
      <div
        style={{
          color: "rgba(255,255,255,0.45)",
          fontFamily: "var(--ide-font-ui), system-ui, sans-serif",
          fontSize: 12,
          padding: 24,
        }}
      >
        Loading popout…
      </div>
    );
  }

  if (!panelKey) {
    return (
      <div
        style={{
          color: "rgba(255,255,255,0.65)",
          fontFamily: "var(--ide-font-ui), system-ui, sans-serif",
          fontSize: 12,
          padding: 24,
        }}
        data-testid="popout-invalid"
      >
        Unknown panel key. Close this window.
      </div>
    );
  }

  // CtxMenuProvider est requis ici parce que `HierarchyPanel` consomme
  // `useCtxMenu()` qui throw sans provider (cf. primitives.tsx). Wrap au
  // root popout : harmless pour les panels qui ne s'en servent pas.
  return (
    <CtxMenuProvider>
      <div
        className="ide-root"
        style={{ height: "100vh", width: "100vw" }}
        data-testid="popout-root"
        data-panel-key={panelKey}
      >
        <div
          className="ide-menubar"
          style={{ height: 28 }}
        >
          <div className="ide-menubar-brand">
            <div className="mark">S</div>
            <span style={{ fontSize: 12, color: "var(--ide-text)" }}>Shugu</span>
            <span style={{ fontSize: 11, color: "var(--ide-text-dim)" }}>
              {panelKey}
            </span>
          </div>
          <div className="ide-menubar-spacer" />
          <div className="ide-menubar-status">
            <span>Detached window · synced</span>
          </div>
        </div>
        <div
          style={{
            flex: 1,
            display: "flex",
            padding: 8,
            minHeight: 0,
            height: "calc(100vh - 28px)",
          }}
        >
          {renderPanelStandalone(panelKey, selectedId, setSelectedId)}
        </div>
      </div>
    </CtxMenuProvider>
  );
}

export default SceneEditorPopoutApp;
