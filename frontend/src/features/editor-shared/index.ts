/**
 * editor-shared — Barrel export.
 *
 * Contrats partagés entre les stores de production, les libs et les données
 * mock. Extrait de `scene-editor/` (Phase 5.5) pour permettre la suppression
 * de l'ancien `scene-editor/` lors de la Phase 6 cleanup.
 */

export type { IconName } from "./icon-types";
export type { PanelKey, DockablePanelKey } from "./panel-types";
export type { TreeNodeData } from "./tree-types";
export type {
  SceneSummary,
  AssetKind,
  AssetItem,
  TriggerKind,
  PatternItem,
  AudioChannel,
  TimelineTrack,
  TimelineClip,
  TimelineData,
  InspectorData,
} from "./mock-data-types";
export {
  MOCK_SCENES,
  MOCK_HIERARCHY,
  MOCK_ASSETS,
  MOCK_PATTERNS,
  MOCK_AUDIO_CHANNELS,
  MOCK_TIMELINE,
  MOCK_INSPECTOR,
} from "./mock-data";
