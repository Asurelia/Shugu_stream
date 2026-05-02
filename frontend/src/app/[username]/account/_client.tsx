"use client";

/**
 * Account client island.
 *
 * Migration Pages Router → App Router (Sprint E5) :
 *   - `useRouter` de `next/router` remplacé par `useRouter` + `useParams`
 *     de `next/navigation`.
 *   - `<Meta>` supprimé — métadonnées déclarées dans `page.tsx`.
 *   - `router.query.username` remplacé par `useParams<{ username?: string }>()`.
 */
import { useEffect, useState } from "react";
import { useRouter, useParams } from "next/navigation";
import Link from "next/link";

import { fetchAuthStatus, logout } from "@/services/shuguClient";
import {
  GlassCard,
  GlassSection,
  GlassRow,
  GlassButton,
  GlassInput,
  GlassSwitch,
  GlassPill,
  GlassTabs,
  GlassModal,
} from "@/features/liquid-glass/primitives";

/**
 * `/[username]/account` — Paramètres utilisateur façon iOS 26 Settings.
 *
 * Couverture :
 *  - Profil (nom, bio, avatar, preview)
 *  - Sécurité (mot de passe, 2FA, sessions)
 *  - Abonnement (VIP / Admin avec shimmer, factures, moyens de paiement)
 *  - Notifications (toggles par canal)
 *  - Connexions (OAuth Google/Discord/Twitch)
 *  - Données (export / supprimer)
 *  - Zone dangereuse (supprimer le compte)
 *
 * Les actions mutantes sont mockées — on affiche un modal de confirmation
 * et on annonce &apos;bientôt&apos; pour les flux non encore câblés côté backend.
 */

type Me = { username: string };
type Tier = "free" | "vip" | "admin";

export function AccountClient() {
  const router = useRouter();
  const params = useParams<{ username?: string }>();
  const urlUsername = params?.username;
  const [me, setMe] = useState<Me | null>(null);
  const [authChecked, setAuthChecked] = useState(false);
  const [section, setSection] = useState<
    "profile" | "security" | "subscription" | "notifications" | "connections" | "data"
  >("profile");
  const [confirmLogout, setConfirmLogout] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetchAuthStatus().then((res) => {
      if (cancelled) return;
      setMe(res);
      setAuthChecked(true);
    });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!authChecked) return;
    if (!me) { router.replace("/login"); return; }
    if (urlUsername && me.username.toLowerCase() !== urlUsername.toLowerCase()) {
      router.replace(`/${encodeURIComponent(me.username)}/account`);
    }
  }, [authChecked, me, urlUsername, router]);

  // Mock — branche à ton store quand dispo.
  const tier = "vip" as Tier;

  if (!authChecked || !me) {
    return (
      <div className="lg-page flex items-center justify-center">
        <span className="text-sm text-shugu-cream-dim">chargement…</span>
      </div>
    );
  }

  return (
    <div className="lg-page font-quicksand">
      <div className="max-w-[960px] mx-auto px-4 sm:px-8 py-8">
        {/* Header page */}
        <header className="mb-6 flex items-end justify-between gap-4 flex-wrap">
          <div>
            <Link
              href={`/${encodeURIComponent(me.username)}/admin`}
              className="text-[11px] tracking-[0.2em] uppercase text-shugu-cream-dim hover:text-shugu-pink-soft"
            >
              ← admin
            </Link>
            <h1 className="font-comfortaa font-bold text-2xl sm:text-3xl text-shugu-cream mt-1">
              Mon compte
            </h1>
            <p className="text-[13px] text-shugu-cream-dim mt-1">
              Gère ton profil, ta sécurité et tes abonnements.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <GlassPill tone={tier === "admin" ? "warn" : tier === "vip" ? "primary" : "default"} dot>
              {tier === "admin" ? "Admin" : tier === "vip" ? "VIP" : "Free"}
            </GlassPill>
            <GlassButton variant="subtle" size="sm" onClick={() => setConfirmLogout(true)}>
              Se déconnecter
            </GlassButton>
          </div>
        </header>

        {/* Tabs */}
        <div className="mb-6 overflow-x-auto">
          <GlassTabs
            aria-label="Sections du compte"
            value={section}
            onChange={(v) => setSection(v as typeof section)}
            tabs={[
              { value: "profile",        label: "Profil" },
              { value: "security",       label: "Sécurité" },
              { value: "subscription",   label: "Abonnement" },
              { value: "notifications",  label: "Notifications" },
              { value: "connections",    label: "Connexions" },
              { value: "data",           label: "Données" },
            ]}
          />
        </div>

        {/* Content */}
        <div className="space-y-4">
          {section === "profile"       && <ProfileSection username={me.username} />}
          {section === "security"      && <SecuritySection />}
          {section === "subscription"  && <SubscriptionSection tier={tier} />}
          {section === "notifications" && <NotificationsSection />}
          {section === "connections"   && <ConnectionsSection />}
          {section === "data"          && <DataSection onDelete={() => setConfirmDelete(true)} />}
        </div>

        <footer className="mt-10 text-center text-[10px] text-shugu-cream-dim tracking-[0.2em] uppercase">
          v0.1 · liquid glass build
        </footer>
      </div>

      {/* Confirm logout */}
      <GlassModal
        open={confirmLogout}
        onClose={() => setConfirmLogout(false)}
        title="Se déconnecter ?"
        footer={
          <>
            <GlassButton variant="subtle" onClick={() => setConfirmLogout(false)}>Annuler</GlassButton>
            <GlassButton
              variant="secondary"
              onClick={async () => { await logout(); router.push("/"); }}
            >
              Déconnexion
            </GlassButton>
          </>
        }
      >
        <p className="text-[13px] text-shugu-cream-dim leading-relaxed">
          Tu devras te reconnecter pour accéder à ton dashboard. Tes streams en cours seront fermés.
        </p>
      </GlassModal>

      {/* Confirm delete */}
      <GlassModal
        open={confirmDelete}
        onClose={() => setConfirmDelete(false)}
        title="Supprimer le compte ?"
        footer={
          <>
            <GlassButton variant="subtle" onClick={() => setConfirmDelete(false)}>Annuler</GlassButton>
            <GlassButton variant="danger" disabled>Supprimer (bientôt)</GlassButton>
          </>
        }
      >
        <p className="text-[13px] text-shugu-cream-dim leading-relaxed">
          Cette action est irréversible. Ton historique de streams, tes assets et tes clips seront perdus.
          Pour l&apos;instant la suppression se fait manuellement — écris à support@shugu.tv.
        </p>
      </GlassModal>
    </div>
  );
}

