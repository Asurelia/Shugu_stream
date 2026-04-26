@echo off
REM ========================================================================
REM  Shugu-Status.cmd — Affiche l'etat actuel de la stack Shugu.
REM
REM  Lit .shugustream\pids.json + tail les 20 dernieres lignes de chaque log
REM  pour diagnostic rapide.
REM ========================================================================
setlocal
cd /d "%~dp0"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0ops\status-shugu.ps1"

echo.
pause
endlocal
