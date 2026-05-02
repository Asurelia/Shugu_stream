/**
 * /account/login — App Router migration (Sprint E2).
 *
 * Server Component shell that exports `metadata` for SEO. The actual form
 * logic lives in `_client.tsx` (Client Component) because it uses
 * `useState` + `useRouter()` for navigation post-login.
 *
 * Pattern adopted across Sprint E2 auth migration : prefer Server shell
 * + small Client island over `"use client"` at page top, so each page's
 * metadata stays statically rendered.
 */
import type { Metadata } from "next";

import { LoginClient } from "./_client";

export const metadata: Metadata = {
  title: "Connexion — Shugu",
};

export default function LoginPage() {
  return <LoginClient />;
}
