import type { Metadata } from "next";

import { MissionsClient } from "./_client";

export const metadata: Metadata = {
  title: "Missions Kanban — Shugu Admin",
};

export default function AdminObservatoryMissionsPage() {
  return <MissionsClient />;
}
