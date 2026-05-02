"use client";

/**
 * /account/verify-email client island.
 *
 * Migration Pages Router → App Router (Sprint E2) :
 *   - `useRouter` + `router.query.token` → `useSearchParams().get("token")`
 *     from `next/navigation` (App Router always ready, no `isReady` check).
 *   - `<Meta title>` removed — the parent Server Component (page.tsx)
 *     declares `metadata` instead.
 */
import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { GlassCard, GlassButton } from "@/features/liquid-glass/primitives";
import { verifyEmail, AccountError } from "@/services/accountClient";

type Status = "loading" | "success" | "error";

export function VerifyEmailClient() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const token = searchParams?.get("token");
  const [status, setStatus] = useState<Status>("loading");
  const [detail, setDetail] = useState<string>("");

  useEffect(() => {
    if (!token) {
      setStatus("error");
      setDetail("Lien invalide : token manquant.");
      return;
    }
    verifyEmail(token)
      .then((res) => {
        setStatus("success");
        setDetail(res.detail ?? "Email vérifié.");
      })
      .catch((err: unknown) => {
        setStatus("error");
        if (err instanceof AccountError) {
          setDetail(err.detail);
        } else {
          setDetail("Erreur réseau inattendue.");
        }
      });
  }, [token]);

  return (
    <div className="lg-page min-h-screen flex items-center justify-center p-6">
      <GlassCard className="max-w-md w-full text-center" padded>
        {status === "loading" && (
          <>
            <h1 className="text-2xl font-light tracking-tight text-shugu-cream mb-2">
              Vérification…
            </h1>
            <p className="text-sm opacity-70">Un instant, on valide ton lien.</p>
          </>
        )}
        {status === "success" && (
          <>
            <h1 className="text-2xl font-light tracking-tight text-shugu-cream mb-2">
              Email vérifié
            </h1>
            <p className="text-sm opacity-70 mb-6">
              Ton compte est activé. Tu peux maintenant te connecter.
            </p>
            <GlassButton type="button" onClick={() => router.push("/account/login")}>
              Se connecter
            </GlassButton>
          </>
        )}
        {status === "error" && (
          <>
            <h1 className="text-2xl font-light tracking-tight text-shugu-cream mb-2">
              Vérification impossible
            </h1>
            <p className="text-sm opacity-70 mb-2">{detail}</p>
            <p className="text-xs opacity-50 mb-6">
              Si le lien a expiré (24 h), demande un nouvel email depuis la page de connexion.
            </p>
            <GlassButton type="button" onClick={() => router.push("/account/login")}>
              Retour login
            </GlassButton>
          </>
        )}
      </GlassCard>
    </div>
  );
}
