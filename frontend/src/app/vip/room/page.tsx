/**
 * /vip/room — App Router migration (Sprint E3).
 *
 * Server Component shell that exports `metadata` for SEO. The actual
 * LiveKit room logic lives in `_client.tsx` (Client Component) because it
 * uses `useState`, `useEffect`, and `useRouter()` from next/navigation.
 *
 * Pattern adopted across Sprint E2-E3 migration : prefer Server shell
 * + small Client island over `"use client"` at page top, so each page's
 * metadata stays statically rendered.
 */
import type { Metadata } from "next";
import { VipRoomClient } from "./_client";

export const metadata: Metadata = {
  title: "VIP Room — Shugu",
};

export default function VipRoomPage() {
  return <VipRoomClient />;
}
