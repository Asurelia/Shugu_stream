type Props = {
  /**
   * Load progress in [0, 1]. When undefined or 0, an indeterminate spinner is
   * shown instead of a bar (server may not send Content-Length).
   */
  progress?: number;
  /** Non-null when the VRM load failed. Shows an error state with a retry CTA. */
  error?: Error | null;
  /** Called when the user clicks the "Réessayer" button. */
  onRetry?: () => void;
};

export function LoadingScreen({ progress, error, onRetry }: Props = {}) {
  const pct = progress != null ? Math.round(progress * 100) : null;
  // Show a determinate bar only when we have reliable byte counts (>0 and
  // the server reported Content-Length → progress is meaningfully >0 after first chunk).
  const hasDeterminate = pct != null && pct > 0;

  if (error) {
    return (
      <div className="fixed inset-0 z-40 flex items-center justify-center bg-shugu-ink/80">
        <div
          className="text-center font-quicksand text-shugu-cream px-6 max-w-sm"
          role="alert"
          aria-live="assertive"
        >
          <div className="mb-4 text-3xl" aria-hidden="true">⚠️</div>
          <div className="text-lg sm:text-xl font-semibold text-shugu-pink-soft mb-2">
            Impossible de charger Shugu
          </div>
          <div className="text-xs sm:text-sm text-shugu-cream-dim mb-5 break-words">
            {error.message || "Une erreur est survenue lors du chargement du modèle."}
          </div>
          {onRetry && (
            <button
              onClick={onRetry}
              className="rounded-full border border-shugu-pink/60 bg-shugu-pink/20 px-6 py-2 text-sm font-semibold text-shugu-pink-soft hover:bg-shugu-pink/40 transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-shugu-pink"
              aria-label="Réessayer le chargement"
            >
              Réessayer
            </button>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-shugu-ink/80">
      <div
        className="text-center font-quicksand text-shugu-cream"
        role="status"
        aria-label={hasDeterminate ? `Chargement ${pct}%` : "Chargement en cours"}
        aria-live="polite"
      >
        {/* Indeterminate spinner — shown when Content-Length is absent (pct === 0 or null) */}
        {!hasDeterminate && (
          <div
            className="mx-auto mb-5 w-14 h-14 rounded-full border-4 border-shugu-pink-soft/30 border-t-shugu-pink animate-spin"
            aria-hidden="true"
          />
        )}

        {/* Determinate progress bar — shown when byte progress is known */}
        {hasDeterminate && (
          <div className="mx-auto mb-5 w-48" aria-hidden="true">
            <div className="h-1.5 w-full rounded-full bg-shugu-pink-soft/20 overflow-hidden">
              <div
                className="h-full rounded-full bg-shugu-pink transition-all duration-200 ease-out"
                style={{ width: `${pct}%` }}
              />
            </div>
          </div>
        )}

        <div className="text-lg sm:text-xl font-semibold text-shugu-pink-soft">
          Shugu se reveille…
        </div>
        <div className="text-xs sm:text-sm text-shugu-cream-dim mt-1">
          {hasDeterminate ? `${pct}%` : "~28 Mo, quelques secondes"}
        </div>
      </div>
    </div>
  );
}
