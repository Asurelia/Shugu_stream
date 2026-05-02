/**
 * useSceneRig — hook React encapsulant le rig Three.js du Scene Composer.
 *
 * Responsabilité unique : gérer le cycle de vie mount/unmount du rig Three.js
 * complet (renderer, scène, caméra, helpers, gizmo, raycaster, RAF, resize).
 * Isole les 7 étapes d'initialisation hors du composant viewer.
 *
 * Extraction de SceneComposerViewer.tsx (Phase E5.3.1 — M2 fix).
 * Aucun changement de logique fonctionnelle — pure extraction.
 *
 * Garanties :
 *   - Fix M1 préservé : dispose gizmo→meshes (try/finally) du commit 961cf76.
 *   - RAF cancel au unmount.
 *   - ResizeObserver disconnect au unmount.
 *   - Token cancellation pour le load VRM async.
 *
 * @module viewer/three-stage/useSceneRig
 */

import { useEffect, useRef } from "react";
import * as THREE from "three";
import { createScene } from "./createScene";
import { createCamera } from "./createCamera";
import { createHelpers } from "./helpers";
import { loadVrm, type CancelToken } from "./loadVrm";
import { disposeAll } from "./dispose";
import {
  playVrmaAnimation,
  tickAnimation,
  type AnimationRig,
} from "./animations";
import {
  attachTransformControls,
  type TransformControlsHandle,
} from "./transform-controls";
import { setupRaycasterSelection } from "./raycaster-selection";
import { disposePropInstance } from "./prop-instances";
import type { SceneRig } from "./createScene";
import type { CameraRig } from "./createCamera";
import type { HelperSet } from "./helpers";
import type { VRM } from "@pixiv/three-vrm";
import type { CameraPreset } from "./createCamera";

// ─── Types ────────────────────────────────────────────────────────────────────

/** Paramètres d'entrée du hook useSceneRig. */
export interface UseSceneRigParams {
  /** Référence au canvas HTML cible du renderer Three.js. */
  canvasRef: React.RefObject<HTMLCanvasElement | null>;
  /** Ref latest du preset caméra (mis à jour à chaque render). */
  cameraPresetRef: React.MutableRefObject<CameraPreset>;
  /** Ref latest du mode d'affichage (mis à jour à chaque render). */
  viewModeRef: React.MutableRefObject<"edit" | "preview">;
  /** Ref latest de l'URL VRMA (mis à jour à chaque render). */
  vrmaUrlRef: React.MutableRefObject<string | undefined>;
  /** Ref latest du flag loop VRMA (mis à jour à chaque render). */
  vrmaLoopRef: React.MutableRefObject<boolean>;
  /** URL du VRM principal à charger au mount. */
  vrmUrl: string;
  /**
   * Ref au callback onGizmoChange (stable, mis à jour après useGizmoBindingWithCallbacks).
   * Utilisé dans attachTransformControls onChange — lu via ref pour rester stable.
   */
  onGizmoChangeRef: React.MutableRefObject<((obj: THREE.Object3D) => void) | null>;
  /** Action store : sélectionne (ou désélectionne) un mesh 3D. */
  setSelectedMeshId: (id: string | null) => void;
}

/** Refs Three.js retournées par le hook pour exposition au composant parent. */
export interface SceneRigRefs {
  /** Rig scène + renderer. */
  sceneRigRef: React.MutableRefObject<SceneRig | null>;
  /** Rig caméra + OrbitControls. */
  cameraRigRef: React.MutableRefObject<CameraRig | null>;
  /** Handle du gizmo TransformControls. */
  gizmoHandleRef: React.MutableRefObject<TransformControlsHandle | null>;
  /** Registry instanceId → Object3D pour la sélection et le gizmo attach. */
  meshRegistryRef: React.MutableRefObject<Map<string, THREE.Object3D>>;
  /** Référence caméra exposée aux hooks d'interaction. */
  cameraRefForHooks: React.MutableRefObject<THREE.PerspectiveCamera | null>;
  /** Référence au VRM chargé. */
  vrmRef: React.MutableRefObject<VRM | null>;
  /** Référence au rig d'animation actif. */
  animRigRef: React.MutableRefObject<AnimationRig | null>;
  /** Référence aux helpers (grid, axes). */
  helpersRef: React.MutableRefObject<HelperSet | null>;
}

