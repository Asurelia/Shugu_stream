import type { Metadata } from "next";

import { AssetsClient } from "./_client";

export const metadata: Metadata = {
  title: "Asset Registry — Shugu Admin",
};

export default function AssetsPage() {
  return <AssetsClient />;
}
