/**
 * editor-shared — Type `IconName` partagé.
 *
 * Extrait de `scene-editor/primitives.tsx` (Phase 5.5). Requis par
 * `TreeNodeData` et `AssetItem` qui migrent aussi vers editor-shared.
 * Le fichier legacy `scene-editor/primitives.tsx` re-exporte ce type
 * pendant la transition ; Phase 6 supprimera le fichier legacy.
 */

export type IconName =
  | "caret" | "close" | "min" | "max" | "popout" | "drag" | "search" | "plus"
  | "folder" | "record" | "play" | "pause" | "stop" | "skip" | "undo" | "redo"
  | "move" | "rotate" | "scale" | "eye" | "eyeOff" | "lock" | "unlock"
  | "camera" | "person" | "image" | "text" | "audio" | "fx" | "scene"
  | "grid" | "wand" | "broadcast" | "mic" | "keyboard" | "bolt" | "link"
  | "plug" | "layers" | "sliders" | "ruler" | "clock" | "chart" | "warn"
  | "check" | "dot" | "code" | "wrench" | "heart" | "star";
