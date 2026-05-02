"use client";

/**
 * /login — Operator login client island.
 *
 * Migration Pages Router → App Router (Sprint E3) :
 *   - `useRouter` import : `next/router` → `next/navigation`. The new API
 *     keeps `.replace(url)` / `.push(url)` and is fully compatible here.
 *   - `<Meta title>` removed — the parent Server Component (page.tsx)
 *     declares `metadata` instead.
 *   - Markup, classes, tabs, and stub signup() left exactly as in the
 *     original Pages Router file.
 *
 * This page is the OPERATOR login (Spoukie / Hermes / scene-editor access),
 * distinct from `/account/login` which is user-self-service.
 */

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Sparkles } from "@/components/Sparkles";
import { fetchAuthStatus, login } from "@/services/shuguClient";

// Stub signup — le backend signup n'est pas encore câblé. On annonce "bientôt"
// plutôt que d'appeler une route qui n'existe pas. À remplacer par un vrai
// `signup()` dans `@/services/shuguClient` quand le flow sera en place.
async function signup(_payload: {
  username: string; email: string; password: string;
}): Promise<string | null> {
  return "La création de compte arrive bientôt — connecte-toi avec un compte existant.";
}
import {
  GlassCard,
  GlassButton,
  GlassInput,
  GlassTabs,
} from "@/features/liquid-glass/primitives";

type Mode = "signin" | "signup";

