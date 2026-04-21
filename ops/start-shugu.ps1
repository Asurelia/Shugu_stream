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
$PythonExe      = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $PythonExe) { Write-Error "python introuvable dans PATH"; exit 1 }

$BackendDir     = Join-Path $Root "backend"
$FrontendDir    = Join-Path $Root "frontend"
$CloudflaredExe = "C:\Users\rafai\cloudflared\cloudflared.exe"

$BackendPort    = if ($env:SHUGU_PORT) { $env:SHUGU_PORT } else { "8701" }

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

# --- Save PIDs ---------------------------------------------------------------
$Pids = @{
    backend     = $Backend.Id
    frontend    = $Frontend.Id
    cloudflared = if ($Tunnel) { $Tunnel.Id } else { $null }
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
Write-Host ""
Write-Host "Local  : http://127.0.0.1:3005" -ForegroundColor White
Write-Host "Public : https://shugu.spoukie.uk" -ForegroundColor White
Write-Host ""
Write-Host "Stop : .\ops\stop-shugu.ps1" -ForegroundColor DarkGray
Write-Host "Logs : Get-Content -Tail 50 -Wait $LogDir\backend.log" -ForegroundColor DarkGray
