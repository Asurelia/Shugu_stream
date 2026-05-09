# Voice-Body Runtime Setup Guide (Smoke Test)

Guide pour démarrer le stack voice-body **end-to-end en runtime** sur ta machine
Windows + AMD GPU (Vulkan) + Ollama + Gemma 4 26B-A4B existant.

> **Public** : utilisateur Shugu_stream qui veut faire le **1ère smoke test live**
> du pipeline voice-body après merge de l'umbrella PR #111.

## TL;DR — 3 double-clicks Windows

| Action | Double-click sur | Description |
|---|---|---|
| **1. Setup** (one-shot, ~5-10 min) | `Shugu-VoiceBody-Setup.cmd` | Télécharge tout, génère secrets, lance LiveKit |
| **2. Démarre le stack** | `Shugu-VoiceBody-Start.cmd` | Backend + frontend dans 2 fenêtres + ouvre Chrome auto |
| **3. Stop propre** | `Shugu-VoiceBody-Stop.cmd` | Kill processes + stop container LiveKit (préserve Ollama) |

**Alternative ligne de commande (pour devs)** :

```powershell
# Setup avec rotation de secrets
.\Shugu-VoiceBody-Setup.cmd --rotate

# Setup en skip downloads (re-run rapide)
.\Shugu-VoiceBody-Setup.cmd --skip-downloads

# Direct PowerShell (debug)
pwsh tools/setup-voice-body-env.ps1
pwsh ops/start-voice-body.ps1
pwsh ops/stop-voice-body.ps1
```

## Ce que tu as déjà (audit effectué)

| Composant | Statut |
|---|---|
| Python 3.13 + venv backend | ✅ |
| Node.js v24 + frontend deps + build | ✅ |
| Docker Desktop | ✅ |
| **llama-server.exe (Docker AI Runtime, Vulkan)** | ✅ (`C:/Users/rafai/.docker/bin/inference/`) |
| **Gemma 4 26B-A4B GGUF** | ✅ (`E:/ai/models/gemma4-26b/gemma-4-26B-A4B-it-UD-IQ4_XS.gguf`) |
| GPU AMD Radeon RX 7800 XT 16GB | ✅ (Vulkan compatible) |
| Ollama | (non requis par voice-body — port 11434 reste libre pour autres apps) |

## Pourquoi llama-server (pas Ollama)

Le stack voice-body utilise **llama-server.exe** natif llama.cpp directement, pas Ollama.

| Critère | Ollama | llama-server |
|---|---|---|
| Performance Vulkan AMD | -10 à -15% (wrapper) | **Optimal natif** |
| Setup | Modelfile + import (auto) | Args directs (lecture GGUF) |
| Contrôle Vulkan | Limité | Total (`-ngl`, `--flash-attn`, `--ubatch-size`) |
| Logs debug | Stack traces masquées | Logs llama.cpp directs |

llama-server tourne sur le **port 11435** (≠ 11434 Ollama → coexistence safe si tu utilises Ollama pour autre chose).

## Ce que le script `setup-voice-body-env.ps1` fait pour toi

| Étape | Action |
|---|---|
| 1. Vérifications | Docker UP, Ollama UP, Gemma 4 GGUF présent |
| 2. Arborescence | Crée `E:/ai/{tools,models}/{piper,whisper}/` |
| 3. **Génère `.env.local`** | Secrets autogénérés (JWT × 3, IP_HASH_SALT, VIP, DB pwd, LiveKit secret) |
| 4. **Télécharge Piper** | Binary Windows AMD64 + voice `fr_FR-siwis-medium.onnx` (féminin français) |
| 5. **Télécharge Whisper.cpp** | Binary Windows Vulkan + model `ggml-base.bin` |
| 6. **Détecte llama-server.exe** | Path Docker AI Runtime ou PATH ; pas d'import nécessaire (lecture directe GGUF au runtime) |
| 7. **Lance LiveKit Docker** | Container `shugu-livekit` sur port 7880 (mode dev) |
| 8. Smoke check final | `python tools/voice_body_smoke_check.py` valide tout |

