#requires -Version 5.1
<#
.SYNOPSIS
    Démarre le stack voice-body complet (LiveKit + backend + frontend).

.DESCRIPTION
    Lance dans l'ordre :
      1. Vérifie Docker Desktop + Ollama UP (sinon abort avec instructions)
      2. Démarre LiveKit container `shugu-livekit` (start si stopped, run si absent)
      3. Vérifie Gemma 4 importé dans Ollama (sinon abort)
      4. Lance backend FastAPI uvicorn dans une nouvelle fenêtre pwsh
      5. Lance frontend Next.js dans une nouvelle fenêtre pwsh
      6. Attend que le backend réponde sur :8701/api/health
      7. Ouvre Chrome sur http://localhost:3100
      8. Logue les PIDs dans .shugustream/pids-voice-body.json pour Stop propre

.NOTES
    Pré-requis : Shugu-VoiceBody-Setup.cmd exécuté avec succès auparavant.
    Architecture : suit le pattern start-shugu.ps1 (PIDs → JSON pour stop).
#>

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path "$PSScriptRoot/.."
$PidsDir = "$RepoRoot/.shugustream"
$PidsFile = "$PidsDir/pids-voice-body.json"

Write-Host ""
Write-Host "╔══════════════════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║   Shugu_stream — Voice-Body stack START                              ║" -ForegroundColor Cyan
Write-Host "╚══════════════════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

# ─────────────────────────────────────────────────────────────────────────────
# 1. Vérifications préalables
# ─────────────────────────────────────────────────────────────────────────────

if (-not (Test-Path "$RepoRoot/.env.local")) {
    Write-Host "✗ .env.local absent — exécute d'abord Shugu-VoiceBody-Setup.cmd" -ForegroundColor Red
    exit 1
}
Write-Host "✓ .env.local présent" -ForegroundColor Green

# Docker UP ?
try { & docker ps 2>&1 | Out-Null }
catch {
    Write-Host "✗ Docker Desktop down — démarre Docker Desktop puis relance" -ForegroundColor Red
    exit 1
}
Write-Host "✓ Docker Desktop UP" -ForegroundColor Green

# Frontend buildé ?
if (-not (Test-Path "$RepoRoot/frontend/.next")) {
    Write-Host "⚠ Frontend pas buildé — build en cours (~1 min)" -ForegroundColor DarkYellow
    Push-Location "$RepoRoot/frontend"
    try { & npm run build } finally { Pop-Location }
}
Write-Host "✓ Frontend buildé" -ForegroundColor Green

# Ollama UP + Gemma 4 ?
try {
    $r = Invoke-RestMethod -Uri "http://localhost:11434/api/tags" -TimeoutSec 3 -ErrorAction Stop
    $hasGemma = $r.models | Where-Object { $_.name -like "*gemma4-26b-a4b*" }
    if (-not $hasGemma) {
        Write-Host "✗ Ollama UP mais Gemma 4 pas importé" -ForegroundColor Red
        Write-Host "    → Relance Shugu-VoiceBody-Setup.cmd --skip-downloads" -ForegroundColor Gray
        exit 1
    }
    Write-Host "✓ Ollama UP + Gemma 4 importé" -ForegroundColor Green
}
catch {
    Write-Host "✗ Ollama down — démarre 'ollama serve' dans un terminal séparé" -ForegroundColor Red
    exit 1
}

# ─────────────────────────────────────────────────────────────────────────────
# 2. LiveKit container
# ─────────────────────────────────────────────────────────────────────────────

$lkStatus = & docker ps -a --filter "name=shugu-livekit" --format "{{.Status}}" 2>$null
if ($lkStatus -match "Up") {
    Write-Host "✓ LiveKit container déjà UP" -ForegroundColor Green
}
elseif ($lkStatus) {
    Write-Host "→ LiveKit container existe mais arrêté — restart" -ForegroundColor Yellow
    & docker start shugu-livekit | Out-Null
    Start-Sleep -Seconds 2
    Write-Host "✓ LiveKit container restarted" -ForegroundColor Green
}
else {
    Write-Host "✗ LiveKit container absent — relance Shugu-VoiceBody-Setup.cmd --skip-downloads" -ForegroundColor Red
    exit 1
}

# ─────────────────────────────────────────────────────────────────────────────
# 3. Crée le dossier PIDs
# ─────────────────────────────────────────────────────────────────────────────

if (-not (Test-Path $PidsDir)) { New-Item -ItemType Directory -Path $PidsDir -Force | Out-Null }
$pids = @{}

# ─────────────────────────────────────────────────────────────────────────────
# 4. Lance backend FastAPI
# ─────────────────────────────────────────────────────────────────────────────

