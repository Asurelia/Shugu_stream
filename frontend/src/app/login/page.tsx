import type { Metadata } from "next";
import { LoginClient } from "./_client";

export const metadata: Metadata = {
  title: "Connexion opérateur — Shugu",
};

export default function LoginPage() {
  return <LoginClient />;
}
