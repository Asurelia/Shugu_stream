#requires -Version 5.1
<#
.SYNOPSIS
    Lance llama-server.exe (llama.cpp natif Vulkan) avec Gemma 4 26B-A4B.

.DESCRIPTION
    Backend LLM voice agent. Wraps llama-server.exe avec args optimaux
    pour AMD GPU Vulkan. Expose une API OpenAI-compat sur localhost:11435
    (port 11435 ≠ 11434 Ollama → coexistence sans conflit).

    Args optimaux Vulkan AMD (RX 7800 XT 16GB) :
    - `-ngl 99` : full GPU offload (le model 16GB tient en VRAM)
    - `--flash-attn` : réduit ~10% VRAM, gain perf
    - `-c 8192` : context window 8k (model supporte 256k mais 8k suffit
      pour smoke test, économise VRAM)
    - `--ubatch-size 512` : batch size GPU optimal pour RDNA3
    - `-t -1` : threads CPU auto (pour pre/post processing)
    - `--host 0.0.0.0` : accepte connexions depuis backend FastAPI

    Performance attendue (AMD RX 7800 XT, Gemma 4 26B-A4B-IQ4_XS) :
    ~15-25 tokens/sec en génération (vs ~12-20 t/s via Ollama wrapper).

.PARAMETER Port
    Port d'écoute (default 11435). 11434 réservé à Ollama si présent.

.PARAMETER Background
    Lance en background (Start-Process), retourne le PID. Sinon foreground
    (utile pour debug).

.NOTES
    Détecte automatiquement le binaire llama-server.exe en testant :
    1. $env:SHUGU_LLAMA_SERVER_BIN (override explicite)
    2. C:/Users/$user/.docker/bin/inference/llama-server.exe (Docker AI Runtime)
    3. PATH (where.exe llama-server)

    Référence : https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md
#>

[CmdletBinding()]
param(
    [int]$Port = 11435,
    [switch]$Background
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path "$PSScriptRoot/.."

# ─────────────────────────────────────────────────────────────────────────────
# 1. Détection llama-server.exe
# ─────────────────────────────────────────────────────────────────────────────

function Find-LlamaServer {
    if ($env:SHUGU_LLAMA_SERVER_BIN -and (Test-Path $env:SHUGU_LLAMA_SERVER_BIN)) {
        return $env:SHUGU_LLAMA_SERVER_BIN
    }
    $dockerAI = "$env:USERPROFILE/.docker/bin/inference/llama-server.exe"
    if (Test-Path $dockerAI) {
        return (Resolve-Path $dockerAI).Path
    }
    $inPath = Get-Command "llama-server" -ErrorAction SilentlyContinue
    if ($inPath) {
        return $inPath.Source
    }
    throw "llama-server.exe introuvable. Set `$env:SHUGU_LLAMA_SERVER_BIN ou installe Docker AI Runtime."
}

$llamaBin = Find-LlamaServer
Write-Host "→ llama-server : $llamaBin" -ForegroundColor Yellow

# ─────────────────────────────────────────────────────────────────────────────
# 2. Détection du model GGUF
# ─────────────────────────────────────────────────────────────────────────────

# Lit SHUGU_LLM_MODEL_PATH depuis .env.local s'il existe, sinon default.
$gemmaPath = "E:/ai/models/gemma4-26b/gemma-4-26B-A4B-it-UD-IQ4_XS.gguf"
$envFile = "$RepoRoot/.env.local"
if (Test-Path $envFile) {
    $envLines = Get-Content $envFile
    $match = $envLines | Where-Object { $_ -match "^SHUGU_LLM_MODEL_PATH=(.+)$" }
    if ($match) {
        $gemmaPath = ($match[0] -replace "^SHUGU_LLM_MODEL_PATH=", "").Trim()
    }
}

if (-not (Test-Path $gemmaPath)) {
    throw "Model GGUF introuvable : $gemmaPath. Set SHUGU_LLM_MODEL_PATH dans .env.local."
}
$modelSize = [math]::Round((Get-Item $gemmaPath).Length / 1GB, 2)
Write-Host "→ Model : $gemmaPath ($modelSize GB)" -ForegroundColor Yellow

# ─────────────────────────────────────────────────────────────────────────────
# 3. Args optimaux Vulkan AMD
# ─────────────────────────────────────────────────────────────────────────────

$llamaArgs = @(
    "-m", $gemmaPath
    "--host", "0.0.0.0"
    "--port", $Port
    "-ngl", "99"            # full GPU offload (Vulkan AMD)
    "--flash-attn"          # ~10% VRAM saved + speed up
    "-c", "8192"            # context 8k (suffit smoke test)
    "--ubatch-size", "512"  # batch GPU optimal RDNA3
    "-t", "-1"              # threads CPU auto
    "--metrics"             # /metrics endpoint Prometheus-compat
)

Write-Host "→ Args : $($llamaArgs -join ' ')" -ForegroundColor Gray
Write-Host ""

# ─────────────────────────────────────────────────────────────────────────────
# 4. Conflit port ?
# ─────────────────────────────────────────────────────────────────────────────

$conflict = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($conflict) {
    Write-Host "✗ Port $Port déjà utilisé (PID $($conflict.OwningProcess))" -ForegroundColor Red
    Write-Host "  Stop le service occupant ou change Port" -ForegroundColor Gray
    throw "Port conflict"
}

# ─────────────────────────────────────────────────────────────────────────────
# 5. Lancement
# ─────────────────────────────────────────────────────────────────────────────

if ($Background) {
    Write-Host "→ Lancement llama-server en background sur port $Port" -ForegroundColor Yellow
    $logFile = "$RepoRoot/.shugustream/llama-server.log"
    $logDir = Split-Path -Parent $logFile
    if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }

    $proc = Start-Process -FilePath $llamaBin `
        -ArgumentList $llamaArgs `
        -RedirectStandardOutput $logFile `
        -RedirectStandardError "$logFile.err" `
        -PassThru `
        -WindowStyle Hidden `
        -NoNewWindow:$false

    Write-Host "  ✓ PID $($proc.Id) — logs : $logFile" -ForegroundColor Green
    Write-Host ""

    # Poll readiness sur /v1/models
    Write-Host "→ Attente readiness (max 60s, model 16GB load)..." -ForegroundColor Yellow
    $ready = $false
    for ($i = 1; $i -le 60; $i++) {
        Start-Sleep -Seconds 1
        try {
            $r = Invoke-RestMethod -Uri "http://localhost:$Port/v1/models" -TimeoutSec 1 -ErrorAction Stop
            if ($r.data) {
                $ready = $true
                Write-Host "  ✓ llama-server ready ($($r.data[0].id))" -ForegroundColor Green
                break
            }
        }
        catch {
            if ($i % 10 -eq 0) { Write-Host "  ... ($i s, model still loading)" -ForegroundColor Gray }
        }
    }
    if (-not $ready) {
        Write-Host "  ⚠ llama-server pas ready après 60s — check $logFile" -ForegroundColor DarkYellow
    }

    # Retourne le PID via stdout (capture par le caller)
    return $proc.Id
}
else {
    Write-Host "→ Foreground mode (Ctrl+C pour stopper)" -ForegroundColor Yellow
    & $llamaBin @llamaArgs
}
