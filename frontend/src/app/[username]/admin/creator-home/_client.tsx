"use client";

/**
 * Creator Home client island.
 *
 * Migration Pages Router → App Router (Sprint E5) :
 *   - `useRouter` de `next/router` remplacé par `useRouter` + `useParams`
 *     de `next/navigation`.
 *   - `<Head>` + `<Meta>` supprimés — métadonnées déclarées dans `page.tsx`.
 *   - `router.query.username` remplacé par `useParams<{ username?: string }>()`.
 *   - `router.query.preview` remplacé par `useSearchParams()`.
 */
import { useEffect, useState } from "react";
import { useRouter, useParams, useSearchParams } from "next/navigation";

import { fetchAuthStatus } from "@/services/shuguClient";
import CreatorHomeShell from "@/features/creator-home/CreatorHomeShell";

export function CreatorHomeClient() {
  const router = useRouter();
  const params = useParams<{ username?: string }>();
  const searchParams = useSearchParams();
  const urlUsername = params?.username;
  // `?preview=1` permet de voir le design sans être connecté — utile pour
  // itérer sur le visuel avant d&apos;avoir un backend auth stable.
  const previewMode = searchParams?.get("preview") === "1";
  const [operator, setOperator] = useState<{ username: string; is_operator: boolean } | null>(null);
  const [authChecked, setAuthChecked] = useState(false);

  /* eslint-disable react-hooks/set-state-in-effect -- FIXME P5: fetch-on-mount auth check, cancelled flag prevents stale updates */
  useEffect(() => {
    if (previewMode) { setAuthChecked(true); return; }
    let cancelled = false;
    fetchAuthStatus().then((me) => {
      if (cancelled) return;
      setOperator(me);
      setAuthChecked(true);
    });
    return () => { cancelled = true; };
  }, [previewMode]);
  /* eslint-enable react-hooks/set-state-in-effect */

  useEffect(() => {
    if (previewMode) return;
    if (!authChecked || !urlUsername) return;
    if (!operator) { router.replace("/login"); return; }
    // S1 fix: members who now get a 200 from /auth/me must not reach admin pages.
    if (!operator.is_operator) { router.replace("/"); return; }
    if (operator.username.toLowerCase() !== urlUsername.toLowerCase()) {
      router.replace(`/${encodeURIComponent(operator.username)}/admin/creator-home`);
    }
  }, [previewMode, authChecked, operator, urlUsername, router]);

  // Nécessaire pour que `body { overflow: hidden }` s&apos;applique seulement sur
  // cette page (le shell est plein écran, on veut éviter une scrollbar).
  useEffect(() => {
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = prev; };
  }, []);

  return (
    <>
      {authChecked && (operator || previewMode) ? (
        <CreatorHomeShell />
      ) : (
        <div style={{
          width: "100vw", height: "100vh",
          display: "flex", alignItems: "center", justifyContent: "center",
          color: "#a5a0bf", fontFamily: "sans-serif", fontSize: 14,
        }}>
          chargement…
        </div>
      )}
    </>
  );
}
