/**
 * SceneComposerViewer — wrapper React autour du rig Three.js du Scene Composer.
 *
 * Responsabilité unique : gérer le cycle de vie React ↔ Three.js.
 *   - Mount : crée le rig (renderer + scène + caméra + helpers).
 *   - Prop update : applique les changements de preset caméra sans recréer le rig.
 *   - Unmount : annule le RAF, dispose toutes les ressources GPU.
 *
 * OUT OF SCOPE E5.2 :
 *   - Gizmos / TransformControls (E5.3)
 *   - Drag-drop d'assets (E5.3)
 *   - Play Mode toolbar (E5.4)
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
import type { SceneRig } from "./three-stage/createScene";
import type { CameraRig } from "./three-stage/createCamera";
import type { HelperSet } from "./three-stage/helpers";
import type { VRM } from "@pixiv/three-vrm";

// ─── Types ────────────────────────────────────────────────────────────────────

export interface SceneComposerViewerProps {
  /** URL relative du VRM à afficher (ex: `/assets/vrm/shugu.vrm`). */
  vrmUrl: string;
  /** Preset de caméra actif (modifiable en cours de session). */
  cameraPreset: CameraPreset;
  /** Mode d'affichage : "edit" (avec helpers) ou "preview" (propre). */
  viewMode: "edit" | "preview";
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
}: SceneComposerViewerProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  // Refs Three.js — construits une seule fois au mount.
  const sceneRigRef = useRef<SceneRig | null>(null);
  const cameraRigRef = useRef<CameraRig | null>(null);
  const helpersRef = useRef<HelperSet | null>(null);
  const vrmRef = useRef<VRM | null>(null);
  const rafRef = useRef<number | null>(null);
  const clockRef = useRef(new THREE.Clock());

  // Refs latest pour les props lues dans les closures (RAF loop, async load).
  const cameraPresetRef = useRef<CameraPreset>(cameraPreset);
  cameraPresetRef.current = cameraPreset;
  const viewModeRef = useRef<"edit" | "preview">(viewMode);
  viewModeRef.current = viewMode;

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

    // 3. Helpers (edit mode uniquement — mais créés toujours pour dispose propre).
    const helpers = createHelpers(sceneRig.scene);
    helpersRef.current = helpers;
    // Masquer en mode preview au mount.
    helpers.grid.visible = viewModeRef.current === "edit";
    helpers.axes.visible = viewModeRef.current === "edit";

    // 4. Boucle RAF.
    function tick(): void {
      const delta = clockRef.current.getDelta();

      cameraRig.controls.update();

      // Update VRM update (blendshapes, springbones) si chargé.
      if (vrmRef.current) {
        vrmRef.current.update(delta);
      }

      const activeCamera = cameraRig.camera;
      sceneRig.renderer.render(sceneRig.scene, activeCamera);

      rafRef.current = requestAnimationFrame(tick);
    }

    rafRef.current = requestAnimationFrame(tick);

    // 5. ResizeObserver pour adapter le renderer à la taille du conteneur.
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

    // 6. Load VRM async.
    loadVrm(vrmUrl, sceneRig.scene, token).then((vrm) => {
      if (vrm) {
        vrmRef.current = vrm;
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

      disposeAll({
        renderer: sceneRigRef.current?.renderer,
        scene: sceneRigRef.current?.scene,
        floor: sceneRigRef.current?.floor,
        controls: cameraRigRef.current?.controls,
        vrm: vrmRef.current,
        helpers: helpersRef.current,
      });

      sceneRigRef.current = null;
      cameraRigRef.current = null;
      helpersRef.current = null;
      vrmRef.current = null;
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []); // Mount-only — les props dynamiques sont lues via refs.

  // ── Sync cameraPreset (prop change sans remount) ─────────────────────────
  useEffect(() => {
    cameraRigRef.current?.applyPreset(cameraPreset);
  }, [cameraPreset]);

  // ── Sync viewMode (toggle helpers visibility) ────────────────────────────
  useEffect(() => {
    const helpers = helpersRef.current;
    if (!helpers) return;
    helpers.grid.visible = viewMode === "edit";
    helpers.axes.visible = viewMode === "edit";
  }, [viewMode]);

  // ── VRM URL change (reload) ──────────────────────────────────────────────
  const vrmUrlRef = useRef<string>(vrmUrl);
  const loadNewVrm = useCallback(
    (url: string) => {
      const sceneRig = sceneRigRef.current;
      if (!sceneRig) return;

      // Dispose l'ancien VRM si présent.
      if (vrmRef.current) {
        disposeAll({
          scene: sceneRig.scene,
          vrm: vrmRef.current,
        });
        vrmRef.current = null;
      }

      const token: CancelToken = { cancelled: false };
      loadVrm(url, sceneRig.scene, token).then((vrm) => {
        if (vrm) {
          vrmRef.current = vrm;
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
