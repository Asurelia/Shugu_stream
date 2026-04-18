export function Brand() {
  return (
    <div className="fixed top-4 left-4 z-20 select-none pointer-events-none">
      <div
        className="font-comfortaa font-bold text-lg sm:text-xl text-shugu-cream flex items-center gap-1 sm:gap-1.5"
        style={{ textShadow: "0 2px 10px rgba(255, 97, 127, 0.45)" }}
      >
        <span className="text-shugu-pink text-base sm:text-lg">🌸</span>
        <span className="bg-gradient-to-r from-shugu-pink-soft via-shugu-cream to-shugu-lavender bg-clip-text text-transparent">
          Shugu
        </span>
      </div>
      <div className="hidden sm:block text-shugu-cream-dim text-[10px] mt-0.5 tracking-wide">
        ♡ AI VTuber live
      </div>
    </div>
  );
}
