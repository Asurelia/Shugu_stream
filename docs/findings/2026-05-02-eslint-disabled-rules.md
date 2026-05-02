---
date: 2026-05-02
status: open
severity: low
discovered_during: PR #76 (Sprint A migration Next 13→16)
related_files:
  - frontend/.eslintrc.json
---

## Résumé

PR #76 a désactivé 2 règles ESLint globalement pour permettre la CI de passer. Ces règles devraient idéalement être ré-activées :

```json
{
  "rules": {
    "react/no-unescaped-entities": "off",
    "@typescript-eslint/no-explicit-any": "off"
  }
}
```

## Détail des 2 règles

### `react/no-unescaped-entities`

**10 occurrences** dans le code (8 fichiers) — apostrophes/quotes en JSX texte (français : "n'a", "c'est", quotes typographiques).

Exemples :
```tsx
<p>L'application n'a pas pu démarrer.</p>
//   ^                ^
// react/no-unescaped-entities flagge les apostrophes
```

**Pourquoi désactivé** : règle cosmétique purement syntaxique. Les apostrophes/quotes JSX rendent correctement dans le DOM, c'est juste du nitpick pour la "pureté" HTML strict.

**Risque réel** : très faible. Les browsers traitent ces caractères correctement.

### `@typescript-eslint/no-explicit-any`

**Plugin `@typescript-eslint/eslint-plugin` non installé** (cf finding `typescript-eslint-plugin-missing.md`). 7 commentaires `eslint-disable-next-line` référençaient cette règle, mais sans le plugin elle n'existe pas.

**Pourquoi désactivé** : éviter erreur "Definition for rule was not found" sans devoir installer le plugin maintenant.

**Risque réel** : moyen. Cette règle catch les `any` explicites qui sont des shortcut typing — souvent symptômes de typing incorrect ailleurs.

## Action recommandée

**Sprint B/C/D (bumps Next)** :

1. **Pour `@typescript-eslint/no-explicit-any`** : installer le plugin et ré-activer en `"warn"` (pas `"error"` pour ne pas bloquer Sprint B). Voir finding `typescript-eslint-plugin-missing.md` pour la manip.

2. **Pour `react/no-unescaped-entities`** : décision à prendre — soit garder désactivée (cosmétique), soit fixer les 10 occurrences. Option 1 est OK si l'équipe valide que c'est un choix conscient.

**Phase 2 (App Router migration)** : à minima documenter dans `frontend/.eslintrc.json` un commentaire (oui ESLint accepte les commentaires JSON5 avec extensions) ou un README à côté pour expliquer pourquoi ces règles sont off.

## Visibilité

Le `.eslintrc.json` actuel **n'explique pas** pourquoi les règles sont
désactivées. Un dev arrivant frais ne sait pas si c'est intentionnel ou
un oubli. À terme, soit :
- Ajouter un fichier `.eslintrc.json5` avec commentaires,
- Soit migrer vers flat config `eslint.config.js` (Sprint D : ESLint 9)
  qui supporte JS et donc commentaires.
