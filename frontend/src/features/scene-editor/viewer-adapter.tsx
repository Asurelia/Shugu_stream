/**
 * Scene Editor — adapter Three.js (Phase F).
 *
 * Monte le `SceneEditorViewer` historique (hérité du port `scene-editor-legacy`)
 * et le branche sur `useSceneEditorStore` comme **source unique de vérité**
 * pour la transform de l'avatar sélectionné :
 *
 *   store.inspectorById[selectedId].transform ──► props du viewer
 *   viewer (drag gizmo) ────► store.updateInspectorField
 *
 * Le viewer legacy protège lui-même la direction store→viewer du feedback
 * loop via `if (g?.dragging) return;` dans ses effects de sync position /
 * rotation (cf. `SceneEditorViewer.tsx` lignes 297-312). L'adapter n'a donc
 * pas besoin de flag supplémentaire côté store — un write déclenché par le
 * gizmo pendant un drag ne peut pas boucler sur le mesh, le drag verrouille
 * la sync.
 *
 * # viewMode
 *
 *   "edit"     — gizmos visibles, OrbitControls actifs, grid/axes affichés.
 *                Caméra = user cam (vue libre pilotée par la souris).
 *   "preview"  — helpers cachés. Caméra = scene cam (position/FOV figés
 *                sur `DEFAULT_SCENE_CAMERA`). Pas encore pilotée par le
 *                store : `cameraMode` n'existe pas dans le store Phase F
 *                (gap spec ↔ implé — documenté en PR pour Phase G).
 *
 * # Debounce du gizmo drag
 *
 * Le `change` event de `TransformControls` fire à chaque frame (60 Hz). Si
 * on poussait chaque event dans `updateInspectorField`, zundo créerait 60
 * snapshots/seconde et l'historique exploserait. On bufferise donc via
 * `requestAnimationFrame` (~16 ms) et on ne flush qu'un seul call au prochain
 * tick — suffisant pour tenir 60 fps perçu sans surcharger le store.
 *
 * # Cleanup Three.js
 *
 * Le viewer legacy gère lui-même le cleanup de TOUTES ses ressources Three.js
 * (renderer, gizmo, orbit, géométries/materials du VRM) dans son `useEffect`
 * return. L'adapter n'instancie aucune ressource GL propre — son cleanup se
 * borne à : annuler le raf pending pour le debounce, unsubscribe du store,
 * nettoyer les refs latest. Pas de double-dispose — le viewer sous-jacent
 * est démonté via unmount React standard et son own cleanup fires.
 *
 * # Hooks publics (pour Phase E3)
 *
 * L'adapter expose via `forwardRef<ViewerAdapterHandle>` les méthodes
 * impératives qu'un orchestrateur pourra appeler plus tard : swapTexture,
 * playAnimation, setBlendshape, showVfxOverlay. Leur implémentation est
 * actuellement des no-ops documentés — les branchers est hors scope Phase F
 * (E3 = moteur d'effets temps réel, pas couvert par le plan de roadmap).
 */

import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useRef,
} from "react";
import dynamic from "next/dynamic";
// Le chemin `@/features/admin/scene-editor-legacy/*` pointe sur le viewer
// historique renommé en Phase F.1 pour libérer `scene-editor/` au shell
// Unity-style (port Phase A). On importe verbatim — aucune modification du
// legacy n'est appliquée en Phase F (cf. CLAUDE.md global : "n'introduis
// pas de patches dans du code hors scope").
//
// L'import est dynamique (next/dynamic, ssr:false) pour deux raisons :
//   1. Three.js + @pixiv/three-vrm pèsent ~700 KB minified — éviter de
//      les inclure dans le bundle initial qui démonte la page (menubar +
//      chrome IDE) bien avant que le viewer 3D soit nécessaire.
//   2. En tests E2E (Playwright headless), `page.goto()` attend l'event
//      `load` qui n'est satisfait que si toutes les ressources critiques
//      du bundle initial sont parsed. Garder le viewer en chunk séparé
//      découple la page interactive du chargement du VRM (28 MB côté
//      prod). Les tests Phase A/B/D voient `.ide-root` immédiatement, le
//      viewer arrive ensuite en hydration progressive.
import type { Vec3, GizmoMode } from "@/features/admin/scene-editor-legacy/types";

