/**
 * /account/verify-email — App Router migration (Sprint E2).
 *
 * Server Component shell : declares static `metadata` and wraps the
 * client island in `<Suspense>`. Required by Next 14+ App Router :
 * pages that read query params via `useSearchParams()` must sit under
 * a Suspense boundary so the static prerender can bail out gracefully
 * (otherwise `next build` errors with "missing-suspense-with-csr-bailout").
 *
 * The fallback mirrors the loading state of `_client.tsx` so the user
 * perceives a single seamless loading screen during the brief CSR
 * bailout window.
 */
import type { Metadata } from "next";
import { Suspense } from "react";

import { GlassCard } from "@/features/liquid-glass/primitives";

import { VerifyEmailClient } from "./_client";

export const metadata: Metadata = {
  title: "Vérification email — Shugu",
};

function VerifyEmailFallback() {
  return (
    <div className="lg-page min-h-screen flex items-center justify-center p-6">
      <GlassCard className="max-w-md w-full text-center" padded>
        <h1 className="text-2xl font-light tracking-tight text-shugu-cream mb-2">
          Vérification…
        </h1>
        <p className="text-sm opacity-70">Un instant, on valide ton lien.</p>
      </GlassCard>
    </div>
  );
}

export default function VerifyEmailPage() {
  return (
    <Suspense fallback={<VerifyEmailFallback />}>
      <VerifyEmailClient />
    </Suspense>
  );
}
