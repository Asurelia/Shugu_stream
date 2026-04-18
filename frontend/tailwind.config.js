const { light, dark } = require("@charcoal-ui/theme");
const { createTailwindConfig } = require("@charcoal-ui/tailwind-config");
/**
 * Shugu stream UI — Hololive-kawaii palette.
 *   pink / pink-soft  → LIVE badge, actions, Hermes mode
 *   blue / lavender   → accent secondaire, chat messages, halos
 *   cream             → texte sur fond sombre
 *   ink / ink-soft    → backgrounds
 */
module.exports = {
  darkMode: true,
  content: ["./src/**/*.tsx", "./src/**/*.html"],
  presets: [
    createTailwindConfig({
      version: "v3",
      theme: {
        ":root": light,
      },
    }),
  ],
  theme: {
    // Restore the standard Tailwind breakpoints. The charcoal-ui preset
    // replaces `screens` with `screen1..screen5`, so without this the entire
    // `sm:/md:` system silently no-ops (leading to the famous "chat panel
    // stuck bottom, toggle invisible" bug pre-v3).
    screens: {
      sm: "640px",
      md: "768px",
      lg: "1024px",
      xl: "1280px",
      "2xl": "1536px",
    },
    extend: {
      colors: {
        shugu: {
          pink: "#FF617F",
          "pink-soft": "#FFA8B9",
          "pink-glow": "#FF8FA5",
          blue: "#A8C5FF",
          "blue-soft": "#CFE0FF",
          lavender: "#D8B4FE",
          cream: "#FFF8F1",
          "cream-dim": "rgba(255, 248, 241, 0.72)",
          ink: "#1A0A20",
          "ink-soft": "#2A1437",
          "ink-card": "rgba(42, 20, 55, 0.72)",
          live: "#FF3B5C",
        },
        primary: "#FF617F",
        secondary: "#A8C5FF",
      },
      fontFamily: {
        quicksand: ["var(--font-quicksand)"],
        comfortaa: ["var(--font-comfortaa)"],
      },
      animation: {
        "dreamy-shift": "dreamyShift 20s ease-in-out infinite",
        "live-pulse": "livePulse 1.6s ease-in-out infinite",
        "sparkle-float": "sparkleFloat 8s ease-in-out infinite",
        "bubble-pop": "bubblePop 250ms cubic-bezier(0.34, 1.56, 0.64, 1) both",
        "fade-up": "fadeUp 280ms ease-out both",
        "fade-out-up": "fadeOutUp 350ms ease-in both",
      },
      keyframes: {
        dreamyShift: {
          "0%, 100%": { "background-position": "0% 50%" },
          "50%": { "background-position": "100% 50%" },
        },
        livePulse: {
          "0%, 100%": { transform: "scale(1)", opacity: "1" },
          "50%": { transform: "scale(1.15)", opacity: "0.7" },
        },
        sparkleFloat: {
          "0%, 100%": { transform: "translateY(0) rotate(0deg)", opacity: "0.55" },
          "50%": { transform: "translateY(-28px) rotate(12deg)", opacity: "0.9" },
        },
        bubblePop: {
          "0%": { transform: "scale(0.85)", opacity: "0" },
          "100%": { transform: "scale(1)", opacity: "1" },
        },
        fadeUp: {
          "0%": { transform: "translateY(8px)", opacity: "0" },
          "100%": { transform: "translateY(0)", opacity: "1" },
        },
        fadeOutUp: {
          "0%": { transform: "translateY(0)", opacity: "1" },
          "100%": { transform: "translateY(-12px)", opacity: "0" },
        },
      },
    },
  },
  plugins: [require("@tailwindcss/line-clamp")],
};
