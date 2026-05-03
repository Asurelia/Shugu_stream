# Setup voice realtime — Windows + AMD 7800 XT + Vulkan

## Prérequis hardware
- CPU : i5 12600k ou équivalent (10+ cores)
- RAM : 32GB+ (64GB recommandé pour offload models)
- GPU AMD : RDNA3+ (RX 7800 XT 16GB minimum)
- Stockage : 50GB libre (modèles Whisper + Gemma 4 + Piper voices)

## Composants à installer

### 1. Docker Desktop (déjà installé chez l'utilisateur)
```powershell
docker --version
```

### 2. LLM backend — llama.cpp + llama-server (default) OU Ollama (alternative)

#### Option A — llama.cpp (recommandée, latence top, contrôle max)

Pré-requis :
- Visual Studio 2022 Build Tools ou Community (avec C++ workload)
- CMake 3.20+
- Ninja (via `pip install ninja` ou `conda install ninja`)
- Vulkan SDK installé (https://vulkan.lunarg.com/)
- Git

Build :
```powershell
git clone https://github.com/ggml-org/llama.cpp E:\ai\tools\llama.cpp
cd E:\ai\tools\llama.cpp

# Charger l'env VS2022 puis configurer + build
$vcvars = "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat"
cmd /c "`"$vcvars`" && cmake -B build -G Ninja -DCMAKE_BUILD_TYPE=Release -DGGML_VULKAN=ON -DLLAMA_CURL=OFF"
cmd /c "`"$vcvars`" && cmake --build build --config Release"
```

Vérifier le GPU :
```powershell
E:\ai\tools\llama.cpp\build\bin\llama-cli.exe --list-devices
# Doit afficher : Vulkan0: AMD Radeon RX 7800 XT (16368 MiB, ~15400 MiB free)
```

Télécharger le modèle Gemma 4 26B-A4B IQ4_XS (13.4 GB, sweet spot pour 16GB VRAM) :
```powershell
mkdir E:\ai\models\gemma4 -ErrorAction SilentlyContinue
cd E:\ai\models\gemma4
huggingface-cli download unsloth/gemma-4-26B-A4B-it-GGUF gemma-4-26B-A4B-it-UD-IQ4_XS.gguf --local-dir . --local-dir-use-symlinks False
```

Lancer le serveur (utilisera les flags optimisés Vulkan) :
```powershell
pwsh -File infra/llama/start-llama-server.ps1
```

API exposée sur `http://localhost:11434/v1/chat/completions` (OpenAI-compat).

#### Option B — Ollama (fallback, plus simple, 5-10% overhead)

Si déjà installé sur ta machine, set les env vars sur E: pour ne pas remplir C: :
```powershell
[System.Environment]::SetEnvironmentVariable("OLLAMA_MODELS", "E:\ai\ollama\models", "User")
[System.Environment]::SetEnvironmentVariable("OLLAMA_VULKAN", "1", "User")
[System.Environment]::SetEnvironmentVariable("OLLAMA_FLASH_ATTENTION", "1", "User")
[System.Environment]::SetEnvironmentVariable("OLLAMA_KV_CACHE_TYPE", "q8_0", "User")

# Redémarrer le service Ollama après set des env vars
ollama pull gemma4:26b-a4b-iq4_xs  # vérifier le tag exact sur ollama.com/library
```

Dans `.env`, l'endpoint reste le même (`http://localhost:11434`) — le code Python ne fait pas la distinction.

### 3. whisper.cpp + Vulkan
```powershell
# Cloner et compiler whisper.cpp avec Vulkan
git clone https://github.com/ggerganov/whisper.cpp F:\tools\whisper.cpp
cd F:\tools\whisper.cpp
cmake -B build -DGGML_VULKAN=ON
cmake --build build -j --config Release

# Nom du binaire selon la version de whisper.cpp :
#   whisper.cpp >= v1.7.x : whisper-cli.exe  (nom actuel recommandé)
#   whisper.cpp < v1.7.x  : main.exe         (ancien nom — fallback)
# Adapter WHISPER_BIN dans .env en conséquence.

# Télécharger modèle small (multilingue FR)
.\models\download-ggml-model.cmd small

# Test (adapter le nom du binaire selon votre build)
.\build\bin\Release\whisper-cli.exe -m models\ggml-small.bin -f samples\jfk.wav --language fr
```

### 4. Piper TTS (voix française)
```powershell
# Télécharger binaire Piper Windows
# https://github.com/rhasspy/piper/releases — piper_windows_amd64.zip
# Extraire dans F:\tools\piper

# Télécharger voix française "siwis-medium" (ou "upmc-medium")
# https://huggingface.co/rhasspy/piper-voices/tree/main/fr/fr_FR/siwis/medium
# Récupérer fr_FR-siwis-medium.onnx + fr_FR-siwis-medium.onnx.json
# Placer dans F:\tools\piper\voices\

# Test
echo "Bonjour, je suis Shugu" | F:\tools\piper\piper.exe --model F:\tools\piper\voices\fr_FR-siwis-medium.onnx --output_file test.wav
```

### 5. LiveKit local (via Docker)
```powershell
cd F:\Dev\Fork\Shugu_stream\infra\livekit
docker-compose up -d
docker logs shugu-livekit  # vérifier "Server listening on port 7880"
```

## Variables à ajouter au .env
```
LIVEKIT_URL=ws://localhost:7880
LIVEKIT_API_KEY=devkey
LIVEKIT_API_SECRET=secret_change_me_at_least_32_characters_long_xxxxxx
LLM_BASE_URL=http://localhost:11434
LLM_MODEL=gemma-4-26b-a4b-iq4_xs   # référence cosmétique (llama-server l'ignore, c'est le -m qui compte)
WHISPER_BIN=F:/tools/whisper.cpp/build/bin/Release/whisper-cli.exe
WHISPER_MODEL=F:/tools/whisper.cpp/models/ggml-small.bin
PIPER_BIN=F:/tools/piper/piper.exe
PIPER_VOICE=F:/tools/piper/voices/fr_FR-siwis-medium.onnx
VOICE_RECORDINGS_DIR=F:/Dev/Fork/Shugu_stream/data/voice_recordings
```

Note : `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` activent aussi le token endpoint `/api/livekit/token` (VIP voice agent existant). Conserver la valeur de dev (`devkey` / secret placeholder) en local uniquement.

## Tests de bench

### Bench LLM
```powershell
# Option A — llama.cpp bench
E:\ai\tools\llama.cpp\build\bin\llama-bench.exe -m E:\ai\models\gemma4\gemma-4-26B-A4B-it-UD-IQ4_XS.gguf -ngl 99 -t 8
# Note tokens/s et TTFB

# Option B — Ollama (si utilisé en fallback)
# ollama run gemma4:26b-a4b-iq4_xs "Raconte une blague" --verbose
```

### Bench STT
```powershell
F:\tools\whisper.cpp\build\bin\Release\whisper-cli.exe -m F:\tools\whisper.cpp\models\ggml-small.bin -f sample_fr.wav --language fr --output-json
# Note durée transcription
```

### Bench TTS
```powershell
Measure-Command { echo "Bonjour, je suis Shugu et je test la synthèse vocale" | F:\tools\piper\piper.exe --model F:\tools\piper\voices\fr_FR-siwis-medium.onnx --output_file test.wav }
```

## Latences cibles
- STT : 80-150ms
- LLM TTFB : 150-200ms
- TTS TTFB : 80-100ms
- End-to-end : 330-450ms

## Troubleshooting

### llama-server ne démarre pas
- Vérifier que `E:\ai\tools\llama.cpp\build\bin\llama-server.exe` existe (recompiler si absent)
- Vérifier que le modèle GGUF est bien téléchargé dans `E:\ai\models\gemma4\`
- Vérifier que le Vulkan SDK est installé : `vulkaninfo` doit retourner le 7800 XT

### Ollama n'utilise pas le GPU (fallback Option B)
- Vérifier `OLLAMA_VULKAN=1` dans Environment Variables (System Properties → Environment Variables)
- Redémarrer le service Ollama (Task Manager → Services → Ollama)
- Attention conflit de port : un seul entre llama-server et Ollama peut tourner sur :11434 à la fois

### LiveKit container ne démarre pas
- Vérifier les ports 7880, 7881, 50000-50100 disponibles
- `docker logs shugu-livekit`

### Piper voix robotique
- Tester voix alternative `fr_FR-upmc-medium` ou `fr_FR-tom-medium`

### whisper-cli.exe introuvable
- Les builds antérieurs à v1.7 utilisent `main.exe` — vérifier le contenu de `build/bin/Release/`
- Adapter `WHISPER_BIN` dans `.env` en conséquence
