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
        // Celestial Veil design system — "Luminous Etherealism".
        // Surface hierarchy: stacked frosted-glass layers, darker → lighter.
        // Never use 1px borders between these; rely on tonal shifts.
        veil: {
          "surface-dim":           "#0d0d18",
          "surface":               "#12121e",
          "surface-container-low": "#12121e",
          "surface-container":     "#1a1a28",
          "surface-container-high":"#1e1e2d",
          "surface-container-top": "#242434",
          "surface-bright":        "#2b2a3c",
          "on-surface":            "#ECE9F5",
          "on-surface-variant":    "#A8A4C0",
          "outline":               "#3a3a4a",
          "outline-variant":       "#474754",
          // Accents
          "primary":               "#e08efe",
          "primary-container":     "#d180ef",
          "primary-dim":           "#b87cd9",
          "secondary":             "#fd6c9c",
          "secondary-container":   "#e85f8b",
          "tertiary":              "#81ecff",
          "tertiary-container":    "#5fd4f0",
          "surface-tint":          "#e08efe",
        },
        primary: "#FF617F",
        secondary: "#A8C5FF",
      },
      backgroundImage: {
        "veil-primary": "linear-gradient(135deg, #e08efe 0%, #d180ef 100%)",
        "veil-secondary": "linear-gradient(135deg, #fd6c9c 0%, #e85f8b 100%)",
        "veil-tertiary": "linear-gradient(135deg, #81ecff 0%, #5fd4f0 100%)",
        "veil-header": "linear-gradient(90deg, rgba(224,142,254,0.18) 0%, rgba(129,236,255,0.08) 100%)",
      },
      boxShadow: {
        // Diffused rose-tinted halos instead of grey drop shadows.
        "veil-glow": "0 8px 30px rgba(224,142,254,0.15)",
        "veil-glow-lg": "0 14px 44px rgba(224,142,254,0.22)",
        "veil-glow-cyan": "0 8px 30px rgba(129,236,255,0.16)",
        "veil-pink-pulse": "0 0 0 0 rgba(253,108,156,0.55)",
      },
      fontFamily: {
        quicksand: ["var(--font-quicksand)"],
        comfortaa: ["var(--font-comfortaa)"],
        // Celestial Veil typography pair.
        display: ["'Plus Jakarta Sans'", "var(--font-quicksand)", "system-ui", "sans-serif"],
        body: ["'Inter'", "var(--font-quicksand)", "system-ui", "sans-serif"],
      },
      backdropBlur: {
        "veil-sm": "12px",
        "veil":    "20px",
        "veil-lg": "32px",
      },
      // NOTE: the `fontFamily` key is intentionally defined ONCE here. A previous
      // iteration of this file had a duplicate `fontFamily` block further up in
      // `extend`, which silently overrode the `display`/`body` entries declared
      // here (object-literal "last key wins" semantics). Keep it merged.
      animation: {
        "dreamy-shift": "dreamyShift 20s ease-in-out infinite",
        "live-pulse": "livePulse 1.6s ease-in-out infinite",
        "sparkle-float": "sparkleFloat 8s ease-in-out infinite",
        "bubble-pop": "bubblePop 250ms cubic-bezier(0.34, 1.56, 0.64, 1) both",
        "fade-up": "fadeUp 280ms ease-out both",
        "fade-out-up": "fadeOutUp 350ms ease-in both",
        // Celestial Veil additions: slow floating for persistent overlays.
        "veil-float": "veilFloat 6s ease-in-out infinite",
        "veil-pulse-glow": "veilPulseGlow 2s ease-in-out infinite",
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
        veilFloat: {
          "0%, 100%": { transform: "translateY(0)" },
          "50%":      { transform: "translateY(-5px)" },
        },
        veilPulseGlow: {
          "0%, 100%": { boxShadow: "0 0 0 0 rgba(224,142,254,0.45)" },
          "50%":      { boxShadow: "0 0 0 8px rgba(224,142,254,0)" },
        },
      },
    },
  },
  plugins: [require("@tailwindcss/line-clamp")],
};
