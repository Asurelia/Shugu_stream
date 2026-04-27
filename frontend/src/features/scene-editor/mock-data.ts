/**
 * Scene Editor — mock data (legacy re-export).
 *
 * La source unique de vérité a été déplacée vers
 * `@/features/editor-shared` (Phase 5.5). Ce fichier re-exporte tout
 * pour maintenir la compatibilité des imports legacy pendant la transition.
 * Phase 6 supprimera ce fichier et ses consumers (pages legacy).
 */

// mock-data.ts (legacy) — re-exporté depuis editor-shared pendant la transition.
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
} from "@/features/editor-shared";
export {
  MOCK_SCENES,
  MOCK_HIERARCHY,
  MOCK_ASSETS,
  MOCK_PATTERNS,
  MOCK_AUDIO_CHANNELS,
  MOCK_TIMELINE,
  MOCK_INSPECTOR,
} from "@/features/editor-shared";
