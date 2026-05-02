/**
 * useGizmoBinding — hook React qui binde les événements TransformControls ↔ store.
 *
 * Responsabilité unique : synchronisation bidirectionnelle entre le gizmo
 * TransformControls et le store Zustand :
 *   - Drag gizmo → debounce RAF → `store.updateMeshTransform`
 *   - `store.selectedMeshId` change → `controls.attach(mesh)` / `controls.detach()`
 *   - `store.transformMode` change → `controls.setMode(mode)`
 *
 * Debounce via `requestAnimationFrame` (pattern exact de `viewer-adapter.tsx`
 * lignes 348-385) : le `change` event de TransformControls fire à ~60Hz
 * pendant un drag — on bufferise et ne flush qu'une fois par frame.
 *
 * Feedback loop prevention : quand l'inspector modifie le store et que le
 * viewer-effect ré-applique sur le mesh, si le gizmo est en cours de drag
 * (`controls.dragging === true`), le useEffect du viewer doit ignorer la mise
 * à jour (guard implémenté dans SceneComposerViewer via `gizmo.dragging`).
 *
 * @module viewer/interactions/useGizmoBinding
 */

import { useCallback, useEffect, useRef, type MutableRefObject } from "react";
import * as THREE from "three";
import type { TransformControlsHandle, GizmoMode } from "../three-stage/transform-controls";
import {
  useSceneComposerStore,
  selectSelectedMeshId,
  selectTransformMode,
  type ObjectTransform,
} from "../../store/useSceneComposerStore";

// ─── Types ────────────────────────────────────────────────────────────────────

/** Props du hook `useGizmoBinding`. */
export interface UseGizmoBindingProps {
  /**
   * Ref au handle du TransformControls.
   * Dereferencé à l'intérieur des useEffect — jamais au render.
   */
  gizmoHandleRef: MutableRefObject<TransformControlsHandle | null>;
  /**
   * Signal React-friendly : true une fois que `gizmoHandleRef.current` est non-null.
   * Utilisé comme dep dans les useEffect pour éviter les stale reads.
   */
  gizmoReady: boolean;
  /**
   * Map des Object3D de la scène, indexée par instanceId.
   * Fourni par le viewer pour permettre la résolution `selectedMeshId → Object3D`.
   */
  meshRegistry: React.MutableRefObject<Map<string, THREE.Object3D>>;
}

// ─── Hook ─────────────────────────────────────────────────────────────────────

/**
 * Hook avec callbacks exposés — utilisé par le viewer pour
 * déclencher le debounce RAF depuis les event listeners Three.js.
 *
 * Retourne un objet stable avec `onGizmoChange(transform)` à appeler
 * depuis le callback `onChange` de `attachTransformControls`.
 */
export function useGizmoBindingWithCallbacks(props: UseGizmoBindingProps): {
  onGizmoChange: (object: THREE.Object3D) => void;
} {
  const { gizmoHandleRef, gizmoReady, meshRegistry } = props;
  const selectedMeshId = useSceneComposerStore(selectSelectedMeshId);
  const transformMode = useSceneComposerStore(selectTransformMode);
  const updateMeshTransform = useSceneComposerStore((s) => s.updateMeshTransform);

  // Debounce
  const pendingTransformRef = useRef<{ instanceId: string; transform: Partial<ObjectTransform> } | null>(null);
  const rafIdRef = useRef<number | null>(null);
  const updateMeshTransformRef = useRef(updateMeshTransform);

  // Sync ref mirror after each commit (no dep array → runs after every render).
  useEffect(() => {
    updateMeshTransformRef.current = updateMeshTransform;
  });

  const flushPending = useCallback(() => {
    rafIdRef.current = null;
    const pending = pendingTransformRef.current;
    if (!pending) return;
    pendingTransformRef.current = null;

    updateMeshTransformRef.current(pending.instanceId, pending.transform);
  }, []);

  // Callback stable à passer comme `onChange` dans attachTransformControls.
  const onGizmoChange = useCallback(
    (object: THREE.Object3D) => {
      // Extrait l'instanceId depuis userData — requis pour tracer la source du transform.
      const instanceId = object.userData["instanceId"] as string | undefined;
      if (!instanceId) return; // objet non-enregistré, ignorer

      // Extrait le transform depuis l'Object3D (en degrés pour le store).
      const pos = object.position;
      const rot = object.rotation;
      const scl = object.scale;

      const RAD_TO_DEG = 180 / Math.PI;

      pendingTransformRef.current = {
        instanceId,
        transform: {
          position: [pos.x, pos.y, pos.z],
          // Convention : rotation stockée en degrés dans le store.
          rotation: [rot.x * RAD_TO_DEG, rot.y * RAD_TO_DEG, rot.z * RAD_TO_DEG],
          scale: [scl.x, scl.y, scl.z],
        },
      };

      // Debounce : ne programme qu'un seul RAF si pas déjà pending.
      if (rafIdRef.current !== null) return;
      if (typeof requestAnimationFrame !== "undefined") {
        rafIdRef.current = requestAnimationFrame(flushPending);
      } else {
        // Fallback jsdom : flush synchrone.
        flushPending();
      }
    },
    [flushPending],
  );

  // Sync transformMode → gizmo. Deps on gizmoReady ensures this fires once gizmo is mounted.
  useEffect(() => {
    const gizmoHandle = gizmoHandleRef.current;
    if (!gizmoHandle) return;
    gizmoHandle.setMode(transformMode as GizmoMode);
  }, [gizmoHandleRef, gizmoReady, transformMode]);

  // Sync selectedMeshId → gizmo attach. Deps on gizmoReady ensures correct initial attach.
  useEffect(() => {
    const gizmoHandle = gizmoHandleRef.current;
    if (!gizmoHandle) return;

    if (!selectedMeshId) {
      gizmoHandle.attach(null);
      return;
    }

    const mesh = meshRegistry.current.get(selectedMeshId);
    if (mesh) {
      gizmoHandle.attach(mesh);
    } else {
      gizmoHandle.attach(null);
    }
  }, [gizmoHandleRef, gizmoReady, selectedMeshId, meshRegistry]);

  // Cleanup RAF.
  useEffect(() => {
    return () => {
      if (rafIdRef.current !== null) {
        if (typeof cancelAnimationFrame !== "undefined") {
          cancelAnimationFrame(rafIdRef.current);
        }
        rafIdRef.current = null;
      }
      pendingTransformRef.current = null;
    };
  }, []);

  return { onGizmoChange };
}
