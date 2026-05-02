import type { Metadata } from "next";

import { ScheduleClient } from "./_client";

export const metadata: Metadata = {
  title: "Schedule — Shugu Admin",
};

export default function SchedulePage() {
  return <ScheduleClient />;
}
