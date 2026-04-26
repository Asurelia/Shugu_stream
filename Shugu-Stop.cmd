@echo off
REM ========================================================================
REM  Shugu-Stop.cmd — Arrete proprement toute la stack Shugu en 1 double-click.
REM
REM  Délègue à ops\stop-shugu.ps1 qui lit .shugustream\pids.json et kill chaque
REM  PID avec ses descendants (taskkill /T /F).
REM ========================================================================
setlocal
cd /d "%~dp0"

echo.
echo === Arret Shugu ===
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0ops\stop-shugu.ps1"

echo.
pause
endlocal
