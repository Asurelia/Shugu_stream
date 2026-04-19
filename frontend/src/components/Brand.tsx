export function Brand() {
  return (
    <div className="fixed top-4 left-4 z-20 select-none pointer-events-none">
      <div
        className="veil-headline text-xl sm:text-2xl text-shugu-cream flex items-center gap-1.5 sm:gap-2"
        style={{ textShadow: "0 2px 14px rgba(224, 142, 254, 0.55)" }}
      >
        <span className="text-veil-primary text-base sm:text-lg animate-veil-pulse-glow rounded-full">✦</span>
        <span className="bg-gradient-to-r from-veil-primary via-veil-tertiary to-veil-primary-container bg-clip-text text-transparent">
          Shugu
        </span>
      </div>
      <div className="hidden sm:block veil-body text-veil-on-surface-variant text-[10px] mt-0.5 tracking-[0.15em] uppercase">
        AI VTuber · live
      </div>
    </div>
  );
}
