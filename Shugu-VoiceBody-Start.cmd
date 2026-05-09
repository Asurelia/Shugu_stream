@echo off
REM ========================================================================
REM  Shugu-VoiceBody-Start.cmd — Lance toute la stack voice-body.
REM
REM  Vérifie pré-requis (LiveKit Docker, Ollama, .env.local), lance backend
REM  uvicorn + frontend Next.js dans 2 fenêtres séparées, ouvre Chrome.
REM
REM  Logue les PIDs dans .shugustream\pids-voice-body.json pour Stop propre.
REM
REM  Usage : double-click sur ce fichier OU depuis cmd/PowerShell.
REM ========================================================================
setlocal
cd /d "%~dp0"

echo.
echo === Demarrage stack voice-body ===
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0ops\start-voice-body.ps1"

echo.
echo Pour arreter proprement : double-click sur Shugu-VoiceBody-Stop.cmd
echo.
endlocal
