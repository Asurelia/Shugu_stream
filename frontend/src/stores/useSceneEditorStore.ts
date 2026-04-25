/**
 * Scene Editor — store principal (état UI + data mockée côté front).
 *
 * Ce store est la **source unique de vérité** pour l'état qui transite entre
 * les panels du Scene Editor (hierarchy, assets, inspector, etc.). Il est
 * volontairement séparé de `useDockLayoutStore` (qui persiste le layout des
 * docks) : le contenu du store ici **ne doit pas survivre** au reload — on
 * veut qu'une nouvelle session repart propre sur la scène active et l'outil
 * sélectionné, uniquement l'ergonomie de dock est mémorisée.
 *
 * # Architecture
 *
 *   (UI state)             (Data state)
 *   - currentScene         - scenes[]        ← seeded from mock-data.ts
 *   - selectedId           - hierarchy[]
 *   - tool                 - inspector
 *   - layoutPreset         - assets[]
 *                          - patterns[]
 *                          - audioChannels[]
 *                          - timeline
 *
 * Toutes les Phase C+ (backend CRUD), les `scenes` / `hierarchy` / etc.
 * seront rafraîchies depuis l'API au mount ; le store devient alors un
 * cache local. Pour Phase B on se contente de wrap les mocks pour ouvrir
 * le chemin.
 *
 * # Undo/Redo (Zundo / temporal middleware)
 *
 * Seuls `currentScene` et `layoutPreset` sont suivis par l'historique — les
 * changements de `tool`/`selectedId` sont des gestes éphémères qu'il serait
 * confusant de voir repasser en ⌘Z. Les *vrais* edits (move avatar, set FOV,
 * etc.) seront ajoutés au `partialize` au fil des Phases E/F quand la
 * sémantique DraftScene sera implémentée.
 *
 * Les actions `undo()` / `redo()` sont branchées sur les hotkeys ⌘Z / ⌘⇧Z
 * via `SceneEditorApp` → `useHotkeys`. L'accès se fait via
 * `useSceneEditorStore.temporal.getState().undo()`.
 */

import { create } from "zustand";
import { temporal } from "zundo";
import type { TemporalState } from "zundo";
import { useStore } from "zustand";
import { produce } from "immer";
import {
  MOCK_ASSETS,
  MOCK_AUDIO_CHANNELS,
  MOCK_HIERARCHY,
  MOCK_INSPECTOR,
  MOCK_PATTERNS,
  MOCK_SCENES,
  MOCK_TIMELINE,
  type AssetItem,
  type AudioChannel,
  type InspectorData,
  type PatternItem,
  type SceneSummary,
  type TimelineData,
} from "@/features/scene-editor/mock-data";
import type { TreeNodeData } from "@/features/scene-editor/primitives";

/* ─────────────────────────── TYPES ─────────────────────────── */

/** Outil actif dans la main toolbar + hotkeys W/E/R. */
export type Tool = "move" | "rotate" | "scale";

/**
 * Presets de layout prédéfinis. Port verbatim des options du Select dans
 * `SceneEditorApp.tsx::MainToolbar` (design bundle Claude Design) — toute
 * divergence ici casse l'UI car le `<Select>` ne matche pas sa `value`.
 * Fix Phase B H-1 : les valeurs étaient lowercase (default/coding/streaming)
 * → 3 options sur 4 devenaient silent no-op.
 */
export type LayoutPreset = "Streaming" | "Editing" | "Performance" | "Custom…";

/** Liste source des options, identique à celle passée à Select. */
export const LAYOUT_PRESETS: readonly LayoutPreset[] = [
  "Streaming",
  "Editing",
  "Performance",
  "Custom…",
] as const;

/**
 * Phase E3 — kinds supportés dans le payload `scene.apply` broadcast par
 * le Director backend. Chaque kind correspond à un tag inline émis par
 * Shugu Soul (E2) et exécuté par le worker du même nom (cf.
 * `backend/shugu/director/workers/`). Le frontend route ces events via
 * `useEditorWebSocket` → `dispatchSceneApply` → `<ViewerAdapter>`.
 *
 * `say_emotion` est livré ici pour traçabilité (debug, logs front), mais
 * n'a pas d'effet visuel sur le viewer 3D — le tag est consommé en E4 par
 * le pipeline TTS pour choisir un preset voix.
 */
