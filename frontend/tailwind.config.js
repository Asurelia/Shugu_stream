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
    // Restore le scale `spacing` standard Tailwind. Charcoal redéfinit
    // `spacing` en valeurs pixel directes (0→0, 4→4px, 8→8px, 16→16px, etc.)
    // ce qui casse TOUT `h-16` / `top-24` / `bottom-12` / `space-x-6` en les
    // rendant soit minuscules soit ignorés. On remet le scale par défaut de
    // Tailwind ici — indispensable dès qu'on écrit des layouts modernes.
    //
    // Note : Charcoal redéfinit AUSSI `width` / `height` / `padding` / `margin`
    // à côté de `spacing`. Les override ci-dessous (dans le même theme root)
    // restaurent la dérivation standard depuis `spacing`.
    width:   (t) => ({ auto: "auto", full: "100%", screen: "100vw", min: "min-content", max: "max-content", fit: "fit-content", ...t("spacing") }),
    height:  (t) => ({ auto: "auto", full: "100%", screen: "100vh", svh: "100svh", dvh: "100dvh", min: "min-content", max: "max-content", fit: "fit-content", ...t("spacing") }),
    minWidth:  (t) => ({ 0: "0px", full: "100%", min: "min-content", max: "max-content", fit: "fit-content", ...t("spacing") }),
    minHeight: (t) => ({ 0: "0px", full: "100%", svh: "100svh", screen: "100vh", min: "min-content", max: "max-content", fit: "fit-content", ...t("spacing") }),
    maxWidth:  (t) => ({ none: "none", xs: "20rem", sm: "24rem", md: "28rem", lg: "32rem", xl: "36rem", "2xl": "42rem", "3xl": "48rem", "4xl": "56rem", "5xl": "64rem", "6xl": "72rem", "7xl": "80rem", full: "100%", screen: "100vw", prose: "65ch", ...t("spacing") }),
    maxHeight: (t) => ({ none: "none", full: "100%", screen: "100vh", svh: "100svh", ...t("spacing") }),
    padding: (t) => t("spacing"),
    margin:  (t) => ({ auto: "auto", ...t("spacing"), ...Object.fromEntries(Object.entries(t("spacing")).filter(([k]) => k !== "px" && k !== "0").map(([k, v]) => ["-" + k, `-${v}`])) }),
    inset:   (t) => ({ auto: "auto", full: "100%", ...t("spacing") }),
    gap:     (t) => t("spacing"),
    // Charcoal preset supprime le scale `borderRadius` standard de Tailwind :
    // seul `.rounded-none` reste, donc `rounded-full`/`rounded-xl`/etc. sont
    // silencieusement inertes (le bouton send apparaît carré au lieu de rond,
    // le rail chat handle n'a plus son coin arrondi, etc.). On rétablit le
    // scale Tailwind par défaut ici — safe car aucun code n'exploite l'absence
    // de ces utilities, et indispensable pour les UI récentes.
    borderRadius: {
      none: "0px",
      sm: "0.125rem",
      DEFAULT: "0.25rem",
      md: "0.375rem",
      lg: "0.5rem",
      xl: "0.75rem",
      "2xl": "1rem",
      "3xl": "1.5rem",
      full: "9999px",
    },
    spacing: {
      px: "1px",
      0: "0px",
      0.5: "0.125rem",
      1: "0.25rem",
      1.5: "0.375rem",
      2: "0.5rem",
      2.5: "0.625rem",
      3: "0.75rem",
      3.5: "0.875rem",
      4: "1rem",
      5: "1.25rem",
      6: "1.5rem",
      7: "1.75rem",
      8: "2rem",
      9: "2.25rem",
      10: "2.5rem",
      11: "2.75rem",
      12: "3rem",
      14: "3.5rem",
      16: "4rem",
      20: "5rem",
      24: "6rem",
      28: "7rem",
      32: "8rem",
      36: "9rem",
      40: "10rem",
      44: "11rem",
      48: "12rem",
      52: "13rem",
      56: "14rem",
      60: "15rem",
      64: "16rem",
      72: "18rem",
      80: "20rem",
      96: "24rem",
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
        // Celestial Veil — palette officielle (alignée sur le HTML Stitch).
        celestial: {
          purple:  "#b585ff",
          pink:    "#e879f9",
          overlay: "#0a0a0f",
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