/* ──────────────────────────────────────────────── Profile ──────── */

function ProfileSection({ username }: { username: string }) {
  const [name, setName] = useState(username);
  const [bio, setBio] = useState("VTuber — streams Aura AI ♡");
  const [dirty, setDirty] = useState(false);

  return (
    <>
      <GlassSection
        title="Profil public"
        subtitle="Ce que voient les viewers dans le chat et sur ta chaîne."
        right={
          <GlassButton
            variant="primary" size="sm"
            disabled={!dirty}
            onClick={() => setDirty(false)}
          >
            Enregistrer
          </GlassButton>
        }
      >
        <div className="flex items-center gap-4 mb-4">
          <div
            className="w-16 h-16 rounded-2xl flex items-center justify-center shrink-0"
            style={{
              background: "linear-gradient(135deg, #e08efe 0%, #fd6c9c 100%)",
              boxShadow: "0 10px 28px -10px rgba(224,142,254,0.55), inset 0 1px 0 rgba(255,255,255,0.35)",
            }}
          >
            <span className="text-2xl text-white font-bold font-comfortaa">
              {username.slice(0, 1).toUpperCase()}
            </span>
          </div>
          <div className="flex-1">
            <div className="text-[13px] text-shugu-cream font-semibold">{username}</div>
            <div className="text-[11px] text-shugu-cream-dim font-mono tracking-wide">
              shugu.tv/{username}
            </div>
          </div>
          <GlassButton variant="ghost" size="sm" onClick={() => {/* TODO upload */}}>
            Changer l&apos;avatar
          </GlassButton>
        </div>
        <div className="flex flex-col gap-3">
          <GlassInput
            label="Nom affiché"
            value={name}
            onChange={(e) => { setName(e.target.value); setDirty(true); }}
          />
          <GlassInput
            label="Bio"
            value={bio}
            onChange={(e) => { setBio(e.target.value); setDirty(true); }}
            hint="Max 160 caractères."
            maxLength={160}
          />
        </div>
      </GlassSection>

      <GlassSection title="Préférences de langue">
        <GlassRow label="Langue de l&apos;interface" value={<code className="text-shugu-cream font-mono text-[12px]">fr-FR</code>} />
        <GlassRow label="Fuseau horaire" value={<code className="text-shugu-cream font-mono text-[12px]">Europe/Paris</code>} />
      </GlassSection>
    </>
  );
}