export type SceneApplyKind =
  | "outfit"
  | "vfx"
  | "anim"
  | "face"
  | "say_emotion"
  | "camera"
  | "scene";

/**
 * Payload `scene.apply` reçu via WS, normalisé pour le store.
 *
 * `seq` est local au store (incrémenté à chaque `dispatchSceneApply`) — il
 * permet à un `useEffect([lastSceneApply])` de re-trigger même si le
 * backend ré-émet exactement le même `(kind, id)` (changement de la
 * référence d'objet garanti). Sans `seq`, deux broadcasts identiques
 * partageraient la même structure JSON parsée et useEffect skipperait.
 */
export type SceneApplyEvent = {
  /** Discriminator du kind d'effet (cf. `SceneApplyKind`). */
  kind: SceneApplyKind;
  /** Slug de l'asset / mode (id pour outfit/vfx/anim/face/scene/say_emotion ; mode pour camera). */
  id: string;
  /** Durée d'effet en ms (VFX uniquement, sinon undefined). */
  durationMs?: number;
  /** Loop flag (animations uniquement). */
  loop?: boolean;
  /** Timestamp ISO-8601 d'émission backend (debug, logs). */
  ts?: string;
  /** Numéro de séquence local (incrémenté à chaque dispatch). */
  seq: number;
};

/* ─────────────────────────── STATE ─────────────────────────── */

export interface SceneEditorState {
  /* ---- UI state (éphémère, non persisté) ---- */
  currentScene: string;
  selectedId: string | null;
  tool: Tool;
  layoutPreset: LayoutPreset;

  /* ---- Data state (mocks côté Phase B, remplacés par API Phase C+) ---- */
  scenes: SceneSummary[];
  hierarchy: TreeNodeData[];
  /**
   * Map node id → propriétés inspectables. L'Inspector Panel lit
   * `inspectorById[selectedId]` à la volée ; on garde cette shape plutôt
   * qu'un seul blob pour faciliter Phase D (WS) où chaque node peut être
   * mis à jour indépendamment.
   */
  inspectorById: Record<string, InspectorData>;
  assets: AssetItem[];
  audioChannels: AudioChannel[];
  patterns: PatternItem[];
  timeline: TimelineData;

  /* ---- Phase D — WS collaboration state (éphémère, reset au unmount) ---- */
  /**
   * Liste des autres operators actuellement subscribed à la même scène via
   * `/ws/editor`. Ne contient jamais l'operator courant. Mise à jour par
   * `useEditorWebSocket` au fil des events `subscribed` / `peer.joined` /
   * `peer.left`. Utile pour afficher un avatar-ring "X personnes éditent"
   * dans la menubar (implémentation UI réservée Phase F).
   */
  peers: string[];

  /**
   * Deltas de draft reçus via `/ws/editor` (d'autres operators qui bougent
   * un avatar, changent un FOV, etc.). Stocké comme un simple blob JSON
   * par clé du delta, via shallow merge — Phase F élargira à un vrai
   * patch-apply contre la scène active. Pour Phase D le contenu est
   * observable par les panels mais AUCUNE transformation visuelle n'est
   * câblée ; c'est intentionnel (pas de régression de l'éditeur local).
   */
  remoteDraftDeltas: Record<string, unknown>;

  /**
   * Dernier event `scene.apply` reçu sur `/ws/editor` (Phase E3 — broadcast
   * Director vers le viewer). Stocke un champ unique pour que les
   * `ViewerAdapter` montés (vue edit ET vue preview, cf. `panels-main.tsx`)
   * puissent réagir simultanément via un `useEffect([lastSceneApply])` sans
   * créer une seconde WS. La sérialisation `seq` (incrémenté par chaque
   * dispatch) garantit qu'un même payload reçu deux fois déclenche bien
   * deux callbacks (le shallow-equal de useEffect compare la ref de l'objet,
   * mais on veut un re-trigger sur dispatch identique).
   */
  lastSceneApply: SceneApplyEvent | null;

  /* ---- UI actions ---- */
  setCurrentScene: (id: string) => void;
  setSelectedId: (id: string | null) => void;
  setTool: (t: Tool) => void;
  setLayoutPreset: (name: LayoutPreset) => void;

