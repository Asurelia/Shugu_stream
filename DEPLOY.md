# Shugu v4 — Déploiement et configuration

> Cible par défaut : **Hostinger KVM 2** (2 vCPU, 8 GB RAM, 100 GB NVMe, 8 TB bandwidth).
> Les paramètres par défaut sont tunés pour cette machine.

## 1. Prérequis

### Système

- Linux x86_64 (Ubuntu 22.04+ / Debian 12+ testé).
- Python 3.12+ (3.13 recommandé).
- Node.js 18+ (20+ recommandé).
- Redis 6+ (local, bind 127.0.0.1).
- PostgreSQL 14+ (schéma déjà migré via Alembic).
- Nginx 1.22+ pour le reverse proxy TLS.
- PM2 pour la supervision des process.
- **RAM libre ≥ 2 GB** après boot de tous les services (whisper + uvicorn + node + redis + postgres).

### Comptes externes

- **MiniMax plan Highspeed** (Plus | Max | Ultra). Clé API + identifiant.
  - Plus : 4 500 req LLM / 5h, 9 000 chars TTS / jour
  - **Max (défaut) : 15 000 req / 5h, 19 000 chars / jour**
  - Ultra : 30 000 req / 5h, 50 000 chars / jour
- **Hermes agent** accessible HTTP OpenAI-compat sur `127.0.0.1:8642` (ou override).
- (Optionnel) ElevenLabs API key pour voix secondaire plus fine qu'Edge-TTS.

## 2. Fichier `.env`

Chemin par défaut : `/home/openclaw/shugu/ops/env/.env` (override via `SHUGU_ENV_FILE`).

```env
# ─── Binding ────────────────────────────────────────────────────────────────
SHUGU_HOST=127.0.0.1
SHUGU_PORT=8701

# ─── Auth (opérateur) ──────────────────────────────────────────────────────
SHUGU_JWT_SECRET=CHANGEME_64_random_hex_bytes
OPERATOR_USERNAME=spoukie
# bcrypt hash produit par : python -c "import bcrypt; print(bcrypt.hashpw(b'MY_PASSWORD', bcrypt.gensalt()).decode())"
OPERATOR_PASSWORD_HASH=$2b$12$...

# ─── MiniMax (LLM + TTS) ────────────────────────────────────────────────────
MINIMAX_API_KEY=your_key_here
MINIMAX_BASE_URL=https://api.minimax.io/v1
MINIMAX_MODEL=minimax-m2.7
MINIMAX_PLAN=max               # plus | max | ultra — drives quota tracker
MINIMAX_TTS_MODEL=speech-2.8-hd
MINIMAX_VOICE_ID=French_MovieLeadFemale
MINIMAX_TTS_SPEED=1.0

# ─── TTS primary + fallbacks ───────────────────────────────────────────────
TTS_PRIMARY=minimax            # minimax | elevenlabs | edge
TTS_STREAMING=true             # stream chunks via Picker (3-4× lower TTFB)
ELEVENLABS_API_KEY=            # optional — secondary blob-only
SHUGU_VOICE_ID=OhWejZm6c7D8CIm5epRM
ELEVENLABS_MODEL_ID=eleven_multilingual_v2
EDGE_TTS_VOICE=fr-FR-VivienneMultilingualNeural

# ─── Hermes bridge ─────────────────────────────────────────────────────────
HERMES_API_KEY=local_token_or_empty
HERMES_BASE_URL=http://127.0.0.1:8642
HERMES_TASK_TIMEOUT_S=300
HERMES_EMBODIED=true           # true = tool_call loop ; false = legacy delegation

# ─── Storage ───────────────────────────────────────────────────────────────
SHUGU_POSTGRES_DSN=postgresql+asyncpg://openclaw@localhost/shugu
SHUGU_REDIS_URL=redis://localhost:6379/1
IP_HASH_SALT=CHANGEME_random_salt

# ─── Pipeline ──────────────────────────────────────────────────────────────
QUEUE_PENDING_CAP=50
VISITOR_RATE_LIMIT_WINDOW_S=60
VISITOR_RATE_LIMIT_MAX=5
VISITOR_HISTORY_TURNS=8

# ─── Personality hot-reload ────────────────────────────────────────────────
PERSONALITY_DIR=/home/openclaw/shugu/backend/shugu/personalities
PERSONALITY_RELOAD_POLL_S=5

# ─── Voice duplex (phase 5) ────────────────────────────────────────────────
VOICE_DUPLEX_ENABLED=true
# tiny | base | small | medium | large-v3
# KVM 2 recommendation: `base` (~140 MB, ~1.5 GB RAM, 4-5× realtime, WER ~10%)
# Upgrade to `small` if stream has idle CPU budget. `medium`+ → GPU only.
STT_MODEL=base
STT_COMPUTE_TYPE=int8
STT_DEVICE=auto                # cpu | cuda | auto
STT_LANGUAGE=fr
```

