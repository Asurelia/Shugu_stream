# LLM backend — llama.cpp + llama-server (Vulkan AMD)

Stack par défaut pour Shugu_stream voice realtime.

## Pré-requis
- llama.cpp compilé Vulkan dans `E:\ai\tools\llama.cpp\` (cf. `docs/setup/voice-realtime-windows-amd.md`)
- Modèle GGUF dans `E:\ai\models\gemma4\` (Gemma 4 26B-A4B IQ4_XS recommandé)

## Lancer le serveur
```powershell
pwsh -File infra/llama/start-llama-server.ps1
```

Le serveur écoute sur `http://localhost:11434` (port Ollama-compat).

## API
OpenAI-compatible :
- `POST /v1/chat/completions` — chat streaming
- `POST /v1/completions` — text completion
- `GET /health` — health check
- `GET /models` — modèle chargé

Le code Python `backend/shugu/voice/llm_local.py` consomme `/v1/chat/completions` en streaming.

## Tuning par cas d'usage

### Sur 7800 XT 16GB (single stream)
Voir `start-llama-server.ps1` pour les flags par défaut.

### Optimisations possibles
- **Latence pure** : `--ubatch-size 128` (chunks plus petits, première sortie plus rapide)
- **Throughput batch** : `--batch-size 1024` (utile si plusieurs prompts concurrents — pas notre cas)
- **VRAM économisée** : `--cache-type-k q4_0 --cache-type-v q4_0` (qualité légèrement dégradée)
- **Pas de Flash Attention** : retirer `--flash-attn auto` si crash sur certains GPU/drivers

### Tester un autre modèle (ex: Qwen3.6-35B-A3B)
Modifier la variable `$Model` dans `start-llama-server.ps1`. Le port 11434 reste le même → backend Shugu ignore le changement de modèle.

## Bench latence

```powershell
E:\ai\tools\llama.cpp\build\bin\llama-bench.exe -m E:\ai\models\gemma4\gemma-4-26B-A4B-it-UD-IQ4_XS.gguf -ngl 99 -t 8
```

## Fallback Ollama

Si llama-server crash ou config bizarre, Ollama (sur le même port) sert de fallback :
```powershell
ollama serve  # écoute aussi sur localhost:11434 par défaut
ollama run gemma4:26b-a4b-iq4_xs
```

Attention conflit de port — un seul des deux peut tourner à la fois.