  /* ---- Data actions (stubs Phase B — enrichis par les phases suivantes) ---- */
  /**
   * Toggle visibility d'un node dans la hiérarchie. Modifie l'arbre en place
   * (immuable côté Zustand : on reconstruit la branche concernée). Utilisé
   * par `HierarchyPanel` quand on clique l'œil d'un node.
   */
  toggleNodeVisibility: (nodeId: string) => void;

  /** Toggle lock d'un node (verrouillage édition). */
  toggleNodeLock: (nodeId: string) => void;

  /* ---- Phase F — Inspector deep patch ---- */
  /**
   * Met à jour un champ profond de `inspectorById[nodeId]` via un chemin
   * dot-separated (ex: "transform.pos.0", "transform.pos", "render.opacity").
   * L'intégration Immer assure que les snapshots zundo voient bien un
   * changement de référence sur `inspectorById` à chaque appel (sinon
   * l'historique ne verrait que la première mutation d'une série et ne
   * re-snapshot plus tant que la ref est identique).
   *
   * Les `path` acceptés :
   *  - "transform.pos"        → value = [x, y, z]
   *  - "transform.pos.0"      → value = number (index array)
   *  - "transform.rot"        → value = [x, y, z]
   *  - "transform.scale"      → value = [x, y, z]
   *  - "render.opacity"       → value = number
   *  - "vrm.expression"       → value = string
   *  - … (tout chemin valide dans `InspectorData`)
   *
   * Un path qui pointe sur un segment inexistant est un no-op silencieux
   * (impossible d'ajouter `camera` à un node qui n'en a pas via ce chemin
   * pour éviter de corrompre la shape du type). Les consumers doivent
   * initialiser les sous-sections via `setInspectorData` (Phase H).
   */
  updateInspectorField: (nodeId: string, path: string, value: unknown) => void;

  /* ---- Phase D — WS collab actions ---- */
  /** Remplace la liste des peers (appelé par `useEditorWebSocket` au `subscribed`). */
  setPeers: (peers: string[]) => void;
  /** Ajoute un peer (peer.joined). No-op si déjà présent. */
  addPeer: (operator: string) => void;
  /** Retire un peer (peer.left). No-op si absent. */
  removePeer: (operator: string) => void;

  /**
   * Applique un delta distant reçu via WS. Shallow-merge dans
   * `remoteDraftDeltas`. Pas de re-broadcast — c'est par définition l'input,
   * pas l'output (évite les boucles infinies quand la Phase F branchera le
   * vrai write-back des gestes live).
   */
  applyRemoteDraftUpdate: (delta: Record<string, unknown>) => void;

  /**
   * Phase E3 — dispatch d'un payload `scene.apply` reçu sur `/ws/editor`.
   *
   * Construit un `SceneApplyEvent` normalisé et le pose dans `lastSceneApply`.
   * Les `<ViewerAdapter>` montés réagissent via `useEffect([lastSceneApply])`
   * et appellent les méthodes impératives du viewer (swapTexture,
   * playAnimation, setBlendshape, showVfxOverlay).
   *
   * `seq` est incrémenté à chaque appel — garantit qu'un même `(kind, id)`
   * envoyé deux fois fait bien re-trigger l'effet (sinon useEffect compare
   * les refs d'objet et skip un dispatch identique).
   */
  dispatchSceneApply: (payload: {
    kind: SceneApplyKind;
    id: string;
    durationMs?: number;
    loop?: boolean;
    ts?: string;
  }) => void;

  /** Réinitialise l'état UI (utile pour tests et pour un "Close all"). */
  resetUI: () => void;
}

/* ─────────────────────────── HELPERS ─────────────────────────── */

/**
 * Applique `mutator` récursivement à l'arbre : renvoie un NOUVEL arbre si un
 * node matche, sinon le même (référence stable → pas de re-render inutile).
 */
function mapTree(
  nodes: TreeNodeData[],
  predicate: (n: TreeNodeData) => boolean,
  mutator: (n: TreeNodeData) => TreeNodeData,
): TreeNodeData[] {
  let changed = false;
  const out = nodes.map((n) => {
    if (predicate(n)) {
      changed = true;
      return mutator(n);
    }
    if (n.children && n.children.length > 0) {
      const newChildren = mapTree(n.children, predicate, mutator);
      if (newChildren !== n.children) {
        changed = true;
        return { ...n, children: newChildren };
      }
    }
    return n;
  });
  return changed ? out : nodes;
}

