#requires -Version 5.1
<#
.SYNOPSIS
    Setup environnement voice-body smoke test (Windows + AMD GPU Vulkan).

.DESCRIPTION
    Automatise tous les pré-requis runtime pour le smoke test voice-body :

    1. Génère un `.env.local` à la racine repo avec :
       - JWT secrets (operator/user/viewer) via secrets.token_urlsafe(32)
       - LiveKit API key/secret pour le container Docker local
       - Postgres password + IP_HASH_SALT + VIP_INTERNAL_SECRET
       - Tous les paths ML defaults (E:/ai/...)

    2. Crée l'arborescence `E:/ai/{tools,models}/{piper,whisper}` si manquante.

    3. Télécharge les binaires + voice models manquants :
       - Piper TTS Windows release + voice fr_FR-siwis-medium.onnx
       - Whisper.cpp release Windows Vulkan binaries
       - Whisper ggml-base.bin model

    4. Importe ton GGUF Gemma 4 26B-A4B existant dans Ollama via Modelfile
       (pas de re-download — utilise le path local E:/ai/models/gemma4-26b/).

    5. Lance le container LiveKit Docker self-hosted local (port 7880).

    6. Lance le smoke check final : `python tools/voice_body_smoke_check.py`.

    Idempotent : peut être ré-exécuté sans casse. Ne ré-écrase pas .env.local
    si présent (préserve tes éventuelles modifications). Skip downloads si
    fichiers déjà présents avec bonne taille.

.PARAMETER SkipDownloads
    Skip les téléchargements (utile si tu as déjà tout). Crée juste .env.local
    + Modelfile Ollama + lance LiveKit.

.PARAMETER ForceRegenerateEnv
    Force la régénération du .env.local même s'il existe (overwrite secrets —
    invalide les sessions JWT existantes). À utiliser pour rotation de secrets.

.EXAMPLE
    pwsh tools/setup-voice-body-env.ps1
    # Setup complet first-run.

.EXAMPLE
    pwsh tools/setup-voice-body-env.ps1 -SkipDownloads
    # Si tout est déjà téléchargé, juste relancer LiveKit + Modelfile.

.NOTES
    Requirements :
    - Windows 10/11 PowerShell 5.1+ (ou PowerShell 7+)
    - Docker Desktop UP (pour LiveKit container)
    - Ollama UP (pour import GGUF)
    - Python venv backend déjà setup (pour smoke check final)
    - Drive E: avec ~2 GB libres pour ML binaries + models
    - GGUF Gemma 4 26B-A4B déjà téléchargé à E:/ai/models/gemma4-26b/

    Spec : docs/specs/2026-05-08-voice-body-pipeline-design.md
    Checklist : docs/ops/voice-body-live-test-checklist.md
#>

