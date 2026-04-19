# `shugustream` CLI — local dev/prod launcher

Un petit outil PowerShell pour ne plus avoir à jongler avec 2 fenêtres
manuelles quand on code sur Shugu v4.

## Installation (une seule fois)

```powershell
# Depuis n'importe où :
F:\Dev\Fork\Shugu_stream\tools\shugustream.ps1 install

# Recharge le profile PowerShell :
. $PROFILE

# C'est bon, la commande `shugustream` est maintenant dispo partout :
shugustream
```

La commande ajoute une fonction à `$PROFILE.CurrentUserAllHosts` qui pointe
vers ce script. Aucun fichier n'est copié ; la source reste dans le repo.

## Usage quotidien

```powershell
shugustream dev        # démarre backend + frontend en mode dev (hot-reload)
shugustream status     # vérifie que tout tourne
shugustream logs back  # tail live du backend (Ctrl+C sort sans tuer)
shugustream logs front # tail live du frontend
shugustream stop       # tue les 2 services
```

## Autres sous-commandes

```powershell
shugustream prod       # après un build, lance en mode production
shugustream build      # pip install -e . + npm ci + next build
shugustream health     # HTTP probe /healthz + frontend /
shugustream install    # (re)configure la fonction du profile
shugustream help       # affiche l'aide
```

## Où les choses vivent

- **Script** : `tools/shugustream.ps1` (250 lignes, structuré en fonctions
  `Invoke-XXX` par sous-commande).
- **État runtime** : `.shugustream/state.json` (PIDs + mode + timestamps).
- **Logs** : `.shugustream/logs/{backend,frontend}.log` et leurs `.err.log`.
- **.gitignore** : `.shugustream/` est déjà ignoré.

## Pré-flight checks

Avant `dev` ou `prod`, l'outil vérifie :

| Check | Action si échoue |
|---|---|
| `.env` présent | **bloque** (fix l'env d'abord) |
| `python` + `node` dans le PATH | **bloque** |
| Port 8701 + 3100 libres | **bloque** + affiche quel process tient le port |
| Redis reachable (127.0.0.1:6379) | warn only (moderation/quota cassés sans) |
| Postgres reachable (127.0.0.1:5432) | warn only (archive désactivée sans) |

## Edge cases gérés

- Double `dev` → refus avec "already running, use `stop` first"
- `stop` sans rien qui tourne → silent no-op
- PIDs orphelins après crash OS → `status` nettoie auto le state
- `logs` sans log → message "no log yet, start first"
- Port déjà pris → message "Port 8701 already in use by python.exe (PID X)"

## Troubleshooting

**`shugustream` introuvable après install** → `. $PROFILE` pour recharger
le profile, ou ouvre un nouveau terminal PowerShell.

**`state.json` corrompu** → supprime `.shugustream/state.json`, puis
`shugustream stop` (no-op) puis `shugustream dev`.

**Logs qui grossissent trop** → ils sont truncés à chaque `shugustream dev`
ou `prod`. Tu peux aussi `Clear-Content .shugustream\logs\*.log` manuellement.

**PowerShell 5 au lieu de 7** → le script exige `pwsh` (PowerShell 7+).
Installer via `winget install Microsoft.PowerShell`.