## 2.5. Dev local via `shugustream` CLI (recommandé)

Pour ne pas avoir à jongler avec 2 fenêtres PowerShell à chaque session,
utilise le CLI fourni dans `tools/shugustream.ps1`.

```powershell
# Installation (une seule fois)
F:\Dev\Fork\Shugu_stream\tools\shugustream.ps1 install
. $PROFILE                     # recharge le profile

# Usage quotidien
shugustream dev                # backend uvicorn --reload + next dev
shugustream status             # process + ports + /healthz
shugustream logs back          # tail live du backend
shugustream stop               # kill les 2
```

Autres sous-commandes : `prod`, `build`, `health`, `help`. Le pré-flight
check bloque le démarrage si `.env` manque, ports pris, Python/node
introuvables ; warn (non-bloquant) pour Redis/Postgres.

État + logs : `.shugustream/state.json` et `.shugustream/logs/` (ignorés
par Git). Voir `tools/README.md` pour tout le détail.

## 3. Installation backend

```bash
cd /home/openclaw/shugu/backend
python3 -m venv venv
source venv/bin/activate
pip install -e .
```

Cette commande tire **toutes** les dépendances incluant les lourdes de la phase 5 :

- `faster-whisper>=1.0` (download CTranslate2 + Whisper model au 1er run, ~140 MB disque pour `base`)
- `webrtcvad-wheels>=2.0`
- `numpy>=1.26`
- `edge-tts>=7.0`

**Note importante** : au tout premier démarrage, le modèle faster-whisper se
télécharge dans `~/.cache/huggingface/hub/` (~140 MB pour `base`, ~460 MB pour
`small`). Prévoir 30-90 s de warmup lors du premier `GET /ws/operator/voice`.
Les run suivants utilisent le cache.

### Migrations Postgres

```bash
cd /home/openclaw/shugu/backend
source venv/bin/activate
alembic upgrade head
```

### Démarrage

Via uvicorn direct :

```bash
uvicorn shugu.app:app --host 127.0.0.1 --port 8701
```

Ou via PM2 (cf. `ops/pm2/ecosystem.config.js`).

## 4. Installation frontend

```bash
cd /home/openclaw/shugu/frontend
npm ci --no-audit --no-fund
npx next build
```

Puis `next start -p 3100` (ou PM2).

Le fichier `/public/voice-worklet.js` est servi statiquement par Next, pas
de config particulière.

## 5. Nginx

Voir `ops/nginx/shugu.spoukie.uk.conf`. Points importants :

- `/ws` (tout chemin commençant par `/ws/`) → `127.0.0.1:8701` avec Upgrade
  headers pour visiteur + opérateur + voice.
- `/auth/`, `/api/` → `127.0.0.1:8701`.
- `/_next/static/` → `127.0.0.1:3100` avec cache 30d.
- `/` → `127.0.0.1:3100`.
- `proxy_read_timeout 3600s` pour les WS long-lived.

TLS via Let's Encrypt (certbot). **Obligatoire** car :
- TTS MiniMax en WebSocket exige `wss://` (refusé en clear par le code).
- `getUserMedia()` (micro opérateur) ne fonctionne pas hors HTTPS.

## 6. Configuration PM2

Le fichier `ops/pm2/ecosystem.config.js` est déjà prêt pour `shugu-frontend`
+ `shugu-backend`. Pour le redémarrage après `git pull` :

```bash
cd /home/openclaw/shugu
./ops/deploy.sh
```

Le script fait : pull → npm ci → next build → pip install -e . → pm2 restart.

## 7. Sizing — pourquoi `base` et pas `small` pour KVM 2

Faster-whisper CPU-only sur 2 vCPU int8 :

| Modèle | RAM | Latence 3s audio | WER FR | Verdict KVM 2 |
|---|---|---|---|---|
| tiny | <1 GB | ~0.3s | ~15% | trop rough pour conv. |
| **base** | **~1.5 GB** | **~0.8s** | **~10%** | **sweet spot** |
| small | ~2 GB | ~1.5s | ~8% | ok si idle, lag sous charge |
| medium | ~5 GB | ~5s | ~6% | inadapté (trop lent + RAM) |

Budget RAM total KVM 2 :

| Service | RAM |
|---|---|
| uvicorn + Python runtime | ~250 MB |
| faster-whisper `base` (chargé) | ~1.5 GB |
| node next start prod | ~300 MB |
| Redis | ~50 MB |
| Postgres | ~150 MB |
| Hermes agent (si colocalisé) | ~500 MB |
| OS + buffers | ~500 MB |
| **Total** | **~3.3 GB utilisés sur 8 GB** |

