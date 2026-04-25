/**
 * SceneEditorViewer — mini-viewer Three.js avec **2 modes** :
 *
 *   `viewMode = "preview"` (défaut)  — WYSIWYG pur.
 *     La caméra du canvas EST la scene camera (position / lookAt / FOV
 *     pilotés par les props `sceneCamera`, `sceneLookAt`, `sceneFov`).
 *     Aucun gizmo, aucun grid, aucun helper : l'admin voit EXACTEMENT
 *     ce que verra le visiteur une fois la config sauvegardée.
 *
 *   `viewMode = "edit"` — manipulation 3D libre.
 *     OrbitControls libre sur une seconde caméra. TransformControls attaché
 *     au VRM. Grid + axes. CameraHelper bleu montre le frustum de la
 *     scene camera pour repère visuel.
 *
 * Les sliders de l'inspector sont **la source de vérité** : bouger un
 * slider met à jour le draft, qui met à jour les props, qui bougent la
 * scène en temps réel. En mode edit, drag un gizmo met à jour le draft via
 * `onAvatarTransformChange` — bidirectionnel.
 *
 * Petit breathing sur le VRM (sin Y à 0.05 Hz, ±0.01 m) pour donner une
 * vie subtile sans charger d'animation complète. Phase 2.5 branchera le
 * vrai idle depuis `payload.idle_animation`.
 */
import { useEffect, useRef } from "react";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls";
import { TransformControls } from "three/examples/jsm/controls/TransformControls";
import { VRMLoaderPlugin } from "@pixiv/three-vrm";
import type { VRM } from "@pixiv/three-vrm";
import type { GizmoMode, Vec3 } from "./types";

export type ViewMode = "preview" | "edit";

type Props = {
  vrmUrl: string;
  viewMode: ViewMode;
  gizmoMode: GizmoMode;
  avatarPosition: Vec3;
  avatarRotationY: number;
  sceneCamera: Vec3;
  sceneLookAt: Vec3;
  sceneFov: number;
  onAvatarTransformChange: (pos: Vec3, rotY: number) => void;
};