export function LoginClient() {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>("signin");
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [busy, setBusy] = useState(false);

  // Si l'op est déjà connecté, on le renvoie direct vers son dashboard.
  useEffect(() => {
    let cancelled = false;
    fetchAuthStatus().then((me) => {
      if (cancelled || !me) return;
      router.replace(`/${encodeURIComponent(me.username)}/admin`);
    });
    return () => { cancelled = true; };
  }, [router]);

  const reset = () => { setError(""); setInfo(""); };

  const handleSignIn = async (e: React.FormEvent) => {
    e.preventDefault();
    reset(); setBusy(true);
    const err = await login(username, password);
    setBusy(false);
    if (err) { setError(err); return; }
    const me = await fetchAuthStatus();
    if (me) router.push(`/${encodeURIComponent(me.username)}/admin`);
    else router.push("/");
  };

  const handleSignUp = async (e: React.FormEvent) => {
    e.preventDefault();
    reset();
    if (password !== confirm) { setError("Les mots de passe ne correspondent pas."); return; }
    setBusy(true);
    const err = await signup({ username, email, password });
    setBusy(false);
    if (err) { setError(err); return; }
    const me = await fetchAuthStatus();
    if (me) router.push(`/${encodeURIComponent(me.username)}/admin`);
    else router.push("/");
  };

  const handleOAuth = (provider: string) => {
    reset();
    setInfo(`${provider} arrive bientôt — pour l'instant, connecte-toi avec ton nom d'utilisateur.`);
  };

  return (
    <div className="lg-page font-quicksand flex items-center justify-center px-4 py-10">
      <Sparkles />

      <main className="relative w-full max-w-md">
        {/* Marque discrète au-dessus de la carte */}
        <header className="text-center mb-5">
          <div className="inline-flex items-center gap-2 text-shugu-cream-dim">
            <span className="text-shugu-pink-glow text-xl">✦</span>
            <span className="font-comfortaa font-bold text-[18px] text-shugu-cream tracking-wide">
              Shugu
            </span>
            <span className="text-xs uppercase tracking-[0.2em] text-shugu-cream-dim">
              · Celestial Veil
            </span>
          </div>
        </header>

        <GlassCard padded={false}>
          <div className="p-6 sm:p-7">
            {/* Tabs */}
            <div className="flex items-center justify-center mb-5">
              <GlassTabs
                aria-label="Mode de connexion"
                value={mode}
                onChange={(v) => { setMode(v as Mode); reset(); }}
                tabs={[
                  { value: "signin", label: "Sign in" },
                  { value: "signup", label: "Create account" },
                ]}
              />
            </div>

            <h1 className="font-comfortaa font-bold text-xl text-shugu-cream tracking-tight text-center">
              {mode === "signin" ? "Welcome back ♡" : "Create your space"}
            </h1>
            <p className="text-[12px] text-shugu-cream-dim text-center mt-1 mb-5">
              {mode === "signin"
                ? "Accès opérateur — commandes Hermes réelles."
                : "Rejoins les créateurs qui streament avec Aura."}
            </p>

            {/* OAuth rail */}
            <div className="grid grid-cols-3 gap-2 mb-5">
              {[
                { label: "Google",  icon: <GoogleG />,  provider: "Google"  },
                { label: "Discord", icon: <DiscordG />, provider: "Discord" },
                { label: "Twitch",  icon: <TwitchG />,  provider: "Twitch"  },
              ].map((o) => (
                <GlassButton
                  key={o.provider}
                  variant="ghost"
                  size="md"
                  onClick={() => handleOAuth(o.provider)}
                  className="!py-2.5"
                  aria-label={`Continuer avec ${o.label}`}
                >
                  <span className="flex items-center gap-2">
                    {o.icon}
                    <span className="text-[12px] hidden sm:inline">{o.label}</span>
                  </span>
                </GlassButton>
              ))}
            </div>

            {/* Séparateur */}
            <div className="flex items-center gap-3 my-4" aria-hidden>
              <span className="flex-1 h-px bg-white/10" />
              <span className="text-[10px] tracking-[0.22em] uppercase text-shugu-cream-dim">
                ou avec email
              </span>
              <span className="flex-1 h-px bg-white/10" />
            </div>

            {/* Forms */}
            {mode === "signin" ? (
              <form onSubmit={handleSignIn} className="flex flex-col gap-3">
                <GlassInput
                  label="Nom d'utilisateur"
                  type="text"
                  autoComplete="username"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  required
                />
                <GlassInput
                  label="Mot de passe"
                  type="password"
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                />

                <div className="flex items-center justify-between text-[11px] text-shugu-cream-dim mt-1">
                  <label className="flex items-center gap-2 cursor-pointer select-none">
                    <input type="checkbox" className="accent-shugu-pink" />
                    <span>Rester connecté</span>
                  </label>
                  <button
                    type="button"
                    onClick={() => setInfo("Un lien de réinitialisation sera envoyé par email.")}
                    className="hover:text-shugu-pink-soft transition-colors"
                  >
                    Mot de passe oublié ?
                  </button>
                </div>

                <Feedback error={error} info={info} />

                <GlassButton
                  type="submit"
                  variant="primary"
                  size="lg"
                  block
                  disabled={busy || !username || !password}
                  className="mt-2"
                >
                  {busy ? "connexion…" : "se connecter ♡"}
                </GlassButton>
              </form>
            ) : (
              <form onSubmit={handleSignUp} className="flex flex-col gap-3">
                <GlassInput
                  label="Nom d'utilisateur"
                  type="text"
                  autoComplete="username"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  required
                  hint="3–24 caractères, lettres/chiffres/_."
                />
                <GlassInput
                  label="Email"
                  type="email"
                  autoComplete="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                />
                <GlassInput
                  label="Mot de passe"
                  type="password"
                  autoComplete="new-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  hint="8 caractères minimum."
                />
                <GlassInput
                  label="Confirmer"
                  type="password"
                  autoComplete="new-password"
                  value={confirm}
                  onChange={(e) => setConfirm(e.target.value)}
                  required
                />

                <Feedback error={error} info={info} />

                <GlassButton
                  type="submit"
                  variant="primary"
                  size="lg"
                  block
                  disabled={busy || !username || !email || !password || !confirm}
                  className="mt-2"
                >
                  créer mon compte ✦
                </GlassButton>
                <p className="text-[10px] text-shugu-cream-dim text-center leading-relaxed">
                  En créant un compte, tu acceptes les conditions d&apos;utilisation et la politique de confidentialité.
                </p>
              </form>
            )}
          </div>

          {/* Pied de carte */}
          <div className="border-t border-white/5 px-6 py-3 text-center">
            <Link
              href="/"
              className="text-[12px] text-shugu-cream-dim hover:text-shugu-pink-soft transition-colors"
            >
              ← retour au live
            </Link>
          </div>
        </GlassCard>

        <footer className="text-center mt-6 text-[10px] text-shugu-cream-dim tracking-[0.18em] uppercase">
          v0.1 · liquid glass build
        </footer>
      </main>
    </div>
  );
}