[CmdletBinding()]
param(
    [switch]$SkipDownloads,
    [switch]$ForceRegenerateEnv
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path "$PSScriptRoot/.."

Write-Host ""
Write-Host "╔══════════════════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║   Shugu_stream — Voice-Body smoke test setup                         ║" -ForegroundColor Cyan
Write-Host "║   Gen secrets + download ML deps + LiveKit Docker + Ollama Modelfile ║" -ForegroundColor Cyan
Write-Host "╚══════════════════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

function Write-Step {
    param([string]$Message)
    Write-Host "→ $Message" -ForegroundColor Yellow
}

function Write-Ok {
    param([string]$Message)
    Write-Host "  ✓ $Message" -ForegroundColor Green
}

function Write-Warn {
    param([string]$Message)
    Write-Host "  ⚠ $Message" -ForegroundColor DarkYellow
}

function Write-Fail {
    param([string]$Message)
    Write-Host "  ✗ $Message" -ForegroundColor Red
}

function Test-Command {
    param([string]$Name)
    return [bool](Get-Command -Name $Name -ErrorAction SilentlyContinue)
}

function New-RandomSecret {
    <#
    .SYNOPSIS
        Génère un secret cryptographiquement sûr (équivalent secrets.token_urlsafe(32)).
    .NOTES
        43 caractères base64url (= 32 octets entropie).
    #>
    param([int]$Bytes = 32)
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $buffer = New-Object byte[] $Bytes
    $rng.GetBytes($buffer)
    # base64url : pas de = padding, + → -, / → _
    return [Convert]::ToBase64String($buffer).TrimEnd("=").Replace("+", "-").Replace("/", "_")
}

function New-HexSecret {
    param([int]$Bytes = 32)
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $buffer = New-Object byte[] $Bytes
    $rng.GetBytes($buffer)
    return ([System.BitConverter]::ToString($buffer)).Replace("-", "").ToLower()
}

function Get-FileSizeBytes {
    param([string]$Path)
    if (Test-Path $Path) { return (Get-Item $Path).Length }
    return 0
}

function Invoke-DownloadIfMissing {
    <#
    .SYNOPSIS
        Télécharge un fichier si absent ou si taille insuffisante.
    .PARAMETER Url
        URL source.
    .PARAMETER Path
        Path destination (full path).
    .PARAMETER MinSizeBytes
        Taille minimum attendue (sanity check). Si fichier existe mais < MinSize, re-download.
    #>
    param(
        [Parameter(Mandatory)] [string]$Url,
        [Parameter(Mandatory)] [string]$Path,
        [int]$MinSizeBytes = 1024
    )
    $existingSize = Get-FileSizeBytes -Path $Path
    if ($existingSize -ge $MinSizeBytes) {
        Write-Ok "$([System.IO.Path]::GetFileName($Path)) déjà présent ($([math]::Round($existingSize / 1MB, 1)) MB)"
        return $true
    }
    if ($SkipDownloads) {
        Write-Warn "$([System.IO.Path]::GetFileName($Path)) absent — skipped via -SkipDownloads"
        return $false
    }
    $dir = Split-Path -Parent $Path
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    Write-Step "Download $Url"
    try {
        Invoke-WebRequest -Uri $Url -OutFile $Path -UseBasicParsing
        $newSize = Get-FileSizeBytes -Path $Path
        Write-Ok "$([System.IO.Path]::GetFileName($Path)) downloaded ($([math]::Round($newSize / 1MB, 1)) MB)"
        return $true
    }
    catch {
        Write-Fail "Download failed: $_"
        return $false
    }
}

# ─────────────────────────────────────────────────────────────────────────────
# 1. Pré-requis système
# ─────────────────────────────────────────────────────────────────────────────

Write-Step "Vérification pré-requis"

$dockerOk = Test-Command "docker"
if ($dockerOk) { Write-Ok "Docker présent" } else { Write-Fail "Docker absent — install Docker Desktop"; exit 1 }

# llama-server.exe : binary natif llama.cpp Vulkan (perf optimale AMD).
# Ollama n'est PAS requis (on n'utilise plus Ollama wrapper — direct llama-server).
$llamaServerPath = ""
$dockerAILlama = "$env:USERPROFILE/.docker/bin/inference/llama-server.exe"
if (Test-Path $dockerAILlama) {
    $llamaServerPath = (Resolve-Path $dockerAILlama).Path
    Write-Ok "llama-server.exe trouvé (Docker AI Runtime) : $llamaServerPath"
}
elseif (Test-Command "llama-server") {
    $llamaServerPath = (Get-Command "llama-server").Source
    Write-Ok "llama-server.exe trouvé (PATH) : $llamaServerPath"
}
else {
    Write-Fail "llama-server.exe introuvable"
    Write-Host "    → Install Docker Desktop avec AI Runtime (binary à $dockerAILlama)" -ForegroundColor Gray
    Write-Host "    → Ou compile llama.cpp Vulkan depuis https://github.com/ggml-org/llama.cpp" -ForegroundColor Gray
    exit 1
}

$pythonOk = Test-Path "$RepoRoot/backend/.venv/Scripts/python.exe"
if ($pythonOk) { Write-Ok "Backend venv présent" } else { Write-Fail "Backend venv absent — exécute setup-backend.ps1 d'abord"; exit 1 }

$gemmaPath = "E:/ai/models/gemma4-26b/gemma-4-26B-A4B-it-UD-IQ4_XS.gguf"
if (Test-Path $gemmaPath) {
    Write-Ok "Gemma 4 26B GGUF présent ($([math]::Round((Get-FileSizeBytes $gemmaPath) / 1GB, 1)) GB)"
}
else {
    Write-Fail "Gemma 4 GGUF absent à $gemmaPath — télécharge depuis HuggingFace d'abord"
    Write-Host "    URL : https://huggingface.co/unsloth/gemma-4-26B-A4B-it-GGUF/blob/main/gemma-4-26B-A4B-it-UD-IQ4_XS.gguf" -ForegroundColor Gray
    exit 1
}

Write-Host ""

# ─────────────────────────────────────────────────────────────────────────────
# 2. Création arborescence ML
# ─────────────────────────────────────────────────────────────────────────────

Write-Step "Création arborescence E:/ai/"
$dirs = @(
    "E:/ai/tools/piper",
    "E:/ai/tools/whisper.cpp/build/bin",
    "E:/ai/models/piper",
    "E:/ai/models/whisper"
)
foreach ($dir in $dirs) {
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
        Write-Ok "Created $dir"
    }
}
Write-Host ""

