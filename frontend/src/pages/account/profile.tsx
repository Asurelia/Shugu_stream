import { useEffect, useState } from "react";
import { useRouter } from "next/router";
import { Meta } from "@/components/meta";
import {
  GlassCard, GlassButton, GlassPill,
} from "@/features/liquid-glass/primitives";
import { me as fetchMe, logout, type Me } from "@/services/accountClient";

export default function AccountProfilePage() {
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    fetchMe()
      .then((res) => {
        if (cancelled) return;
        if (!res) {
          router.replace("/account/login");
          return;
        }
        setMe(res);
      })
      .catch(() => router.replace("/account/login"))
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [router]);

  const onLogout = async () => {
    try {
      await logout();
    } finally {
      router.replace("/account/login");
    }
  };

  if (loading || !me) {
    return (
      <div className="lg-page min-h-screen flex items-center justify-center">
        <Meta title="Mon compte — Shugu" />
        <span className="text-sm opacity-60">chargement…</span>
      </div>
    );
  }

  const vipUntilLabel = me.vip_until
    ? new Date(me.vip_until).toLocaleDateString("fr-FR", {
        year: "numeric", month: "long", day: "numeric",
      })
    : null;

  return (
    <div className="lg-page min-h-screen p-6">
      <Meta title="Mon compte — Shugu" />
      <div className="max-w-lg mx-auto space-y-4">
        <GlassCard padded>
          <div className="flex items-start justify-between gap-4 mb-4">
            <div>
              <h1 className="text-2xl font-light tracking-tight text-shugu-cream">
                {me.username}
              </h1>
              <p className="text-xs opacity-60 mt-1">{me.email}</p>
            </div>
            <GlassPill tone={me.role === "vip" ? "primary" : "default"}>
              {me.role}
            </GlassPill>
          </div>

          <dl className="space-y-2 text-sm">
            <div className="flex justify-between">
              <dt className="opacity-60">Email vérifié</dt>
              <dd>{me.email_verified ? "oui" : "non"}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="opacity-60">Statut VIP</dt>
              <dd>{me.vip_active ? "actif" : "inactif"}</dd>
            </div>
            {vipUntilLabel && (
              <div className="flex justify-between">
                <dt className="opacity-60">VIP jusqu'au</dt>
                <dd>{vipUntilLabel}</dd>
              </div>
            )}
          </dl>
        </GlassCard>

        {me.role === "vip" && (
          <GlassCard padded>
            <h2 className="text-sm font-medium text-shugu-cream mb-2">
              Salon VIP
            </h2>
            <p className="text-xs opacity-60 mb-4">
              Discute en voix avec Shugu en privé. Arrive bientôt.
            </p>
            <GlassButton
              type="button"
              disabled
              className="w-full opacity-40 cursor-not-allowed"
              title="Phase 3a — en cours"
            >
              Rejoindre le salon VIP (bientôt)
            </GlassButton>
          </GlassCard>
        )}

        <GlassCard padded>
          <div className="flex items-center justify-between gap-4">
            <div>
              <h2 className="text-sm font-medium text-shugu-cream">Session</h2>
              <p className="text-xs opacity-60">Déconnecte-toi de ce navigateur.</p>
            </div>
            <GlassButton
              type="button"
              variant="secondary"
              onClick={onLogout}
            >
              Se déconnecter
            </GlassButton>
          </div>
        </GlassCard>
      </div>
    </div>
  );
}
