import { useEffect, useState } from "react";
import { useRouter } from "next/router";
import { Meta } from "@/components/meta";
import { GlassCard, GlassButton } from "@/features/liquid-glass/primitives";
import { verifyEmail, AccountError } from "@/services/accountClient";

type Status = "loading" | "success" | "error";

export default function VerifyEmailPage() {
  const router = useRouter();
  const [status, setStatus] = useState<Status>("loading");
  const [detail, setDetail] = useState<string>("");

  useEffect(() => {
    if (!router.isReady) return;
    const raw = router.query.token;
    const token = Array.isArray(raw) ? raw[0] : raw;
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
  }, [router.isReady, router.query.token]);

  return (
    <div className="lg-page min-h-screen flex items-center justify-center p-6">
      <Meta title="Vérification email — Shugu" />
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
