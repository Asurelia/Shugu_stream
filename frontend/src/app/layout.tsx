/**
 * Root layout — App Router (Sprint E1 bootstrap).
 *
 * Mirrors what `pages/_app.tsx` + `pages/_document.tsx` did under Pages Router :
 *   - Global CSS imports (only allowed in this file under App Router).
 *   - 5 next/font/google families exposed as CSS variables.
 *   - `<html lang="fr">` + `<body className="shugu-body">` (was in _document).
 *   - Client providers mounted via the `<ClientProviders>` boundary.
 *
 * Coexistence Pages Router : as long as `pages/*` exists, those routes keep
 * being served by Pages Router — App Router only takes over the overlapping
 * routes. Sprint E2-E6 migrate page by page.
 *
 * `metadata` export replaces the `<Head>` tags from _document.tsx and the
 * default `<Meta>` component. Per-page metadata can override these via
 * `export const metadata` in each `app/<route>/page.tsx`.
 */
import type { Metadata, Viewport } from "next";
import { Comfortaa, Inter, JetBrains_Mono, Plus_Jakarta_Sans, Quicksand } from "next/font/google";
import type { ReactNode } from "react";

import { ClientProviders } from "./providers";

import "@/styles/globals.css";
import "@/styles/celestial-veil-tokens.css";
import "@/styles/liquid-glass.css";
import "@/styles/viewer-proto.css";
import "@/styles/scene-editor.css";
import "@/features/scene-editor-v2/styles.css";
import "@charcoal-ui/icons";

// Five font families exposed as CSS variables (mirror _app.tsx).
const quicksand = Quicksand({
  variable: "--font-quicksand",
  subsets: ["latin"],
  display: "swap",
  weight: ["400", "500", "600", "700"],
});
const comfortaa = Comfortaa({
  variable: "--font-comfortaa",
  subsets: ["latin"],
  display: "swap",
  weight: ["500", "600", "700"],
});
const plusJakarta = Plus_Jakarta_Sans({
  variable: "--font-display",
  subsets: ["latin"],
  display: "swap",
  weight: ["500", "600", "700", "800"],
});
const interFont = Inter({
  variable: "--font-body",
  subsets: ["latin"],
  display: "swap",
  weight: ["400", "500", "600"],
});
const jetbrainsMono = JetBrains_Mono({
  variable: "--font-mono",
  subsets: ["latin"],
  display: "swap",
  weight: ["400", "500", "600"],
});

export const metadata: Metadata = {
  // metadataBase resolves relative og:image / twitter:image URLs at build time.
  // Falls back to localhost:3000 if NEXT_PUBLIC_SITE_URL is unset, which
  // matches the warning suppression Next 14+ expects.
  metadataBase: new URL(
    process.env.NEXT_PUBLIC_SITE_URL ?? "https://shugu.spoukie.uk",
  ),
  title: "Shugu ♡ AI VTuber live",
  description:
    "Une VTubeuse IA 3D en direct. Discute avec Shugu — elle parle, bouge, réagit. Multi-viewers en direct sur shugu.spoukie.uk ✨",
  icons: {
    icon: { url: "/favicon.svg", type: "image/svg+xml" },
  },
  openGraph: {
    title: "Shugu ♡ AI VTuber live",
    description:
      "Une VTubeuse IA 3D en direct. Discute avec Shugu — elle parle, bouge, réagit. Multi-viewers en direct sur shugu.spoukie.uk ✨",
    images: [{ url: "/shugu-og.png" }],
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "Shugu ♡ AI VTuber live",
    description:
      "Une VTubeuse IA 3D en direct. Discute avec Shugu — elle parle, bouge, réagit. Multi-viewers en direct sur shugu.spoukie.uk ✨",
    images: ["/shugu-og.png"],
  },
};

// Next 14+ requires `themeColor` (and viewport bits) in a separate `viewport`
// export rather than mixed into `metadata` — split out for forward-compat.
export const viewport: Viewport = {
  themeColor: "#FF617F",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  const fontVars = `${quicksand.variable} ${comfortaa.variable} ${plusJakarta.variable} ${interFont.variable} ${jetbrainsMono.variable}`;

  return (
    <html lang="fr" className={fontVars}>
      <body className="shugu-body">
        <ClientProviders>{children}</ClientProviders>
      </body>
    </html>
  );
}
