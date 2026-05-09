#requires -Version 5.1
<#
.SYNOPSIS
    Arrête proprement le stack voice-body (backend + frontend + LiveKit).

.DESCRIPTION
    Lit .shugustream/pids-voice-body.json (créé par start-voice-body.ps1) et :
      1. Kill backend PID + descendants (taskkill /T /F)
      2. Kill frontend PID + descendants
      3. docker stop shugu-livekit
      4. Supprime le fichier pids-voice-body.json
      5. NE touche PAS Ollama (peut être utilisé par d'autres apps)

    Idempotent : safe à relancer même si le stack est déjà stoppé.

.NOTES
    Pattern aligné sur ops/stop-shugu.ps1 (lecture PIDs JSON + taskkill /T /F).
#>

$ErrorActionPreference = "Continue"
$RepoRoot = Resolve-Path "$PSScriptRoot/.."
$PidsFile = "$RepoRoot/.shugustream/pids-voice-body.json"

Write-Host ""
Write-Host "╔══════════════════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║   Shugu_stream — Voice-Body stack STOP                               ║" -ForegroundColor Cyan
Write-Host "╚══════════════════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

# ─────────────────────────────────────────────────────────────────────────────
# 1. Lecture PIDs
# ─────────────────────────────────────────────────────────────────────────────

if (-not (Test-Path $PidsFile)) {
    Write-Host "⚠ $PidsFile absent — stack peut-être déjà stoppé" -ForegroundColor DarkYellow
    Write-Host "  Tente quand même de stopper le container LiveKit..." -ForegroundColor Gray
    $pids = @{ livekit_container = "shugu-livekit" }
}
else {
    try {
        $pids = Get-Content $PidsFile -Raw | ConvertFrom-Json -AsHashtable
        Write-Host "✓ PIDs lus depuis $PidsFile" -ForegroundColor Green
    }
    catch {
        Write-Host "✗ Failed to parse $PidsFile : $_" -ForegroundColor Red
        $pids = @{ livekit_container = "shugu-livekit" }
    }
}

# ─────────────────────────────────────────────────────────────────────────────
# 2. Helper kill PID + descendants (taskkill /T /F)
# ─────────────────────────────────────────────────────────────────────────────

function Stop-ProcessTree {
    <#
    .SYNOPSIS
        Kill un process et tous ses descendants.
    .NOTES
        taskkill /T = tree (descendants), /F = force.
        Ne raise pas si le process n'existe plus (idempotent).
    #>
    param(
        [Parameter(Mandatory)] [int]$ProcessId,
        [string]$Label = "process"
    )
    if (-not $ProcessId -or $ProcessId -le 0) {
        return
    }
    $proc = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if (-not $proc) {
        Write-Host "  ⚠ $Label PID $ProcessId déjà stoppé" -ForegroundColor DarkYellow
        return
    }
    try {
        & taskkill /PID $ProcessId /T /F 2>&1 | Out-Null
        Write-Host "  ✓ $Label PID $ProcessId killed (tree)" -ForegroundColor Green
    }
    catch {
        Write-Host "  ✗ taskkill $ProcessId failed: $_" -ForegroundColor Red
    }
}

# ─────────────────────────────────────────────────────────────────────────────
# 3. Stop backend + frontend
# ─────────────────────────────────────────────────────────────────────────────

Write-Host "→ Arrêt processes" -ForegroundColor Yellow

if ($pids.backend) {
    Stop-ProcessTree -ProcessId $pids.backend -Label "Backend"
}

if ($pids.frontend) {
    Stop-ProcessTree -ProcessId $pids.frontend -Label "Frontend"
}

if ($pids.llama_server) {
    Stop-ProcessTree -ProcessId $pids.llama_server -Label "llama-server"
}

# ─────────────────────────────────────────────────────────────────────────────
# 4. Stop LiveKit container
# ─────────────────────────────────────────────────────────────────────────────

Write-Host "→ Arrêt container LiveKit" -ForegroundColor Yellow

$lkName = if ($pids.livekit_container) { $pids.livekit_container } else { "shugu-livekit" }
$lkStatus = & docker ps --filter "name=$lkName" --format "{{.Status}}" 2>$null
if ($lkStatus -match "Up") {
    & docker stop $lkName 2>&1 | Out-Null
    Write-Host "  ✓ Container $lkName stopped" -ForegroundColor Green
}
else {
    Write-Host "  ⚠ Container $lkName déjà stoppé" -ForegroundColor DarkYellow
}

# ─────────────────────────────────────────────────────────────────────────────
# 5. Cleanup PIDs file
# ─────────────────────────────────────────────────────────────────────────────

if (Test-Path $PidsFile) {
    Remove-Item $PidsFile -Force
    Write-Host "✓ PIDs file supprimé" -ForegroundColor Green
}

# ─────────────────────────────────────────────────────────────────────────────
# 6. Note Ollama (non utilisé par voice-body — stack 100% llama-server)
# ─────────────────────────────────────────────────────────────────────────────

Write-Host ""
Write-Host "ℹ Ollama (port 11434) NON utilisé par voice-body et NON touché." -ForegroundColor Cyan
Write-Host "  voice-body utilise llama-server.exe direct (port 11435, perf optim AMD)." -ForegroundColor Gray
Write-Host ""

Write-Host "╔══════════════════════════════════════════════════════════════════════╗" -ForegroundColor Green
Write-Host "║   Stack stoppé. Tu peux fermer cette fenêtre.                        ║" -ForegroundColor Green
Write-Host "╚══════════════════════════════════════════════════════════════════════╝" -ForegroundColor Green
Write-Host ""
