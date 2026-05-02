import type { Metadata } from "next";

import { CreatorHomeClient } from "./_client";

export const metadata: Metadata = {
  title: "Shugu · Creator Home",
};

export default function CreatorHomePage() {
  return <CreatorHomeClient />;
}
