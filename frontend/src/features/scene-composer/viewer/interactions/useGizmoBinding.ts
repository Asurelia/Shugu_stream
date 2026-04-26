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

import { useCallback, useEffect, useRef } from "react";
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
   * Handle du TransformControls (retourné par `attachTransformControls`).
   * Peut être `null` si le rig n'est pas encore initialisé.
   */
  gizmoHandle: TransformControlsHandle | null;
  /**
   * Map des Object3D de la scène, indexée par instanceId.
   * Fourni par le viewer pour permettre la résolution `selectedMeshId → Object3D`.
   */
  meshRegistry: React.MutableRefObject<Map<string, THREE.Object3D>>;
}

// ─── Hook ─────────────────────────────────────────────────────────────────────

/**
 * Binde les événements du TransformControls au store Zustand.
 *
 * Doit être appelé APRÈS que `gizmoHandle` est disponible (après le mount
 * useEffect du viewer). Si `gizmoHandle` est null, le hook est no-op.
 *
 * Le hook lit les selectors `selectedMeshId` et `transformMode` du store,
 * et pousse les transforms via `updateMeshTransform`.
 */
export function useGizmoBinding({ gizmoHandle, meshRegistry }: UseGizmoBindingProps): void {
  const selectedMeshId = useSceneComposerStore(selectSelectedMeshId);
  const transformMode = useSceneComposerStore(selectTransformMode);
  const updateMeshTransform = useSceneComposerStore((s) => s.updateMeshTransform);

  // ── Debounce RAF pour le store write ────────────────────────────────────
  // Buffer du dernier transform reçu du gizmo. null = pas de flush pending.
  const pendingTransformRef = useRef<Partial<ObjectTransform> | null>(null);
  const rafIdRef = useRef<number | null>(null);
  // Ref latest pour éviter les closures stales dans le flush.
  const selectedMeshIdRef = useRef<string | null>(selectedMeshId);
  selectedMeshIdRef.current = selectedMeshId;
  const updateMeshTransformRef = useRef(updateMeshTransform);
  updateMeshTransformRef.current = updateMeshTransform;

  const flushPending = useCallback(() => {
    rafIdRef.current = null;
    const pending = pendingTransformRef.current;
    if (!pending) return;
    pendingTransformRef.current = null;

    const id = selectedMeshIdRef.current;
    if (!id) return;

    updateMeshTransformRef.current(id, pending);
  }, []);

  // ── Sync transformMode → gizmo ──────────────────────────────────────────
  useEffect(() => {
    if (!gizmoHandle) return;
    gizmoHandle.setMode(transformMode as GizmoMode);
  }, [gizmoHandle, transformMode]);

  // ── Sync selectedMeshId → gizmo attach ─────────────────────────────────
  useEffect(() => {
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
  }, [gizmoHandle, selectedMeshId, meshRegistry]);

  // ── Setup onChange callback (stable — ne dépend pas des state) ─────────
  // Note : l'onChange est configuré dans le gizmoHandle au moment de sa
  // création (dans attachTransformControls). Ce hook reçoit donc le handle
  // déjà configuré — on n'a pas besoin de re-subscribe ici. Le flush est
  // géré par le debounce RAF créé au-dessus, qui est passé via le handle.
  //
  // Pour la modularité : ce hook est responsable du debounce + store write.
  // Le gizmoHandle est responsable de l'event listening Three.js.
  // Le viewer est responsable de passer onChange → flushRef vers ce hook.

  // ── Cleanup RAF au unmount ──────────────────────────────────────────────
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

  // Expose flushPending pour que le viewer puisse déclencher le debounce
  // depuis le callback onChange du gizmoHandle.
  // Stocké dans un ref accessible par le viewer via closure.
  // (Pattern : le viewer appelle gizmoBindingFlushRef.current(transform))
}

/**
 * Version du hook avec callbacks exposés — utilisé par le viewer pour
 * déclencher le debounce RAF depuis les event listeners Three.js.
 *
 * Retourne un objet stable avec `onGizmoChange(transform)` à appeler
 * depuis le callback `onChange` de `attachTransformControls`.
 */
export function useGizmoBindingWithCallbacks(props: UseGizmoBindingProps): {
  onGizmoChange: (object: THREE.Object3D) => void;
} {
  const { gizmoHandle, meshRegistry } = props;
  const selectedMeshId = useSceneComposerStore(selectSelectedMeshId);
  const transformMode = useSceneComposerStore(selectTransformMode);
  const updateMeshTransform = useSceneComposerStore((s) => s.updateMeshTransform);

  // Debounce
  const pendingTransformRef = useRef<Partial<ObjectTransform> | null>(null);
  const rafIdRef = useRef<number | null>(null);
  const selectedMeshIdRef = useRef<string | null>(selectedMeshId);
  selectedMeshIdRef.current = selectedMeshId;
  const updateMeshTransformRef = useRef(updateMeshTransform);
  updateMeshTransformRef.current = updateMeshTransform;

  const flushPending = useCallback(() => {
    rafIdRef.current = null;
    const pending = pendingTransformRef.current;
    if (!pending) return;
    pendingTransformRef.current = null;

    const id = selectedMeshIdRef.current;
    if (!id) return;

    updateMeshTransformRef.current(id, pending);
  }, []);

  // Callback stable à passer comme `onChange` dans attachTransformControls.
  const onGizmoChange = useCallback(
    (object: THREE.Object3D) => {
      // Extrait le transform depuis l'Object3D (en degrés pour le store).
      const pos = object.position;
      const rot = object.rotation;
      const scl = object.scale;

      const RAD_TO_DEG = 180 / Math.PI;

      pendingTransformRef.current = {
        position: [pos.x, pos.y, pos.z],
        // Convention : rotation stockée en degrés dans le store.
        rotation: [rot.x * RAD_TO_DEG, rot.y * RAD_TO_DEG, rot.z * RAD_TO_DEG],
        scale: [scl.x, scl.y, scl.z],
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

  // Sync transformMode → gizmo.
  useEffect(() => {
    if (!gizmoHandle) return;
    gizmoHandle.setMode(transformMode as GizmoMode);
  }, [gizmoHandle, transformMode]);

  // Sync selectedMeshId → gizmo attach.
  useEffect(() => {
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
  }, [gizmoHandle, selectedMeshId, meshRegistry]);

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