export function SceneEditorViewer({
  vrmUrl,
  viewMode, gizmoMode,
  avatarPosition, avatarRotationY,
  sceneCamera, sceneLookAt, sceneFov,
  onAvatarTransformChange,
}: Props) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  // Three.js refs — construits une seule fois au mount.
  const sceneRef = useRef<THREE.Scene | null>(null);
  const rendererRef = useRef<THREE.WebGLRenderer | null>(null);
  // Deux caméras : la "scene camera" (utilisée en mode preview) et la
  // "user camera" pilotée par OrbitControls (utilisée en mode edit).
  const sceneCamRef = useRef<THREE.PerspectiveCamera | null>(null);
  const userCamRef = useRef<THREE.PerspectiveCamera | null>(null);
  const orbitRef = useRef<OrbitControls | null>(null);
  const gizmoRef = useRef<TransformControls | null>(null);
  const vrmRef = useRef<VRM | null>(null);
  const gridRef = useRef<THREE.GridHelper | null>(null);
  const axesRef = useRef<THREE.AxesHelper | null>(null);
  const camHelperRef = useRef<THREE.CameraHelper | null>(null);
  const rafRef = useRef<number | null>(null);
  const clockRef = useRef(new THREE.Clock());

  // Ref latest props pour que les listeners (gizmo change) lisent le
  // callback à jour sans re-subscribe.
  const onChangeRef = useRef(onAvatarTransformChange);
  onChangeRef.current = onAvatarTransformChange;
  const viewModeRef = useRef(viewMode);
  viewModeRef.current = viewMode;
  // Latest refs pour la position/rotation — lues par le tick() et le VRM load
  // callback (tous deux capturés en closure par le useEffect mount `deps: []`).
  // Sans ces refs, la render loop écraserait position.y avec la valeur du mount
  // (= breathing frozen sur valeur initiale) et le load async appliquerait la
  // mauvaise pose si l'utilisateur a changé de scene avant que le VRM charge.
  const avatarPositionRef = useRef(avatarPosition);
  avatarPositionRef.current = avatarPosition;
  const avatarRotationYRef = useRef(avatarRotationY);
  avatarRotationYRef.current = avatarRotationY;

  // ─── Setup one-shot (mount) ────────────────────────────────────
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    // Token d'annulation pour le VRM load async — en StrictMode (dev) le
    // useEffect run 2× et le callback du loader peut résoudre après cleanup.
    let cancelled = false;
    const parent = canvas.parentElement;
    const w = parent?.clientWidth || 800;
    const h = parent?.clientHeight || 600;

    const scene = new THREE.Scene();
    scene.background = null;
    sceneRef.current = scene;

    // Lights — soft + une directionnelle pour donner du volume.
    scene.add(new THREE.AmbientLight(0xffffff, 0.55));
    const dir = new THREE.DirectionalLight(0xffffff, 0.8);
    dir.position.set(1, 2, 1).normalize();
    scene.add(dir);

    // Caméras
    const sceneCam = new THREE.PerspectiveCamera(sceneFov, w / h, 0.05, 50);
    sceneCam.position.set(sceneCamera.x, sceneCamera.y, sceneCamera.z);
    sceneCam.lookAt(sceneLookAt.x, sceneLookAt.y, sceneLookAt.z);
    sceneCamRef.current = sceneCam;

    const userCam = new THREE.PerspectiveCamera(35, w / h, 0.05, 50);
    userCam.position.set(2, 1.8, 2.4);
    userCamRef.current = userCam;

    // Helpers (edit mode only — visibles via viewMode effect ci-dessous)
    const grid = new THREE.GridHelper(4, 8, 0xe08efe, 0x2a2a3c);
    grid.visible = false;
    scene.add(grid);
    gridRef.current = grid;

    const axes = new THREE.AxesHelper(0.6);
    axes.visible = false;
    scene.add(axes);
    axesRef.current = axes;

    const camHelper = new THREE.CameraHelper(sceneCam);
    (camHelper.material as THREE.LineBasicMaterial).color = new THREE.Color(0x81ecff);
    (camHelper.material as THREE.LineBasicMaterial).opacity = 0.55;
    (camHelper.material as THREE.LineBasicMaterial).transparent = true;
    camHelper.visible = false;
    scene.add(camHelper);
    camHelperRef.current = camHelper;

    // Renderer
    const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
    renderer.outputEncoding = THREE.sRGBEncoding;
    renderer.setPixelRatio(window.devicePixelRatio);
    renderer.setSize(w, h);
    rendererRef.current = renderer;

    // OrbitControls (user cam) — désactivé par défaut, activé en mode edit.
    const orbit = new OrbitControls(userCam, renderer.domElement);
    orbit.target.set(0, 1.2, 0);
    orbit.enableDamping = true;
    orbit.dampingFactor = 0.1;
    orbit.enabled = false;
    orbitRef.current = orbit;

    // TransformControls — attaché plus tard quand le VRM est chargé.
    const gizmo = new TransformControls(userCam, renderer.domElement);
    gizmo.setMode("translate");
    gizmo.visible = false;
    gizmo.enabled = false;
    gizmoRef.current = gizmo;
    gizmo.addEventListener("dragging-changed", (e) => {
      if (orbitRef.current) orbitRef.current.enabled = !e.value;
    });
    gizmo.addEventListener("change", () => {
      const v = vrmRef.current;
      if (!v) return;
      const p = v.scene.position;
      onChangeRef.current(
        { x: p.x, y: p.y, z: p.z },
        v.scene.rotation.y,
      );
    });
    scene.add(gizmo as unknown as THREE.Object3D);

    // Resize
    const onResize = () => {
      const el = rendererRef.current?.domElement.parentElement;
      if (!el) return;
      rendererRef.current?.setSize(el.clientWidth, el.clientHeight);
      const aspect = el.clientWidth / el.clientHeight;
      if (sceneCamRef.current) {
        sceneCamRef.current.aspect = aspect;
        sceneCamRef.current.updateProjectionMatrix();
      }
      if (userCamRef.current) {
        userCamRef.current.aspect = aspect;
        userCamRef.current.updateProjectionMatrix();
      }
    };
    window.addEventListener("resize", onResize);

    // Charge le VRM.
    const loader = new GLTFLoader();
    loader.register((parser) => new VRMLoaderPlugin(parser));
    loader.load(
      vrmUrl,
      (gltf) => {
        if (cancelled) return;
        const vrm = gltf.userData.vrm as VRM | undefined;
        if (!vrm) return;
        vrmRef.current = vrm;
        vrm.scene.traverse((obj) => { obj.frustumCulled = false; });
        // Lit depuis les refs pour appliquer la pose à jour (pas celle figée
        // par closure au mount).
        const p = avatarPositionRef.current;
        vrm.scene.position.set(p.x, p.y, p.z);
        vrm.scene.rotation.y = avatarRotationYRef.current;
        // sceneRef.current au lieu de la closure locale `scene` pour résister
        // au StrictMode double-mount (scene locale peut avoir été disposée).
        sceneRef.current?.add(vrm.scene);
        // Attache le gizmo (il restera invisible tant qu'on n'est pas en edit mode).
        gizmoRef.current?.attach(vrm.scene);
      },
      (ev) => {
        if (!cancelled) {
          console.log("[SceneEditorViewer] VRM loading:", ev.loaded, "/", ev.total);
        }
      },
      (err) => console.error("[SceneEditorViewer] VRM load failed:", err),
    );

    // Render loop — utilise la caméra active selon viewMode.
    const tick = () => {
      rafRef.current = requestAnimationFrame(tick);
      const dt = clockRef.current.getDelta();
      // Breathing subtil sur le VRM pour éviter le T-pose mort.
      const v = vrmRef.current;
      if (v) {
        v.update(dt);
        const t = clockRef.current.elapsedTime;
        // Lit depuis le ref pour suivre les changements de slider Y en live —
        // sans ça, la closure fige la valeur du mount et l'utilisateur voit
        // le VRM coincé à Y initial + breathing, même si le useEffect sync
        // applique la nouvelle valeur (elle est écrasée 60 fps).
        v.scene.position.y =
          avatarPositionRef.current.y + Math.sin(t * 1.2) * 0.004;
      }
      // Update controls + render
      orbitRef.current?.update();
      camHelperRef.current?.update();
      const activeCam = viewModeRef.current === "edit"
        ? userCamRef.current
        : sceneCamRef.current;
      const r = rendererRef.current;
      const s = sceneRef.current;
      if (r && s && activeCam) r.render(s, activeCam);
    };
    tick();

    return () => {
      // Annule le callback async du loader : si le VRM finit de charger
      // après le cleanup, on évite d'ajouter à une scene disposée et de
      // polluer vrmRef avec un objet orphelin.
      cancelled = true;
      window.removeEventListener("resize", onResize);
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
      gizmoRef.current?.detach();
      gizmoRef.current?.dispose();
      orbitRef.current?.dispose();
      // Phase F Hardening M2 — dispose des helpers Three.js (Grid / Axes /
      // CameraHelper). Le cleanup historique disposait renderer / orbit /
      // gizmo / VRM mais laissait fuir les helpers ci-dessous. Phase F
      // monte le viewer 2× simultanés (SceneView + GameView) → leak
      // doublé. Ordre : dispose AVANT renderer.dispose() pour libérer les
      // buffers GL avant que le contexte soit perdu.
      //
      // GridHelper et AxesHelper exposent `geometry` + `material` (LineSegments).
      // CameraHelper expose pareil mais sa material est un LineBasicMaterial
      // unique partagé sur tous les segments.
      const grid = gridRef.current;
      if (grid) {
        grid.geometry.dispose();
        const gridMat = grid.material;
        if (Array.isArray(gridMat)) gridMat.forEach((m) => m.dispose());
        else (gridMat as THREE.Material).dispose();
      }
      const axes = axesRef.current;
      if (axes) {
        axes.geometry.dispose();
        const axesMat = axes.material;
        if (Array.isArray(axesMat)) axesMat.forEach((m) => m.dispose());
        else (axesMat as THREE.Material).dispose();
      }
      const camHelper = camHelperRef.current;
      if (camHelper) {
        camHelper.geometry.dispose();
        const camMat = camHelper.material;
        if (Array.isArray(camMat)) camMat.forEach((m) => m.dispose());
        else (camMat as THREE.Material).dispose();
      }
      gridRef.current = null;
      axesRef.current = null;
      camHelperRef.current = null;
      rendererRef.current?.dispose();
      const v = vrmRef.current;
      if (v) {
        v.scene.traverse((obj) => {
          const mesh = obj as THREE.Mesh;
          if (mesh.geometry) mesh.geometry.dispose();
          const mat = mesh.material;
          if (Array.isArray(mat)) mat.forEach((m) => m.dispose());
          else if (mat) (mat as THREE.Material).dispose();
        });
      }
      vrmRef.current = null;
      sceneRef.current = null;
      rendererRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ─── Props sync ────────────────────────────────────────────────

  // ViewMode → montre/cache helpers, active/désactive contrôles.
  useEffect(() => {
    const isEdit = viewMode === "edit";
    if (gridRef.current) gridRef.current.visible = isEdit;
    if (axesRef.current) axesRef.current.visible = isEdit;
    if (camHelperRef.current) camHelperRef.current.visible = isEdit;
    if (orbitRef.current) orbitRef.current.enabled = isEdit;
    const g = gizmoRef.current;
    if (g) {
      g.visible = isEdit;
      g.enabled = isEdit;
    }
  }, [viewMode]);

  // Gizmo mode
  useEffect(() => {
    gizmoRef.current?.setMode(gizmoMode);
  }, [gizmoMode]);

  // Avatar position (inspector → VRM). Ignore pendant un drag gizmo.
  useEffect(() => {
    const v = vrmRef.current;
    const g = gizmoRef.current;
    if (!v) return;
    if (g?.dragging) return;
    v.scene.position.set(avatarPosition.x, avatarPosition.y, avatarPosition.z);
  }, [avatarPosition.x, avatarPosition.y, avatarPosition.z]);

  useEffect(() => {
    const v = vrmRef.current;
    const g = gizmoRef.current;
    if (!v) return;
    if (g?.dragging) return;
    v.scene.rotation.y = avatarRotationY;
  }, [avatarRotationY]);

  // Scene camera live — en mode preview, c'est la caméra du canvas.
  useEffect(() => {
    const sc = sceneCamRef.current;
    if (!sc) return;
    sc.position.set(sceneCamera.x, sceneCamera.y, sceneCamera.z);
    sc.lookAt(sceneLookAt.x, sceneLookAt.y, sceneLookAt.z);
    sc.fov = sceneFov;
    sc.updateProjectionMatrix();
    camHelperRef.current?.update();
  }, [sceneCamera.x, sceneCamera.y, sceneCamera.z,
      sceneLookAt.x, sceneLookAt.y, sceneLookAt.z, sceneFov]);

  return (
    <canvas
      ref={canvasRef}
      style={{ display: "block", width: "100%", height: "100%" }}
    />
  );
}
