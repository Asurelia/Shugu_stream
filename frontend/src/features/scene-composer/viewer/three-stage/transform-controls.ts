/**
 * transform-controls — wrapper TransformControls Three.js pour le Scene Composer.
 *
 * Responsabilité unique : attacher et configurer un `TransformControls` sur
 * une scène. Gère la coexistence OrbitControls + TransformControls via le
 * pattern `dragging-changed` : pendant un drag gizmo, OrbitControls est
 * désactivé pour éviter les conflits de souris.
 *
 * Pattern porté depuis `SceneEditorViewer.tsx` (Phase F legacy) lignes 154-171
 * et 255-256 — adapté pour le Scene Composer (injection d'OrbitControls via
 * callback plutôt que ref locale).
 *
 * Cleanup : appeler `dispose()` retourné avant `renderer.dispose()` — l'ordre
 * est critique (detach AVANT dispose, dispose AVANT perte du contexte GL).
 *
 * Import Three.js r149 : chemin `three/examples/jsm/controls/TransformControls`
 * (NOT `three/addons/...` qui n'existe qu'à partir de r152).
 *
 * @module three-stage/transform-controls
 */

import * as THREE from "three";
import { TransformControls } from "three/examples/jsm/controls/TransformControls.js";
import type { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";

// ─── Types ────────────────────────────────────────────────────────────────────

/** Mode de transformation du gizmo. */
export type GizmoMode = "translate" | "rotate" | "scale";

/** Options de configuration du TransformControls. */
export interface AttachTransformControlsOptions {
  /** Mode initial du gizmo (défaut : "translate"). */
  mode?: GizmoMode;
  /**
   * Callback déclenché à chaque frame pendant le drag du gizmo.
   *
   * Reçoit l'objet attaché. Debouncer via RAF côté consommateur pour ne pas
   * spammer le store à 60Hz (pattern viewer-adapter.tsx L348-385).
   */
  onChange: (object: THREE.Object3D) => void;
  /**
   * Callback déclenché quand l'état de drag change (début/fin).
   *
   * @param dragging - `true` = drag commence, `false` = drag termine.
   * Utilisé pour désactiver/réactiver l'OrbitControls.
   */
  onDraggingChanged: (dragging: boolean) => void;
}

/** Interface retournée par `attachTransformControls`. */
export interface TransformControlsHandle {
  /** L'instance TransformControls (accès direct si besoin). */
  controls: TransformControls;
  /** Change le mode de transformation. */
  setMode: (mode: GizmoMode) => void;
  /**
   * Attache le gizmo à un Object3D.
   *
   * Passer `null` pour détacher sans disposer.
   */
  attach: (obj: THREE.Object3D | null) => void;
  /**
   * Libère toutes les ressources : detach → remove from scene → dispose.
   *
   * À appeler AVANT `renderer.dispose()` au unmount React.
   */
  dispose: () => void;
}

// ─── Implémentation ────────────────────────────────────────────────────────────

/**
 * Attache un TransformControls Three.js à la scène.
 *
 * Le gizmo est ajouté à la `scene` avec le cast `as unknown as THREE.Object3D`
 * requis par r149 (TransformControls n'hérite pas d'Object3D dans les types
 * de cette version).
 *
 * @param camera     - Caméra utilisateur (OrbitControls cam, pas la scene cam).
 * @param domElement - Canvas du renderer (cible des events souris du gizmo).
 * @param scene      - Scène Three.js dans laquelle ajouter le gizmo.
 * @param orbit      - OrbitControls à désactiver pendant le drag (peut être
 *                     `null` si les controls ne sont pas encore créés).
 * @param options    - Callbacks et mode initial.
 * @returns Handle avec `setMode`, `attach`, `dispose`.
 */
export function attachTransformControls(
  camera: THREE.PerspectiveCamera,
  domElement: HTMLElement,
  scene: THREE.Scene,
  orbit: OrbitControls | null,
  options: AttachTransformControlsOptions,
): TransformControlsHandle {
  const { mode = "translate", onChange, onDraggingChanged } = options;

  // Crée le TransformControls sur la caméra utilisateur.
  // Three.js r155+ : `TransformControls` n'est plus un Object3D — c'est le
  // wrapper qui dispatch events et tient l'object attaché. Le gizmo visuel
  // (axes, plans, picking spheres) est sur `getHelper()` (TransformControlsRoot,
  // lui un Object3D). On garde une référence locale `helper` pour : (1)
  // toggle `.visible` au lifecycle, (2) `scene.add(helper)` au mount,
  // (3) `scene.remove(helper)` au dispose. `getHelper()` retourne toujours
  // la même instance (cached `_root`).
  const controls = new TransformControls(camera, domElement);
  const helper = controls.getHelper();
  controls.setMode(mode);

  // Masqué et désactivé par défaut — activé en mode "edit" uniquement.
  helper.visible = false;
  controls.enabled = false;

  // Listener dragging-changed : désactive orbit pendant drag pour éviter le
  // conflit de capture souris (pattern identique à SceneEditorViewer L159-161).
  // Cast via unknown requis pour compatibilité Three.js r149 (type interne
  // `TransformControls.addEventListener` est plus strict que EventListener).
  const onDraggingChanged_ = (e: unknown) => {
    const dragging = !!(e as { value?: boolean }).value;
    if (orbit) {
      orbit.enabled = !dragging;
    }
    onDraggingChanged(dragging);
  };
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  controls.addEventListener("dragging-changed", onDraggingChanged_ as any);

  // Listener change : déclenché à chaque frame pendant drag.
  // Le consommateur doit debouncer via RAF (pattern viewer-adapter.tsx).
  const onChange_ = () => {
    const attached = controls.object;
    if (attached) {
      onChange(attached);
    }
  };
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  controls.addEventListener("change", onChange_ as any);

  // Sans ajouter le helper à la scène, le gizmo ne rendrait pas et le
  // raycast picking ne pourrait pas le toucher (CodeRabbit P1).
  scene.add(helper);

  return {
    controls,

    setMode(m: GizmoMode): void {
      controls.setMode(m);
    },

    attach(obj: THREE.Object3D | null): void {
      if (obj) {
        controls.attach(obj);
      } else {
        controls.detach();
      }
    },

    dispose(): void {
      // Ordre critique : detach → remove → dispose (Phase F lesson M2).
      // Three r155+ : on remove le helper (Object3D ajouté à la scène),
      // pas `controls` directement.
      controls.detach();
      scene.remove(helper);
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      controls.removeEventListener("dragging-changed", onDraggingChanged_ as any);
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      controls.removeEventListener("change", onChange_ as any);
      controls.dispose();
    },
  };
}