/**
 * Segments interdits — bloquent toute tentative de prototype pollution via
 * un path dot-separated. Phase F — Hardening H1 :
 *
 * `setDeepPath` est aujourd'hui appelé en interne avec des chemins
 * hardcodés ("transform.pos", "transform.rot.1") via `viewer-adapter.tsx`.
 * Le contrat publique de `updateInspectorField` est cependant **permissif**
 * (cf. JSDoc : "tout chemin valide dans `InspectorData`"), et la Phase G/H
 * va router des deltas WebSocket *untrusted* vers cette même action. Sans
 * ce filtre, `updateInspectorField("shugu", "__proto__.polluted", "pwn")`
 * aboutit à pollution de `Object.prototype` → côté client `({}).polluted
 * === "pwn"` partout dans l'app.
 *
 * Le filtre rejette aussi `constructor` et `prototype` — moins exploitables
 * directement mais dans la même famille (cf. CWE-1321). Le coût runtime
 * est trivial (un `Set.has` par segment) et la liste reste close — pas
 * d'inflation par fonctionnalités produit légitimes (les noms de champs
 * `InspectorData` sont des identifiants métier, pas des keywords JS).
 */
const FORBIDDEN_PATH_SEGMENTS = new Set([
  "__proto__",
  "constructor",
  "prototype",
]);

/**
 * Pose un value à un chemin dot-separated dans un draft Immer. Renvoie
 * `true` si l'écriture a eu lieu, `false` si le segment parent est absent
 * (on n'écrase jamais un objet qui n'existe pas) ou si un segment du chemin
 * est interdit (cf. `FORBIDDEN_PATH_SEGMENTS`).
 *
 * Les segments numériques (`"0"`, `"1"`) sont interprétés comme index
 * d'array — pratique pour mutter `transform.pos.0` sans réécrire tout le
 * triplet.
 */
function setDeepPath(
  draft: Record<string, unknown>,
  path: string,
  value: unknown,
): boolean {
  const segments = path.split(".");
  if (segments.length === 0) return false;
  for (const seg of segments) {
    if (FORBIDDEN_PATH_SEGMENTS.has(seg)) {
      if (process.env.NODE_ENV !== "production") {
        // Visible en dev/test pour repérer les call-sites buggés ; muet en
        // prod pour ne pas signaler l'attaque à un éventuel scanner.
        console.warn(
          "[useSceneEditorStore] setDeepPath: forbidden segment rejected:",
          seg,
          "in path",
          path,
        );
      }
      return false;
    }
  }
  let cursor: unknown = draft;
  for (let i = 0; i < segments.length - 1; i++) {
    if (cursor === null || typeof cursor !== "object") return false;
    const key = segments[i];
    const next = (cursor as Record<string, unknown>)[key];
    if (next === undefined) return false;
    cursor = next;
  }
  if (cursor === null || typeof cursor !== "object") return false;
  const last = segments[segments.length - 1];
  (cursor as Record<string, unknown>)[last] = value;
  return true;
}

/* ─────────────────────────── INITIAL STATE ─────────────────────────── */

/**
 * Valeurs par défaut ré-injectables via `resetUI()`. On extrait dans une
 * const pour que `useSceneEditorStore.getState()` au premier appel matche
 * exactement ce que le store crée.
 *
 * L'initial UI state reflète le comportement de `SceneEditorApp.tsx` pre-B :
 *   - currentScene = "s2" (Main · Talk, active par défaut dans MOCK_SCENES)
 *   - selectedId = "shugu" (sélection de démo cohérente avec MOCK_INSPECTOR)
 *   - tool = "move"
 *   - layoutPreset = "Streaming" (identique au design bundle verbatim)
 */
