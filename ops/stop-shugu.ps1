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
    $pid = $Pids.$name
    if (-not $pid) { continue }
    # taskkill /T tue aussi les process enfants (npm.cmd -> node)
    $null = & taskkill.exe /T /F /PID $pid 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host ("  stopped {0,-12} PID {1}" -f $name, $pid) -ForegroundColor Yellow
        $stopped++
    } else {
        Write-Host ("  {0,-12} PID {1} déjà arrêté ou introuvable" -f $name, $pid) -ForegroundColor DarkGray
    }
}

Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
Write-Host ""
Write-Host "Shugu stopped ($stopped process killed)." -ForegroundColor Green