**Total disk** : ~2 GB de download (Piper 100 MB + voice 65 MB + Whisper.cpp 80 MB + ggml-base 150 MB + LiveKit Docker image 200 MB + LiveKit volumes).

**Idempotent** : tu peux relancer le script — il skip les fichiers déjà présents.

## Ce que `start-voice-body-stack.ps1` fait

1. Vérifie LiveKit container UP + Ollama UP + Gemma 4 importé
2. Lance **backend FastAPI + voice agent** dans une nouvelle fenêtre pwsh (port 8701)
3. Lance **frontend Next.js** dans une autre fenêtre pwsh (port 3100)
4. T'invite à ouvrir Chrome sur `http://localhost:3100`

## Déroulé du smoke test

Une fois `http://localhost:3100` ouvert dans Chrome :

1. **VRM avatar charge** (~28 MB de modèle 3D, premier load ~5-10s)
2. Overlay **"Click to start audio"** apparaît (Chrome autoplay policy)
   → click pour permettre la sortie audio
3. **Parle dans ton micro** (français) — Shugu écoute via VAD + Whisper STT
4. Quand tu te tais 0.5s, le pipeline déclenche :
   - STT → texte transcrit
   - LLM (Gemma 4) → réponse texte
   - Director → tags `[say_emotion:joy]` etc.
   - Piper TTS → audio PCM
   - LiveKit → transport audio vers le navigateur
   - Frontend → audio joué + lipSync (bouche bouge) + expressions (joie/surprise/etc.)
5. **Test barge-in** : pendant que Shugu parle, parle au micro → son audio se coupe en <200ms, expression neutre

## Troubleshoot

### "VRM model never loaded" dans la console browser
- Le VRM (28 MB) prend trop de temps à charger sur cold cache. Refresh la page.

### "viewer-token fetch failed: 401"
- Le `.env.local` n'a pas été lu correctement par uvicorn. Vérifie le `--env-file` dans `start-voice-body-stack.ps1`.
- Ou les secrets JWT ne matchent pas. Régénère avec `pwsh tools/setup-voice-body-env.ps1 -ForceRegenerateEnv`.

### Audio silencieux mais Shugu "parle" (texte dans le director)
- Le path Sprint C legacy publie sur track `shugu-voice` 48kHz. Vérifie que `SHUGU_VOICE_USE_NEW_PIPELINE=false` dans `.env.local` (default).
- Vérifie console Chrome → onglet Network → WebSocket frames `/ws/viewer/events` reçoit bien `scene.apply` events.

### LiveKit container fail to start
```powershell
docker logs shugu-livekit
# Souvent : port 7880 déjà utilisé. Stop l'autre service ou change le port.
```

### Gemma 4 réponse très lente (>10s par mot)
- GPU offload pas actif. Vérifie `ollama list` : la taille model doit matcher ton GGUF (16 GB).
- `nvidia-smi` ou `gpu-z` : vérifie que la VRAM est utilisée (>14 GB attendu pour 26B-A4B Q4_K_M).
- Si pas de GPU : Ollama tombe en CPU mode (très lent). Vérifie ton driver AMD + Vulkan SDK.

### "No audio devices" dans Chrome
- Permissions micro Chrome : `chrome://settings/content/microphone` → autorise `localhost:3100`.
- Test rapide : `chrome://settings/content/microphone` → micro test.

## Première utilisation — Activer voice-body pour un compte user

> **Contexte AUTH-1** : voice-body s'active uniquement quand `voiceWiringActive = true`,
> ce qui requiert le cookie opérateur (`shugu_access`). Les comptes créés via
> `/account/register` ne l'ont pas par défaut — il faut les "promouvoir" opérateur.

### Étapes

1. **Crée ton compte** via `http://localhost:3100/account/register`

2. **Vérifie ton email** (clique le lien envoyé ou vérifie les logs backend en dev)

3. **Promeus ton compte opérateur** (sur le serveur / en local) :

   ```bash
   # Dans le répertoire backend, avec le venv activé
   python -m shugu.cli.promote_operator <ton_username>
   # Output attendu : [ok] 'ton_username' is now an operator.
   ```