const INITIAL_UI_STATE = {
  currentScene: "s2",
  selectedId: "shugu" as string | null,
  tool: "move" as Tool,
  layoutPreset: "Streaming" as LayoutPreset,
  // Phase D : peers et remoteDraftDeltas sont du state de session WS
  // (éphémère par nature) → ils rejoignent l'UI state et sont reset par
  // `resetUI()` au même titre que les autres champs non persistés.
  peers: [] as string[],
  remoteDraftDeltas: {} as Record<string, unknown>,
  // Phase E3 : event Director le plus récent. `null` au boot et après reset.
  lastSceneApply: null as SceneApplyEvent | null,
};

/* ─────────────────────────── STORE ─────────────────────────── */

export const useSceneEditorStore = create<SceneEditorState>()(
  temporal(
    (set) => ({
      ...INITIAL_UI_STATE,

      // Data state — seedé depuis les mocks. Nouveau ref pour les arrays pour
      // éviter les mutations partagées accidentelles entre tests.
      scenes: [...MOCK_SCENES],
      hierarchy: MOCK_HIERARCHY,
      inspectorById: MOCK_INSPECTOR,
      assets: [...MOCK_ASSETS],
      audioChannels: [...MOCK_AUDIO_CHANNELS],
      patterns: [...MOCK_PATTERNS],
      timeline: MOCK_TIMELINE,

      setCurrentScene: (id) => set({ currentScene: id }),
      setSelectedId: (id) => set({ selectedId: id }),
      setTool: (t) => set({ tool: t }),
      setLayoutPreset: (name) => set({ layoutPreset: name }),

      toggleNodeVisibility: (nodeId) =>
        set((state) => ({
          hierarchy: mapTree(
            state.hierarchy,
            (n) => n.id === nodeId,
            (n) => ({ ...n, visible: !n.visible }),
          ),
        })),

      toggleNodeLock: (nodeId) =>
        set((state) => ({
          hierarchy: mapTree(
            state.hierarchy,
            (n) => n.id === nodeId,
            (n) => ({ ...n, locked: !n.locked }),
          ),
        })),

      /* ─── Phase F — Inspector deep patch (Immer) ─── */
      updateInspectorField: (nodeId, path, value) =>
        set((state) => {
          const existing = state.inspectorById[nodeId];
          if (!existing) return state;
          const nextEntry = produce(existing, (draft) => {
            setDeepPath(draft as unknown as Record<string, unknown>, path, value);
          });
          // Si rien n'a bougé (segment parent absent p.ex.), on garde la même
          // ref pour éviter un snapshot zundo vide.
          if (nextEntry === existing) return state;
          return {
            inspectorById: {
              ...state.inspectorById,
              [nodeId]: nextEntry,
            },
          };
        }),

      /* ─── Phase D — WS collab actions ─── */
      setPeers: (peers) => set({ peers: [...peers] }),
      addPeer: (operator) =>
        set((state) =>
          state.peers.includes(operator)
            ? state
            : { peers: [...state.peers, operator] },
        ),
      removePeer: (operator) =>
        set((state) => ({
          peers: state.peers.filter((p) => p !== operator),
        })),
      applyRemoteDraftUpdate: (delta) =>
        set((state) => ({
          remoteDraftDeltas: { ...state.remoteDraftDeltas, ...delta },
        })),

      /* ─── Phase E3 — Director scene.apply dispatch ─── */
      dispatchSceneApply: (payload) =>
        set((state) => ({
          lastSceneApply: {
            kind: payload.kind,
            id: payload.id,
            durationMs: payload.durationMs,
            loop: payload.loop,
            ts: payload.ts,
            // Incrémente la séquence — compteur partagé du store. Réutilise
            // l'ancien `seq` via `state.lastSceneApply` plutôt qu'un compteur
            // module-level pour que `resetUI()` remette aussi `seq` à 0
            // (tests : isolation entre cas successifs).
            seq: (state.lastSceneApply?.seq ?? 0) + 1,
          },
        })),

      resetUI: () => set({ ...INITIAL_UI_STATE }),
    }),
    {
      // Zundo / temporal : on limite l'historique à ce qui est *sémantiquement*
      // undoable. Tool et selectedId ne rentrent pas (gestes éphémères).
      // `hierarchy` rentre car le toggle visibility est une action cataloguée
      // comme édition utilisateur.
      // Phase F : `inspectorById` rejoint le partialize pour que les edits
      // de transform (gizmo drag, slider) soient undoables par ⌘Z. Sans ça,
      // les mutations via `updateInspectorField` passeraient sous le radar
      // de zundo et seraient perdues pour l'historique.
      partialize: (state) => ({
        currentScene: state.currentScene,
        layoutPreset: state.layoutPreset,
        hierarchy: state.hierarchy,
        inspectorById: state.inspectorById,
      }),
      limit: 50,
      // Par défaut zundo compare par référence (`Object.is`), mais partialize
      // retourne un nouvel objet à chaque `set()` → un changement de `tool`
      // créerait un snapshot vide. On utilise donc une égalité "shallow" sur
      // les 4 champs partialized : un snapshot n'est ajouté que si une des
      // valeurs trackées change réellement.
      equality: (pastState, currentState) =>
        pastState.currentScene === currentState.currentScene &&
        pastState.layoutPreset === currentState.layoutPreset &&
        pastState.hierarchy === currentState.hierarchy &&
        pastState.inspectorById === currentState.inspectorById,
    },
  ),
);

