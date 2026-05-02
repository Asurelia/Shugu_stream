import { useContext, useCallback, useEffect, useRef } from "react";
import { ViewerContext } from "../features/vrmViewer/viewerContext";
import { buildUrl } from "@/utils/buildUrl";

type Props = {
  onLoaded?: () => void;
};

export default function VrmViewer({ onLoaded }: Props) {
  const { viewer } = useContext(ViewerContext);

  // Stable reference to onLoaded — avoids ref callback invalidation on parent re-renders.
  const onLoadedRef = useRef(onLoaded);

  // Sync ref mirror after each commit (no dep array → runs after every render).
  useEffect(() => {
    onLoadedRef.current = onLoaded;
  });

  // Guard: only run setup() + loadVrm() once per canvas element. Prevents multiple
  // requestAnimationFrame loops (which were causing stutter) and duplicate 28 MB downloads.
  const initializedRef = useRef<HTMLCanvasElement | null>(null);

  const AVATAR_URL = "/shugu_avatar.vrm";

  const canvasRef = useCallback(
    (canvas: HTMLCanvasElement | null) => {
      if (!canvas) return;
      if (initializedRef.current === canvas) return;
      initializedRef.current = canvas;

      viewer.setup(canvas);
      viewer
        .loadVrm(buildUrl(AVATAR_URL))
        .then(() => onLoadedRef.current?.())
        .catch((err) => console.error("VRM load failed:", err));
      // No drag-and-drop VRM replacement on the live — a visitor swapping Shugu's
      // body mid-stream is obviously not the intended UX.
    },
    [viewer]     // stable (context singleton) — ref no longer re-attaches on parent render
  );

  return (
    <div className={"absolute top-0 left-0 w-screen h-[100svh] -z-10"}>
      <canvas ref={canvasRef} className={"h-full w-full"}></canvas>
    </div>
  );
}
