import "@/styles/globals.css";
import "@/styles/celestial-veil-tokens.css";
import "@/styles/liquid-glass.css";
import "@/styles/viewer-proto.css";
import type { AppProps } from "next/app";
import "@charcoal-ui/icons";
import { Quicksand, Comfortaa, Plus_Jakarta_Sans, Inter, JetBrains_Mono } from "next/font/google";
import { DesktopProvider } from "@/features/desktop/desktopState";

// Cinq familles exposées comme variables CSS. Les pages admin n'avaient
// pas accès à `--font-display` / `--font-body` quand elles étaient déclarées
// page-par-page : on centralise ici pour que la palette Celestial Veil
// s'applique partout sans boilerplate. JetBrains Mono vient avec le redesign
// Liquid Glass chat (labels mono, timestamps, ts-label, hud-btn).
const quicksand = Quicksand({
  variable: "--font-quicksand", subsets: ["latin"], display: "swap",
  weight: ["400", "500", "600", "700"],
});
const comfortaa = Comfortaa({
  variable: "--font-comfortaa", subsets: ["latin"], display: "swap",
  weight: ["500", "600", "700"],
});
const plusJakarta = Plus_Jakarta_Sans({
  variable: "--font-display", subsets: ["latin"], display: "swap",
  weight: ["500", "600", "700", "800"],
});
const interFont = Inter({
  variable: "--font-body", subsets: ["latin"], display: "swap",
  weight: ["400", "500", "600"],
});
const jetbrainsMono = JetBrains_Mono({
  variable: "--font-mono", subsets: ["latin"], display: "swap",
  weight: ["400", "500", "600"],
});

export default function App({ Component, pageProps }: AppProps) {
  return (
    <div className={`${quicksand.variable} ${comfortaa.variable} ${plusJakarta.variable} ${interFont.variable} ${jetbrainsMono.variable}`}>
      <DesktopProvider>
        <Component {...pageProps} />
      </DesktopProvider>
    </div>
  );
}
