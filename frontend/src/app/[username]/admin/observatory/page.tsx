import type { Metadata } from "next";

import { ObservatoryClient } from "./_client";

export const metadata: Metadata = {
  title: "Observatory — Shugu Admin",
};

export default function AdminObservatoryPage() {
  return <ObservatoryClient />;
}