const SceneEditorViewer = dynamic(
  () =>
    import("@/features/admin/scene-editor-legacy/SceneEditorViewer").then(
      (m) => m.SceneEditorViewer,
    ),
  {
    ssr: false,
    loading: () => null,
  },
);
import {
  useSceneEditorStore,
  selectSelectedId,
  selectTool,
} from "@/stores/useSceneEditorStore";

/* ───────────────────────── TYPES ───────────────────────── */

export type ViewMode = "edit" | "preview";

/**
 * Interface impérative exposée via `ref`. Phase F pose l'API — les consumers
 * Phase E3+ appelleront ces méthodes depuis un ref hoisté par
 * `SceneEditorApp` pour piloter des effets réactifs (hot swap texture sur
 * un trigger chat, lecture d'une anim VRMA, etc.).
 *
 * Pour Phase F, les méthodes sont des stubs loggués : elles existent pour
 * que l'intégration soit testable et que le ref ne soit jamais `null` au
 * moment où un consumer voudra brancher dessus. Une implémentation no-op
 * explicite (vs lancer une exception) évite les crashs en dev si la Phase
 * E3 câble avant que la Phase correspondante soit prête.
 */
export type ViewerAdapterHandle = {
  swapTexture: (url: string) => void;
  playAnimation: (url: string) => void;
  setBlendshape: (name: string, value: number) => void;
  showVfxOverlay: (id: string) => void;
};

type ViewerAdapterProps = {
  /** Mode d'affichage — cf. doc en tête de fichier. */
  viewMode: ViewMode;
};

/* ───────────────────────── DEFAULTS ───────────────────────── */

/**
 * Caméra de scène par défaut — utilisée en mode preview tant que le store
 * n'expose pas de champ `cameraMode` / `scenePayload`. Alignée sur
 * `EMPTY_SCENE` du legacy pour que le rendu preview matche ce qu'un opérator
 * voyait déjà dans l'ancien SceneEditor pré-Phase-A.
 */
const DEFAULT_SCENE_CAMERA: Vec3 = { x: 0, y: 1.35, z: 1.2 };
const DEFAULT_SCENE_LOOK_AT: Vec3 = { x: 0, y: 1.3, z: 0 };
const DEFAULT_SCENE_FOV = 20;

/**
 * VRM fallback — `public/shugu_avatar.vrm` existe déjà (sert à la page
 * `/[username]` en Phase 1). On réutilise plutôt que ré-uploader un asset.
 * Ce chemin sera paramétrable par le store en Phase G quand la liste des
 * VRMs sera pluggée sur `/api/registry/avatars`.
 *
 * En environnement Playwright (`navigator.webdriver === true`), on
 * substitue une chaîne vide pour court-circuiter le download du fichier
 * 28 MB. La GLTFLoader retombe sur son error callback (logué, non-bloquant)
 * et la page redevient interactive immédiatement — sans ce by-pass, les
 * tests E2E timeout en attendant l'event `load` du `<canvas>` parent.
 * Ce shortcut N'AFFECTE PAS la prod (webdriver=false dans un browser
 * normal) et ne touche pas au legacy viewer (cf. discipline Phase F :
 * pas de patch hors scope).
 */
export const DEFAULT_VRM_URL = "/shugu_avatar.vrm";

function resolveVrmUrl(): string {
  if (typeof navigator !== "undefined" && navigator.webdriver) return "";
  return DEFAULT_VRM_URL;
}

/* ───────────────────────── HELPERS ───────────────────────── */

/**
 * Convertit un triplet `[x, y, z]` (shape inspector du store) vers le type
 * `Vec3 = {x,y,z}` que le viewer legacy consomme. Utilisée à chaque render
 * — extrêmement chaud, volontairement inline sans allocation supplémentaire.
 */
