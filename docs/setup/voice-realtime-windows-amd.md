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

### 2. Ollama Windows (Vulkan AMD)
```powershell
# Téléchargement officiel : https://ollama.com/download/windows
# Installer le .exe officiel

# Variables d'environnement permanentes :
[System.Environment]::SetEnvironmentVariable("OLLAMA_VULKAN", "1", "User")
[System.Environment]::SetEnvironmentVariable("OLLAMA_FLASH_ATTENTION", "1", "User")
[System.Environment]::SetEnvironmentVariable("OLLAMA_KV_CACHE_TYPE", "q8_0", "User")

# Redémarrer Ollama service après set des env vars
# Pull le modèle Gemma 4 26B-A4B en Q5_K_M
ollama pull gemma4:26b-a4b-q5_K_M
# NOTE : vérifier le nom exact sur https://ollama.com/library/gemma4 au moment de l'install.
# Le tag exact peut différer (ex: gemma4:26b-q5, gemma4:26b-a4b-instruct-q5_k_m, etc.)

# Vérifier que Vulkan est utilisé
ollama serve  # dans un terminal
# Dans un autre :
ollama run gemma4:26b "Hello" --verbose
# Doit afficher GPU usage
```

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
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=gemma4:26b-a4b-q5_K_M
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
ollama run gemma4:26b "Raconte une blague" --verbose
# Note tokens/s et TTFB
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

### Ollama n'utilise pas le GPU
- Vérifier `OLLAMA_VULKAN=1` dans Environment Variables (System Properties → Environment Variables)
- Redémarrer le service Ollama (Task Manager → Services → Ollama)

### LiveKit container ne démarre pas
- Vérifier les ports 7880, 7881, 50000-50100 disponibles
- `docker logs shugu-livekit`

### Piper voix robotique
- Tester voix alternative `fr_FR-upmc-medium` ou `fr_FR-tom-medium`

### whisper-cli.exe introuvable
- Les builds antérieurs à v1.7 utilisent `main.exe` — vérifier le contenu de `build/bin/Release/`
- Adapter `WHISPER_BIN` dans `.env` en conséquence