/* ──────────────────────────────────────────────── Security ─────── */

function SecuritySection() {
  const [twoFa, setTwoFa] = useState(false);
  return (
    <>
      <GlassSection
        title="Mot de passe"
        subtitle="Utilise au moins 12 caractères avec un mélange de types."
      >
        <div className="flex flex-col gap-3">
          <GlassInput label="Mot de passe actuel" type="password" autoComplete="current-password" />
          <GlassInput label="Nouveau mot de passe" type="password" autoComplete="new-password" />
          <GlassInput label="Confirmer" type="password" autoComplete="new-password" />
        </div>
        <div className="mt-4 flex justify-end">
          <GlassButton variant="primary" size="sm">Mettre à jour</GlassButton>
        </div>
      </GlassSection>

      <GlassSection title="Double authentification">
        <GlassRow
          label="2FA par application"
          sub="Google Authenticator, 1Password, etc."
          trailing={<GlassSwitch checked={twoFa} onChange={setTwoFa} aria-label="Activer la 2FA" />}
        />
        <GlassRow
          label="Codes de secours"
          value={<span className="text-shugu-cream-dim">10 codes disponibles</span>}
          trailing={<GlassButton variant="ghost" size="sm">Régénérer</GlassButton>}
        />
      </GlassSection>

      <GlassSection title="Sessions actives">
        {[
          { label: "MacBook Pro · Safari", sub: "Paris, FR · maintenant", current: true },
          { label: "iPhone 15 · iOS",       sub: "Paris, FR · il y a 2h",  current: false },
          { label: "OBS Studio · Windows",  sub: "Lyon, FR · hier",        current: false },
        ].map((s) => (
          <GlassRow
            key={s.label}
            label={<span className="flex items-center gap-2">
              {s.label}
              {s.current && <GlassPill tone="primary" dot>actuelle</GlassPill>}
            </span>}
            sub={s.sub}
            trailing={!s.current && <GlassButton variant="subtle" size="sm">Révoquer</GlassButton>}
          />
        ))}
      </GlassSection>
    </>
  );
}

/* ──────────────────────────────────────────────── Subscription ── */

function SubscriptionSection({ tier }: { tier: Tier }) {
  return (
    <>
      <GlassSection
        title="Ton tier"
        subtitle="Déverrouille plus de fonctionnalités, commandes Hermes et support prioritaire."
      >
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mt-2">
          <TierCard name="Free"  price="0 €"   features={["Stream 720p", "Chat basique"]} active={tier === "free"} />
          <TierCard name="VIP"   price="9 €/mo" features={["1080p @ 60fps", "Aura expressions +", "Commandes Hermes"]} active={tier === "vip"} tierBtn="vip" />
          <TierCard name="Admin" price="sur demande" features={["Multi-streams", "SLA prioritaire", "Accès tokens API"]} active={tier === "admin"} tierBtn="admin" />
        </div>
      </GlassSection>

      <GlassSection title="Moyen de paiement">
        <GlassRow
          label="Visa •••• 4242"
          sub="expire 08/28"
          trailing={<GlassButton variant="ghost" size="sm">Modifier</GlassButton>}
        />
        <GlassRow
          label="Ajouter une méthode"
          value={<span className="text-shugu-cream-dim">Apple Pay, SEPA</span>}
          trailing={<GlassButton variant="subtle" size="sm">+ Ajouter</GlassButton>}
        />
      </GlassSection>

      <GlassSection title="Factures récentes">
        {[
          { date: "Oct 2025", amount: "9,00 €", id: "INV-0925" },
          { date: "Sep 2025", amount: "9,00 €", id: "INV-0824" },
          { date: "Aug 2025", amount: "9,00 €", id: "INV-0723" },
        ].map((f) => (
          <GlassRow
            key={f.id}
            label={f.date}
            sub={f.id}
            value={f.amount}
            trailing={<GlassButton variant="subtle" size="sm">PDF</GlassButton>}
          />
        ))}
      </GlassSection>
    </>
  );
}