function Feedback({ error, info }: { error: string; info: string }) {
  if (!error && !info) return null;
  return (
    <div
      role={error ? "alert" : "status"}
      className={[
        "mt-1 rounded-xl px-3 py-2 text-[12px] leading-snug",
        error
          ? "bg-[rgba(255,106,138,0.08)] border border-[rgba(255,106,138,0.25)] text-[#ff9fb0]"
          : "bg-[rgba(129,236,255,0.06)] border border-[rgba(129,236,255,0.2)] text-[#9fe5ff]",
      ].join(" ")}
    >
      {error || info}
    </div>
  );
}

/* Inline OAuth glyphs — pas de libs icônes dans le repo, on dessine vite fait. */
function GoogleG() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" aria-hidden>
      <path fill="#ea4335" d="M12 11v3.5h5.1a5.2 5.2 0 0 1-5.1 3.9 5.9 5.9 0 1 1 3.9-10.3l2.5-2.5A9.4 9.4 0 1 0 21.3 12c0-.6 0-1.1-.1-1.6z"/>
      <path fill="#fbbc05" d="M3.6 7.8l2.9 2.1A5.9 5.9 0 0 1 12 6.1a5.6 5.6 0 0 1 3.9 1.5l2.5-2.5A9.4 9.4 0 0 0 3.6 7.8z"/>
      <path fill="#34a853" d="M12 21.4a9.4 9.4 0 0 0 6.5-2.5l-3-2.5a5.7 5.7 0 0 1-8.5-3l-3 2.3a9.4 9.4 0 0 0 8 5.7z"/>
      <path fill="#4285f4" d="M21.2 10.4H12V14h5.3a4.5 4.5 0 0 1-1.8 2.4l3 2.5a9.4 9.4 0 0 0 2.7-6.7c0-.6 0-1.2-.1-1.8z"/>
    </svg>
  );
}
function DiscordG() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" aria-hidden>
      <path fill="#5865f2" d="M20 4.5A17 17 0 0 0 15.4 3l-.2.4a13 13 0 0 1 3.6 1.6 13 13 0 0 0-13.6 0A13 13 0 0 1 8.8 3.4L8.6 3A17 17 0 0 0 4 4.5C1.6 8.1.9 11.7 1.2 15.2c1.9 1.4 3.8 2.3 5.6 2.8l.5-.7a11 11 0 0 1-1.9-.9l.4-.4a11 11 0 0 0 10.4 0l.4.4a11 11 0 0 1-1.9.9l.5.7c1.8-.5 3.7-1.4 5.6-2.8.5-4.1-.5-7.7-2.8-10.7zM9 13.6c-.9 0-1.6-.8-1.6-1.9S8.1 9.9 9 9.9s1.6.8 1.6 1.9S9.9 13.6 9 13.6zm6 0c-.9 0-1.6-.8-1.6-1.9s.7-1.9 1.6-1.9 1.6.8 1.6 1.9-.7 1.9-1.6 1.9z"/>
    </svg>
  );
}
function TwitchG() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" aria-hidden>
      <path fill="#9146ff" d="M4 3v15h5v3h3l3-3h4l5-5V3zm16 9-3 3h-5l-3 3v-3H5V5h15z"/>
      <path fill="#9146ff" d="M11 8h2v5h-2zm5 0h2v5h-2z"/>
    </svg>
  );
}
