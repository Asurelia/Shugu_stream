@echo off
REM ========================================================================
REM  Shugu-Start.cmd — Lance toute la stack Shugu en 1 double-click.
REM
REM  Délègue à ops\start-shugu.ps1 avec ExecutionPolicy Bypass pour ne pas
REM  être bloqué par la policy par défaut Windows.
REM
REM  Usage : double-click sur ce fichier OU le lancer depuis cmd/PowerShell.
REM  Pour le mode prod : Shugu-Start.cmd --prod
REM ========================================================================
setlocal
cd /d "%~dp0"

echo.
echo === Demarrage Shugu (mode dev) ===
echo.

if /I "%~1"=="--prod" (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0ops\start-shugu.ps1" -Prod
) else (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0ops\start-shugu.ps1"
)

echo.
echo Pour arreter : double-click sur Shugu-Stop.cmd
echo Pour voir l'etat : double-click sur Shugu-Status.cmd
echo.
pause
endlocal
