import type { Metadata } from "next";

import { AdminUsersClient } from "./_client";

export const metadata: Metadata = {
  title: "Utilisateurs — Shugu Admin",
};

export default function AdminUsersPage() {
  return <AdminUsersClient />;
}
