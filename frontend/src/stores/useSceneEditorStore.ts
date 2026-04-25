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
 * Pose un value à un chemin dot-separated dans un draft Immer. Renvoie
 * `true` si l'écriture a eu lieu, `false` si le segment parent est absent
 * (on n'écrase jamais un objet qui n'existe pas).
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
