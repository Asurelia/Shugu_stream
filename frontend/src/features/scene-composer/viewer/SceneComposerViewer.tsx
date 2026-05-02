/**
 * SceneComposerViewer — wrapper React autour du rig Three.js du Scene Composer.
 *
 * Responsabilité unique : câbler le hook useSceneRig avec les hooks d'interaction
 * et les useEffects de sync store ↔ Three.js.
 *   - Mount : délégué à useSceneRig (renderer + scène + caméra + helpers + gizmo).
 *   - Prop update : sync cameraPreset, viewMode, selectedMeshId, propInstances.
 *   - Drop : useDragDropTarget (HTML5 drag-drop → prop 3D instancié).
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
 * React dans `interactions/`. Le rig Three.js est isolé dans `useSceneRig`.
 *
 * Pattern Three.js lifecycle : identique à `viewer-adapter.tsx` du Scene Editor
 * (Phase F) — RAF cancel au unmount, `cancelled` token pour le load VRM async.
 *
 * @module viewer/SceneComposerViewer
 */

import { useCallback, useEffect, useRef } from "react";
import * as THREE from "three";
import { disposeAll } from "./three-stage/dispose";
import { loadVrm, type CancelToken } from "./three-stage/loadVrm";
import {
  playVrmaAnimation,
} from "./three-stage/animations";
import {
  createPropInstance,
  disposePropInstance,
} from "./three-stage/prop-instances";
import { useSceneRig } from "./three-stage/useSceneRig";
import { useGizmoBindingWithCallbacks } from "./interactions/useGizmoBinding";
import { useDragDropTarget } from "./interactions/useDragDropTarget";
import type { CameraPreset } from "./three-stage/createCamera";
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

  // Ref au callback onGizmoChange — initialisé null, mis à jour après useGizmoBindingWithCallbacks.
  // Passé à useSceneRig pour que le closure onChange du gizmo lise toujours la version à jour.
  //
  // Pourquoi null-init est sûr : le gizmo Three.js ne peut pas émettre `onChange`
  // avant la fin du useEffect mount de useSceneRig (post-commit React) — moment
  // où `.current` a déjà été assigné par la ligne `onGizmoChangeRef.current = onGizmoChange`
  // ci-dessous. L'optional chaining `?.()` dans useSceneRig.ts est purement
  // défensif contre un cas d'invocation impossible en pratique.
  const onGizmoChangeRef = useRef<((obj: THREE.Object3D) => void) | null>(null);

  // Ref pour annuler les tokens orphelins de VRM load entre 2 appels rapides.
  // Invariant : un seul token peut être "actif" — l'ancien doit être annulé avant
  // d'en créer un nouveau (sinon le .then() de l'ancien peut écraser vrmRef.current).
  // Cleanup au unmount : annule le token en cours (si présent).
  const vrmLoadTokenRef = useRef<CancelToken | null>(null);

  // ── Hook useSceneRig ──────────────────────────────────────────────────────
  // Délègue l'initialisation complète du rig Three.js (7 étapes mount + cleanup).
  const {
    sceneRigRef,
    cameraRigRef,
    gizmoHandleRef,
    meshRegistryRef,
    cameraRefForHooks,
    vrmRef,
    animRigRef,
    helpersRef,
  } = useSceneRig({
    canvasRef,
    cameraPresetRef,
    viewModeRef,
    vrmaUrlRef,
    vrmaLoopRef,
    vrmUrl,
    onGizmoChangeRef,
    setSelectedMeshId,
  });

  // ── Hook useGizmoBindingWithCallbacks ─────────────────────────────────────
  // Fournit `onGizmoChange` (callback stable) à passer dans attachTransformControls.
  // Note : gizmoHandleRef.current sera null au mount initial — le hook est no-op
  // jusqu'à ce que le rig soit initialisé (useSceneRig set gizmoHandleRef).
  const { onGizmoChange } = useGizmoBindingWithCallbacks({
    gizmoHandle: gizmoHandleRef.current,
    meshRegistry: meshRegistryRef,
  });
  // Mise à jour de la ref latest pour que le closure onChange du gizmo soit toujours frais.
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
    [addPropInstance, sceneRigRef, meshRegistryRef],
  );

  useDragDropTarget({
    canvasRef,
    cameraRef: cameraRefForHooks,
    onAssetDropped: handleAssetDropped,
    disabled: viewMode === "preview",
  });

  // ── Sync cameraPreset ────────────────────────────────────────────────────
  useEffect(() => {
    cameraRigRef.current?.applyPreset(cameraPreset);
  }, [cameraPreset, cameraRigRef]);

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
      // Three.js r155+ : visibility sits on `getHelper()` (TransformControlsRoot)
      // rather than on TransformControls itself.
      gizmoHandle.controls.getHelper().visible = isEdit;
      gizmoHandle.controls.enabled = isEdit;
      if (!isEdit) {
        // Mode preview : désattacher le gizmo.
        gizmoHandle.attach(null);
      }
    }
  }, [viewMode, helpersRef, gizmoHandleRef]);

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
  }, [selectedMeshId, gizmoHandleRef, meshRegistryRef]);

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
        // Note : la désélection automatique de selectedMeshId quand une instance est
        // supprimée est gérée au niveau du store (removePropInstance — fix E5.3 C2).
      }
    }
  }, [propInstances, sceneRigRef, meshRegistryRef]);

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
  }, [propInstances, meshRegistryRef, gizmoHandleRef]);

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

      // Annule l'ancien token avant d'en créer un nouveau (defense in depth).
      if (vrmLoadTokenRef.current) {
        vrmLoadTokenRef.current.cancelled = true;
      }
      const token: CancelToken = { cancelled: false };
      vrmLoadTokenRef.current = token;

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
    [sceneRigRef, vrmRef, animRigRef, vrmaUrlRef, vrmaLoopRef],
  );

  useEffect(() => {
    if (vrmUrl !== vrmUrlRef.current) {
      vrmUrlRef.current = vrmUrl;
      loadNewVrm(vrmUrl);
    }
  }, [vrmUrl, loadNewVrm]);

  // ── VRMA URL change (swap animation sans recharger le VRM) ───────────────
  // E5.4 : currentVrmaUrl du store peut changer en runtime (AFK loops ou UI).
  // Ce useEffect dispose l'animRig actuel et relance playVrmaAnimation sur le
  // VRM déjà chargé — sans toucher au VRM ni à la scène.
  // Guard double-dispose : animRigRef est mis à null AVANT l'appel async.
  const prevVrmaUrlRef = useRef<string | undefined>(vrmaUrl);
  useEffect(() => {
    const nextUrl = vrmaUrl;
    if (nextUrl === prevVrmaUrlRef.current) return;
    prevVrmaUrlRef.current = nextUrl;

    const vrm = vrmRef.current;
    // Dispose l'animation précédente (set null AVANT async pour éviter double-dispose).
    const oldRig = animRigRef.current;
    animRigRef.current = null;
    oldRig?.stop();

    if (!vrm || !nextUrl) return;

    let cancelled = false;
    playVrmaAnimation(vrm, nextUrl, vrmaLoopRef.current).then((rig) => {
      if (cancelled) {
        rig?.stop();
        return;
      }
      animRigRef.current = rig;
    });

    return () => {
      cancelled = true;
    };
  // vrmaLoop intentionnellement exclu — changement loop non supporté mid-animation.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [vrmaUrl, vrmRef, animRigRef, vrmaLoopRef]);

  // ── Cleanup vrmLoadTokenRef au unmount ──────────────────────────────────────
  // Annule le token VRM load en cours pour éviter orphelinat si le composant est
  // démonté avant que le load async soit terminé.
  useEffect(() => {
    return () => {
      if (vrmLoadTokenRef.current) {
        vrmLoadTokenRef.current.cancelled = true;
        vrmLoadTokenRef.current = null;
      }
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      style={{ display: "block", width: "100%", height: "100%" }}
    />
  );
}