4. **Connecte-toi** via `/account/login` avec ton username/email + mot de passe

5. Voice-body s'active automatiquement (`voiceWiringActive = true`) et tu es redirigé vers `/`

### Commande promote_operator

| Cas | Sortie | Exit code |
|---|---|---|
| Succès | `[ok] 'username' is now an operator.` | 0 |
| Déjà opérateur | `[ok] 'username' is already an operator. No change.` | 0 |
| User non trouvé | `[error] User 'username' not found.` (stderr) | 1 |
| Erreur DB | `[error] DB error: <msg>` (stderr) | 2 |

**Idempotent** : relancer la commande sur un opérateur existant est sans effet.

---

## Activer la régie scénique (optionnel)

Par défaut le director est **disabled** (smoke test minimal sans régie).

Pour activer la régie complète (commenter la scène, gérer les expressions, anim, vfx) :

### Option A — Ollama local (gratuit, plus lent)

Édite `.env.local` :
```bash
DIRECTOR_ENABLED=true
DIRECTOR_LLM_PROVIDER=ollama
```

### Option B — OpenCode Go (clé API, modèles SOTA)

Édite `.env.local`, **décommente et remplis** :
```bash
DIRECTOR_ENABLED=true
DIRECTOR_LLM_PROVIDER=openai
OPENAI_API_KEY=<ta clé OpenCode Go depuis le dashboard>
OPENAI_BASE_URL=https://opencode.ai/v1
DIRECTOR_OPENAI_MODEL=glm-5.1   # ou kimi-k2.6, qwen3.6-plus, deepseek-v4-pro
```

Restart le backend pour prise en compte.

## Activer le nouveau pipeline (Option A — après merge migration PR)

> **Pré-requis** : la PR `feat/voice-migration-option-a-clean` doit être mergée
> sur main. Avant ça, `voice_use_new_pipeline=true` n'a aucun effet (le branch
> dans `_handle_turn_streaming` n'existe pas encore).

Édite `.env.local` :
```bash
SHUGU_VOICE_USE_NEW_PIPELINE=true
```

Effets :
- TTS routé via `bridge.publish_sentence` (track `shugu-voice-tts` 22kHz natif)
- `audio_at_ms` enrichment actif → drift expression↔audio <100ms
- **FillerBank désactivé** (NullFillerBank forcé tant que migration filler pas faite — follow-up sprint)

**Rollback** : `SHUGU_VOICE_USE_NEW_PIPELINE=false` + restart backend → Sprint C legacy reprend (incl. fillers).

## Stop the stack — propre

**Double-click `Shugu-VoiceBody-Stop.cmd`** — c'est tout. Le script :

1. Lit `.shugustream/pids-voice-body.json` (PIDs persistés au Start)
2. Kill backend PID + descendants via `taskkill /T /F`
3. Kill frontend PID + descendants
4. `docker stop shugu-livekit`
5. Supprime le fichier PIDs
6. **Préserve Ollama** (peut être utilisé par d'autres apps)

**Idempotent** : safe à relancer même si déjà stoppé. Si tu veux aussi stopper Ollama : `Win+R → services.msc → Ollama → Stop`.

## Références

- Spec : [`docs/specs/2026-05-08-voice-body-pipeline-design.md`](../specs/2026-05-08-voice-body-pipeline-design.md)
- Live test checklist : [`docs/ops/voice-body-live-test-checklist.md`](voice-body-live-test-checklist.md)
- Wiring audit : [`docs/ops/voice-body-wiring-audit-2026-05-08.md`](voice-body-wiring-audit-2026-05-08.md)
- Smoke check script : [`tools/voice_body_smoke_check.py`](../../tools/voice_body_smoke_check.py)
- Setup script : [`tools/setup-voice-body-env.ps1`](../../tools/setup-voice-body-env.ps1)
- Start script : [`tools/start-voice-body-stack.ps1`](../../tools/start-voice-body-stack.ps1)
