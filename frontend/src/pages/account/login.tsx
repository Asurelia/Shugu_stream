import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/router";
import { Meta } from "@/components/meta";
import { GlassCard, GlassButton, GlassInput } from "@/features/liquid-glass/primitives";
import { login, resendVerify, AccountError } from "@/services/accountClient";

export default function AccountLoginPage() {
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
      await login({ username_or_email: usernameOrEmail, password });
      router.replace("/account/profile");
    } catch (err) {
      if (err instanceof AccountError) setError(err.detail);
      else setError("Erreur réseau inattendue.");
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
      await resendVerify(usernameOrEmail);
      setResendState("sent");
      setError(null);
    } catch {
      setResendState("error");
    }
  };

  return (
    <div className="lg-page min-h-screen flex items-center justify-center p-6">
      <Meta title="Connexion — Shugu" />
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
              {error.toLowerCase().includes("not verified") && (
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
              Si ton compte existe, un email vient d'être envoyé.
            </div>
          )}
          <GlassButton type="submit" disabled={loading} className="w-full">
            {loading ? "Connexion…" : "Se connecter"}
          </GlassButton>
          <p className="text-xs opacity-50 text-center">
            Pas encore de compte ?{" "}
            <Link href="/account/register" className="underline">S'inscrire</Link>
          </p>
        </form>
      </GlassCard>
    </div>
  );
}
