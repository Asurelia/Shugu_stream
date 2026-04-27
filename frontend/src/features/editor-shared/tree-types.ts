/**
 * editor-shared — Type `TreeNodeData` partagé.
 *
 * Extrait de `scene-editor/primitives.tsx` (Phase 5.5). Utilisé par
 * `useSceneEditorStore` (hiérarchie de scène) et les données mock.
 * Le fichier legacy `scene-editor/primitives.tsx` re-exporte ce type
 * pendant la transition ; Phase 6 supprimera le fichier legacy.
 */

import type { IconName } from "./icon-types";

export type TreeNodeData = {
  id: string;
  label: string;
  icon?: IconName;
  kind?: string;
  open?: boolean;
  visible?: boolean;
  locked?: boolean;
  children?: TreeNodeData[];
};
