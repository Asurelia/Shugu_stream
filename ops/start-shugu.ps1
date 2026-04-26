<#
.SYNOPSIS
  Démarre backend FastAPI + frontend Next.js + cloudflared tunnel en une commande.

.DESCRIPTION
  Lit les variables d'environnement depuis ops/env/.env, lance chaque service en
  arrière-plan (Start-Process -WindowStyle Hidden), stocke les PIDs dans
  .shugustream/pids.json et les logs dans .shugustream/logs/*.{log,err}.

  Mode dev (par défaut) : uvicorn --reload, next dev.
  Mode prod : uvicorn sans reload, next start (build requis au préalable).

.EXAMPLE
  .\ops\start-shugu.ps1          # dev mode (défaut)
  .\ops\start-shugu.ps1 -Prod    # prod mode (après npm run build)
  .\ops\stop-shugu.ps1           # stoppe tout
#>
param(
    [switch]$Prod
)

$ErrorActionPreference = "Stop"
$Root    = Split-Path $PSScriptRoot -Parent
$RunDir  = Join-Path $Root ".shugustream"
$LogDir  = Join-Path $RunDir "logs"
$PidFile = Join-Path $RunDir "pids.json"
$EnvFile = Join-Path $Root "ops\env\.env"

# --- Prep dossier de logs / pids ---------------------------------------------
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

# --- Source .env -> variables process -----------------------------------------
if (Test-Path $EnvFile) {
    Get-Content $EnvFile | ForEach-Object {
        $line = $_.Trim()
        if ($line -eq '' -or $line.StartsWith('#')) { return }
        if ($line -match '^\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.*)$') {
            $key = $Matches[1]
            $val = $Matches[2].Trim('"').Trim("'")
            [Environment]::SetEnvironmentVariable($key, $val, "Process")
        }
    }
} else {
    Write-Warning "ops/env/.env introuvable — les services risquent d'utiliser les defaults."
}

# --- Stop any process encore référencé dans l'ancien pids.json ----------------
if (Test-Path $PidFile) {
    Write-Host "(Session précédente détectée, arrêt avant redémarrage...)" -ForegroundColor DarkYellow
    & (Join-Path $PSScriptRoot "stop-shugu.ps1") | Out-Null
}

# --- Résolution des chemins / exécutables -------------------------------------
$BackendDir     = Join-Path $Root "backend"
$FrontendDir    = Join-Path $Root "frontend"
$CloudflaredExe = "C:\Users\rafai\cloudflared\cloudflared.exe"

# Priorité au venv backend si présent (uvicorn, structlog, etc. installés là).
# Fallback : python du PATH (qui peut ne pas avoir les deps backend).
$VenvPython = Join-Path $BackendDir ".venv\Scripts\python.exe"
if (Test-Path $VenvPython) {
    $PythonExe = $VenvPython
    Write-Host ">> Backend venv détecté : $VenvPython" -ForegroundColor DarkGray
} else {
    $PythonExe = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $PythonExe) { Write-Error "python introuvable (ni venv ni PATH)"; exit 1 }
    Write-Warning "Aucun venv backend (.venv) — utilisation de $PythonExe (peut manquer des deps)"
}

$BackendPort    = if ($env:SHUGU_PORT) { $env:SHUGU_PORT } else { "8701" }

# --- 0) Backing services (Redis via Docker) ----------------------------------
# Le backend a besoin de Redis pour : JWT revocation list (auth/me), pub/sub
# events ambient, cache pgvector. Sans Redis → /auth/me retourne 500 et
# l'utilisateur reste bloqué sur l'écran login malgré un POST /auth/login OK.
$ComposeFile = Join-Path $Root "ops\docker-compose.yml"
$RedisOk = $false

# Test rapide : Redis déjà accessible ? (cas d'un Memurai natif ou docker manuel)
$redisCheck = Test-NetConnection -ComputerName "127.0.0.1" -Port 6379 `
    -InformationLevel Quiet -WarningAction SilentlyContinue
if ($redisCheck) {
    Write-Host ">> Redis déjà accessible sur 127.0.0.1:6379" -ForegroundColor DarkGray
    $RedisOk = $true
} elseif (Test-Path $ComposeFile) {
    Write-Host ">> Redis absent — tentative démarrage via Docker..." -ForegroundColor Cyan
    $dockerExe = (Get-Command docker -ErrorAction SilentlyContinue).Source
    if (-not $dockerExe) {
        Write-Warning "docker introuvable dans PATH — impossible de démarrer Redis."
    } else {
        # Vérifie que le daemon Docker est UP (Docker Desktop démarré).
        & $dockerExe info 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "Docker daemon non joignable. Démarre Docker Desktop puis relance."
            Write-Host "  (Le launcher continue mais le backend va planter sur /auth/me)" -ForegroundColor DarkYellow
        } else {
            & $dockerExe compose -f $ComposeFile up -d redis 2>&1 | Out-Null
            if ($LASTEXITCODE -eq 0) {
                # Attend que Redis soit ready (ping)
                $deadline = (Get-Date).AddSeconds(15)
                while ((Get-Date) -lt $deadline) {
                    if (Test-NetConnection -ComputerName "127.0.0.1" -Port 6379 `
                            -InformationLevel Quiet -WarningAction SilentlyContinue) {
                        $RedisOk = $true
                        break
                    }
                    Start-Sleep -Milliseconds 500
                }
                if ($RedisOk) {
                    Write-Host ">> Redis démarré (container shugu-redis)" -ForegroundColor Green
                } else {
                    Write-Warning "Redis container démarré mais ne répond pas après 15s."
                }
            } else {
                Write-Warning "docker compose up -d redis a échoué."
            }
        }
    }
} else {
    Write-Warning "ops/docker-compose.yml introuvable — Redis non géré par le launcher."
}

# --- 1) Backend (uvicorn) ----------------------------------------------------
Write-Host ">> Starting backend (uvicorn) on port $BackendPort..." -ForegroundColor Cyan
$BackendArgs = @(
    "-m", "uvicorn", "shugu.app:app",
    "--host", "127.0.0.1", "--port", $BackendPort
)
if (-not $Prod) { $BackendArgs += "--reload" }

$Backend = Start-Process -FilePath $PythonExe `
    -ArgumentList $BackendArgs `
    -WorkingDirectory $BackendDir `
    -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $LogDir "backend.log") `
    -RedirectStandardError  (Join-Path $LogDir "backend.err") `
    -PassThru

# --- 2) Frontend (next dev OU start) -----------------------------------------
$NextCmd = if ($Prod) { "start" } else { "dev" }
Write-Host ">> Starting frontend (next $NextCmd)..." -ForegroundColor Cyan
$Frontend = Start-Process -FilePath "cmd.exe" `
    -ArgumentList @("/c", "npm.cmd", "run", $NextCmd) `
    -WorkingDirectory $FrontendDir `
    -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $LogDir "frontend.log") `
    -RedirectStandardError  (Join-Path $LogDir "frontend.err") `
    -PassThru

# --- 3) Cloudflared tunnel (optionnel, skip si pas de token) -----------------
$Tunnel = $null
if (-not (Test-Path $CloudflaredExe)) {
    Write-Warning "cloudflared.exe introuvable à $CloudflaredExe — skip tunnel"
} elseif (-not $env:CLOUDFLARE_TUNNEL_TOKEN) {
    Write-Warning "CLOUDFLARE_TUNNEL_TOKEN absent de ops/env/.env — skip tunnel (shugu.spoukie.uk ne sera pas joignable)"
} else {
    Write-Host ">> Starting cloudflared tunnel..." -ForegroundColor Cyan
    $Tunnel = Start-Process -FilePath $CloudflaredExe `
        -ArgumentList @("tunnel", "--no-autoupdate", "run", "--token", $env:CLOUDFLARE_TUNNEL_TOKEN) `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $LogDir "cloudflared.log") `
        -RedirectStandardError  (Join-Path $LogDir "cloudflared.err") `
        -PassThru
}

# --- 4) LiveKit server (optionnel, VIP voice room) ---------------------------
$LiveKitExe      = "C:\Users\rafai\livekit\livekit-server.exe"
$LiveKitConfig   = Join-Path $Root "ops\livekit\config.yaml"
$LiveKit = $null
if (-not (Test-Path $LiveKitExe)) {
    Write-Warning "livekit-server.exe introuvable à $LiveKitExe — skip (VIP room désactivée)"
} elseif (-not (Test-Path $LiveKitConfig)) {
    Write-Warning "config.yaml LiveKit introuvable à $LiveKitConfig — skip"
} elseif (-not $env:LIVEKIT_API_KEY -or -not $env:LIVEKIT_API_SECRET) {
    Write-Warning "LIVEKIT_API_KEY/SECRET absents de .env — skip LiveKit server"
} else {
    Write-Host ">> Starting livekit-server..." -ForegroundColor Cyan
    $LiveKitKeys = "$($env:LIVEKIT_API_KEY): $($env:LIVEKIT_API_SECRET)"
    $LiveKit = Start-Process -FilePath $LiveKitExe `
        -ArgumentList @("--config", $LiveKitConfig, "--keys", $LiveKitKeys) `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $LogDir "livekit.log") `
        -RedirectStandardError  (Join-Path $LogDir "livekit.err") `
        -PassThru
}

# --- 5) VIP agent Worker (optionnel, nécessite LiveKit + MiniMax) ----------
$VIPAgent = $null
if (-not $LiveKit) {
    Write-Warning "livekit-server pas démarré — skip VIP agent Worker"
} elseif (-not $env:MINIMAX_API_KEY) {
    Write-Warning "MINIMAX_API_KEY absent — skip VIP agent Worker"
} else {
    Write-Host ">> Starting VIP agent Worker..." -ForegroundColor Cyan
    Start-Sleep -Seconds 2  # laisse livekit-server démarrer avant
    $VIPAgent = Start-Process -FilePath $PythonExe `
        -ArgumentList @("-m", "shugu.adapters.vip_agent", "start") `
        -WorkingDirectory $BackendDir `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $LogDir "vip-agent.log") `
        -RedirectStandardError  (Join-Path $LogDir "vip-agent.err") `
        -PassThru
}

# --- Save PIDs ---------------------------------------------------------------
$Pids = @{
    backend     = $Backend.Id
    frontend    = $Frontend.Id
    cloudflared = if ($Tunnel)   { $Tunnel.Id }   else { $null }
    livekit     = if ($LiveKit)  { $LiveKit.Id }  else { $null }
    vip_agent   = if ($VIPAgent) { $VIPAgent.Id } else { $null }
    mode        = if ($Prod) { "prod" } else { "dev" }
    started_at  = (Get-Date).ToString("o")
}
$Pids | ConvertTo-Json | Set-Content $PidFile -Encoding UTF8

# --- Résumé ------------------------------------------------------------------
Write-Host ""
Write-Host "==== Shugu started ($($Pids.mode)) ====" -ForegroundColor Green
Write-Host ("  backend     PID {0,-6}  logs: {1}\backend.{{log,err}}" -f $Backend.Id,  $LogDir)
Write-Host ("  frontend    PID {0,-6}  logs: {1}\frontend.{{log,err}}" -f $Frontend.Id, $LogDir)
if ($Tunnel) {
    Write-Host ("  cloudflared PID {0,-6}  logs: {1}\cloudflared.{{log,err}}" -f $Tunnel.Id, $LogDir)
} else {
    Write-Host "  cloudflared SKIP       (voir warnings ci-dessus)" -ForegroundColor DarkYellow
}
if ($LiveKit) {
    Write-Host ("  livekit     PID {0,-6}  logs: {1}\livekit.{{log,err}}" -f $LiveKit.Id, $LogDir)
} else {
    Write-Host "  livekit     SKIP       (voir warnings ci-dessus)" -ForegroundColor DarkYellow
}
if ($VIPAgent) {
    Write-Host ("  vip-agent   PID {0,-6}  logs: {1}\vip-agent.{{log,err}}" -f $VIPAgent.Id, $LogDir)
} else {
    Write-Host "  vip-agent   SKIP       (voir warnings ci-dessus)" -ForegroundColor DarkYellow
}
Write-Host ""
Write-Host "Local  : http://127.0.0.1:3005" -ForegroundColor White
Write-Host "Public : https://shugu.spoukie.uk" -ForegroundColor White
Write-Host ""
Write-Host "Stop : .\ops\stop-shugu.ps1" -ForegroundColor DarkGray
Write-Host "Logs : Get-Content -Tail 50 -Wait $LogDir\backend.log" -ForegroundColor DarkGray
