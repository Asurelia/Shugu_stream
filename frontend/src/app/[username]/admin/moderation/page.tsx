import type { Metadata } from "next";

import { ModerationClient } from "./_client";

export const metadata: Metadata = {
  title: "Moderation Hub — Shugu Admin",
};

export default function ModerationPage() {
  return <ModerationClient />;
}
