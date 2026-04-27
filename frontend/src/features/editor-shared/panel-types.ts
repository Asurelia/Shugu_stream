/**
 * editor-shared — Panel key types partagés entre l'éditeur et les stores.
 *
 * Source unique de vérité pour `PanelKey` et `DockablePanelKey`. Extrait de
 * `scene-editor/dnd-context.ts` (Phase 5.5) pour que les stores et lib
 * n'importent plus depuis `scene-editor/` (ancien). Le fichier legacy
 * `scene-editor/dnd-context.ts` re-exporte ces types pendant la transition ;
 * Phase 6 supprimera le fichier legacy.
 */

/**
 * Sous-ensemble de panels qui peuvent vivre dans un dock (tabs draggable).
 * Note : `hierarchy` est volontairement exclu — il a sa propre colonne
 * fixe à gauche et n'est pas un tab. Garder ce type strict évite que des
 * opérations de drag-drop ou move-tab ne reçoivent un panelKey invalide.
 */
export type DockablePanelKey =
  | "scene" | "live"
  | "inspector" | "effects" | "stream" | "perf"
  | "assets" | "timeline" | "patterns" | "mixer";

/**
 * Ensemble complet des panels du Scene Editor — inclut les non-dockables
 * comme `hierarchy`. C'est ce type qui est utilisé pour le routing popout
 * (chaque panel peut être pop-out, dockable ou pas).
 */
export type PanelKey = DockablePanelKey | "hierarchy";
