import Link from "next/link";

/**
 * Discreet login button shown in the top-right corner when no operator is
 * currently authenticated. Logged-in users see the OperatorPanel instead.
 */
export function VisitorLogin() {
  return (
    <Link
      href="/login"
      className="fixed top-4 right-4 md:right-[340px] z-20 text-[11px] text-shugu-cream-dim hover:text-shugu-pink-soft underline-offset-2 hover:underline font-quicksand transition-colors"
    >
      login ♡
    </Link>
  );
}
