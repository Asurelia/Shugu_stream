# Stop llama-server — libère la VRAM (~13 GB occupée par Gemma 4 IQ4_XS).
#
# IMPORTANT : llama-server tient le modèle résident en VRAM tant qu'il tourne
# (par design, pour latence top). Ne PAS laisser tourner en background si tu
# ne fais pas de session voice : ton GPU est sinon réservé à 80%.
#
# Workflow normal :
#   1. start-llama-server.ps1   → tu démarres avant la session
#   2. (session voice live)
#   3. stop-llama-server.ps1    → tu tues quand tu termines
#
# Sprint B+ : le LiveKit Agent worker gérera le start/stop automatique
# au début/fin d'une session room.

Write-Host "Stopping llama-server processes..." -ForegroundColor Cyan

$procs = Get-Process llama-server -ErrorAction SilentlyContinue
if (-not $procs) {
    Write-Host "  No llama-server process running." -ForegroundColor Yellow
    exit 0
}

$procs | ForEach-Object {
    Write-Host "  Killing PID $($_.Id) ($($_.ProcessName))" -ForegroundColor Gray
    Stop-Process -Id $_.Id -Force
}

Start-Sleep -Seconds 2

$still = Get-Process llama-server -ErrorAction SilentlyContinue
if ($still) {
    Write-Host "WARNING: $($still.Count) process(es) still running." -ForegroundColor Red
    exit 1
}

Write-Host "[OK] llama-server stopped — VRAM freed." -ForegroundColor Green