// ─── Hook ─────────────────────────────────────────────────────────────────────

/**
 * Initialise et gère le cycle de vie du rig Three.js du Scene Composer.
 *
 * Monte au premier render (deps=[]) et détruit au unmount.
 * Retourne les refs Three.js pour que le composant parent puisse
 * les utiliser dans ses propres useEffects de sync.
 *
 * @example
 * ```tsx
 * const rig = useSceneRig({
 *   canvasRef,
 *   cameraPresetRef,
 *   viewModeRef,
 *   vrmaUrlRef,
 *   vrmaLoopRef,
 *   vrmUrl,
 *   onGizmoChangeRef,
 *   setSelectedMeshId,
 * });
 * // Utiliser rig.sceneRigRef, rig.cameraRigRef, etc.
 * ```
 */
export function useSceneRig({
  canvasRef,
  cameraPresetRef,
  viewModeRef,
  vrmaUrlRef,
  vrmaLoopRef,
  vrmUrl,
  onGizmoChangeRef,
  setSelectedMeshId,
}: UseSceneRigParams): SceneRigRefs {
  // Refs Three.js — construits une seule fois au mount.
  const sceneRigRef = useRef<SceneRig | null>(null);
  const cameraRigRef = useRef<CameraRig | null>(null);
  const helpersRef = useRef<HelperSet | null>(null);
  const vrmRef = useRef<VRM | null>(null);
  const animRigRef = useRef<AnimationRig | null>(null);
  const rafRef = useRef<number | null>(null);
  const clockRef = useRef(new THREE.Clock());

  // Refs E5.3 — gizmo + selection + registry.
  const gizmoHandleRef = useRef<TransformControlsHandle | null>(null);
  /** Registry instanceId → Object3D pour la sélection et le gizmo attach. */
  const meshRegistryRef = useRef<Map<string, THREE.Object3D>>(new Map());
  /** Ref de la caméra exposée aux hooks interaction. */
  const cameraRefForHooks = useRef<THREE.PerspectiveCamera | null>(null);

  // Capture stable de setSelectedMeshId pour la closure du mount effect.
  // (la ref évite que le useEffect[] se re-exécute si le store change)
  const setSelectedMeshIdRef = useRef(setSelectedMeshId);
  setSelectedMeshIdRef.current = setSelectedMeshId;

  // Capture stable de vrmUrl pour le load initial.
  const vrmUrlInitRef = useRef(vrmUrl);

  // ── Setup one-shot (mount) ───────────────────────────────────────────────
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const token: CancelToken = { cancelled: false };
    const parent = canvas.parentElement;
    const w = parent?.clientWidth || 800;
    const h = parent?.clientHeight || 600;

    // 1. Scene + renderer.
    const sceneRig = createScene(canvas, w, h);
    sceneRigRef.current = sceneRig;

    // 2. Camera + OrbitControls.
    const cameraRig = createCamera(canvas, w / h, cameraPresetRef.current);
    cameraRigRef.current = cameraRig;
    cameraRefForHooks.current = cameraRig.camera;

    // 3. Helpers (edit mode uniquement — mais créés toujours pour dispose propre).
    const helpers = createHelpers(sceneRig.scene);
    helpersRef.current = helpers;
    helpers.grid.visible = viewModeRef.current === "edit";
    helpers.axes.visible = viewModeRef.current === "edit";

    // 4. TransformControls (gizmo E5.3) — masqué par défaut, visible en edit mode.
    const gizmoHandle = attachTransformControls(
      cameraRig.camera,
      canvas,
      sceneRig.scene,
      cameraRig.controls,
      {
        mode: "translate",
        onChange: (obj) => {
          // Debounce via le callback stable du hook useGizmoBindingWithCallbacks.
          onGizmoChangeRef.current?.(obj);
        },
        onDraggingChanged: (dragging) => {
          // OrbitControls déjà géré dans attachTransformControls via le paramètre orbit.
          // Ce callback permet des effets UI supplémentaires si besoin.
          void dragging;
        },
      },
    );
    gizmoHandleRef.current = gizmoHandle;

    // Gizmo visible seulement en mode edit.
    // Three.js r155+ : `.visible` est sur `getHelper()` (TransformControlsRoot).
    gizmoHandle.controls.getHelper().visible = viewModeRef.current === "edit";
    gizmoHandle.controls.enabled = viewModeRef.current === "edit";

    // 5. Raycaster selection (click-to-pick).
    const selectionHandle = setupRaycasterSelection(
      sceneRig.scene,
      cameraRig.camera,
      canvas,
      (mesh) => {
        if (!mesh) {
          // Clic dans le vide → désélection.
          setSelectedMeshIdRef.current(null);
          gizmoHandle.attach(null);
          return;
        }
        // Identifie l'instance via userData.instanceId.
        const instanceId = mesh.userData["instanceId"] as string | undefined;
        if (instanceId) {
          setSelectedMeshIdRef.current(instanceId);
          gizmoHandle.attach(mesh);
        }
      },
      {
        ignoreNamePrefixes: ["__helper_", "__gizmo_"],
        ignoreNames: ["__floor__"],
      },
    );

    // 6. Boucle RAF.
    function tick(): void {
      const delta = clockRef.current.getDelta();
      cameraRig.controls.update();
      tickAnimation(animRigRef.current, delta);

      if (vrmRef.current) {
        vrmRef.current.update(delta);
      }

      const activeCamera = cameraRig.camera;
      sceneRig.renderer.render(sceneRig.scene, activeCamera);
      rafRef.current = requestAnimationFrame(tick);
    }
    rafRef.current = requestAnimationFrame(tick);

    // 7. ResizeObserver.
    const resizeObserver = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width, height } = entry.contentRect;
        if (width > 0 && height > 0) {
          sceneRig.renderer.setSize(width, height);
          cameraRig.camera.aspect = width / height;
          cameraRig.camera.updateProjectionMatrix();
        }
      }
    });
    if (parent) resizeObserver.observe(parent);

    // 8. Load VRM async.
    loadVrm(vrmUrlInitRef.current, sceneRig.scene, token).then((vrm) => {
      if (token.cancelled || !vrm) return;
      vrmRef.current = vrm;

      const url = vrmaUrlRef.current;
      if (url) {
        playVrmaAnimation(vrm, url, vrmaLoopRef.current).then((rig) => {
          if (token.cancelled) {
            rig?.stop();
            return;
          }
          animRigRef.current = rig;
        });
      }
    });

    // ── Cleanup (unmount) ──────────────────────────────────────────────────
    return () => {
      token.cancelled = true;

      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }

      resizeObserver.disconnect();

      // E5.3 fix M1 : dispose gizmo AVANT meshes (le gizmo peut détenir
      // controls.object pointant vers un mesh ; le détacher d'abord évite
      // les références à des geometries libérées). Selection idem.
      selectionHandle.dispose();
      gizmoHandle.dispose();
      gizmoHandleRef.current = null;

      // E5.3 fix M1 : try/finally garantit que disposeAll tourne même si
      // disposePropInstance throw sur un material corrompu.
      try {
        // Dispose toutes les props de la scène.
        for (const [, obj] of meshRegistryRef.current) {
          sceneRig.scene.remove(obj);
          disposePropInstance(obj);
        }
      } finally {
        meshRegistryRef.current.clear();

        disposeAll({
          renderer: sceneRigRef.current?.renderer,
          scene: sceneRigRef.current?.scene,
          floor: sceneRigRef.current?.floor,
          controls: cameraRigRef.current?.controls,
          vrm: vrmRef.current,
          helpers: helpersRef.current,
          animRig: animRigRef.current,
        });

        sceneRigRef.current = null;
        cameraRigRef.current = null;
        cameraRefForHooks.current = null;
        helpersRef.current = null;
        vrmRef.current = null;
        animRigRef.current = null;
      }
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []); // Mount-only — les props dynamiques sont lues via refs.

  return {
    sceneRigRef,
    cameraRigRef,
    gizmoHandleRef,
    meshRegistryRef,
    cameraRefForHooks,
    vrmRef,
    animRigRef,
    helpersRef,
  };
}
