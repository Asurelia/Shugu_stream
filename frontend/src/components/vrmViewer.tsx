import { useContext, useCallback, useEffect, useRef, useState } from "react";
import { ViewerContext } from "../features/vrmViewer/viewerContext";
import { buildUrl } from "@/utils/buildUrl";
import { LoadingScreen } from "./LoadingScreen";

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

  // U4 audit: track load progress and error state so users see feedback instead
  // of an infinite spinner when the VRM is loading slowly or fails.
  const [progress, setProgress] = useState<number>(0);
  const [error, setError] = useState<Error | null>(null);
  // When false, the loading overlay is shown. Flipped to true once loadVrm resolves.
  const [loaded, setLoaded] = useState(false);

  const AVATAR_URL = "/shugu_avatar.vrm";

  // Extracted load function so retry can call it directly without re-running
  // viewer.setup() — the canvas and renderer are already initialised.
  const doLoad = useCallback(
    (url: string) => {
      setProgress(0);
      setError(null);
      viewer
        .loadVrm(url, {
          onProgress: (loaded: number, total: number) => {
            // total is 0 when Content-Length is absent; show indeterminate in that case.
            if (total > 0) {
              setProgress(loaded / total);
            }
          },
          onError: (err: Error) => {
            setError(err);
          },
        })
        .then(() => {
          setProgress(1);
          setLoaded(true);
          onLoadedRef.current?.();
        })
        .catch((err: unknown) => {
          const error = err instanceof Error ? err : new Error(String(err));
          setError(error);
        });
    },
    [viewer],
  );

  const canvasRef = useCallback(
    (canvas: HTMLCanvasElement | null) => {
      if (!canvas) return;
      if (initializedRef.current === canvas) return;
      initializedRef.current = canvas;

      viewer.setup(canvas);
      doLoad(buildUrl(AVATAR_URL));
      // No drag-and-drop VRM replacement on the live — a visitor swapping Shugu's
      // body mid-stream is obviously not the intended UX.
    },
    [viewer, doLoad],
  );

  const retry = useCallback(() => {
    doLoad(buildUrl(AVATAR_URL));
  }, [doLoad]);

  return (
    <div className={"absolute top-0 left-0 w-screen h-[100svh] -z-10"}>
      <canvas ref={canvasRef} className={"h-full w-full"}></canvas>
      {!loaded && (
        <LoadingScreen
          progress={progress}
          error={error}
          onRetry={retry}
        />
      )}
    </div>
  );
}
