"use client";

/**
 * Admin Users client island.
 *
 * Migration Pages Router → App Router (Sprint E5) :
 *   - `useRouter` de `next/router` remplacé par `useRouter` + `useParams`
 *     de `next/navigation`.
 *   - `<Meta title>` supprimé — métadonnées déclarées dans `page.tsx`.
 *   - `AdminShell` migré vers `next/navigation` — fonctionne uniquement
 *     sous App Router (toutes les pages admin migrent ensemble Sprint E5).
 */
import { useCallback, useEffect, useMemo, useState } from "react";

import { AdminShell } from "@/components/admin/AdminShell";
import {
  GlassSection,
  GlassRow,
  GlassPill,
  GlassButton,
  GlassInput,
  GlassTabs,
  GlassModal,
  useToast,
} from "@/features/liquid-glass/primitives";
import { MetricTile } from "@/features/liquid-glass/dataviz";
import {
  listUsers,
  setVIP,
  deactivateUser,
  type AdminUser,
  AdminError,
} from "@/services/adminUsersClient";

/**
 * `/[username]/admin/users` — Gestion des comptes self-service (member/vip).
 *
 * Pipeline v4 Phase 1. L&apos;opérateur peut :
 *   - Voir la liste paginée des UserAccount avec filtre role/verified/active
 *   - Promouvoir un member → VIP (optionnellement avec durée)
 *   - Révoquer un VIP → redescend en member
 *   - Désactiver un compte (soft-delete, is_active=false)
 *
 * Les mutations déclenchent un email (vip_promoted.html / vip_revoked.html)
 * envoyé via Resend (ou loggé si NullSender).
 */

type RoleFilter = "all" | "member" | "vip";
type PendingAction =
  | { kind: "grant"; user: AdminUser }
  | { kind: "revoke"; user: AdminUser }
  | { kind: "deactivate"; user: AdminUser }
  | null;

const PAGE_SIZE = 25;

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString("fr-FR", {
      day: "2-digit", month: "short", year: "numeric",
    });
  } catch { return iso; }
}

function RoleBadge({ user }: { user: AdminUser }) {
  if (!user.is_active) return <GlassPill tone="danger">désactivé</GlassPill>;
  if (!user.email_verified) return <GlassPill tone="warn">non vérifié</GlassPill>;
  if (user.vip_active) return <GlassPill tone="primary" dot>VIP</GlassPill>;
  return <GlassPill>member</GlassPill>;
}

