"use client";

/**
 * AdminAuthGuard — wrap minimal "êtes-vous operator ?" pour les pages admin.
 *
 * Extrait de `AdminShell.tsx` (ligne 57-74) qui couplait l'auth guard avec
 * la rail sidebar + le header + le container `lg-page`. Le Scene Editor
 * Unity-style prend 100 % du viewport et ne veut RIEN de l'AdminShell visuel,
 * mais a quand même besoin de garantir qu'un visiteur non authentifié ne
 * puisse pas atteindre `/[username]/admin/scene-editor`.
 *
 * Pattern :
 *   1. On lance `fetchAuthStatus()` au mount (1 HTTP call vers `/auth/me`).
 *   2. Tant que le check est en cours, on rend un placeholder minimal
 *      (écran sombre pleine page sans chrome — évite le flash d'une UI
 *      partielle qui serait redirigée).
 *   3. Si pas d'operator → redirect `/login`.
 *   4. Si operator.username ≠ URL :username → redirect vers la cible
 *      déterminée par `redirectPath` (explicite) ou par le défaut intelligent
 *      : on garde la page courante mais on remplace le segment username par
 *      celui de l'operator connecté (`/{operator.username}/admin/{page…}`).
 *      Cela évite que le guard soit hardcodé sur une page spécifique.
 *   5. Sinon on rend `children` avec `operator` en prop (pour que la page
 *      en descente puisse afficher le username sans refetch).
 *
 * Ce composant NE rend aucun chrome propre : c'est intentionnel pour
 * préserver le plein écran du Scene Editor. Les autres pages admin qui
 * veulent la sidebar continuent d'utiliser `AdminShell` qui garde son guard
 * inline (la duplication est consciemment acceptée pour ne pas casser les
 * 7 pages admin existantes dans cette PR).
 */

import { useRouter, useParams, usePathname } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { fetchAuthStatus } from "@/services/shuguClient";

export type Operator = { username: string; is_operator: boolean };

type Props = {
  /** Si fourni, le children n'est monté qu'après auth success. */
  children: (operator: Operator) => ReactNode;
  /**
   * Placeholder pendant le check auth. Par défaut un écran noir minimal
   * aligné sur le chrome IDE du Scene Editor (`#05050a`). Les pages qui
   * veulent un autre fond peuvent surcharger.
   */
  fallback?: ReactNode;
  /**
   * Cible du redirect sur mismatch username (l'operator connecté n'est pas
   * le propriétaire de l'URL courante).
   *
   * - Si fourni : utilisé tel quel (override explicite).
   * - Si absent : défaut intelligent — on reconstruit la même page en
   *   remplaçant le segment username par celui de l'operator connecté.
   *   Ex. `/john/admin/analytics` → `/{operator.username}/admin/analytics`.
   *   Retombe sur `/{operator.username}/admin` si le pathname n'est pas
   *   parseable (null lors d'une transition SSR, etc.).
   *
   * @default `/{operator.username}/admin/{currentPage}` (segment reconstruit)
   */
  redirectPath?: string;
};

const DEFAULT_FALLBACK = (
  <div
    style={{
      position: "fixed",
      inset: 0,
      background: "#05050a",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      color: "rgba(255,255,255,0.35)",
      fontFamily: "system-ui, -apple-system, sans-serif",
      fontSize: 12,
      letterSpacing: "0.08em",
      textTransform: "uppercase",
    }}
  >
    <span>Authentification…</span>
  </div>
);

export function AdminAuthGuard({
  children,
  fallback = DEFAULT_FALLBACK,
  redirectPath,
}: Props) {
  const router = useRouter();
  const params = useParams<{ username?: string }>();
  const urlUsername = params?.username;
  const pathname = usePathname();

  const [operator, setOperator] = useState<Operator | null>(null);
  const [authChecked, setAuthChecked] = useState(false);

  // Fetch auth status une fois au mount. Cancel-safe en cas d'unmount rapide.
  useEffect(() => {
    let cancelled = false;
    fetchAuthStatus().then((me) => {
      if (cancelled) return;
      setOperator(me);
      setAuthChecked(true);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  // Redirect selon le résultat du check. Même flow que AdminShell pour
  // garantir une expérience cohérente entre les pages admin.
  useEffect(() => {
    if (!authChecked) return;
    if (!operator) {
      router.replace("/login");
      return;
    }
    // S1 fix: members who now get a 200 from /auth/me must not reach admin pages.
    if (!operator.is_operator) {
      router.replace("/");
      return;
    }
    if (!urlUsername) return;
    if (operator.username.toLowerCase() !== urlUsername.toLowerCase()) {
      // Calcul de la cible du redirect :
      //   1. Si `redirectPath` est fourni explicitement, l'utiliser tel quel.
      //   2. Sinon, construire un redirect intelligent en gardant la même page
      //      mais en remplaçant le segment username par celui de l'operator
      //      connecté. Ex. `/john/admin/analytics` → `/{op}/admin/analytics`.
      //   3. Si `pathname` est null/invalide (transition SSR), se replier sur
      //      `/{op}/admin` pour rester dans la zone admin sans boucle.
      let target: string;
      if (redirectPath !== undefined) {
        target = redirectPath;
      } else {
        const segs = (pathname ?? "").split("/").filter(Boolean);
        if (segs.length > 0) {
          segs[0] = encodeURIComponent(operator.username);
          target = "/" + segs.join("/");
        } else {
          target = `/${encodeURIComponent(operator.username)}/admin`;
        }
      }
      router.replace(target);
    }
  }, [authChecked, operator, urlUsername, router, pathname, redirectPath]);

  // Pendant le check OU tant que le mismatch redirect n'a pas fini, on
  // reste sur le fallback. `children` n'est jamais monté pour un visiteur
  // non authentifié (évite la fuite des mocks / du chrome IDE).
  if (!authChecked || !operator) return <>{fallback}</>;
  if (!operator.is_operator) return <>{fallback}</>;
  if (urlUsername && operator.username.toLowerCase() !== urlUsername.toLowerCase()) {
    return <>{fallback}</>;
  }

  return <>{children(operator)}</>;
}