Write-Host "→ Démarrage backend FastAPI (port 8701)" -ForegroundColor Yellow
$backendCmd = @"
`$Host.UI.RawUI.WindowTitle = 'Shugu Voice-Body Backend (uvicorn :8701)'
cd '$RepoRoot'
`$env:PYTHONPATH = '$RepoRoot/backend'
& '$RepoRoot/backend/.venv/Scripts/python.exe' -m uvicorn shugu.app:app --host 0.0.0.0 --port 8701 --env-file '$RepoRoot/.env.local'
"@
$backendProc = Start-Process -FilePath "pwsh" `
    -ArgumentList "-NoExit", "-Command", $backendCmd `
    -PassThru `
    -WindowStyle Normal
$pids.backend = $backendProc.Id
Write-Host "  ✓ Backend PID $($backendProc.Id)" -ForegroundColor Green

# ─────────────────────────────────────────────────────────────────────────────
# 5. Lance frontend Next.js
# ─────────────────────────────────────────────────────────────────────────────

Write-Host "→ Démarrage frontend Next.js (port 3100)" -ForegroundColor Yellow
$frontendCmd = @"
`$Host.UI.RawUI.WindowTitle = 'Shugu Voice-Body Frontend (next :3100)'
cd '$RepoRoot/frontend'
npm run start
"@
$frontendProc = Start-Process -FilePath "pwsh" `
    -ArgumentList "-NoExit", "-Command", $frontendCmd `
    -PassThru `
    -WindowStyle Normal
$pids.frontend = $frontendProc.Id
Write-Host "  ✓ Frontend PID $($frontendProc.Id)" -ForegroundColor Green

# ─────────────────────────────────────────────────────────────────────────────
# 6. Persist PIDs pour Stop
# ─────────────────────────────────────────────────────────────────────────────

$pids.startedAt = (Get-Date).ToString("o")
$pids.livekit_container = "shugu-livekit"
$pids | ConvertTo-Json | Set-Content -Path $PidsFile -Encoding UTF8
Write-Host "✓ PIDs persistés → $PidsFile" -ForegroundColor Green

# ─────────────────────────────────────────────────────────────────────────────
# 7. Attente readiness backend
# ─────────────────────────────────────────────────────────────────────────────

Write-Host "→ Attente backend ready (max 30s)..." -ForegroundColor Yellow
$ready = $false
for ($i = 1; $i -le 30; $i++) {
    Start-Sleep -Seconds 1
    try {
        $resp = Invoke-WebRequest -Uri "http://localhost:8701/api/health" -TimeoutSec 1 -ErrorAction Stop
        if ($resp.StatusCode -eq 200) {
            $ready = $true
            break
        }
    }
    catch {
        # Pas encore ready, retry
        if ($i % 5 -eq 0) { Write-Host "  ... ($i s)" -ForegroundColor Gray }
    }
}

if ($ready) {
    Write-Host "  ✓ Backend ready" -ForegroundColor Green
}
else {
    Write-Host "  ⚠ Backend pas ready après 30s — vérifie la fenêtre Backend" -ForegroundColor DarkYellow
}

# ─────────────────────────────────────────────────────────────────────────────
# 8. Ouvre Chrome
# ─────────────────────────────────────────────────────────────────────────────

Write-Host "→ Ouverture Chrome sur http://localhost:3100" -ForegroundColor Yellow
Start-Sleep -Seconds 2
Start-Process "http://localhost:3100"

Write-Host ""
Write-Host "╔══════════════════════════════════════════════════════════════════════╗" -ForegroundColor Green
Write-Host "║   Stack UP. Smoke test prêt :                                        ║" -ForegroundColor Green
Write-Host "║                                                                      ║" -ForegroundColor Green
Write-Host "║   1. Click 'Click to start audio' overlay (autoplay policy Chrome)   ║" -ForegroundColor Green
Write-Host "║   2. Parle dans le micro — Shugu écoute via VAD + Whisper            ║" -ForegroundColor Green
Write-Host "║   3. Quand tu te tais, Gemma 4 répond + Piper TTS + lipSync          ║" -ForegroundColor Green
Write-Host "║   4. Coupe la parole en parlant pendant qu'elle parle (barge-in)     ║" -ForegroundColor Green
Write-Host "║                                                                      ║" -ForegroundColor Green
Write-Host "║   Stop : double-click Shugu-VoiceBody-Stop.cmd                       ║" -ForegroundColor Green
Write-Host "╚══════════════════════════════════════════════════════════════════════╝" -ForegroundColor Green
Write-Host ""
