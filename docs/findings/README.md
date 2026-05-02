# Findings — registre des bugs/dette/incohérences détectés en chemin

Ce dossier collecte **tout problème, bug, mock incomplet, outil non appelé, incohérence ou dette technique** repéré pendant des travaux ciblés ailleurs, **mais pas immédiatement fixé** parce qu'hors scope. L'idée : ne JAMAIS jeter ces signaux — ils s'accumulent et finissent par bloquer un sprint imprévu.

## Convention de nommage

`YYYY-MM-DD-<sujet-court>.md` — un fichier par finding ou par batch homogène. Exemples :
- `2026-05-02-frontend-no-ci-broken-build.md`
- `2026-05-02-livekit-react-jsx-typing.md`

## Schéma d'un finding

Chaque fichier suit cette structure :

```markdown
---
date: YYYY-MM-DD
status: open | mitigated | fixed | wontfix
severity: critical | high | medium | low
discovered_during: <PR ou contexte qui a révélé le problème>
related_files: [list of paths]
---

## Résumé
1-2 phrases expliquant le problème.

## Symptôme observé
Comment c'est apparu (commande échouée, log, comportement inattendu).

## Cause racine probable
Pourquoi (analyse, pas hypothèse).

## Impact
Qui est affecté, dans quelle situation. Pourquoi c'est pas critique.

## Mitigation appliquée
(Si une mitigation a été poussée dans la PR qui a découvert le problème — ex: workaround, désactivation rule, cast.)

## Action recommandée
Ce qu'il faut faire pour vraiment résoudre. Sprint cible si applicable.
```

## Règles d'usage

1. **Documenter EN CHEMIN** : dès qu'on découvre un problème hors scope, on crée le fichier avant d'oublier. Pas après.
2. **Ne pas fixer si c'est hors scope** : la mitigation minimale dans la PR courante OK ; le vrai fix attend son sprint dédié.
3. **Lier les PRs** : quand un finding est pris en compte par une PR, mettre `status: fixed` + ajouter le lien vers la PR.
4. **Lister dans `INDEX.md`** : tous les findings open doivent figurer dans l'index pour scan rapide.

## Pourquoi ce registre

Demande utilisateur 2026-05-02 : « ci tu trouve des erreur ou des mocou tout autre bug / soucie / outil jamais appeler ou mal fait/ tout autre probleme potentiel en chemin meme hors de ton scope d'action actuelle tu ne les ignore pas tu les documente dans des fichier dans la doc ».

L'audit Pass 2 (2026-04-26) a révélé que beaucoup de problèmes étaient connus *implicitement* par les agents IA qui avaient écrit le code, mais jamais documentés explicitement. Résultat : friction sur les sprints suivants quand on redécouvrait les mêmes patterns. Ce registre force la trace écrite.

## Index actuel

Voir `INDEX.md`.
