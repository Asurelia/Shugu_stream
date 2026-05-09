@echo off
REM ========================================================================
REM  Shugu-VoiceBody-Stop.cmd — Arrête proprement toute la stack voice-body.
REM
REM  Lit .shugustream\pids-voice-body.json (créé par Start) et kill chaque
REM  PID avec descendants (taskkill /T /F). Stop le container LiveKit.
REM  NE TOUCHE PAS Ollama (peut être utilisé par d'autres apps).
REM ========================================================================
setlocal
cd /d "%~dp0"

echo.
echo === Arret stack voice-body ===
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0ops\stop-voice-body.ps1"

echo.
pause
endlocal
