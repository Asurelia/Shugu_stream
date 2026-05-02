import type { Metadata } from "next";
import { ProfileClient } from "./_client";

export const metadata: Metadata = {
  title: "Mon compte — Shugu",
};

export default function ProfilePage() {
  return <ProfileClient />;
}
