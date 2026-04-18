import { useState } from "react";
import { useRouter } from "next/router";
import Link from "next/link";
import { Quicksand, Comfortaa } from "next/font/google";
import { Meta } from "@/components/meta";
import { Sparkles } from "@/components/Sparkles";
import { login } from "../services/shuguClient";

const quicksand = Quicksand({ variable: "--font-quicksand", subsets: ["latin"], display: "swap", weight: ["400","500","600","700"] });
const comfortaa = Comfortaa({ variable: "--font-comfortaa", subsets: ["latin"], display: "swap", weight: ["500","600","700"] });

export default function LoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true); setError("");
    const err = await login(username, password);
    setBusy(false);
    if (err) setError(err);
    else router.push("/");
  };

  return (
    <div className={`${quicksand.variable} ${comfortaa.variable} font-quicksand min-h-screen flex items-center justify-center p-4`}>
      <Meta />
      <Sparkles />
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-sm glass-pink rounded-3xl p-7 sm:p-8 shadow-2xl relative z-10"
      >
        <h1 className="font-comfortaa font-bold text-2xl text-shugu-pink-glow flex items-center gap-2">
          🌸 Shugu <span className="text-shugu-cream-dim font-normal text-base">♡ opérateur</span>
        </h1>
        <p className="text-xs text-shugu-cream-dim mb-6 mt-1">
          {"Accès réservé — commandes Hermes réelles."}
        </p>

        <label className="block text-xs mb-1 text-shugu-cream-dim">{"Nom d'utilisateur"}</label>
        <input
          type="text"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          autoComplete="username"
          className="w-full px-4 py-2.5 rounded-full bg-shugu-ink/60 border border-shugu-pink-soft/20 text-shugu-cream placeholder-shugu-cream-dim focus:outline-none focus:ring-2 focus:ring-shugu-pink/40 mb-4"
          required
        />

        <label className="block text-xs mb-1 text-shugu-cream-dim">Mot de passe</label>
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete="current-password"
          className="w-full px-4 py-2.5 rounded-full bg-shugu-ink/60 border border-shugu-pink-soft/20 text-shugu-cream placeholder-shugu-cream-dim focus:outline-none focus:ring-2 focus:ring-shugu-pink/40 mb-4"
          required
        />

        {error && <div className="text-shugu-live text-xs mb-3 text-center">{error}</div>}

        <button
          type="submit"
          disabled={busy || !username || !password}
          className="w-full py-2.5 rounded-full bg-shugu-pink hover:bg-shugu-pink-glow disabled:opacity-50 font-bold text-white transition shadow-[0_0_18px_rgba(255,97,127,0.5)]"
        >
          {busy ? "connexion…" : "se connecter ♡"}
        </button>

        <Link href="/" className="block mt-5 text-center text-xs text-shugu-cream-dim hover:text-shugu-pink-soft">
          ← retour au live
        </Link>
      </form>
    </div>
  );
}
