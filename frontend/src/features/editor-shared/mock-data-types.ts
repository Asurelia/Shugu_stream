/**
 * editor-shared — Types des données mock (AssetItem, AudioChannel, etc.).
 *
 * Extrait de `scene-editor/mock-data.ts` (Phase 5.5). Ces types étaient
 * utilisés directement par les stores de production ; ils migrent ici pour
 * que `scene-editor/` (ancien) ne soit plus une dépendance directe des stores.
 * Le fichier legacy `scene-editor/mock-data.ts` re-exporte ces types pendant
 * la transition ; Phase 6 supprimera le fichier legacy.
 */

import type { IconName } from "./icon-types";

/* ───── Scenes & hierarchy ───── */

export type SceneSummary = {
  id: string;
  name: string;
  active: boolean;
  thumb: string;
};

/* ───── Assets ───── */

export type AssetKind = "VRM" | "BG" | "PROP" | "OVL" | "SFX" | "BGM" | "FX";

export type AssetItem = {
  id: string;
  kind: AssetKind;
  label: string;
  icon: IconName;
  color: string;
};

/* ───── Patterns ───── */

export type TriggerKind = "chat" | "hotkey" | "manual";

export type PatternItem = {
  id: string;
  name: string;
  trigger: string;
  triggerKind: TriggerKind;
  duration: string;
  actions: number;
};

/* ───── Audio channels ───── */

export type AudioChannel = {
  id: string;
  name: string;
  level: number;
  muted: boolean;
  solo: boolean;
};

/* ───── Timeline ───── */

export type TimelineTrack = { name: string; keys: number[] };
export type TimelineClip = { track: string; start: number; end: number; label: string };
export type TimelineData = { duration: number; tracks: TimelineTrack[]; clips: TimelineClip[] };

/* ───── Inspector ───── */

export type InspectorData = {
  name: string;
  kind: string;
  transform: { pos: [number, number, number]; rot: [number, number, number]; scale: [number, number, number] };
  vrm?: {
    model: string;
    expression: string;
    blink: boolean;
    lookAtCamera: boolean;
  };
  render?: {
    opacity: number;
    outline?: boolean;
    outlineColor?: string;
    rimLight?: number;
    shadow?: boolean;
    tint?: string;
    blur?: number;
    parallax?: number;
  };
  camera?: {
    fov: number;
    near: number;
    far: number;
    dof: boolean;
    focusDistance: number;
    aperture: number;
  };
  tracking?: {
    source: string;
    blendshapeSmoothing: number;
    handTracking: boolean;
  };
};
