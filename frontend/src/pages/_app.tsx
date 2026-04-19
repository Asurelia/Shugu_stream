import "@/styles/globals.css";
import type { AppProps } from "next/app";
import "@charcoal-ui/icons";
import { DesktopProvider } from "@/features/desktop/desktopState";

export default function App({ Component, pageProps }: AppProps) {
  return (
    <DesktopProvider>
      <Component {...pageProps} />
    </DesktopProvider>
  );
}
