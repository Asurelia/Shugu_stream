/**
 * A soft pulsed ring centered around where Shugu's head typically sits in the
 * frame. Only visible while she speaks.
 *
 * Positioned absolutely over the canvas zone (canvas fills the viewport, so we
 * use a fixed-position ring at a known screen spot).
 */
export function SpeakingRing({ visible }: { visible: boolean }) {
  if (!visible) return null;
  return (
    <div
      className="pointer-events-none fixed z-[5] left-1/2 top-[38%] -translate-x-1/2 -translate-y-1/2"
      aria-hidden
    >
      <div
        className="w-[260px] h-[260px] sm:w-[340px] sm:h-[340px] rounded-full animate-pulse"
        style={{
          background:
            "radial-gradient(circle, rgba(255,143,165,0.0) 48%, rgba(255,143,165,0.25) 60%, rgba(216,180,254,0.0) 80%)",
          filter: "blur(8px)",
        }}
      />
    </div>
  );
}
