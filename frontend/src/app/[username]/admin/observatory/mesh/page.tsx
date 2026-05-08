import type { Metadata } from "next";

import { ObservatoryMeshClient } from "./_client";

export const metadata: Metadata = {
  title: "Observatory · Mesh — Shugu Admin",
};

export default function AdminObservatoryMeshPage() {
  return <ObservatoryMeshClient />;
}