export function AdminUsersClient() {
  const toast = useToast();
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [roleFilter, setRoleFilter] = useState<RoleFilter>("all");
  const [verifiedOnly, setVerifiedOnly] = useState<boolean | undefined>(undefined);
  const [page, setPage] = useState(0);
  const [pendingAction, setPendingAction] = useState<PendingAction>(null);
  const [durationDays, setDurationDays] = useState<string>("");
  const [mutating, setMutating] = useState(false);

  const offset = page * PAGE_SIZE;

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await listUsers({
        role: roleFilter,
        email_verified: verifiedOnly,
        is_active: true,
        limit: PAGE_SIZE,
        offset,
      });
      setUsers(res.items);
      setTotal(res.total);
    } catch (err) {
      if (err instanceof AdminError)
        toast.error("Chargement échoué", { description: err.detail });
      else toast.error("Chargement échoué", { description: "Erreur réseau" });
    } finally {
      setLoading(false);
    }
  }, [roleFilter, verifiedOnly, offset, toast]);

  /* eslint-disable react-hooks/set-state-in-effect -- FIXME P5: fetch-on-mount + filter deps, refactor to useReducer when adopting data lib */
  useEffect(() => { load(); }, [load]);
  /* eslint-enable react-hooks/set-state-in-effect */

  const vipCount = useMemo(() => users.filter((u) => u.vip_active).length, [users]);
  const pendingCount = useMemo(() => users.filter((u) => !u.email_verified).length, [users]);

  const onAction = (action: PendingAction) => {
    setPendingAction(action);
    setDurationDays("");
  };

  const commitAction = async () => {
    if (!pendingAction) return;
    setMutating(true);
    try {
      if (pendingAction.kind === "grant") {
        const dur = durationDays.trim() ? parseInt(durationDays, 10) : undefined;
        await setVIP(pendingAction.user.id, "grant", dur);
      } else if (pendingAction.kind === "revoke") {
        await setVIP(pendingAction.user.id, "revoke");
      } else {
        await deactivateUser(pendingAction.user.id);
      }
      setPendingAction(null);
      await load();
    } catch (err) {
      if (err instanceof AdminError)
        toast.error("Action échouée", { description: err.detail });
      else toast.error("Action échouée", { description: "Erreur lors de l'action" });
    } finally {
      setMutating(false);
    }
  };

  return (
    <AdminShell
      active="users"
      title="Utilisateurs"
      subtitle="Comptes self-service : members & VIPs."
      headerRight={
        <GlassPill tone="primary" dot>{total} comptes actifs</GlassPill>
      }
    >
      <section className="flex flex-col gap-5">
        {/* KPIs */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <MetricTile label="Comptes actifs" value={String(total)} color="#e08efe" />
          <MetricTile label="VIPs (page)" value={String(vipCount)} color="#ffd98c" />
          <MetricTile label="Non vérifiés (page)" value={String(pendingCount)} color="#fd6c9c" />
          <MetricTile label="Affichés" value={String(users.length)} color="#81ecff" />
        </div>

        {/* Filtres */}
        <GlassSection title="Filtres" subtitle="Affine la liste affichée.">
          <div className="flex flex-wrap items-center gap-3">
            <GlassTabs
              value={roleFilter}
              onChange={(v) => { setRoleFilter(v as RoleFilter); setPage(0); }}
              tabs={[
                { value: "all", label: "Tous" },
                { value: "member", label: "Members" },
                { value: "vip", label: "VIPs" },
              ]}
            />
            <div className="flex items-center gap-2">
              <GlassButton
                variant={verifiedOnly === undefined ? "secondary" : "ghost"}
                size="sm"
                onClick={() => { setVerifiedOnly(undefined); setPage(0); }}
              >Tous</GlassButton>
              <GlassButton
                variant={verifiedOnly === true ? "secondary" : "ghost"}
                size="sm"
                onClick={() => { setVerifiedOnly(true); setPage(0); }}
              >Vérifiés</GlassButton>
              <GlassButton
                variant={verifiedOnly === false ? "secondary" : "ghost"}
                size="sm"
                onClick={() => { setVerifiedOnly(false); setPage(0); }}
              >En attente</GlassButton>
            </div>
            <div className="ml-auto">
              <GlassButton variant="ghost" size="sm" onClick={load}>
                {loading ? "…" : "Rafraîchir"}
              </GlassButton>
            </div>
          </div>
        </GlassSection>

        {/* Liste */}
        <GlassSection title="Comptes" subtitle={`${total} total · page ${page + 1}/${Math.max(1, Math.ceil(total / PAGE_SIZE))}`}>
          {loading && users.length === 0 ? (
            <div className="p-4 text-sm opacity-60">chargement…</div>
          ) : users.length === 0 ? (
            <div className="p-4 text-sm opacity-60">aucun utilisateur</div>
          ) : (
            users.map((u) => (
              <GlassRow
                key={u.id}
                label={
                  <span className="flex items-center gap-2">
                    <span className="text-shugu-cream">{u.username}</span>
                    <RoleBadge user={u} />
                  </span>
                }
                sub={
                  <span className="block text-[12px] opacity-65">
                    {u.email}
                    {u.vip_until && u.vip_active && (
                      <span className="ml-2 opacity-80">&middot; VIP jusqu&apos;au {formatDate(u.vip_until)}</span>
                    )}
                    <span className="ml-2 opacity-40">&middot; créé {formatDate(u.created_at)}</span>
                  </span>
                }
                trailing={
                  <div className="flex items-center gap-2">
                    {u.vip_active ? (
                      <GlassButton variant="subtle" size="sm"
                        onClick={() => onAction({ kind: "revoke", user: u })}>
                        Retirer VIP
                      </GlassButton>
                    ) : (
                      <GlassButton variant="secondary" size="sm" tier="vip"
                        onClick={() => onAction({ kind: "grant", user: u })}
                        disabled={!u.email_verified}
                        title={u.email_verified ? "Promouvoir VIP" : "Email non vérifié"}>
                        Promouvoir VIP
                      </GlassButton>
                    )}
                    <GlassButton variant="danger" size="sm"
                      onClick={() => onAction({ kind: "deactivate", user: u })}>
                      Désactiver
                    </GlassButton>
                  </div>
                }
              />
            ))
          )}

          {/* Pagination */}
          {total > PAGE_SIZE && (
            <div className="flex items-center justify-between gap-3 pt-4">
              <GlassButton variant="ghost" size="sm"
                disabled={page === 0}
                onClick={() => setPage((p) => Math.max(0, p - 1))}>
                ← Précédent
              </GlassButton>
              <span className="text-[12px] opacity-60">
                {offset + 1}–{Math.min(offset + users.length, total)} sur {total}
              </span>
              <GlassButton variant="ghost" size="sm"
                disabled={offset + users.length >= total}
                onClick={() => setPage((p) => p + 1)}>
                Suivant →
              </GlassButton>
            </div>
          )}
        </GlassSection>
      </section>

      {/* Modal de confirmation */}
      {pendingAction && (
        <GlassModal open onClose={() => !mutating && setPendingAction(null)}>
          <div className="p-5 space-y-4">
            <h3 className="text-lg font-light text-shugu-cream">
              {pendingAction.kind === "grant" && `Promouvoir ${pendingAction.user.username} VIP ?`}
              {pendingAction.kind === "revoke" && `Retirer le VIP à ${pendingAction.user.username} ?`}
              {pendingAction.kind === "deactivate" && `Désactiver le compte de ${pendingAction.user.username} ?`}
            </h3>
            <p className="text-sm opacity-70">
              {pendingAction.kind === "grant" && (
                <>Un email de notification sera envoyé à <code>{pendingAction.user.email}</code>.</>
              )}
              {pendingAction.kind === "revoke" && (
                <>Le compte redevient member standard. Un email de notification sera envoyé.</>
              )}
              {pendingAction.kind === "deactivate" && (
                <>Le compte est désactivé (is_active=false) — il ne pourra plus se connecter. Réversible côté DB.</>
              )}
            </p>
            {pendingAction.kind === "grant" && (
              <label className="block">
                <span className="text-xs opacity-70 mb-1 block">
                  Durée VIP en jours (optionnel — vide = illimité)
                </span>
                <GlassInput
                  type="number"
                  min={1}
                  max={3650}
                  placeholder="30"
                  value={durationDays}
                  onChange={(e) => setDurationDays(e.target.value)}
                />
              </label>
            )}
            <div className="flex items-center justify-end gap-2 pt-2">
              <GlassButton variant="ghost" size="sm"
                onClick={() => setPendingAction(null)}
                disabled={mutating}>
                Annuler
              </GlassButton>
              <GlassButton
                variant={pendingAction.kind === "deactivate" ? "danger" : "primary"}
                size="sm"
                onClick={commitAction}
                disabled={mutating}>
                {mutating ? "…" : "Confirmer"}
              </GlassButton>
            </div>
          </div>
        </GlassModal>
      )}
    </AdminShell>
  );
}
