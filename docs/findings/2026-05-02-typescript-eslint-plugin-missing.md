---
date: 2026-05-02
status: open
severity: high
discovered_during: PR #76 (Sprint A migration Next 13→16)
related_files:
  - frontend/.eslintrc.json
  - frontend/src/features/scene-composer/viewer/three-stage/transform-controls.ts
  - frontend/src/lib/__tests__/editorPopout.test.ts
  - frontend/package.json
---

## Résumé

Le code source contient 7 commentaires `// eslint-disable-next-line @typescript-eslint/no-explicit-any` mais le plugin `@typescript-eslint/eslint-plugin` n'a JAMAIS été installé dans `frontend/package.json`. ESLint tombait en erreur "Definition for rule was not found".

## Symptôme observé

```
./src/features/scene-composer/viewer/three-stage/transform-controls.ts
116:3  Error: Definition for rule '@typescript-eslint/no-explicit-any' was not found.
127:3  Error: Definition for rule '@typescript-eslint/no-explicit-any' was not found.
153:7  Error: Definition for rule '@typescript-eslint/no-explicit-any' was not found.
155:7  Error: Definition for rule '@typescript-eslint/no-explicit-any' was not found.

./src/lib/__tests__/editorPopout.test.ts
441:5  Error: Definition for rule '@typescript-eslint/no-explicit-any' was not found.
443:5  Error: Definition for rule '@typescript-eslint/no-explicit-any' was not found.
456:7  Error: Definition for rule '@typescript-eslint/no-explicit-any' was not found.
```

## Cause racine probable

Quelqu'un a écrit du code en pensant que la règle `@typescript-eslint/no-explicit-any`
était active (probablement par habitude d'autres projets avec `eslint-config-next` +
typescript-eslint), mais a oublié d'installer le plugin. `eslint-config-next@13.2.4`
inclut `next/core-web-vitals` qui fournit certaines règles TypeScript de base
mais PAS le plugin complet `@typescript-eslint`.

## Impact

- Les `any` explicites dans `transform-controls.ts` et `editorPopout.test.ts`
  ne sont pas vérifiés (la règle n'est jamais évaluée).
- ESLint plante en erreur en mode strict.
- Implicitement : il y a peut-être d'autres règles `@typescript-eslint/*`
  qui auraient flaggé du code mais ne tournent pas.

## Mitigation appliquée (PR #76)

Les 7 commentaires `eslint-disable-next-line @typescript-eslint/no-explicit-any`
ont été remplacés par `eslint-disable-next-line` (sans cible). Ça désactive
toutes les règles pour la ligne, ce qui est moins ciblé mais débloque ESLint
sans installer de dep. Combiné avec `"@typescript-eslint/no-explicit-any": "off"`
dans `.eslintrc.json` (préventif).

## Action recommandée

**Sprint B (13→14) ou Sprint C (14→15)** :

1. Installer le plugin :
   ```bash
   cd frontend
   npm install --save-dev @typescript-eslint/eslint-plugin @typescript-eslint/parser
   ```
   Versions compatibles ESLint 8.36 + TS 5.0 : `^6.21.0`. Avec ESLint 9 (Next 15+),
   bump à `^7.x`.

2. Configurer `.eslintrc.json` :
   ```json
   {
     "extends": [
       "next/core-web-vitals",
       "plugin:@typescript-eslint/recommended"
     ],
     "rules": {
       "@typescript-eslint/no-explicit-any": "warn"
     }
   }
   ```

3. Restaurer les `eslint-disable-next-line @typescript-eslint/no-explicit-any`
   ciblés sur les 7 emplacements (mieux qu'un disable global pour la ligne).

4. Audit du code : faire un `npm run lint` après installation pour révéler
   les `any` non taggés. Probablement plusieurs dizaines.

## Risque si non traité

- Friction sur le bump ESLint 9 en Sprint D : la lib peut avoir changé
  d'API et les commentaires sans cible peuvent être encore plus permissifs.
- Perte d'opportunité de catcher des bugs : `any` explicites sont souvent
  des shortcuts qui cachent du code typé incorrectement.
