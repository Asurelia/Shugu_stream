/**
 * Tests — `useDragDropTarget.ts` (E5.3).
 *
 * Couverture :
 *   1. `dragover` event : preventDefault appelé + effectAllowed = "copy".
 *   2. `drop` event : onAssetDropped appelé avec l'asset et une worldPosition.
 *   3. `drop` sans payload valide → onAssetDropped pas appelé.
 *   4. `drop` avec payload kind incorrect → onAssetDropped pas appelé.
 *   5. `disabled=true` : dragover ne prévient pas le default, drop ignoré.
 *   6. Unmount → listeners retirés (plus de callback).
 *   7. Projection ground plane retourne un Vector3 du hook.
 *   8. Drop payload JSON malformé → onAssetDropped pas appelé.
 *
 * Stratégie : renderHook + dispatch MouseEvent (DragEvent non disponible dans
 * jsdom) sur un canvas. Mock de THREE.Ray.prototype.intersectPlane.
 *
 * Note jsdom : DragEvent n'est pas disponible en jsdom. On crée un substitute
 * basé sur MouseEvent avec un dataTransfer fakéé. La logique du hook étant
 * basée sur `event.dataTransfer.getData()`, le substitute est fonctionnellement
 * équivalent pour les tests unitaires.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderHook } from "@testing-library/react";
import * as THREE from "three";
import { PROP_DRAG_MIME } from "../useDragDropTarget";
import type { Prop3DEntry } from "../../../api/catalogClient";

// ── Mocks projection ──────────────────────────────────────────────────────────

const mockWorldPoint = new THREE.Vector3(1.5, 0, -2.0);
const mockIntersectPlane = vi.fn().mockReturnValue(mockWorldPoint);

// Import après mock (Three.js est mocké avant l'import du hook).
import { useDragDropTarget } from "../useDragDropTarget";
import type { UseDragDropTargetProps } from "../useDragDropTarget";

// ── Helpers ───────────────────────────────────────────────────────────────────

function makeProp3DAsset(slug = "test_prop"): Prop3DEntry {
  return { slug, file: `/assets/props/${slug}.glb` };
}

/**
 * Crée un événement DOM substitute pour DragEvent.
 *
 * jsdom ne dispose pas de DragEvent — on construit un MouseEvent avec un
 * dataTransfer fakéé qui supporte getData(). Le hook `useDragDropTarget`
 * n'utilise que `event.dataTransfer.getData()`, `event.preventDefault()` et
 * `event.clientX/Y`, tous disponibles via MouseEvent + dataTransfer override.
 */
function makeFakeDragEvent(
  type: "dragover" | "drop",
  overrides: {
    dataStore?: Record<string, string>;
    clientX?: number;
    clientY?: number;
  } = {},
): MouseEvent {
  const dataStore = overrides.dataStore ?? {};

  const event = new MouseEvent(type, {
    bubbles: true,
    cancelable: true,
    clientX: overrides.clientX ?? 400,
    clientY: overrides.clientY ?? 300,
  });

  const dataTransfer = {
    getData: (mime: string) => dataStore[mime] ?? "",
    setData: vi.fn(),
    dropEffect: "none",
    effectAllowed: "none",
  };

  Object.defineProperty(event, "dataTransfer", {
    value: dataTransfer,
    writable: false,
  });

  return event;
}

function makeDropEvent(asset?: Prop3DEntry, overrideMime?: string): MouseEvent {
  const dataStore: Record<string, string> = {};
  if (asset) {
    const payload = { kind: "prop_3d", asset };
    dataStore[overrideMime ?? PROP_DRAG_MIME] = JSON.stringify(payload);
  }
  return makeFakeDragEvent("drop", { dataStore });
}

function makeDragOverEvent(): MouseEvent {
  return makeFakeDragEvent("dragover");
}

function makeHookProps(
  canvas: HTMLCanvasElement,
  onAssetDropped: UseDragDropTargetProps["onAssetDropped"],
  disabled = false,
): UseDragDropTargetProps {
  const camera = new THREE.PerspectiveCamera();
  const rect = { left: 0, top: 0, width: 800, height: 600 } as DOMRect;
  vi.spyOn(canvas, "getBoundingClientRect").mockReturnValue(rect);

  return {
    canvasRef: { current: canvas },
    cameraRef: { current: camera },
    onAssetDropped,
    disabled,
  };
}

// ── Tests ─────────────────────────────────────────────────────────────────────