# ─────────────────────────────────────────────────────────────────────────────
# 3. Génération .env.local
# ─────────────────────────────────────────────────────────────────────────────

$envLocalPath = "$RepoRoot/.env.local"
$envExists = Test-Path $envLocalPath

if ($envExists -and -not $ForceRegenerateEnv) {
    Write-Step ".env.local existe déjà — préservation (utilise -ForceRegenerateEnv pour overwrite)"
    Write-Ok "Skipping (vos secrets actuels préservés)"
}
else {
    Write-Step "Génération .env.local avec secrets autogénérés"
    $jwtOp = New-RandomSecret 32
    $jwtUser = New-RandomSecret 32
    $jwtViewer = New-RandomSecret 32
    $ipSalt = New-RandomSecret 32
    $vipSecret = New-HexSecret 32
    $dbPwd = New-RandomSecret 24
    $lkSecret = New-RandomSecret 32

    $envContent = @"
# Shugu_stream — .env.local
# AUTO-GENERATED par tools/setup-voice-body-env.ps1 (2026-05-09)
# Ce fichier est gitignored (*.env.local). Ne jamais commit.
# Pour rotater un secret : pwsh tools/setup-voice-body-env.ps1 -ForceRegenerateEnv

SHUGU_HOST=0.0.0.0
SHUGU_PORT=8701
SHUGU_ENV=dev

# JWT secrets (auto-générés)
SHUGU_JWT_SECRET=$jwtOp
USER_JWT_SECRET=$jwtUser
SHUGU_VIEWER_JWT_SECRET=$jwtViewer
USER_ACCESS_TTL_S=3600
USER_REFRESH_TTL_S=2592000

# Operator (FILL ME : décommente + génère hash bcrypt avec :
# python -c "import bcrypt; print(bcrypt.hashpw(b'mon-mot-de-passe', bcrypt.gensalt()).decode())")
OPERATOR_USERNAME=Spoukie
# OPERATOR_PASSWORD_HASH=

# Crypto
IP_HASH_SALT=$ipSalt

# Postgres / Redis (Docker stack)
SHUGU_REDIS_URL=redis://redis:6379/1
SHUGU_DB_PASSWORD=$dbPwd
POSTGRES_PASSWORD=$dbPwd
SHUGU_POSTGRES_DSN=postgresql+asyncpg://shugu:`${SHUGU_DB_PASSWORD}@postgres/shugu

# LiveKit (Docker self-hosted local — lancé par ce script)
LIVEKIT_URL=ws://localhost:7880
LIVEKIT_API_KEY=devkey
LIVEKIT_API_SECRET=$lkSecret

# VIP bridge HMAC
VIP_INTERNAL_URL=http://backend:8701
VIP_INTERNAL_SECRET=$vipSecret

# Event bus + Memory (smoke test : inproc + memory off)
EVENT_BUS_MODE=inproc
MEMORY_ENABLED=false

# ── Voice-Body pipeline ──────────────────────────────────────
SHUGU_VOICE_AGENT_ENABLED=true
SHUGU_VOICE_USE_NEW_PIPELINE=false
SHUGU_VOICE_METRICS_ENABLED=true
SHUGU_STREAM_MODE=operator_only

# ML binaries
WHISPER_BIN=E:/ai/tools/whisper.cpp/build/bin/whisper-cli.exe
WHISPER_MODEL=E:/ai/models/whisper/ggml-base.bin
PIPER_BIN=E:/ai/tools/piper/piper.exe
PIPER_VOICE=E:/ai/models/piper/fr_FR-siwis-medium.onnx

# Local LLM voice agent (Gemma 4 via Ollama)
SHUGU_LLM_BASE_URL=http://localhost:11435
SHUGU_LLM_MODEL=gemma4-26b-a4b-iq4_xs
SHUGU_LLM_MODEL_PATH=$gemmaPath
# Path absolu vers llama-server.exe (détecté par setup script).
# Surchargeable via env var SHUGU_LLAMA_SERVER_BIN au runtime.
SHUGU_LLAMA_SERVER_BIN=$llamaServerPath
SHUGU_LLM_N_GPU_LAYERS=99
SHUGU_LLM_N_CTX=8192
SHUGU_LLM_FLASH_ATTN=true

# Director (régie scénique — disabled pour smoke test minimal)
DIRECTOR_ENABLED=false
DIRECTOR_LLM_PROVIDER=ollama

# STT
STT_MODEL=base
STT_LANGUAGE=fr

# OpenCode Go (FILL ME si tu veux activer la régie via DeepSeek/Qwen) :
# DIRECTOR_LLM_PROVIDER=openai
# OPENAI_API_KEY=<ta clé OpenCode Go>
# OPENAI_BASE_URL=https://opencode.ai/v1
# DIRECTOR_OPENAI_MODEL=glm-5.1

# Optional API keys (vides = features dépendantes skipped)
ANTHROPIC_API_KEY=
MINIMAX_API_KEY=
ELEVENLABS_API_KEY=
TAVILY_API_KEY=
BRAVE_SEARCH_API_KEY=
"@
    Set-Content -Path $envLocalPath -Value $envContent -Encoding UTF8
    Write-Ok ".env.local généré ($(($envContent -split "`n").Count) lignes, secrets uniques 2026-05-09)"
}
Write-Host ""

# ─────────────────────────────────────────────────────────────────────────────
# 4. Téléchargement Piper TTS + voice fr_FR
# ─────────────────────────────────────────────────────────────────────────────

Write-Step "Piper TTS (Windows AMD64)"

$piperZip = "E:/ai/tools/piper/piper_windows_amd64.zip"
$piperExe = "E:/ai/tools/piper/piper.exe"
$piperUrl = "https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_windows_amd64.zip"

if (-not (Test-Path $piperExe)) {
    if (Invoke-DownloadIfMissing -Url $piperUrl -Path $piperZip -MinSizeBytes (5 * 1MB)) {
        Write-Step "Extraction Piper zip"
        try {
            Expand-Archive -Path $piperZip -DestinationPath "E:/ai/tools/" -Force
            # Le zip contient un dossier `piper/` à la racine — vérifie où piper.exe atterrit
            if (Test-Path "E:/ai/tools/piper/piper/piper.exe") {
                # Si extraction crée E:/ai/tools/piper/piper/, déplace les fichiers d'un niveau
                Move-Item -Path "E:/ai/tools/piper/piper/*" -Destination "E:/ai/tools/piper/" -Force
                Remove-Item "E:/ai/tools/piper/piper" -Recurse -Force -ErrorAction SilentlyContinue
            }
            Remove-Item $piperZip -Force
            Write-Ok "Piper extrait → $piperExe"
        }
        catch {
            Write-Fail "Extraction Piper failed: $_"
        }
    }
}
else {
    Write-Ok "piper.exe déjà présent"
}

Write-Step "Piper voice fr_FR-siwis-medium"
$voicePath = "E:/ai/models/piper/fr_FR-siwis-medium.onnx"
$voiceConfigPath = "E:/ai/models/piper/fr_FR-siwis-medium.onnx.json"
Invoke-DownloadIfMissing `
    -Url "https://huggingface.co/rhasspy/piper-voices/resolve/main/fr/fr_FR/siwis/medium/fr_FR-siwis-medium.onnx" `
    -Path $voicePath -MinSizeBytes (50 * 1MB) | Out-Null
Invoke-DownloadIfMissing `
    -Url "https://huggingface.co/rhasspy/piper-voices/resolve/main/fr/fr_FR/siwis/medium/fr_FR-siwis-medium.onnx.json" `
    -Path $voiceConfigPath -MinSizeBytes 1024 | Out-Null
Write-Host ""

# ─────────────────────────────────────────────────────────────────────────────
# 5. Téléchargement Whisper.cpp Vulkan + ggml-base.bin
# ─────────────────────────────────────────────────────────────────────────────

Write-Step "Whisper.cpp Vulkan binaries"

$whisperZip = "E:/ai/tools/whisper.cpp/whisper-bin-x64.zip"
$whisperExe = "E:/ai/tools/whisper.cpp/build/bin/whisper-cli.exe"
# Latest Vulkan release (vérifier https://github.com/ggml-org/whisper.cpp/releases)
$whisperUrl = "https://github.com/ggml-org/whisper.cpp/releases/latest/download/whisper-bin-x64.zip"

if (-not (Test-Path $whisperExe)) {
    if (Invoke-DownloadIfMissing -Url $whisperUrl -Path $whisperZip -MinSizeBytes (5 * 1MB)) {
        Write-Step "Extraction Whisper.cpp"
        try {
            $extractDir = "E:/ai/tools/whisper.cpp/build/bin"
            if (-not (Test-Path $extractDir)) { New-Item -ItemType Directory -Path $extractDir -Force | Out-Null }
            Expand-Archive -Path $whisperZip -DestinationPath $extractDir -Force
            Remove-Item $whisperZip -Force
            Write-Ok "Whisper.cpp extrait → $whisperExe"
        }
        catch {
            Write-Fail "Extraction Whisper.cpp failed: $_"
        }
    }
}
else {
    Write-Ok "whisper-cli.exe déjà présent"
}

Write-Step "Whisper model ggml-base.bin"
Invoke-DownloadIfMissing `
    -Url "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin" `
    -Path "E:/ai/models/whisper/ggml-base.bin" -MinSizeBytes (50 * 1MB) | Out-Null
Write-Host ""

# ─────────────────────────────────────────────────────────────────────────────
# 6. llama-server : pas d'import nécessaire, lecture directe du GGUF au runtime
# ─────────────────────────────────────────────────────────────────────────────

Write-Step "llama-server (Vulkan AMD natif)"
Write-Ok "Pas d'import requis — llama-server lit le GGUF directement au start"
Write-Ok "Args optimaux Vulkan AMD configurés dans ops/run-llama-server.ps1"
Write-Host "  → -ngl 99 (full GPU offload), --flash-attn, -c 8192, --ubatch-size 512" -ForegroundColor Gray
Write-Host "  → Port 11435 (≠ 11434 Ollama → coexistence safe)" -ForegroundColor Gray
Write-Host ""

# ─────────────────────────────────────────────────────────────────────────────
# 7. LiveKit Docker container
# ─────────────────────────────────────────────────────────────────────────────

Write-Step "LiveKit Docker container (port 7880)"

# Read API key/secret from .env.local
$envLines = Get-Content $envLocalPath
$lkApiKey = ($envLines | Where-Object { $_ -match "^LIVEKIT_API_KEY=(.+)$" } | ForEach-Object { $Matches[1] }) | Select-Object -First 1
$lkApiSecret = ($envLines | Where-Object { $_ -match "^LIVEKIT_API_SECRET=(.+)$" } | ForEach-Object { $Matches[1] }) | Select-Object -First 1

if (-not $lkApiKey -or -not $lkApiSecret) {
    Write-Fail "LIVEKIT_API_KEY/SECRET introuvables dans .env.local"
}
else {
    # Stop le container existant s'il y en a un
    $existing = & docker ps -a --filter "name=shugu-livekit" --format "{{.Names}}" 2>$null
    if ($existing -match "shugu-livekit") {
        Write-Step "Arrêt du container LiveKit existant"
        & docker stop shugu-livekit 2>$null | Out-Null
        & docker rm shugu-livekit 2>$null | Out-Null
    }

    # Lance LiveKit en mode dev (in-memory, no persistence — suffit pour smoke test)
    Write-Step "Lancement LiveKit container (mode dev)"
    $lkArgs = @(
        "run", "-d",
        "--name", "shugu-livekit",
        "-p", "7880:7880",
        "-p", "7881:7881",
        "-p", "7882:7882/udp",
        "-e", "LIVEKIT_KEYS=${lkApiKey}: ${lkApiSecret}",
        "livekit/livekit-server:latest",
        "--dev",
        "--bind", "0.0.0.0"
    )
    try {
        & docker @lkArgs | Out-Null
        Start-Sleep -Seconds 3
        $running = & docker ps --filter "name=shugu-livekit" --format "{{.Status}}" 2>$null
        if ($running -match "Up") {
            Write-Ok "LiveKit UP sur ws://localhost:7880 ($running)"
        }
        else {
            Write-Fail "LiveKit container démarré mais pas Up — check 'docker logs shugu-livekit'"
        }
    }
    catch {
        Write-Fail "docker run failed: $_"
    }
}
Write-Host ""

# ─────────────────────────────────────────────────────────────────────────────
# 8. Smoke check final
# ─────────────────────────────────────────────────────────────────────────────

Write-Step "Smoke check final (tools/voice_body_smoke_check.py)"
Push-Location $RepoRoot
try {
    & "$RepoRoot/backend/.venv/Scripts/python.exe" "tools/voice_body_smoke_check.py"
    Write-Host ""
    Write-Host "╔══════════════════════════════════════════════════════════════════════╗" -ForegroundColor Green
    Write-Host "║   Setup terminé. Prochaine étape : démarrer le stack runtime         ║" -ForegroundColor Green
    Write-Host "║                                                                      ║" -ForegroundColor Green
    Write-Host "║     pwsh tools/start-voice-body-stack.ps1                            ║" -ForegroundColor Green
    Write-Host "║                                                                      ║" -ForegroundColor Green
    Write-Host "║   Puis ouvre http://localhost:3100 dans Chrome.                      ║" -ForegroundColor Green
    Write-Host "╚══════════════════════════════════════════════════════════════════════╝" -ForegroundColor Green
}
finally {
    Pop-Location
}
