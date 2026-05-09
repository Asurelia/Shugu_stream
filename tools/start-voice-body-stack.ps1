#requires -Version 5.1
<#
.SYNOPSIS
    Démarre le stack voice-body complet pour le smoke test runtime.

.DESCRIPTION
    Lance dans des fenêtres séparées :
      1. Ollama (si pas déjà UP)
      2. Backend FastAPI + voice agent (uvicorn)
      3. Frontend Next.js (npm run start sur prod build)

    LiveKit Docker doit déjà tourner (lancé par setup-voice-body-env.ps1).

    Une fois tout UP, ouvre Chrome sur http://localhost:3100.

.PARAMETER Foreground
    Lance backend + frontend dans la fenêtre courante (pas de spawn). Utile
    pour debug quand tu veux voir les logs en stream.

.EXAMPLE
    pwsh tools/start-voice-body-stack.ps1

.NOTES
    Pré-requis :
    - tools/setup-voice-body-env.ps1 exécuté avec succès
    - .env.local présent à la racine
    - Frontend buildé (cd frontend && npm run build)
    - LiveKit container UP (docker ps | grep shugu-livekit)
#>

[CmdletBinding()]
param(
    [switch]$Foreground
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path "$PSScriptRoot/.."

Write-Host ""
Write-Host "╔══════════════════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║   Shugu_stream — Voice-Body stack runtime start                      ║" -ForegroundColor Cyan
Write-Host "╚══════════════════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

# ─────────────────────────────────────────────────────────────────────────────
# Vérifications préalables
# ─────────────────────────────────────────────────────────────────────────────

if (-not (Test-Path "$RepoRoot/.env.local")) {
    Write-Host "✗ .env.local absent — exécute d'abord pwsh tools/setup-voice-body-env.ps1" -ForegroundColor Red
    exit 1
}

if (-not (Test-Path "$RepoRoot/frontend/.next")) {
    Write-Host "✗ Frontend pas buildé — cd frontend && npm run build d'abord" -ForegroundColor Red
    exit 1
}

# Check LiveKit container UP
$lkRunning = & docker ps --filter "name=shugu-livekit" --format "{{.Status}}" 2>$null
if (-not ($lkRunning -match "Up")) {
    Write-Host "⚠ LiveKit container down — relance via setup script" -ForegroundColor DarkYellow
    Write-Host "    pwsh tools/setup-voice-body-env.ps1 -SkipDownloads" -ForegroundColor Gray
    exit 1
}
Write-Host "✓ LiveKit container UP ($lkRunning)" -ForegroundColor Green

# Check Ollama UP + Gemma 4 model imported
$ollamaUp = $false
try {
    $r = Invoke-RestMethod -Uri "http://localhost:11434/api/tags" -TimeoutSec 2 -ErrorAction Stop
    $ollamaUp = $true
    $hasGemma = $r.models | Where-Object { $_.name -like "*gemma4-26b-a4b*" }
    if ($hasGemma) {
        Write-Host "✓ Ollama UP + Gemma 4 importé" -ForegroundColor Green
    }
    else {
        Write-Host "⚠ Ollama UP mais Gemma 4 pas importé — relance setup avec ollama create" -ForegroundColor DarkYellow
        Write-Host "    pwsh tools/setup-voice-body-env.ps1 -SkipDownloads" -ForegroundColor Gray
        exit 1
    }
}
catch {
    Write-Host "✗ Ollama down — démarre-le manuellement (ollama serve)" -ForegroundColor Red
    exit 1
}
Write-Host ""

# ─────────────────────────────────────────────────────────────────────────────
# Démarrage backend + frontend
# ─────────────────────────────────────────────────────────────────────────────

if ($Foreground) {
    Write-Host "Mode foreground : démarre backend dans cette fenêtre, frontend dans une seconde." -ForegroundColor Yellow
    Write-Host "Lance manuellement le frontend dans un autre terminal :" -ForegroundColor Yellow
    Write-Host "    cd $RepoRoot/frontend ; npm run start" -ForegroundColor Gray
    Write-Host ""

    $env:PYTHONPATH = "$RepoRoot/backend"
    & "$RepoRoot/backend/.venv/Scripts/python.exe" -m uvicorn shugu.app:app --host 0.0.0.0 --port 8701 --env-file "$RepoRoot/.env.local"
}
else {
    Write-Host "→ Démarrage backend FastAPI dans une nouvelle fenêtre" -ForegroundColor Yellow
    $backendCmd = "cd '$RepoRoot' ; `$env:PYTHONPATH = '$RepoRoot/backend' ; & '$RepoRoot/backend/.venv/Scripts/python.exe' -m uvicorn shugu.app:app --host 0.0.0.0 --port 8701 --env-file '$RepoRoot/.env.local'"
    Start-Process -FilePath "pwsh" -ArgumentList "-NoExit", "-Command", $backendCmd
    Write-Host "  ✓ Backend lancé (port 8701)" -ForegroundColor Green

    Start-Sleep -Seconds 3

    Write-Host "→ Démarrage frontend Next.js dans une nouvelle fenêtre" -ForegroundColor Yellow
    $frontendCmd = "cd '$RepoRoot/frontend' ; npm run start"
    Start-Process -FilePath "pwsh" -ArgumentList "-NoExit", "-Command", $frontendCmd
    Write-Host "  ✓ Frontend lancé (port 3100)" -ForegroundColor Green

    Write-Host ""
    Write-Host "╔══════════════════════════════════════════════════════════════════════╗" -ForegroundColor Green
    Write-Host "║   Stack UP. Ouvre dans Chrome :                                      ║" -ForegroundColor Green
    Write-Host "║                                                                      ║" -ForegroundColor Green
    Write-Host "║       http://localhost:3100                                          ║" -ForegroundColor Green
    Write-Host "║                                                                      ║" -ForegroundColor Green
    Write-Host "║   Déroulé attendu :                                                  ║" -ForegroundColor Green
    Write-Host "║   1. VRM avatar charge (~28 MB, premier load lent)                   ║" -ForegroundColor Green
    Write-Host "║   2. Click sur "Click to start audio" overlay (autoplay policy)      ║" -ForegroundColor Green
    Write-Host "║   3. Parle dans le micro — Shugu te répond                           ║" -ForegroundColor Green
    Write-Host "║   4. Avatar bouge la bouche en synchro avec sa voix                  ║" -ForegroundColor Green
    Write-Host "║   5. Coupe la parole de Shugu en parlant — barge-in                  ║" -ForegroundColor Green
    Write-Host "║                                                                      ║" -ForegroundColor Green
    Write-Host "║   Stop : ferme les 2 fenêtres pwsh + docker stop shugu-livekit       ║" -ForegroundColor Green
    Write-Host "╚══════════════════════════════════════════════════════════════════════╝" -ForegroundColor Green
}
