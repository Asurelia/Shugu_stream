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

### 2. LLM backend — llama-cpp-python avec Vulkan AMD (Voie A finale)

#### Pourquoi llama-cpp-python (pas llama-server)

`llama-server` master b9011 a un bug router : `/v1/models` retourne `null` et `/v1/chat/completions` rejette tous les model names. Cf. issue [#18234](https://github.com/ggml-org/llama.cpp/issues/18234). On contourne en embedding llama.cpp directement dans le process Python.

#### Pré-requis

- Visual Studio 2022 Build Tools ou Community (avec C++ workload)
- CMake 3.20+ + Ninja
- Vulkan SDK installé (https://vulkan.lunarg.com/)
- Python 3.13+ (déjà dans le projet)

#### Install (Windows + AMD 7800 XT + Vulkan)

```powershell
$vcvars = "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat"
$env:CMAKE_ARGS = "-DGGML_VULKAN=on"
$env:FORCE_CMAKE = "1"
cmd /c "`"$vcvars`" && pip install llama-cpp-python --no-cache-dir"
```

Compilation ~5-10 min. Vérifier au runtime que Vulkan est actif :
```python
from llama_cpp import Llama
llm = Llama(model_path='...', n_gpu_layers=99, verbose=True)
# Doit afficher au load :
#   ggml_vulkan: Found 2 Vulkan devices:
#   ggml_vulkan: 0 = AMD Radeon RX 7800 XT
#   register_backend: registered backend Vulkan (2 devices)
#   llama_model_load_from_file_impl: using device Vulkan0
```

Si tu vois 1 tok/s en gen, c'est que Vulkan n'est pas actif (CPU pure). Réinstalle avec les env vars correctes.

#### Modèle MVP — Gemma 4 26B-A4B IQ4_XS

```powershell
mkdir E:\ai\models\gemma4-26b -ErrorAction SilentlyContinue
cd E:\ai\models\gemma4-26b
huggingface-cli download unsloth/gemma-4-26B-A4B-it-GGUF gemma-4-26B-A4B-it-UD-IQ4_XS.gguf --local-dir . --local-dir-use-symlinks False
```

Fichier ~13.4 GB. Tient en VRAM 16 GB du 7800 XT en single-model mode.

#### Bench attendu (mesuré)

| Métrique | Valeur |
|---|---|
| TTFB chaud | 187ms |
| Gen tok/s | 43-50 |
| Prompt eval tok/s | 288 |
| VRAM utilisée | ~12.5 GB |
| VRAM libre | ~3.5 GB (suffit pour Whisper small Q5 ~470 MB) |

#### Option B — Ollama (en stand-by, llama-server abandonné)

`llama-server` est en stand-by (bug router master b9011). Ollama reste une option de fallback si llama-cpp-python pose un problème de build :
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
