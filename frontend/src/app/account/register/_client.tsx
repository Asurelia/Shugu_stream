"use client";

/**
 * /account/register client island.
 *
 * Migration Pages Router → App Router (Sprint E2) :
 *   - `useRouter` import : `next/router` → `next/navigation`. The new API
 *     keeps `.push(url)` but drops `.query` (we don't use it here).
 *   - `<Meta title>` removed — the parent Server Component (page.tsx)
 *     declares `metadata` instead.
 *   - `<Link href>` from `next/link` keeps the same API.
 *
 * Form logic untouched : same accountClient calls, same password validation,
 * same error/success UX.
 */
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { GlassButton, GlassCard, GlassInput } from "@/features/liquid-glass/primitives";
import { AccountError, register } from "@/services/accountClient";

type FormState = {
  username: string;
  email: string;
  password: string;
};

export function RegisterClient() {
  const router = useRouter();
  const [form, setForm] = useState<FormState>({ username: "", email: "", password: "" });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const onChange = (k: keyof FormState) => (e: React.ChangeEvent<HTMLInputElement>) => {
    setForm((f) => ({ ...f, [k]: e.target.value }));
  };

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSuccess(null);
    if (form.password.length < 10) {
      setError("Le mot de passe doit faire au moins 10 caractères.");
      return;
    }
    setLoading(true);
    try {
      const res = await register(form);
      setSuccess(
        res.email_sent
          ? `Un email de vérification a été envoyé à ${res.email}. Vérifie ta boîte et tes spams.`
          : "Compte créé. L'email a rencontré un souci, demande un renvoi depuis la page login.",
      );
    } catch (err) {
      if (err instanceof AccountError) setError(err.detail);
      else setError("Erreur réseau inattendue.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="lg-page min-h-screen flex items-center justify-center p-6">
      <GlassCard className="max-w-md w-full" padded>
        <h1 className="text-2xl font-light tracking-tight text-shugu-cream mb-1">
          Crée ton compte
        </h1>
        <p className="text-sm opacity-60 mb-6">
          Un espace pour parler avec Shugu. Le VIP arrive bientôt.
        </p>
        {success ? (
          <div className="space-y-4">
            <div className="p-4 rounded-xl bg-emerald-500/10 border border-emerald-500/30 text-sm text-emerald-100">
              {success}
            </div>
            <p className="text-xs opacity-60">
              Une fois l&apos;email vérifié, tu pourras te connecter.
            </p>
            <GlassButton type="button" onClick={() => router.push("/account/login")}>
              Aller à la connexion
            </GlassButton>
          </div>
        ) : (
          <form onSubmit={onSubmit} className="space-y-4">
            <label className="block">
              <span className="text-xs opacity-70 mb-1 block">Pseudo</span>
              <GlassInput
                type="text"
                value={form.username}
                onChange={onChange("username")}
                placeholder="3-32 chars, lettres/chiffres/_ "
                required
                minLength={3}
                maxLength={32}
                autoComplete="username"
              />
            </label>
            <label className="block">
              <span className="text-xs opacity-70 mb-1 block">Email</span>
              <GlassInput
                type="email"
                value={form.email}
                onChange={onChange("email")}
                placeholder="toi@exemple.com"
                required
                autoComplete="email"
              />
            </label>
            <label className="block">
              <span className="text-xs opacity-70 mb-1 block">
                Mot de passe <span className="opacity-50">(10 caractères min)</span>
              </span>
              <GlassInput
                type="password"
                value={form.password}
                onChange={onChange("password")}
                placeholder="••••••••••"
                required
                minLength={10}
                maxLength={72}
                autoComplete="new-password"
              />
            </label>
            {error && (
              <div className="p-3 rounded-xl bg-rose-500/10 border border-rose-500/30 text-sm text-rose-100">
                {error}
              </div>
            )}
            <GlassButton type="submit" disabled={loading} className="w-full">
              {loading ? "Création…" : "Créer le compte"}
            </GlassButton>
            <p className="text-xs opacity-50 text-center">
              Déjà inscrit ?{" "}
              <Link href="/account/login" className="underline">Se connecter</Link>
            </p>
          </form>
        )}
      </GlassCard>
    </div>
  );
}
