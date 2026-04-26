<#
.SYNOPSIS
  Arrête les 3 services démarrés par start-shugu.ps1 (backend + frontend + tunnel).

.DESCRIPTION
  Lit .shugustream/pids.json et kill chaque PID avec ses descendants
  (`taskkill /T /F` pour que npm.cmd emmène node avec lui).
#>
$ErrorActionPreference = "Continue"
$Root    = Split-Path $PSScriptRoot -Parent
$PidFile = Join-Path $Root ".shugustream\pids.json"

if (-not (Test-Path $PidFile)) {
    Write-Warning "Pas de pids.json dans .shugustream/ — rien à arrêter."
    exit 0
}

$Pids = Get-Content $PidFile -Raw | ConvertFrom-Json

$stopped = 0
foreach ($name in "backend", "frontend", "cloudflared", "livekit", "vip_agent") {
    # NB : `$pid` est une variable automatique PS (Process ID courant — read-only).
    # On utilise `$procId` pour ne pas la shadow.
    $procId = $Pids.$name
    if (-not $procId) { continue }
    # taskkill /T tue aussi les process enfants (npm.cmd -> node)
    $null = & taskkill.exe /T /F /PID $procId 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host ("  stopped {0,-12} PID {1}" -f $name, $procId) -ForegroundColor Yellow
        $stopped++
    } else {
        Write-Host ("  {0,-12} PID {1} déjà arrêté ou introuvable" -f $name, $procId) -ForegroundColor DarkGray
    }
}

Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
Write-Host ""
Write-Host "Shugu stopped ($stopped process killed)." -ForegroundColor Green
