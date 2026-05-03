# Start llama-server (Vulkan AMD 7800 XT) — Shugu voice realtime LLM backend.
#
# Usage: pwsh -File infra/llama/start-llama-server.ps1
#
# Tunes (flags llama-server — single dash sauf indication):
#   -ngl 99            — pousse toutes les couches sur GPU (16GB VRAM)
#   -b 512             — batch size logique
#   -ub 256            — micro-batches pour streaming
#   -ctk q8_0          — KV cache K en Q8 (économise VRAM)
#   -ctv q8_0          — KV cache V en Q8
#   -fa auto           — Flash Attention auto-detect
#   --parallel 1       — 1 stream concurrent
#   -c 16384           — contexte conversation 16k tokens
#   --device Vulkan0   — force GPU AMD (skip iGPU Intel)
#   --alias gemma4     — nom modèle pour API /v1/chat/completions
#
# API exposée sur http://localhost:11434 (port Ollama-compat)
# Endpoint OpenAI-compat : POST /v1/chat/completions
#
# IMPORTANT : ce serveur charge ~12.5 GB en VRAM tant qu'il tourne (modèle
# résident pour latence top). Lance UNIQUEMENT pendant les sessions voice.
# Kill avec stop-llama-server.ps1 ou Ctrl+C dans le terminal.

$LlamaServer = "E:\ai\tools\llama.cpp\build\bin\llama-server.exe"
$Model       = "E:\ai\models\gemma4-26b\gemma-4-26B-A4B-it-UD-IQ4_XS.gguf"

if (-not (Test-Path $LlamaServer)) {
    Write-Host "ERROR: llama-server.exe not found at $LlamaServer" -ForegroundColor Red
    Write-Host "Run: cmake --build E:\ai\tools\llama.cpp\build --config Release" -ForegroundColor Yellow
    exit 1
}

if (-not (Test-Path $Model)) {
    Write-Host "ERROR: model not found at $Model" -ForegroundColor Red
    Write-Host "Run: huggingface-cli download unsloth/gemma-4-26B-A4B-it-GGUF gemma-4-26B-A4B-it-UD-IQ4_XS.gguf --local-dir E:\ai\models\gemma4-26b" -ForegroundColor Yellow
    exit 1
}

Write-Host "Starting llama-server with Gemma 4 26B-A4B IQ4_XS on Vulkan (7800 XT)..." -ForegroundColor Cyan

# Config boost (E4B = ~5.5GB VRAM → ~10GB libre pour KV + batch buffers):
#   -b 4096 / -ub 1024  : prompt processing rapide (input long)
#   -c 32768            : contexte 32k tokens (Gemma 4 supporte jusqu'à 131k)
#   -ctk f16 -ctv f16   : KV cache en FP16 (plus rapide que Q8 si VRAM dispo)
#   -fa on              : Flash Attention forcé (RDNA3 supporte)
#   -t 10               : 10 threads CPU (i5 12600k = 10 cores P+E)
#   -tb 10              : threads batch processing
#   (--no-mmap et --mlock retirés : assertion failure sur Windows + Vulkan)

& $LlamaServer `
    -m $Model `
    --host 127.0.0.1 `
    --port 11434 `
    -ngl 99 `
    -b 4096 `
    -ub 1024 `
    -c 32768 `
    -ctk f16 `
    -ctv f16 `
    -fa on `
    -t 10 `
    -tb 10 `
    --parallel 1 `
    --device Vulkan0 `
    --alias gemma4 `
    --jinja
