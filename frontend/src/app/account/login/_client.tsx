"use client";

/**
 * /account/login client island — unified auth entry (AUTH-1 sprint).
 *
 * Calls POST /auth/login (unified endpoint) instead of /api/account/login.
 * The unified endpoint handles both operator and member accounts:
 *
 *   - is_operator=true  → dual cookies set (shugu_access + shugu_user_access)
 *                         → redirect to / (root activates voiceWiringActive)
 *   - is_operator=false → user cookie only (shugu_user_access)
 *                         → redirect to /account/profile
 *
 * This is the single canonical login entry point for all users.
 * The /login page redirects here.
 *
 * Error handling:
 *   - 403 "verify email first" → show resend verification CTA
 *   - 401 "invalid credentials" → show generic error
 *   - 429 rate limit → show rate limit message
 */
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { GlassButton, GlassCard, GlassInput } from "@/features/liquid-glass/primitives";
import { login } from "@/services/shuguClient";

export function LoginClient() {
  const router = useRouter();
  const [usernameOrEmail, setUsernameOrEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [resendState, setResendState] = useState<"idle" | "sent" | "error">("idle");

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const { data, error: loginError } = await login(usernameOrEmail, password);
      if (loginError || !data) {
        setError(loginError ?? "Erreur réseau inattendue.");
        return;
      }
      // AUTH-1: route based on is_operator flag from unified response.
      if (data.is_operator) {
        // Operator: dual cookies are set (shugu_access + shugu_user_access).
        // Redirect to root which activates voiceWiringActive via /auth/me.
        router.replace("/");
      } else {
        // Regular member/VIP: only shugu_user_access cookie set.
        router.replace("/account/profile");
      }
    } catch {
      setError("Erreur réseau inattendue.");
    } finally {
      setLoading(false);
    }
  };

  const onResend = async () => {
    if (!usernameOrEmail.includes("@")) {
      setError("Tape ton email pour qu'on te renvoie le lien.");
      return;
    }
    try {
      const r = await fetch("/api/account/resend-verify", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ email: usernameOrEmail }),
      });
      if (!r.ok) {
        setResendState("error");
      } else {
        setResendState("sent");
        setError(null);
      }
    } catch {
      setResendState("error");
    }
  };

  return (
    <div className="lg-page min-h-screen flex items-center justify-center p-6">
      <GlassCard className="max-w-md w-full" padded>
        <h1 className="text-2xl font-light tracking-tight text-shugu-cream mb-1">
          Bon retour
        </h1>
        <p className="text-sm opacity-60 mb-6">
          Connecte-toi avec ton pseudo ou ton email.
        </p>
        <form onSubmit={onSubmit} className="space-y-4">
          <label className="block">
            <span className="text-xs opacity-70 mb-1 block">Pseudo ou email</span>
            <GlassInput
              type="text"
              value={usernameOrEmail}
              onChange={(e) => setUsernameOrEmail(e.target.value)}
              required
              autoComplete="username"
              autoFocus
            />
          </label>
          <label className="block">
            <span className="text-xs opacity-70 mb-1 block">Mot de passe</span>
            <GlassInput
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              autoComplete="current-password"
            />
          </label>
          {error && (
            <div className="p-3 rounded-xl bg-rose-500/10 border border-rose-500/30 text-sm text-rose-100">
              {error}
              {error.toLowerCase().includes("verify email") && (
                <button
                  type="button"
                  onClick={onResend}
                  className="mt-2 underline text-xs block"
                >
                  Renvoyer le lien de vérification
                </button>
              )}
            </div>
          )}
          {resendState === "sent" && (
            <div className="p-3 rounded-xl bg-emerald-500/10 border border-emerald-500/30 text-sm text-emerald-100">
              Si ton compte existe, un email vient d&apos;être envoyé.
            </div>
          )}
          <GlassButton type="submit" disabled={loading} className="w-full">
            {loading ? "Connexion…" : "Se connecter"}
          </GlassButton>
          <p className="text-xs opacity-50 text-center">
            Pas encore de compte ?{" "}
            <Link href="/account/register" className="underline">S&apos;inscrire</Link>
          </p>
        </form>
      </GlassCard>
    </div>
  );
}
