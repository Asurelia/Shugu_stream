/**
 * useDragDropTarget — hook React qui transforme le canvas viewer en drop target.
 *
 * Responsabilité unique : gérer les événements HTML5 drag-drop natifs sur le
 * canvas Three.js, projeter les coordonnées de drop sur le plan sol (Y=0) et
 * appeler `onAssetDropped(asset, worldPosition)`.
 *
 * Scope E5.3 : uniquement les assets `props_3d` sont droppables. Les autres
 * types (VRM, VRMA, VFX, etc.) ont des sémantiques à définir en E5.4+ et
 * sont silencieusement ignorés.
 *
 * Pattern HTML5 natif — cohérent avec `scene-editor/dnd-context.ts` (Phase A)
 * qui utilise aussi du drag-drop HTML5 sans react-dnd. Le payload de l'asset
 * est encodé en JSON dans `dataTransfer.setData("application/json", ...)`.
 *
 * Projection drop → world : utilise `THREE.Plane` sur Y=0 (plan infini)
 * plutôt que la CircleGeometry du sol (rayon 3m — les drops en dehors du
 * cercle échoueraient silencieusement). Le plan infini garantit un drop
 * valide partout sur le canvas.
 *
 * @module viewer/interactions/useDragDropTarget
 */

import { useEffect, useRef } from "react";
import * as THREE from "three";
import type { Prop3DEntry } from "../../api/catalogClient";

// ─── Types ────────────────────────────────────────────────────────────────────

/** Payload encodé dans le dataTransfer lors du dragStart d'un asset prop. */
export interface PropDragPayload {
  /** Type discriminant pour filtrer les autres drag payloads. */
  kind: "prop_3d";
  /** Métadonnées de l'asset (slug + file). */
  asset: Prop3DEntry;
}

/** Props du hook `useDragDropTarget`. */
export interface UseDragDropTargetProps {
  /** Canvas du renderer (reçoit les événements dragover + drop). */
  canvasRef: React.RefObject<HTMLCanvasElement | null>;
  /** Caméra active pour la projection drop → world. */
  cameraRef: React.RefObject<THREE.PerspectiveCamera | null>;
  /**
   * Callback déclenché quand un asset `prop_3d` est dropé sur le canvas.
   *
   * @param asset         - Métadonnées de l'asset droppé.
   * @param worldPosition - Position mondiale projetée sur le plan Y=0.
   */
  onAssetDropped: (asset: Prop3DEntry, worldPosition: THREE.Vector3) => void;
  /**
   * Si `true`, le canvas est désactivé comme drop target (mode preview).
   * Défaut : false.
   */
  disabled?: boolean;
}

// ─── Constantes ───────────────────────────────────────────────────────────────

/** Type MIME du payload d'asset dans le dataTransfer. */
export const PROP_DRAG_MIME = "application/x-shugu-prop";

/** Plan sol Y=0 réutilisé pour la projection (instance partagée, pas de GC). */
const GROUND_PLANE = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);

// ─── Helpers ─────────────────────────────────────────────────────────────────

/**
 * Parse le payload de drag depuis le dataTransfer.
 *
 * Retourne `null` si le payload est absent, malformé, ou n'est pas un prop_3d.
 *
 * Valide la structure de Prop3DEntry (slug et file requis).
 */
function parsePropDragPayload(transfer: DataTransfer): PropDragPayload | null {
  const raw = transfer.getData(PROP_DRAG_MIME);
  if (!raw) return null;

  try {
    const parsed = JSON.parse(raw) as unknown;
    if (
      typeof parsed === "object" &&
      parsed !== null &&
      "kind" in parsed &&
      (parsed as { kind: unknown }).kind === "prop_3d" &&
      "asset" in parsed
    ) {
      // Validation supplémentaire : la structure asset doit être un objet avec slug string et file string.
      const asset = (parsed as { asset: unknown }).asset;
      if (typeof asset !== "object" || asset === null) return null;
      if (typeof (asset as { slug?: unknown }).slug !== "string" || (asset as { slug: string }).slug.length === 0) return null;
      if (typeof (asset as { file?: unknown }).file !== "string" || (asset as { file: string }).file.length === 0) return null;

      return parsed as PropDragPayload;
    }
  } catch {
    // JSON.parse failed — payload invalide.
  }

  return null;
}

/**
 * Projette des coordonnées écran (clientX, clientY) vers le plan sol Y=0
 * en world space, via un raycaster sur la caméra active.
 *
 * Retourne `null` si la projection échoue (ray parallèle au plan, caméra null).
 */
function projectToGroundPlane(
  clientX: number,
  clientY: number,
  canvas: HTMLCanvasElement,
  camera: THREE.PerspectiveCamera,
): THREE.Vector3 | null {
  const rect = canvas.getBoundingClientRect();
  const ndc = new THREE.Vector2(
    ((clientX - rect.left) / rect.width) * 2 - 1,
    -((clientY - rect.top) / rect.height) * 2 + 1,
  );

  const raycaster = new THREE.Raycaster();
  raycaster.setFromCamera(ndc, camera);

  const target = new THREE.Vector3();
  const hit = raycaster.ray.intersectPlane(GROUND_PLANE, target);

  return hit ? target : null;
}

// ─── Hook ─────────────────────────────────────────────────────────────────────

/**
 * Attache les event listeners HTML5 drag-drop sur le canvas viewer.
 *
 * Lifecycle : les listeners sont ajoutés au mount (quand `canvasRef.current`
 * est disponible) et retirés au unmount via le return du useEffect.
 *
 * `disabled` permet de désactiver le drop en mode preview sans démonter
 * le hook — les listeners restent attachés mais retournent immédiatement.
 */
export function useDragDropTarget({
  canvasRef,
  cameraRef,
  onAssetDropped,
  disabled = false,
}: UseDragDropTargetProps): void {
  // Ref latest pour les callbacks (évite les closures stales).
  const onAssetDroppedRef = useRef(onAssetDropped);
  onAssetDroppedRef.current = onAssetDropped;
  const disabledRef = useRef(disabled);
  disabledRef.current = disabled;

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const onDragOver = (event: DragEvent) => {
      if (disabledRef.current) return;
      // Autoriser le drop en changeant l'effet visuel du curseur.
      event.preventDefault();
      if (event.dataTransfer) {
        event.dataTransfer.dropEffect = "copy";
      }
    };

    const onDrop = (event: DragEvent) => {
      if (disabledRef.current) return;
      event.preventDefault();

      if (!event.dataTransfer) return;

      const payload = parsePropDragPayload(event.dataTransfer);
      if (!payload) return;

      const camera = cameraRef.current;
      const currentCanvas = canvasRef.current;
      if (!camera || !currentCanvas) return;

      const worldPos = projectToGroundPlane(
        event.clientX,
        event.clientY,
        currentCanvas,
        camera,
      );

      if (!worldPos) return;

      onAssetDroppedRef.current(payload.asset, worldPos);
    };

    canvas.addEventListener("dragover", onDragOver);
    canvas.addEventListener("drop", onDrop);

    return () => {
      canvas.removeEventListener("dragover", onDragOver);
      canvas.removeEventListener("drop", onDrop);
    };
  }, [canvasRef, cameraRef]);
  // Note : `onAssetDropped` et `disabled` sont lus via refs → pas de deps.
}
