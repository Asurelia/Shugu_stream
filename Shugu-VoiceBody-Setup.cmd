@echo off
REM ========================================================================
REM  Shugu-VoiceBody-Setup.cmd — One-shot setup voice-body smoke test.
REM
REM  Génère .env.local, télécharge Piper + Whisper.cpp, importe Gemma 4
REM  dans Ollama via Modelfile (zéro re-download), lance LiveKit Docker.
REM
REM  Idempotent : peut être ré-exécuté sans casse.
REM
REM  Usage : double-click sur ce fichier OU depuis cmd/PowerShell.
REM  Flag : Shugu-VoiceBody-Setup.cmd --rotate (force régénération secrets)
REM ========================================================================
setlocal
cd /d "%~dp0"

echo.
echo === Setup voice-body smoke test (premier run ~5-10 min download) ===
echo.

if /I "%~1"=="--rotate" (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\setup-voice-body-env.ps1" -ForceRegenerateEnv
) else if /I "%~1"=="--skip-downloads" (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\setup-voice-body-env.ps1" -SkipDownloads
) else (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\setup-voice-body-env.ps1"
)

echo.
echo Pour demarrer le stack : double-click sur Shugu-VoiceBody-Start.cmd
echo Pour arreter : double-click sur Shugu-VoiceBody-Stop.cmd
echo.
pause
endlocal
