# Lanceur Shugu — usage 1-clic

Trois wrappers `.cmd` à la racine pour démarrer/arrêter toute la stack en double-click depuis l'explorateur Windows.

## Lancement

| Action | Fichier | Effet |
|---|---|---|
| **Démarrer** | `Shugu-Start.cmd` | Lance backend (uvicorn) + frontend (next dev) + cloudflared + livekit + vip-agent en arrière-plan |
| **Arrêter** | `Shugu-Stop.cmd` | Kill tous les services proprement (taskkill /T /F) |
| **État** | `Shugu-Status.cmd` | Affiche PIDs alive + tail des 20 dernières lignes de chaque log |

Mode prod (après `npm run build`) : ouvrir un terminal et lancer `.\Shugu-Start.cmd --prod`.

## Pré-requis

| Pré-requis | Vérification |
|---|---|
| `python` dans PATH | `python --version` (3.11+) |
| `npm` dans PATH | `npm --version` |
| `ops/env/.env` configuré | Doit contenir au minimum `DATABASE_URL`, `REDIS_URL`, `MINIMAX_API_KEY` |
| Postgres + Redis accessibles | docker compose up depuis ops/ ou services locaux |
| (optionnel) `cloudflared.exe` | `C:\Users\<user>\cloudflared\cloudflared.exe` pour tunnel public |
| (optionnel) `livekit-server.exe` | `C:\Users\<user>\livekit\livekit-server.exe` pour VIP voice room |

Backend port par défaut : `8701` (override via `SHUGU_PORT` dans `.env`).
Frontend : `http://127.0.0.1:3005`.
Public : `https://shugu.spoukie.uk` (si tunnel configuré).

## Logs

Tous les services écrivent leurs stdout/stderr dans `.shugustream/logs/` :
- `backend.log` / `backend.err`
- `frontend.log` / `frontend.err`
- `cloudflared.log` / `cloudflared.err`
- `livekit.log` / `livekit.err`
- `vip-agent.log` / `vip-agent.err`

Tail temps-réel d'un service :
```powershell
Get-Content -Tail 50 -Wait .shugustream\logs\backend.log
```

## Création raccourci bureau (optionnel)

Pour vraiment avoir 1-clic depuis le bureau Windows :
1. Clic-droit `Shugu-Start.cmd` → Envoyer vers → Bureau (créer un raccourci)
2. Idem pour `Shugu-Stop.cmd` et `Shugu-Status.cmd`
3. (Optionnel) Clic-droit le raccourci → Propriétés → Changer l'icône pour personnaliser

## Internals

Les `.cmd` ne contiennent qu'un wrapper qui appelle les `.ps1` du dossier `ops/` avec `-ExecutionPolicy Bypass` :

```cmd
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0ops\start-shugu.ps1"
```

Cela évite d'avoir à modifier la policy d'exécution PowerShell globale ou d'ouvrir un terminal manuellement.

PIDs persistés dans `.shugustream/pids.json` au format JSON :
```json
{
  "backend": 12345,
  "frontend": 12346,
  "cloudflared": 12347,
  "livekit": 12348,
  "vip_agent": 12349,
  "mode": "dev",
  "started_at": "2026-04-26T21:00:00.000+02:00"
}
```

`Shugu-Stop.cmd` lit ce fichier puis `taskkill /T /F /PID <pid>` pour chaque entrée non-null.
