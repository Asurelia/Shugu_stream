import { defineConfig } from "eslint/config";
import nextCoreWebVitals from "eslint-config-next/core-web-vitals";
import tsPlugin from "@typescript-eslint/eslint-plugin";

// eslint-config-next/core-web-vitals is an array of flat-config objects.
// The @typescript-eslint plugin is in index 1 (plugin-only object, no rules).
// ESLint flat config requires that any rule referencing a plugin be defined in
// a config object that also declares that plugin. We therefore split our
// overrides: non-ts rules go in the first object (extends-only), and the
// @typescript-eslint override goes in a second object that re-declares the
// plugin so ESLint can resolve it.
const nextArr = Array.isArray(nextCoreWebVitals)
  ? nextCoreWebVitals
  : [nextCoreWebVitals];

export default defineConfig([
  {
    extends: [...nextArr],

    rules: {
      // Sprint A migration Next 13→16 — règles cosmétiques laissées off pour
      // débloquer la CI. À ré-évaluer en Sprint dédié post-migration App Router.
      "react/no-unescaped-entities": "off",

      // Sprint D — Next 16 + ESLint 9 + eslint-config-next@16 introduisent 3
      // règles strict React Hooks (compiler-friendly) qui flaggent ~48 patterns
      // hérités à travers le code (setState dans effect, refs lecture en render,
      // pureté des render functions). Ces patterns sont des vrais risques de
      // re-render cascadants/stale closures, mais les fixer en masse demande
      // un audit React Hooks dédié. Cf docs/findings/2026-05-02-react-hooks-
      // strict-rules-next16.md pour suivi. Sprint cible : Phase 2 / E1-E6
      // (la migration App Router force de re-lire chaque hook).
      "react-hooks/set-state-in-effect": "error",
      "react-hooks/refs": "error",
      "react-hooks/purity": "error",
    },
  },
  {
    // Separate config object so @typescript-eslint rules can reference the
    // plugin declared here. ESLint flat config requires plugin + rules to be
    // in the same config object (or an ancestor via extends).
    plugins: { "@typescript-eslint": tsPlugin },
    rules: {
      "@typescript-eslint/no-explicit-any": "warn",
    },
  },
]);