/* ─────────────────────────── DEV / TEST GLOBAL ─────────────────────────── */

/**
 * Phase G : on expose le store comme global `window.__SHUGU_SCENE_STORE__`
 * hors production. Ça permet aux tests Playwright d'observer/muter l'état
 * sans passer par une UI qui n'existe pas toujours dans le popout (qui ne
 * rend qu'un seul panel). Le scope dev-only évite d'exposer le store à
 * des scripts tiers en prod (même si le risque est faible : un attaquant
 * a déjà un full XSS s'il peut écrire sur `window`).
 */
if (typeof window !== "undefined" && process.env.NODE_ENV !== "production") {
  (window as unknown as Record<string, unknown>).__SHUGU_SCENE_STORE__ =
    useSceneEditorStore;
}

/* ─────────────────────────── TEMPORAL HOOK ─────────────────────────── */

/**
 * Hook qui retourne l'état temporal (undo/redo) avec sélecteur fin : ne
 * re-render que si pastStates.length ou futureStates.length change.
 * Pratique pour greyer les boutons Undo/Redo sans abonner au store entier.
 */
export function useSceneEditorTemporal<T>(
  selector: (
    state: TemporalState<
      Pick<
        SceneEditorState,
        "currentScene" | "layoutPreset" | "hierarchy" | "inspectorById"
      >
    >,
  ) => T,
): T {
  return useStore(useSceneEditorStore.temporal, selector);
}

/* ─────────────────────────── SELECTORS ─────────────────────────── */

export const selectCurrentScene = (s: SceneEditorState): string => s.currentScene;
export const selectSelectedId = (s: SceneEditorState): string | null => s.selectedId;
export const selectTool = (s: SceneEditorState): Tool => s.tool;
export const selectLayoutPreset = (s: SceneEditorState): LayoutPreset => s.layoutPreset;

export const selectScenes = (s: SceneEditorState): SceneSummary[] => s.scenes;
export const selectHierarchy = (s: SceneEditorState): TreeNodeData[] => s.hierarchy;
export const selectInspectorById = (s: SceneEditorState): Record<string, InspectorData> =>
  s.inspectorById;
/**
 * Selector pratique : retourne l'InspectorData du node sélectionné, ou
 * `null` si rien n'est sélectionné ou si le node n'a pas d'inspectable.
 */
export const selectCurrentInspector = (s: SceneEditorState): InspectorData | null => {
  if (!s.selectedId) return null;
  return s.inspectorById[s.selectedId] ?? null;
};
export const selectAssets = (s: SceneEditorState): AssetItem[] => s.assets;
export const selectPatterns = (s: SceneEditorState): PatternItem[] => s.patterns;
export const selectAudioChannels = (s: SceneEditorState): AudioChannel[] => s.audioChannels;
export const selectTimeline = (s: SceneEditorState): TimelineData => s.timeline;

/* ─── Phase D — WS collab selectors ─── */
export const selectPeers = (s: SceneEditorState): string[] => s.peers;
export const selectRemoteDraftDeltas = (s: SceneEditorState): Record<string, unknown> =>
  s.remoteDraftDeltas;

/* ─── Phase E3 — Director scene.apply selector ─── */
export const selectLastSceneApply = (s: SceneEditorState): SceneApplyEvent | null =>
  s.lastSceneApply;