function TierCard({
  name, price, features, active, tierBtn,
}: {
  name: string; price: string; features: string[]; active?: boolean;
  tierBtn?: "vip" | "admin";
}) {
  return (
    <GlassCard
      padded={false}
      className={active ? "ring-1 ring-[rgba(224,142,254,0.5)]" : ""}
    >
      <div className="p-4">
        <div className="flex items-center justify-between">
          <div className="font-comfortaa font-bold text-[14px] text-shugu-cream">{name}</div>
          {active && <GlassPill tone="primary" dot>actif</GlassPill>}
        </div>
        <div className="text-[18px] font-bold text-shugu-cream mt-1">{price}</div>
        <ul className="mt-3 space-y-1">
          {features.map((f) => (
            <li key={f} className="text-[11px] text-shugu-cream-dim flex items-center gap-2">
              <span className="text-shugu-pink-soft">✓</span>{f}
            </li>
          ))}
        </ul>
        <div className="mt-4">
          {active ? (
            <GlassButton variant="subtle" size="sm" block disabled>
              ton plan actuel
            </GlassButton>
          ) : tierBtn ? (
            <GlassButton variant="ghost" size="sm" block tier={tierBtn}>
              {tierBtn === "admin" ? "nous contacter" : "upgrade"}
            </GlassButton>
          ) : (
            <GlassButton variant="ghost" size="sm" block>
              downgrade
            </GlassButton>
          )}
        </div>
      </div>
    </GlassCard>
  );
}

/* ──────────────────────────────────────────────── Notifications ── */

function NotificationsSection() {
  const [state, set] = useState({
    liveEmail: true, liveDiscord: true, liveChat: false,
    billing: true, security: true, marketing: false,
  });
  const toggle = (k: keyof typeof state) => set({ ...state, [k]: !state[k] });
  return (
    <>
      <GlassSection title="Alertes live">
        <GlassRow label="Email quand un stream commence"
          trailing={<GlassSwitch checked={state.liveEmail} onChange={() => toggle("liveEmail")} aria-label="Email" />} />
        <GlassRow label="Webhook Discord"
          sub="envoie un ping dans ton serveur"
          trailing={<GlassSwitch checked={state.liveDiscord} onChange={() => toggle("liveDiscord")} aria-label="Discord" />} />
        <GlassRow label="Chat browser push"
          sub="notifications quand un viewer te mentionne"
          trailing={<GlassSwitch checked={state.liveChat} onChange={() => toggle("liveChat")} aria-label="Push" />} />
      </GlassSection>
      <GlassSection title="Facturation et compte">
        <GlassRow label="Reçus de paiement"
          trailing={<GlassSwitch checked={state.billing} onChange={() => toggle("billing")} aria-label="Reçus" />} />
        <GlassRow label="Alertes de sécurité"
          sub="connexions, changements de mot de passe"
          trailing={<GlassSwitch checked={state.security} onChange={() => toggle("security")} aria-label="Sécurité" />} />
        <GlassRow label="Nouveautés produit"
          trailing={<GlassSwitch checked={state.marketing} onChange={() => toggle("marketing")} aria-label="Marketing" />} />
      </GlassSection>
    </>
  );
}

/* ──────────────────────────────────────────────── Connections ─── */

function ConnectionsSection() {
  return (
    <GlassSection title="Services connectés" subtitle="Relie tes comptes pour l&apos;auth et les webhooks.">
      {[
        { name: "Google",  sub: "non connecté",            connected: false },
        { name: "Discord", sub: "@spoukie#0001 · depuis juin", connected: true },
        { name: "Twitch",  sub: "non connecté",            connected: false },
        { name: "YouTube", sub: "non connecté",            connected: false },
      ].map((p) => (
        <GlassRow
          key={p.name}
          label={p.name}
          sub={p.sub}
          trailing={
            p.connected
              ? <GlassButton variant="subtle" size="sm">Déconnecter</GlassButton>
              : <GlassButton variant="ghost"   size="sm">Connecter</GlassButton>
          }
        />
      ))}
    </GlassSection>
  );
}

/* ──────────────────────────────────────────────── Data ─────────── */

function DataSection({ onDelete }: { onDelete: () => void }) {
  return (
    <>
      <GlassSection title="Export de données" subtitle="Reçois une archive JSON + médias par email.">
        <GlassRow
          label="Historique de streams"
          sub="VODs, chat logs, métriques"
          trailing={<GlassButton variant="ghost" size="sm">Exporter</GlassButton>}
        />
        <GlassRow
          label="Assets Aura"
          sub="modèles VRM, expressions, voix"
          trailing={<GlassButton variant="ghost" size="sm">Exporter</GlassButton>}
        />
      </GlassSection>

      <GlassSection danger title="Zone dangereuse" subtitle="Actions irréversibles — on te demande confirmation.">
        <GlassRow
          label="Supprimer le compte"
          sub="efface toutes les données associées"
          trailing={<GlassButton variant="danger" size="sm" onClick={onDelete}>Supprimer</GlassButton>}
        />
      </GlassSection>
    </>
  );
}
