/**
 * editor-shared — Données mock partagées.
 *
 * Extrait de `scene-editor/mock-data.ts` (Phase 5.5). Ces constantes étaient
 * importées directement par les stores de production et les tests ; elles
 * migrent ici pour que `scene-editor/` (ancien) ne soit plus une dépendance
 * directe des stores. Le fichier legacy `scene-editor/mock-data.ts` re-exporte
 * ces constantes pendant la transition ; Phase 6 supprimera le fichier legacy.
 */

import type { TreeNodeData } from "./tree-types";
import type {
  SceneSummary,
  AssetItem,
  PatternItem,
  AudioChannel,
  TimelineData,
  InspectorData,
} from "./mock-data-types";

/* ───── Scenes & hierarchy ───── */

export const MOCK_SCENES: SceneSummary[] = [
  { id: "s1", name: "Starting Soon", active: false, thumb: "starting" },
  { id: "s2", name: "Main · Talk", active: true, thumb: "talk" },
  { id: "s3", name: "Gaming · Solo", active: false, thumb: "gaming" },
  { id: "s4", name: "Brb", active: false, thumb: "brb" },
  { id: "s5", name: "Ending", active: false, thumb: "ending" },
];

export const MOCK_HIERARCHY: TreeNodeData[] = [
  {
    id: "scene",
    kind: "scene",
    icon: "scene",
    label: "Main · Talk",
    open: true,
    visible: true,
    children: [
      { id: "camera1", kind: "cam", icon: "camera", label: "Main Camera", open: true, children: [] },
      {
        id: "group-stage", kind: "scene", icon: "folder", label: "Stage",
        open: true, visible: true,
        children: [
          { id: "shugu",  kind: "vrm",   icon: "person", label: "Shugu (VRM)", visible: true },
          { id: "aura",   kind: "vrm",   icon: "person", label: "Aura (VRM)",  visible: true },
          { id: "set-bg", kind: "image", icon: "image",  label: "Cozy Room BG", visible: true, locked: true },
          { id: "plant",  kind: "image", icon: "image",  label: "Plant prop",   visible: true },
        ],
      },
      {
        id: "group-ui", kind: "scene", icon: "folder", label: "UI Overlays",
        open: true, visible: true,
        children: [
          { id: "chatbox", kind: "text",  icon: "text",  label: "Chat overlay",    visible: true },
          { id: "lower",   kind: "text",  icon: "text",  label: "Lower third",     visible: true },
          { id: "follow",  kind: "image", icon: "image", label: "Follow alert",    visible: false },
        ],
      },
      {
        id: "group-audio", kind: "scene", icon: "folder", label: "Audio",
        open: false, visible: true,
        children: [
          { id: "mic",   kind: "audio", icon: "mic",   label: "Mic input",      visible: true },
          { id: "music", kind: "audio", icon: "audio", label: "Background OST", visible: true },
          { id: "sfx",   kind: "audio", icon: "audio", label: "SFX bus",        visible: true },
        ],
      },
      {
        id: "group-fx", kind: "scene", icon: "folder", label: "Effects",
        open: false, visible: true,
        children: [
          { id: "bloom", kind: "fx", icon: "fx", label: "Bloom",         visible: true },
          { id: "grain", kind: "fx", icon: "fx", label: "Film grain",    visible: true },
          { id: "grade", kind: "fx", icon: "fx", label: "Color grading", visible: true },
        ],
      },
    ],
  },
];

/* ───── Assets ───── */

export const MOCK_ASSETS: AssetItem[] = [
  { id: "a1",  kind: "VRM",  label: "Shugu v4",     icon: "person", color: "#e08efe" },
  { id: "a2",  kind: "VRM",  label: "Aura",         icon: "person", color: "#fd6c9c" },
  { id: "a3",  kind: "VRM",  label: "Mori (draft)", icon: "person", color: "#81ecff" },
  { id: "a4",  kind: "BG",   label: "Cozy Room",    icon: "image",  color: "#b585ff" },
  { id: "a5",  kind: "BG",   label: "Neon City",    icon: "image",  color: "#fd6c9c" },
  { id: "a6",  kind: "BG",   label: "Studio",       icon: "image",  color: "#7fe3b0" },
  { id: "a7",  kind: "BG",   label: "Cafe",         icon: "image",  color: "#ffcf6b" },
  { id: "a8",  kind: "PROP", label: "Plant",        icon: "image",  color: "#7fe3b0" },
  { id: "a9",  kind: "PROP", label: "Lamp",         icon: "image",  color: "#ffcf6b" },
  { id: "a10", kind: "PROP", label: "Laptop",       icon: "image",  color: "#81ecff" },
  { id: "a11", kind: "OVL",  label: "Chat box",     icon: "text",   color: "#e08efe" },
  { id: "a12", kind: "OVL",  label: "Lower third",  icon: "text",   color: "#b585ff" },
  { id: "a13", kind: "OVL",  label: "Follow alert", icon: "image",  color: "#fd6c9c" },
  { id: "a14", kind: "SFX",  label: "Pop",          icon: "audio",  color: "#ffcf6b" },
  { id: "a15", kind: "SFX",  label: "Giggle",       icon: "audio",  color: "#fd6c9c" },
  { id: "a16", kind: "SFX",  label: "Cheer",        icon: "audio",  color: "#81ecff" },
  { id: "a17", kind: "BGM",  label: "Lo-fi loop",   icon: "audio",  color: "#b585ff" },
  { id: "a18", kind: "FX",   label: "Particles",    icon: "fx",     color: "#e08efe" },
  { id: "a19", kind: "FX",   label: "Glitch",       icon: "fx",     color: "#81ecff" },
  { id: "a20", kind: "FX",   label: "Bloom",        icon: "fx",     color: "#ffcf6b" },
];