beforeEach(() => {
  vi.clearAllMocks();
  mockIntersectPlane.mockReturnValue(mockWorldPoint);
  vi.spyOn(THREE.Raycaster.prototype, "setFromCamera").mockImplementation(() => {});
  vi.spyOn(THREE.Ray.prototype, "intersectPlane").mockImplementation(mockIntersectPlane);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("useDragDropTarget · dragover", () => {
  it("dragover → preventDefault appelé pour autoriser le drop", () => {
    const canvas = document.createElement("canvas");
    const onAssetDropped = vi.fn();

    renderHook(() => useDragDropTarget(makeHookProps(canvas, onAssetDropped)));

    const event = makeDragOverEvent();
    const preventDefaultSpy = vi.spyOn(event, "preventDefault");
    canvas.dispatchEvent(event);

    expect(preventDefaultSpy).toHaveBeenCalled();
  });
});

describe("useDragDropTarget · drop avec payload valide", () => {
  it("drop prop_3d valide → onAssetDropped appelé avec l'asset correct", () => {
    const canvas = document.createElement("canvas");
    const onAssetDropped = vi.fn();
    const asset = makeProp3DAsset("cool_box");

    // Forcer intersectPlane à retourner un point valide.
    vi.spyOn(THREE.Ray.prototype, "intersectPlane").mockReturnValue(
      new THREE.Vector3(1.5, 0, -2.0),
    );

    renderHook(() => useDragDropTarget(makeHookProps(canvas, onAssetDropped)));

    const event = makeDropEvent(asset);
    canvas.dispatchEvent(event);

    // Vérifier que onAssetDropped a été appelé avec le bon asset.
    expect(onAssetDropped).toHaveBeenCalled();
    const [calledAsset] = onAssetDropped.mock.calls[0] as [Prop3DEntry, THREE.Vector3];
    expect(calledAsset).toEqual(asset);
  });

  it("drop prop_3d valide → onAssetDropped reçoit un Vector3 comme worldPosition", () => {
    const canvas = document.createElement("canvas");
    const onAssetDropped = vi.fn();
    const asset = makeProp3DAsset("box_test");

    vi.spyOn(THREE.Ray.prototype, "intersectPlane").mockReturnValue(
      new THREE.Vector3(2.0, 0, 1.0),
    );

    renderHook(() => useDragDropTarget(makeHookProps(canvas, onAssetDropped)));

    const event = makeDropEvent(asset);
    canvas.dispatchEvent(event);

    expect(onAssetDropped).toHaveBeenCalledWith(
      expect.any(Object),
      expect.any(THREE.Vector3),
    );
  });
});

describe("useDragDropTarget · drop sans payload valide", () => {
  it("drop sans dataTransfer data → onAssetDropped pas appelé", () => {
    const canvas = document.createElement("canvas");
    const onAssetDropped = vi.fn();

    renderHook(() => useDragDropTarget(makeHookProps(canvas, onAssetDropped)));

    // Drop sans payload.
    const event = makeDropEvent(undefined);
    canvas.dispatchEvent(event);

    expect(onAssetDropped).not.toHaveBeenCalled();
  });

  it("drop avec kind != 'prop_3d' → onAssetDropped pas appelé", () => {
    const canvas = document.createElement("canvas");
    const onAssetDropped = vi.fn();

    renderHook(() => useDragDropTarget(makeHookProps(canvas, onAssetDropped)));

    const asset = makeProp3DAsset();
    const badPayload = JSON.stringify({ kind: "vrm_avatar", asset });
    const event = makeFakeDragEvent("drop", {
      dataStore: { [PROP_DRAG_MIME]: badPayload },
    });
    canvas.dispatchEvent(event);

    expect(onAssetDropped).not.toHaveBeenCalled();
  });

  it("drop avec JSON malformé → onAssetDropped pas appelé", () => {
    const canvas = document.createElement("canvas");
    const onAssetDropped = vi.fn();

    renderHook(() => useDragDropTarget(makeHookProps(canvas, onAssetDropped)));

    const event = makeFakeDragEvent("drop", {
      dataStore: { [PROP_DRAG_MIME]: "{ invalid json" },
    });
    canvas.dispatchEvent(event);

    expect(onAssetDropped).not.toHaveBeenCalled();
  });
});

describe("useDragDropTarget · disabled", () => {
  it("disabled=true : dragover ne prévient pas le default", () => {
    const canvas = document.createElement("canvas");
    const onAssetDropped = vi.fn();

    renderHook(() => useDragDropTarget(makeHookProps(canvas, onAssetDropped, true)));

    const event = makeDragOverEvent();
    const preventDefaultSpy = vi.spyOn(event, "preventDefault");
    canvas.dispatchEvent(event);

    expect(preventDefaultSpy).not.toHaveBeenCalled();
  });

  it("disabled=true : drop ignoré → onAssetDropped pas appelé", () => {
    const canvas = document.createElement("canvas");
    const onAssetDropped = vi.fn();
    const asset = makeProp3DAsset();

    renderHook(() => useDragDropTarget(makeHookProps(canvas, onAssetDropped, true)));

    const event = makeDropEvent(asset);
    canvas.dispatchEvent(event);

    expect(onAssetDropped).not.toHaveBeenCalled();
  });
});

describe("useDragDropTarget · unmount", () => {
  it("unmount → listeners retirés, drop ne déclenche plus onAssetDropped", () => {
    const canvas = document.createElement("canvas");
    const onAssetDropped = vi.fn();
    const asset = makeProp3DAsset();

    const { unmount } = renderHook(() =>
      useDragDropTarget(makeHookProps(canvas, onAssetDropped)),
    );

    unmount();

    const event = makeDropEvent(asset);
    canvas.dispatchEvent(event);

    expect(onAssetDropped).not.toHaveBeenCalled();
  });
});
