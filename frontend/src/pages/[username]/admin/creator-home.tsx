/**
 * `/{username}/admin/creator-home` — port du bundle Claude Design.
 *
 * Expose les 6 variations "Shugu Creator Home" que l'opérateur peut
 * parcourir avec 1-6 / ← → / T. Pour l'instant c'est un **aperçu design**
 * non-câblé aux données live — le but est d'affiner visuellement avant
 * de choisir la variation finale à promouvoir sur la page visiteur `/`.
 */
import Head from "next/head";
import { useEffect, useState } from "react";
import { useRouter } from "next/router";
import { fetchAuthStatus } from "@/services/shuguClient";
import CreatorHomeShell from "@/features/creator-home/CreatorHomeShell";

export default function CreatorHomePage() {
  const router = useRouter();
  const rawUsername = router.query.username;
  const urlUsername = Array.isArray(rawUsername) ? rawUsername[0] : rawUsername;
  // `?preview=1` permet de voir le design sans être connecté — utile pour
  // itérer sur le visuel avant d'avoir un backend auth stable.
  const previewMode = router.query.preview === "1";
  const [operator, setOperator] = useState<{ username: string } | null>(null);
  const [authChecked, setAuthChecked] = useState(false);

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

  useEffect(() => {
    if (previewMode) return;
    if (!authChecked || !urlUsername) return;
    if (!operator) { router.replace("/login"); return; }
    if (operator.username.toLowerCase() !== urlUsername.toLowerCase()) {
      router.replace(`/${encodeURIComponent(operator.username)}/admin/creator-home`);
    }
  }, [previewMode, authChecked, operator, urlUsername, router]);

  // Nécessaire pour que `body { overflow: hidden }` s'applique seulement sur
  // cette page (le shell est plein écran, on veut éviter une scrollbar).
  useEffect(() => {
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = prev; };
  }, []);

  return (
    <>
      <Head>
        <title>Shugu · Creator Home</title>
        <meta name="viewport" content="width=device-width, initial-scale=1" />
      </Head>
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