/* ───── Patterns ───── */

export const MOCK_PATTERNS: PatternItem[] = [
  { id: "p1", name: "Shy wave",        trigger: "!hello", triggerKind: "chat",   duration: "2.4s", actions: 3 },
  { id: "p2", name: "Nervous giggle",  trigger: "F2",     triggerKind: "hotkey", duration: "1.8s", actions: 4 },
  { id: "p3", name: "BRB bounce",      trigger: "manual", triggerKind: "manual", duration: "4.0s", actions: 6 },
  { id: "p4", name: "Hype dance",      trigger: "!dance", triggerKind: "chat",   duration: "6.5s", actions: 9 },
  { id: "p5", name: "Scene → Gaming",  trigger: "F5",     triggerKind: "hotkey", duration: "0.8s", actions: 2 },
  { id: "p6", name: "Thank you bow",   trigger: "manual", triggerKind: "manual", duration: "3.2s", actions: 5 },
];

/* ───── Audio channels ───── */

export const MOCK_AUDIO_CHANNELS: AudioChannel[] = [
  { id: "mic",   name: "Mic",        level: 0.72, muted: false, solo: false },
  { id: "bgm",   name: "BGM",        level: 0.38, muted: false, solo: false },
  { id: "sfx",   name: "SFX",        level: 0.55, muted: false, solo: false },
  { id: "alert", name: "Alerts",     level: 0.64, muted: false, solo: false },
  { id: "aura",  name: "Aura voice", level: 0.58, muted: true,  solo: false },
  { id: "game",  name: "Game",       level: 0.45, muted: false, solo: false },
];

/* ───── Timeline ───── */

export const MOCK_TIMELINE: TimelineData = {
  duration: 12,
  tracks: [
    { name: "Shugu · pos",  keys: [0.5, 2.1, 4.8, 7.2, 9.5] },
    { name: "Shugu · expr", keys: [0, 1.4, 3.0, 5.6] },
    { name: "Aura · pos",   keys: [1.0, 3.8, 6.2, 8.9] },
    { name: "Camera",       keys: [0, 6, 12] },
    { name: "Bloom",        keys: [] },
  ],
  clips: [
    { track: "Shugu · pos", start: 0.5, end: 4.8, label: "wave" },
    { track: "Aura · pos",  start: 3.8, end: 8.9, label: "enter" },
    { track: "Camera",      start: 0,   end: 6,   label: "dolly in" },
  ],
};

/* ───── Inspector ───── */

export const MOCK_INSPECTOR: Record<string, InspectorData> = {
  shugu: {
    name: "Shugu (VRM)",
    kind: "VRM Avatar",
    transform: { pos: [-0.6, 0, 0.2], rot: [0, 12, 0], scale: [1, 1, 1] },
    vrm: { model: "shugu_v4.vrm", expression: "Happy", blink: true, lookAtCamera: true },
    render: {
      opacity: 1.0, outline: true, outlineColor: "#fd6c9c",
      rimLight: 0.4, shadow: true,
    },
    tracking: { source: "iPhone LiveLink", blendshapeSmoothing: 0.25, handTracking: false },
  },
  aura: {
    name: "Aura (VRM)",
    kind: "VRM Avatar",
    transform: { pos: [0.9, 0, 0.4], rot: [0, -8, 0], scale: [1, 1, 1] },
    vrm: { model: "aura_v2.vrm", expression: "Neutral", blink: true, lookAtCamera: false },
    render: {
      opacity: 1.0, outline: true, outlineColor: "#b585ff",
      rimLight: 0.3, shadow: true,
    },
    tracking: { source: "AI-driven", blendshapeSmoothing: 0.4, handTracking: true },
  },
  camera1: {
    name: "Main Camera",
    kind: "Camera",
    transform: { pos: [0, 1.3, 2.8], rot: [-3, 0, 0], scale: [1, 1, 1] },
    camera: { fov: 42, near: 0.1, far: 100, dof: true, focusDistance: 2.5, aperture: 2.0 },
  },
  "set-bg": {
    name: "Cozy Room BG",
    kind: "Background",
    transform: { pos: [0, 0, -5], rot: [0, 0, 0], scale: [6, 3.4, 1] },
    render: { opacity: 1.0, tint: "#ffffff", blur: 0, parallax: 0.2 },
  },
};