Confortable. Si Hermes tourne ailleurs, on a ~5 GB de marge pour upgrade à
`small` sans pression.

Pour basculer à `small` : `STT_MODEL=small` dans `.env` + redémarrer.

## 8. Production d'assets (optionnel)

### Animations Mixamo → VRMA

1. Télécharger un FBX de Mixamo (ou utiliser un clip existant).
2. Drop dans `frontend/public/animations/NOM.fbx`.
3. Ajouter l'entrée dans `frontend/src/features/animations/animationPack.ts` :
   ```ts
   export const ACTION_CLIPS = { ..., nom: "/animations/NOM.fbx" };
   ```
4. Ajouter `"nom"` à la whitelist `GESTURE_CLIPS` dans `backend/shugu/core/body_control.py`.
5. Redémarrer le backend.

### Storyboards ambient avec audio

1. Générer un MP3 (MiniMax manuel, Music-2.6, freesound, etc.) — ~10-30 s.
2. Drop dans `frontend/public/ambient/NOM.mp3`.
3. Dans `backend/shugu/core/ambient_bank.py` : set `weight > 0` sur le
   `AmbientScene` correspondant + `audio_path="/ambient/NOM.mp3"`.
4. Redémarrer.

Zéro coût TTS/LLM récurrent après cette étape.

### VRoid Studio → VRM

1. Créer/exporter le modèle dans VRoid Studio (VRM 0 ou 1).
2. Remplacer `assets/avatar_sample_b.vrm`.
3. Si nouveau modèle avec expressions custom, ajuster `EXPRESSIONS`
   whitelist dans `body_control.py`.

## 9. Runbook — incidents fréquents

### Le stream ne parle plus mais l'avatar bouge

Probable quota MiniMax TTS épuisé. Check :

```bash
curl -H "Cookie: shugu_access=..." https://shugu.spoukie.uk/api/admin/quota
```

Si `tts.ratio > 1.0`, le FallbackTTS a basculé sur Edge-TTS (voix différente).
Attendre le reset minuit UTC ou upgrade de plan.

### Latence TTFB audio > 3s en streaming

Vérifier `/api/admin/metrics`. Si `tts_ttfb.p90_ms > 3000`, probable saturation
MiniMax ou réseau. Toggle `TTS_PRIMARY=edge` temporairement (Edge reste <1s).

### Barge-in ne coupe pas Shugu

Vérifier que `voice_duplex_enabled=True` ET que le mic opérateur est actif
(bouton vert dans OperatorVoicePanel). Si `picker.interrupt_requested` log
apparait mais pas `picker.stream_interrupted`, le stream est probablement
déjà fini (rien à interrompre — comportement normal).

### Whisper bloque au premier enregistrement

Download du modèle en cours. 30-90 s au premier usage. Les logs doivent
contenir `stt.loading_model` puis `stt.model_ready`. Persistant dans
`~/.cache/huggingface/hub/` après.

### Fenêtre desktop vide / Hermes HUD "available: false"

`~/.hermes/` n'existe pas sur le host. Soit installer hermes-hud upstream,
soit set `HERMES_HOME=/autre/chemin` si le format est émulé ailleurs.
Comportement défensif : le endpoint retourne `available: false` sans
crasher, l'UI affiche un placeholder explicatif.

## 10. Troubleshooting rapide

| Symptôme | Check |
|---|---|
| 4401 sur /ws/operator | JWT expiré → refresh ou re-login |
| 4413 sur /ws/operator/voice | Client envoie frames trop grosses → config AudioContext à 16kHz |
| SpeakingRing stays lit | `performance.end` pas envoyé → vérifier logs picker.play_error |
| "too many requests" tool_call | Rate limit → cf. `/api/admin/metrics` rate_limits snapshot |
| Fonts Plus Jakarta missing | `next build` pas re-run après changes tailwind config |

## 11. Sécurité — checklist avant go-live

- [ ] `SHUGU_JWT_SECRET` généré via `openssl rand -hex 64`, pas de default commit
- [ ] `OPERATOR_PASSWORD_HASH` à jour, pas le hash `default_hash`
- [ ] `IP_HASH_SALT` random, pas commit
- [ ] HTTPS Let's Encrypt actif (`certbot certificates`)
- [ ] Nginx bloque `/ws/operator` et `/api/admin/*` hors auth (déjà fait via
      cookies httpOnly)
- [ ] `~/.hermes/` n'a pas de symlinks vers des paths sensibles
- [ ] Logs rotation configurée (`logrotate` sur `~/.pm2/logs/`)
- [ ] Backup DB automatique (postgres → rclone vers stockage tiers)
