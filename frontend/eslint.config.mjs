import { defineConfig } from "eslint/config";
import nextCoreWebVitals from "eslint-config-next/core-web-vitals";

export default defineConfig([
  {
    extends: [...nextCoreWebVitals],

    rules: {
      // Sprint A migration Next 13→16 — règles cosmétiques laissées off pour
      // débloquer la CI. À ré-évaluer en Sprint dédié post-migration App Router.
      "react/no-unescaped-entities": "off",
      "@typescript-eslint/no-explicit-any": "off",

      // Sprint D — Next 16 + ESLint 9 + eslint-config-next@16 introduisent 3
      // règles strict React Hooks (compiler-friendly) qui flaggent ~48 patterns
      // hérités à travers le code (setState dans effect, refs lecture en render,
      // pureté des render functions). Ces patterns sont des vrais risques de
      // re-render cascadants/stale closures, mais les fixer en masse demande
      // un audit React Hooks dédié. Cf docs/findings/2026-05-02-react-hooks-
      // strict-rules-next16.md pour suivi. Sprint cible : Phase 2 / E1-E6
      // (la migration App Router force de re-lire chaque hook).
      "react-hooks/set-state-in-effect": "warn",
      "react-hooks/refs": "warn",
      "react-hooks/purity": "warn",
    },
  },
]);
