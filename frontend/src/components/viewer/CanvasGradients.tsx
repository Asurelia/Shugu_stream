/**
 * Deux dégradés sombres superposés sur le canvas VRM pour garantir la
 * lisibilité des overlays HUD. Posés à z:1 (au-dessus du canvas, sous les
 * autres overlays). `chatOpen` → les gradients s'arrêtent au rail chat
 * (marge 16px + rail 360px + marge 16px = 392px depuis le bord droit quand
 * le rail est ouvert), sinon fullscreen.
 */

type Props = { chatOpen: boolean };

export function CanvasGradients({ chatOpen }: Props) {
  const rightOffset = chatOpen ? 392 : 0;
  const transition = "right 0.45s cubic-bezier(0.5, 1.5, 0.5, 1)";
  return (
    <>
      <div
        className="pointer-events-none fixed top-0 bottom-0 left-0 hidden md:block"
        style={{
          right: rightOffset, zIndex: 1, transition,
          background: "linear-gradient(180deg, rgba(8,8,16,0.6) 0%, transparent 30%, transparent 60%, rgba(8,8,16,0.85) 100%)",
        }}
        aria-hidden
      />
      <div
        className="pointer-events-none fixed top-0 bottom-0 left-0 hidden md:block"
        style={{
          right: rightOffset, zIndex: 1, transition,
          background: "linear-gradient(90deg, rgba(8,8,16,0.4) 0%, transparent 30%, transparent 70%, rgba(8,8,16,0.5) 100%)",
        }}
        aria-hidden
      />
      <div
        className="pointer-events-none fixed inset-0 md:hidden"
        style={{
          zIndex: 1,
          background: "linear-gradient(180deg, rgba(8,8,16,0.6) 0%, transparent 30%, transparent 60%, rgba(8,8,16,0.85) 100%)",
        }}
        aria-hidden
      />
    </>
  );
}