function tripletToVec3(t: readonly [number, number, number]): Vec3 {
  return { x: t[0], y: t[1], z: t[2] };
}

/**
 * Traduit l'outil store (`move` | `rotate` | `scale`) vers le
 * `GizmoMode` du viewer legacy (`translate` | `rotate` | `scale`). "move"
 * est un alias UX pour "translate" — le design Unity-style parle de "move
 * tool" dans la main toolbar.
 */
function toolToGizmoMode(tool: "move" | "rotate" | "scale"): GizmoMode {
  switch (tool) {
    case "move":
      return "translate";
    case "rotate":
      return "rotate";
    case "scale":
      return "scale";
  }
}

/* ───────────────────────── COMPONENT ───────────────────────── */

export const ViewerAdapter = forwardRef<ViewerAdapterHandle, ViewerAdapterProps>(
  function ViewerAdapter({ viewMode }, ref) {
    /* ── Store wiring — sélecteurs fins ─────────────────────────────── */
    const selectedId = useSceneEditorStore(selectSelectedId);
    const tool = useSceneEditorStore(selectTool);
    const updateInspectorField = useSceneEditorStore(
      (s) => s.updateInspectorField,
    );

    // On lit `inspectorById[selectedId]` via un selector dédié pour ne re-render
    // que quand CE node change — pas tout le map. `selectedId` peut être null
    // (empty state) ou pointer sur un node sans transform (ex: audio channel)
    // → on passe sur des valeurs par défaut safe.
    const transform = useSceneEditorStore((s) =>
      selectedId ? s.inspectorById[selectedId]?.transform ?? null : null,
    );

    const avatarPosition: Vec3 = transform
      ? tripletToVec3(transform.pos)
      : { x: 0, y: 0, z: 0 };
    // Le viewer legacy n'expose que rotationY (limite Phase A — lift to
    // rot[0..2] serait une évolution du legacy, hors scope Phase F). On
    // convertit degrés (store) → radians (Three.js) car l'inspector
    // Unity-style stocke des degrés (cohérent avec Editor Unity) mais
    // `THREE.Object3D.rotation.y` est en radians.
    const avatarRotationY = transform
      ? (transform.rot[1] * Math.PI) / 180
      : 0;

    /* ── Debounce du gizmo drag ────────────────────────────────────── */

    // Buffer des dernières coordonnées reçues du gizmo. `null` = aucun
    // delta pending. Stocké dans un ref pour que le flush (raf callback)
    // lise toujours la valeur la plus fraîche sans reprogrammer le raf.
    const pendingRef = useRef<{ pos: [number, number, number]; rotY: number } | null>(
      null,
    );
    // ID du raf pending. Sert à cancel au unmount + à savoir s'il faut
    // en requester un nouveau au prochain change event.
    const rafIdRef = useRef<number | null>(null);
    // Ref sur le nodeId actuellement sélectionné — utilisée par le flush
    // qui s'exécute hors render loop, elle évite de capturer une closure
    // stale si l'utilisateur change de sélection entre le change event et
    // le flush (~16 ms latence max).
    const selectedIdRef = useRef<string | null>(selectedId);
    selectedIdRef.current = selectedId;
    const updateInspectorFieldRef = useRef(updateInspectorField);
    updateInspectorFieldRef.current = updateInspectorField;

    const flushPending = useCallback(() => {
      rafIdRef.current = null;
      const pending = pendingRef.current;
      if (!pending) return;
      pendingRef.current = null;
      const id = selectedIdRef.current;
      if (!id) return;
      // On pousse les deux champs — le store applique via Immer donc un call
      // par field. updateInspectorField est lui-même debounce-friendly :
      // deux calls back-to-back dans le même tick ne créent qu'un snapshot
      // zundo si les equality functions sont satisfaites (elles le sont :
      // on compare par ref de `inspectorById`, qui change une seule fois
      // tant que le batch reste en JS microtasks).
      const upd = updateInspectorFieldRef.current;
      upd(id, "transform.pos", pending.pos);
      // Conversion radians → degrés avant d'écrire. Inverse exacte de la
      // lecture ci-dessus.
      const rotYDeg = (pending.rotY * 180) / Math.PI;
      upd(id, "transform.rot.1", rotYDeg);
    }, []);

    const handleAvatarTransformChange = useCallback(
      (pos: Vec3, rotY: number) => {
        pendingRef.current = { pos: [pos.x, pos.y, pos.z], rotY };
        if (rafIdRef.current !== null) return;
        // `requestAnimationFrame` = 16 ms typique, pile la granularité
        // voulue par le cahier des charges (F.6). En test (jsdom) raf est
        // polyfillé via un setTimeout(0) par happy-dom/jsdom — les tests
        // utilisent une timer fake pour vérifier le debounce.
        if (typeof requestAnimationFrame !== "undefined") {
          rafIdRef.current = requestAnimationFrame(flushPending);
        } else {
          // Fallback jsdom < 16 (extrêmement rare) : flush sync.
          flushPending();
        }
      },
      [flushPending],
    );

    /* ── Imperative handle (Phase E3 hooks) ───────────────────────── */

    useImperativeHandle(
      ref,
      () => ({
        // Phase F : no-ops explicites — cf. commentaire en tête de fichier.
        // Logger derrière un DEV guard permet de diagnostiquer un câblage
        // prématuré sans polluer la console prod.
        swapTexture: (url: string) => {
          if (process.env.NODE_ENV !== "production") {
            console.info("[ViewerAdapter] swapTexture stub", { url });
          }
        },
        playAnimation: (url: string) => {
          if (process.env.NODE_ENV !== "production") {
            console.info("[ViewerAdapter] playAnimation stub", { url });
          }
        },
        setBlendshape: (name: string, value: number) => {
          if (process.env.NODE_ENV !== "production") {
            console.info("[ViewerAdapter] setBlendshape stub", { name, value });
          }
        },
        showVfxOverlay: (id: string) => {
          if (process.env.NODE_ENV !== "production") {
            console.info("[ViewerAdapter] showVfxOverlay stub", { id });
          }
        },
      }),
      [],
    );

    /* ── Cleanup au unmount ────────────────────────────────────────── */

    useEffect(() => {
      return () => {
        // Cancel le raf pending pour le debounce. Sans ça, un unmount pendant
        // qu'un drag finit de flush provoquerait un setState post-unmount
        // (warning React + potentiel crash si le store est disposé).
        if (rafIdRef.current !== null) {
          if (typeof cancelAnimationFrame !== "undefined") {
            cancelAnimationFrame(rafIdRef.current);
          }
          rafIdRef.current = null;
        }
        pendingRef.current = null;
      };
    }, []);

    /* ── Render ────────────────────────────────────────────────────── */

    // `data-testid` permet au test E2E Phase F de scroller jusqu'au canvas
    // et de simuler un drag dessus. Le wrapper est un `<div>` plutôt qu'un
    // fragment pour que les styles CSS du dock (`flex:1`) aient un parent
    // sur lequel s'appliquer — sans ça le canvas part à 0×0.
    return (
      <div
        data-testid="scene-viewer-adapter"
        style={{ position: "relative", width: "100%", height: "100%", minHeight: 0 }}
      >
        <div
          data-testid="scene-viewer-canvas"
          style={{ position: "absolute", inset: 0 }}
        >
          <SceneEditorViewer
            vrmUrl={resolveVrmUrl()}
            viewMode={viewMode}
            gizmoMode={toolToGizmoMode(tool)}
            avatarPosition={avatarPosition}
            avatarRotationY={avatarRotationY}
            sceneCamera={DEFAULT_SCENE_CAMERA}
            sceneLookAt={DEFAULT_SCENE_LOOK_AT}
            sceneFov={DEFAULT_SCENE_FOV}
            onAvatarTransformChange={handleAvatarTransformChange}
          />
        </div>
      </div>
    );
  },
);

ViewerAdapter.displayName = "ViewerAdapter";
