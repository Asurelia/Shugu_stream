/**
 * SceneComposerViewer — wrapper React autour du rig Three.js du Scene Composer.
 *
 * Responsabilité unique : gérer le cycle de vie React ↔ Three.js.
 *   - Mount : crée le rig (renderer + scène + caméra + helpers + gizmo + selection).
 *   - Prop update : applique les changements de preset caméra sans recréer le rig.
 *   - Unmount : annule le RAF, dispose toutes les ressources GPU.
 *
 * Extensions E5.3 :
 *   - TransformControls (gizmo W/E/R) + coexistence OrbitControls
 *   - Raycaster click-to-select (pointerdown → store.setSelectedMeshId)
 *   - Drop target HTML5 (drop depuis AssetCataloguePanel → instancie prop 3D)
 *   - Sync store.selectedMeshId → gizmo.attach(mesh)
 *   - Sync store.propInstances → mount/unmount Object3D dans la scène
 *   - Bidirectionnel : gizmo change → store.updateMeshTransform (debounce RAF)
 *
 * Modularité : les modules purs Three.js sont dans `three-stage/`, les hooks
 * React dans `interactions/`. Ce composant câble ensemble les deux couches.
 *
 * Limite modularité : SceneComposerViewer reste < 400 lignes en E5.3 car
 * l'ensemble rig + gizmo + selection + drop tient dans un seul `useEffect` mount.
 *
 * Pattern Three.js lifecycle : identique à `viewer-adapter.tsx` du Scene Editor
 * (Phase F) — RAF cancel au unmount, `cancelled` token pour le load VRM async.
 *
 * @module viewer/SceneComposerViewer
 */

import { useCallback, useEffect, useRef } from "react";
import * as THREE from "three";
import { createScene } from "./three-stage/createScene";
import { createCamera, type CameraPreset } from "./three-stage/createCamera";
import { createHelpers } from "./three-stage/helpers";
import { loadVrm, type CancelToken } from "./three-stage/loadVrm";
import { disposeAll } from "./three-stage/dispose";
import {
  playVrmaAnimation,
  tickAnimation,
  type AnimationRig,
} from "./three-stage/animations";
import {
  attachTransformControls,
  type TransformControlsHandle,
} from "./three-stage/transform-controls";
import { setupRaycasterSelection } from "./three-stage/raycaster-selection";
import {
  createPropInstance,
  disposePropInstance,
} from "./three-stage/prop-instances";
import { useGizmoBindingWithCallbacks } from "./interactions/useGizmoBinding";
import { useDragDropTarget } from "./interactions/useDragDropTarget";
import type { SceneRig } from "./three-stage/createScene";
import type { CameraRig } from "./three-stage/createCamera";
import type { HelperSet } from "./three-stage/helpers";
import type { VRM } from "@pixiv/three-vrm";
import {
  useSceneComposerStore,
  selectSelectedMeshId,
  selectPropInstances,
} from "../store/useSceneComposerStore";
import type { Prop3DEntry } from "../api/catalogClient";

// ─── Types ────────────────────────────────────────────────────────────────────

export interface SceneComposerViewerProps {
  /** URL relative du VRM à afficher (ex: `/assets/vrm/shugu.vrm`). */
  vrmUrl: string;
  /** Preset de caméra actif (modifiable en cours de session). */
  cameraPreset: CameraPreset;
  /** Mode d'affichage : "edit" (avec helpers) ou "preview" (propre). */
  viewMode: "edit" | "preview";
  /**
   * URL VRMA à jouer une fois le VRM chargé (optionnel).
   *
   * Wiring complet en E5.3 (UI panel pour piocher dans le catalogue VRMA).
   * En E5.2 c'est une prop opt-in pour que la mécanique RAF + dispose soit
   * exercée et testée — `tickAnimation(null, delta)` est no-op si non fourni.
   */
  vrmaUrl?: string;
  /** Si `true`, l'animation boucle (LoopRepeat). Défaut : `false`. */
  vrmaLoop?: boolean;
}

// ─── Helpers internes ─────────────────────────────────────────────────────────

/**
 * Génère un ID unique simple pour les instances de props.
 * UUID-like — pas besoin d'un vrai UUID pour ce contexte.
 */
function generateInstanceId(): string {
  return `prop_${Date.now()}_${Math.random().toString(36).slice(2, 9)}`;
}

// ─── Composant ────────────────────────────────────────────────────────────────

/**
 * Viewer Three.js du Scene Composer.
 *
 * Rendu 100% `useEffect` — le canvas est passif (React ne gère que le DOM node).
 * Le renderer Three.js pilote le canvas en dehors du cycle React.
 */
