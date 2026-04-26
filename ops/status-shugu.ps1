<#
.SYNOPSIS
  Affiche l'état actuel de la stack Shugu (PIDs alive + tail des logs).

.DESCRIPTION
  Lit .shugustream/pids.json, vérifie pour chaque PID s'il est encore en vie
  (Get-Process), et affiche les 20 dernières lignes de chaque fichier log.
  Utile pour diagnostic rapide après un Shugu-Start.cmd.
#>
$ErrorActionPreference = "Continue"
$Root    = Split-Path $PSScriptRoot -Parent
$RunDir  = Join-Path $Root ".shugustream"
$LogDir  = Join-Path $RunDir "logs"
$PidFile = Join-Path $RunDir "pids.json"

Write-Host ""
Write-Host "==== Shugu Status ====" -ForegroundColor Cyan
Write-Host ""

if (-not (Test-Path $PidFile)) {
    Write-Host "Aucune session active (pas de pids.json dans .shugustream/)." -ForegroundColor DarkYellow
    Write-Host ""
    Write-Host "Pour demarrer : double-click sur Shugu-Start.cmd" -ForegroundColor DarkGray
    exit 0
}

$Pids = Get-Content $PidFile -Raw | ConvertFrom-Json

Write-Host ("Mode      : {0}" -f $Pids.mode) -ForegroundColor White
Write-Host ("Demarre   : {0}" -f $Pids.started_at) -ForegroundColor White
Write-Host ""

foreach ($name in "backend", "frontend", "cloudflared", "livekit", "vip_agent") {
    # NB : `$pid` est une variable automatique PS (Process ID courant — read-only).
    # On utilise `$procId` pour ne pas la shadow.
    $procId = $Pids.$name
    if (-not $procId) {
        Write-Host ("  {0,-12} SKIP (non lance)" -f $name) -ForegroundColor DarkGray
        continue
    }

    $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
    if ($proc) {
        $cpu = [math]::Round($proc.CPU, 1)
        $mem = [math]::Round($proc.WorkingSet64 / 1MB, 0)
        Write-Host ("  {0,-12} PID {1,-6} ALIVE   CPU={2}s  MEM={3}MB" -f $name, $procId, $cpu, $mem) -ForegroundColor Green
    } else {
        Write-Host ("  {0,-12} PID {1,-6} DEAD    (process introuvable)" -f $name, $procId) -ForegroundColor Red
    }
}

Write-Host ""
Write-Host "URLs:" -ForegroundColor Cyan
Write-Host "  Local  : http://127.0.0.1:3005"
Write-Host "  Public : https://shugu.spoukie.uk"
Write-Host ""

# Tail des logs récents
if (Test-Path $LogDir) {
    Write-Host "Derniers logs (20 lignes chacun):" -ForegroundColor Cyan
    foreach ($name in "backend", "frontend", "cloudflared", "livekit", "vip_agent") {
        $logFile = Join-Path $LogDir "$name.log"
        $errFile = Join-Path $LogDir "$name.err"
        if (Test-Path $logFile) {
            Write-Host ""
            Write-Host ("--- $name.log (tail 20) ---") -ForegroundColor DarkGray
            Get-Content $logFile -Tail 20 -ErrorAction SilentlyContinue
        }
        if (Test-Path $errFile) {
            $errSize = (Get-Item $errFile -ErrorAction SilentlyContinue).Length
            if ($errSize -gt 0) {
                Write-Host ("--- $name.err (tail 5) ---") -ForegroundColor Red
                Get-Content $errFile -Tail 5 -ErrorAction SilentlyContinue
            }
        }
    }
}

Write-Host ""
Write-Host "Stop : double-click sur Shugu-Stop.cmd" -ForegroundColor DarkGray
