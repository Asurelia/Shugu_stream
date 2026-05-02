import type { Metadata } from "next";

import { AccountClient } from "./_client";

export const metadata: Metadata = {
  title: "Mon compte — Shugu",
};

export default function AccountPage() {
  return <AccountClient />;
}