export function SceneComposerViewer({
  vrmUrl,
  cameraPreset,
  viewMode,
  vrmaUrl,
  vrmaLoop = false,
}: SceneComposerViewerProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

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

  // Refs latest pour les props lues dans les closures (RAF loop, async load).
  const cameraPresetRef = useRef<CameraPreset>(cameraPreset);
  cameraPresetRef.current = cameraPreset;
  const viewModeRef = useRef<"edit" | "preview">(viewMode);
  viewModeRef.current = viewMode;
  const vrmaUrlRef = useRef<string | undefined>(vrmaUrl);
  vrmaUrlRef.current = vrmaUrl;
  const vrmaLoopRef = useRef<boolean>(vrmaLoop);
  vrmaLoopRef.current = vrmaLoop;

  // Store — sélecteurs fins.
  const selectedMeshId = useSceneComposerStore(selectSelectedMeshId);
  const propInstances = useSceneComposerStore(selectPropInstances);
  const setSelectedMeshId = useSceneComposerStore((s) => s.setSelectedMeshId);
  const addPropInstance = useSceneComposerStore((s) => s.addPropInstance);

  // ── Hook useGizmoBindingWithCallbacks ─────────────────────────────────────
  // Fournit `onGizmoChange` (callback stable) à passer dans attachTransformControls.
  // Note : gizmoHandleRef.current sera null au mount initial — le hook est no-op
  // jusqu'à ce que le rig soit initialisé (le useEffect mount set gizmoHandleRef).
  const { onGizmoChange } = useGizmoBindingWithCallbacks({
    gizmoHandle: gizmoHandleRef.current,
    meshRegistry: meshRegistryRef,
  });
  // Ref latest pour que le callback onChange du gizmo lise toujours la version
  // à jour (le hook peut re-render entre le mount et le premier drag).
  const onGizmoChangeRef = useRef(onGizmoChange);
  onGizmoChangeRef.current = onGizmoChange;

  // ── Hook useDragDropTarget ────────────────────────────────────────────────
  const handleAssetDropped = useCallback(
    (asset: Prop3DEntry, worldPosition: THREE.Vector3) => {
      const scene = sceneRigRef.current?.scene;
      if (!scene) return;

      const instanceId = generateInstanceId();
      const obj = createPropInstance(asset, worldPosition, instanceId);
      scene.add(obj);
      meshRegistryRef.current.set(instanceId, obj);

      addPropInstance({
        id: instanceId,
        assetSlug: asset.slug,
        transform: {
          position: [worldPosition.x, worldPosition.y, worldPosition.z],
          rotation: [0, 0, 0],
          scale: [1, 1, 1],
        },
      });
    },
    [addPropInstance],
  );

  useDragDropTarget({
    canvasRef,
    cameraRef: cameraRefForHooks,
    onAssetDropped: handleAssetDropped,
    disabled: viewMode === "preview",
  });

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
          onGizmoChangeRef.current(obj);
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
    gizmoHandle.controls.visible = viewModeRef.current === "edit";
    gizmoHandle.controls.enabled = viewModeRef.current === "edit";

    // 5. Raycaster selection (click-to-pick).
    const selectionHandle = setupRaycasterSelection(
      sceneRig.scene,
      cameraRig.camera,
      canvas,
      (mesh) => {
        if (!mesh) {
          // Clic dans le vide → désélection.
          setSelectedMeshId(null);
          gizmoHandle.attach(null);
          return;
        }
        // Identifie l'instance via userData.instanceId.
        const instanceId = mesh.userData["instanceId"] as string | undefined;
        if (instanceId) {
          setSelectedMeshId(instanceId);
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
    loadVrm(vrmUrl, sceneRig.scene, token).then((vrm) => {
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

      // Dispose E5.3 : gizmo + selection + props (avant disposeAll).
      selectionHandle.dispose();

      // Dispose toutes les props de la scène.
      for (const [, obj] of meshRegistryRef.current) {
        sceneRig.scene.remove(obj);
        disposePropInstance(obj);
      }
      meshRegistryRef.current.clear();

      gizmoHandle.dispose();
      gizmoHandleRef.current = null;

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
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []); // Mount-only — les props dynamiques sont lues via refs.

  // ── Sync cameraPreset ────────────────────────────────────────────────────
  useEffect(() => {
    cameraRigRef.current?.applyPreset(cameraPreset);
  }, [cameraPreset]);

  // ── Sync viewMode (helpers + gizmo visibility) ───────────────────────────
  useEffect(() => {
    const helpers = helpersRef.current;
    const gizmoHandle = gizmoHandleRef.current;
    const isEdit = viewMode === "edit";

    if (helpers) {
      helpers.grid.visible = isEdit;
      helpers.axes.visible = isEdit;
    }

    if (gizmoHandle) {
      gizmoHandle.controls.visible = isEdit;
      gizmoHandle.controls.enabled = isEdit;
      if (!isEdit) {
        // Mode preview : désattacher le gizmo.
        gizmoHandle.attach(null);
      }
    }
  }, [viewMode]);

  // ── Sync selectedMeshId → gizmo attach ───────────────────────────────────
  // Ce useEffect est le point de sync bidirectionnel Inspector → gizmo.
  // Note : le gizmo → store est géré dans useGizmoBindingWithCallbacks.
  useEffect(() => {
    const gizmoHandle = gizmoHandleRef.current;
    if (!gizmoHandle) return;

    if (!selectedMeshId) {
      gizmoHandle.attach(null);
      return;
    }

    const mesh = meshRegistryRef.current.get(selectedMeshId);
    gizmoHandle.attach(mesh ?? null);
  }, [selectedMeshId]);

  // ── Sync propInstances → scene (ajout/retrait) ───────────────────────────
  // Ce useEffect réconcilie le store avec la scène Three.js.
  // Attention : le drag-drop ajoute directement via handleAssetDropped +
  // addPropInstance. Cet effect gère les removePropInstance (côté inspector).
  useEffect(() => {
    const scene = sceneRigRef.current?.scene;
    if (!scene) return;

    // Retire les props qui ne sont plus dans le store.
    for (const [id, obj] of meshRegistryRef.current) {
      if (!propInstances[id]) {
        scene.remove(obj);
        disposePropInstance(obj);
        meshRegistryRef.current.delete(id);
        // Si l'instance supprimée était sélectionnée, désélectionner.
        // (lecture via closure — setSelectedMeshId est stable Zustand)
      }
    }
  }, [propInstances]);

  // ── Sync Inspector transform → mesh (store → Three.js) ───────────────────
  // Applique les changements de transform (sliders inspector) sur les meshes.
  // Guard : si le gizmo est en cours de drag, on ignore (évite feedback loop).
  useEffect(() => {
    for (const [id, instance] of Object.entries(propInstances)) {
      const obj = meshRegistryRef.current.get(id);
      if (!obj) continue;

      // Guard feedback loop : si le gizmo est dragging cet objet, ignorer.
      const gizmoHandle = gizmoHandleRef.current;
      if (gizmoHandle?.controls.dragging && gizmoHandle.controls.object === obj) {
        continue;
      }

      const { position, rotation, scale } = instance.transform;
      const DEG_TO_RAD = Math.PI / 180;

      obj.position.set(position[0], position[1], position[2]);
      obj.rotation.set(
        rotation[0] * DEG_TO_RAD,
        rotation[1] * DEG_TO_RAD,
        rotation[2] * DEG_TO_RAD,
      );
      obj.scale.set(scale[0], scale[1], scale[2]);
    }
  }, [propInstances]);

  // ── VRM URL change (reload) ──────────────────────────────────────────────
  const vrmUrlRef = useRef<string>(vrmUrl);
  const loadNewVrm = useCallback(
    (url: string) => {
      const sceneRig = sceneRigRef.current;
      if (!sceneRig) return;

      if (vrmRef.current || animRigRef.current) {
        disposeAll({
          scene: sceneRig.scene,
          vrm: vrmRef.current,
          animRig: animRigRef.current,
        });
        vrmRef.current = null;
        animRigRef.current = null;
      }

      const token: CancelToken = { cancelled: false };
      loadVrm(url, sceneRig.scene, token).then((vrm) => {
        if (token.cancelled || !vrm) return;
        vrmRef.current = vrm;

        const animUrl = vrmaUrlRef.current;
        if (animUrl) {
          playVrmaAnimation(vrm, animUrl, vrmaLoopRef.current).then((rig) => {
            if (token.cancelled) {
              rig?.stop();
              return;
            }
            animRigRef.current = rig;
          });
        }
      });
    },
    [],
  );

  useEffect(() => {
    if (vrmUrl !== vrmUrlRef.current) {
      vrmUrlRef.current = vrmUrl;
      loadNewVrm(vrmUrl);
    }
  }, [vrmUrl, loadNewVrm]);

  return (
    <canvas
      ref={canvasRef}
      style={{ display: "block", width: "100%", height: "100%" }}
    />
  );
}
