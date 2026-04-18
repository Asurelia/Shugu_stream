export function LoadingScreen() {
  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-shugu-ink/80">
      <div className="text-center font-quicksand text-shugu-cream">
        <div className="mx-auto mb-5 w-14 h-14 rounded-full border-4 border-shugu-pink-soft/30 border-t-shugu-pink animate-spin" />
        <div className="text-lg sm:text-xl font-semibold text-shugu-pink-soft">
          🌸 Shugu se réveille…
        </div>
        <div className="text-xs sm:text-sm text-shugu-cream-dim mt-1">
          ~28 Mo, quelques secondes ✨
        </div>
      </div>
    </div>
  );
}
