---
date: 2026-05-03
status: spec-final-v1
target-sprint: TBD
target-stack: 100% local Windows+Vulkan AMD 7800 XT (i5 12600k + 64GB RAM, no cloud)
related-prs:
  - "#91 (backend Hermes removal)"
  - "#92 (frontend Hermes removal)"
  - "#93 (docs cleanup)"
  - "#?? (PR4 voice POC cleanup — vip_agent.py refactor)"
---

# Spec — Realtime voice Shugu

## 1. Vision produit

Shugu_stream est aujourd'hui un VTuber IA texte → TTS : flow plafonné à 3-6 s par tour, pas de vraie conversation à plusieurs voix. Le subsystem **Realtime voice** ajoute une room audio temps réel (LiveKit) où l'**operator**, des **invités humains** ponctuels (VIP ou guests one-shot) et **Shugu** parlent ensemble, **diffusé en direct** vers les viewers via `visitor_ws`. Cible end-to-end (fin parole user → début TTS Shugu) : **~330-450 ms** perçu, alignée sur LiveKit Agents 1.x avec stack STT/LLM/TTS streaming **100% local** (Vulkan AMD 7800 XT) bien tuné.

**Topologie verrouillée** : l'app tourne **sur le PC de dev** de l'operator (i5 12600k + Radeon 7800 XT 16GB VRAM + 64GB RAM, Windows natif, **pas de WSL**). Tout l'inférence (STT, LLM, TTS) se fait sur la machine locale via Vulkan ; LiveKit lui-même tourne en self-hosted Docker (container local). **Aucun appel cloud payant** récurrent — coût mensuel cible **$0** (modulo une éventuelle clé API web search en free tier). Single-stream concurrent (1 seul GPU partagé entre les legs, pas de multi-room).

Deux modes basculables à chaud par l'operator :

- **`live`** : mix audio de la room fan-outé sur le topic `stage` de l'`EventBus` existant. Viewers read-only.
- **`private`** : audio reste dans la room LiveKit, viewers n'entendent rien. Off-air pour préparer un segment, debrief invité, test prompt.

Use cases : interview live d'un invité (Twitch raid), one-on-one chill avec Shugu off-air, brief raise-handé d'un viewer avant passage live, recording 30 j d'archive pour ré-entraînement.

## 2. Architecture cible

```
   ┌───────────────── PC LOCAL (Windows + Vulkan AMD 7800 XT) ─────────────────┐
   │                                                                            │
   │   Operator mic ─────▶ ┌─────────────────────────────┐                      │
   │   Guest mic ────────▶ │  LiveKit (Docker container  │── Egress ──▶ data/   │
   │   Shugu TTS frames ─▶ │  local, self-hosted)        │      voice_recordings│
   │                       └─────┬───────────────┬───────┘      + Postgres meta │
   │                             │               │                              │
   │                             ▼               ▼                              │
   │              ┌──────────────────────┐  ┌──────────────────────┐            │
   │              │ shugu-voice Worker   │  │ Audio Bridge Worker  │            │
   │              │ (LiveKit Agents Py)  │  │ (subscribes mix)     │            │
   │              │ whisper.cpp Vulkan  ──┐ │ Opus → TTSChunk      │            │
   │              │ Ollama Gemma 4 26B-A4B│ │ + emit stage events  │            │
   │              │ Piper TTS (CPU/ONNX) │ │ + lip-sync hints     │            │
   │              │ + barge-in FSM       │ │                      │            │
   │              │ + tool_calls         │ │                      │            │
   │              └──────────┬───────────┘ └──────────┬───────────┘            │
   │                         │                        │                         │
   │                         │      mode == "live"    │                         │
   │                         │                        ▼                         │
   │                         │             ┌──────────────────────┐            │
   │                         │             │ EventBus (stage)     │            │
   │                         │             └──────────┬───────────┘            │
   │                         ▼                        │                         │
   │                ┌─────────────────┐               │                         │
   │                │ /internal/voice │               │                         │
   │                │ (FastAPI bridge)│               │                         │
   │                └─────────────────┘               │                         │
   │                                                  ▼                         │
   │                                       ┌─────────────────────┐             │
   │                                       │ visitor_ws (fanout) │             │
   │                                       └──────────┬──────────┘             │
   └──────────────────────────────────────────────────┼──────────────────────────┘
                                                      │
                                                      ▼
                                              Viewers (browsers)
                                              + optional:
                                              Tavily/Brave web search
                                              (only outbound HTTPS)
```

Le `shugu-voice` Worker est l'**évolution de `adapters/vip_agent.py`** (cf. §11), branché en local sur :
- **STT** : whisper.cpp compilé Vulkan (binding subprocess ou Python).
- **LLM** : llama-server HTTP API `localhost:11434` (Gemma 4 26B-A4B IQ4_XS GGUF, 13.4 GB VRAM, streaming OpenAI-compat). Ollama supporté en fallback (même port).
- **TTS** : Piper subprocess (CPU/ONNX, voix française).

Le `Audio Bridge` est un nouveau worker qui souscrit en SUBSCRIBE-only à la room LiveKit Docker locale, ré-empaquette les frames audio Opus en `TTSChunk` (schéma déjà défini dans `core/protocols.py`) et les publie sur le topic `stage` quand `mode == "live"`. Toggle `live/private` = un flag stocké dans Redis (`voice:mode = live|private`), lu par le Bridge avant chaque frame. **Aucun service cloud payant** dans le chemin chaud — seul l'outil web search (Tavily/Brave free tier) sort vers Internet, et uniquement sur tool_call explicite du LLM.

## 3. Stack technique

**Stack 100 % locale, Windows natif + Vulkan AMD 7800 XT 16 GB. Pas de WSL, pas de ROCm Windows, pas de cloud LLM/STT/TTS payant.**

| Composant | Choix v1 (verrouillé) | Alternative / bench post-MVP | Raison |
|---|---|---|---|
| Audio room | **LiveKit self-hosted Docker** (container local) | LiveKit Cloud (KO — coût), Daily.co | Docker Desktop déjà installé, full control, $0/mois |
| Agent framework | **livekit-agents** (Python, déjà installé) | Pipecat, custom | VAD / turn / barge-in / tool_calls out of the box |
| STT streaming | **whisper.cpp + Vulkan** (`small.en` ou `small` multilingue) | faster-whisper CUDA (KO sur AMD), Deepgram (KO budget) | Build natif Vulkan AMD, latence ~80-150 ms, modèles `.bin` locaux dans `models/whisper/` |
| **LLM** | llama.cpp + llama-server + Gemma 4 26B-A4B IQ4_XS GGUF | Ollama supporté en fallback (même API OpenAI sur port 11434) | Sortie 2026-04-02, pensé pour edge inference, TTFB ~150-200 ms sur 7800 XT Vulkan |
| TTS streaming | **Piper TTS** (CPU/ONNX, voix française `fr_FR-siwis-medium`) | Coqui XTTS v2 (voice cloning post-MVP), ElevenLabs (KO budget) | TTFB ~80 ms sur i5 12600k, $0, offline, open source |
| VAD | **Silero VAD** (`livekit-plugins-silero`, déjà utilisé) | webrtcvad (présent pour `stt_streaming.py`) | ML, robuste fond bruyant, embedded LiveKit Agents |
| Turn detection | **LiveKit End-of-Utterance** (`livekit-plugins-turn-detector` alpha 2025-2026) | VAD-only timeout fallback | Réduit faux-positif interruption sur pauses naturelles |
| Web search | **Tavily API free tier** (1000 req/mois) | Brave Search API free tier | Tool_call uniquement, hors chemin chaud, $0 dans la limite free |
| Recording | **LiveKit Egress** → **disque local** (`data/voice_recordings/`) | S3/R2 (post multi-node, hors scope) | Mono-node, FS dispo, metadata Postgres |

> **Pivot backend LLM (2026-05-03)** : llama.cpp natif au lieu d'Ollama wrapper. Raisons : latence (~5-10% gain), contrôle fin des paramètres GPU (`--ngl`, `--batch-size`, `--ubatch-size`, `--cache-type-k/v`, `--flash-attn`), API HTTP identique (OpenAI-compat `/v1/chat/completions`) → zéro impact sur le code Python `llm_local.py`.
>
> Découverte quant : Q5_K_M (21.2 GB) ne tient pas dans 16GB VRAM. Le sweet spot est **IQ4_XS (13.4 GB)** : marge 2GB pour KV cache + Whisper concurrent, qualité 4-bit Unsloth Dynamic 2.0 quasi-équivalente Q5.

### Variables d'environnement llama-server (Option A — default)

Cf. `infra/llama/start-llama-server.ps1` pour les flags Vulkan optimisés 7800 XT.

### Variables d'environnement Ollama AMD Windows Vulkan (Option B — fallback)

```ini
OLLAMA_VULKAN=1
OLLAMA_FLASH_ATTENTION=1
OLLAMA_KV_CACHE_TYPE=q8_0  # économise VRAM, perte qualité négligeable
```

Sans ces variables, Ollama peut fallback CPU et ruiner la latence. Attention : conflit port 11434 avec llama-server — un seul peut tourner à la fois.

### Benchmarks attendus 7800 XT (TTFB par leg, P50)

| Étape | Cible 7800 XT Vulkan | Backend | Notes |
|---|---|---|---|
| End-of-utterance detect | 50-100 ms | Silero VAD (CPU) | LiveKit turn-detector |
| STT first interim | 80-150 ms | whisper.cpp Vulkan (`small`) | bench dans Sprint A |
| LLM first token (TTFT) | 150-200 ms | llama-server Gemma 4 26B-A4B IQ4_XS Vulkan | Avantage MoE 4B actifs |
| Chunker → 1er segment | +100-200 ms | Pure Python | Frontière prosodique |
| TTS TTFB (1er chunk) | ~80 ms | Piper CPU/ONNX | i5 12600k 4-6 threads |
| Network → client | 5-20 ms | LiveKit Docker localhost | Boucle locale |
| **Total réel cible** | **~330-450 ms** | | Fillers acoustiques pré-rendus comblent encore les 1ers ~80 ms |

Toutes les latences vendor sont à confirmer en bench réel Sprint A → C (cf. §15). Si Gemma 4 26B-A4B sous-performe ou hallucine trop, fallback bench Qwen3.6-35B-A3B en offload CPU/GPU (Sprint H).

## 4. State machine barge-in

L'agent Shugu vit en permanence dans une de ces 7 phases. Les transitions sont implémentées dans la classe qui remplace `_entrypoint` de `vip_agent.py` (typiquement `ShuguVoiceAgent(agent_session_handlers)`).

```
              ┌──────┐  user_turn_start (VAD + EoU)   ┌───────────┐
   ┌─────────▶│ IDLE │───────────────────────────────▶│ LISTENING │
   │          └──────┘                                └─────┬─────┘
   │             ▲                                          │ end_of_utterance
   │             │ session_idle_15s                         ▼
   │          ┌──────────┐                            ┌──────────┐
   │          │ YIELDING │◀──── tts_done ─────────────│ THINKING │
   │          └──────────┘                            └────┬─────┘
   │                ▲                                      │ first_token
   │                │ tts_drained                          ▼
   │                │                                ┌──────────┐
   │     ┌──────────┴────────┐    user_interrupt   │ SPEAKING │
   │     │ STUBBORN_SPEAKING │◀───────────────────── └────┬─────┘
   │     └──────────┬────────┘                           │
   │                │ thought_complete                    │ user_interrupt
   │                ▼                                     ▼
   │           (yield)                              ┌─────────────┐
   └─────────────────────────────────────────────── │ INTERRUPTED │
                                                    └─────────────┘
                                                    decide:
                                                     a) graceful_stop → LISTENING
                                                     b) pivot       → THINKING (new prompt)
                                                     c) stubborn    → STUBBORN_SPEAKING
```

Décisions clés :

- `INTERRUPTED` est éphémère (≤200 ms). Mini-prompt LLM contraint en JSON : `"You were interrupted at: '<partial>'. User said: '<interrupt>'. Decide:"` → `{"decision": "stop|pivot|stubborn"}`.
- `STUBBORN_SPEAKING` finit la TTS du thought original puis force `YIELDING` (Shugu cède explicitement la parole).
- `YIELDING` joue un signal court ("ouais ?", "vas-y") → retour `LISTENING`.
- Chaque transition publie sur `voice.fsm` pour observabilité.

## 5. Streaming TTS + fillers

Pour atteindre ~330-450 ms end-to-end (réaliste sur stack 100 % local Vulkan), Shugu doit **commencer à parler avant la fin du LLM**. Pattern :

1. `THINKING` lance le streaming llama-server (`stream=true` sur `POST localhost:11434/v1/chat/completions`). Premier token observé sur Gemma 4 26B-A4B IQ4_XS Vulkan ~150-200 ms (avantage MoE 4B actifs).
2. Un **chunker** accumule les tokens jusqu'à atteindre une **frontière prosodique** : ponctuation forte (`.`, `?`, `!`), virgule + ≥4 mots, ou `\n`. Cela évite de couper en plein milieu d'un syntagme et donne assez de contexte au TTS pour intoner correctement.
3. À chaque frontière, on push le segment vers **Piper TTS** (subprocess streaming via stdin/stdout, ONNX runtime CPU 4-6 threads). TTFB ~80 ms par segment, débit ~5-10× temps réel sur i5 12600k.
4. Les `TTSChunk` produits sont publiés dans la LiveKit room Docker locale (audio track Shugu) ET, via le Bridge, sur `stage` si `mode == "live"`.

Latence target voir tableau §3 — récap : **~330-450 ms total**, vs ~200-300 ms cloud (perte assumée pour gagner $0/mois et zéro dépendance externe).

Le ressenti sub-300 ms est atteint via **fillers acoustiques joués immédiatement** à la transition `LISTENING → THINKING`. Deux stratégies combinées :

- **Acoustic-side (priorité v1)** : 30-50 fillers **audio clips pré-enregistrés** (générés une fois via Piper au build, stockés dans `models/piper/fillers/<mood>/*.wav`), choix aléatoire selon mood. Latence de jeu = 0. **Note** : Piper ne génère pas de fillers expressifs aussi naturels que Cartesia/ElevenLabs ; on compense en élargissant la banque (50+ clips variés "euh", "hm", "alors...", "attends une seconde", "ouais...") et on ré-enregistre offline si la qualité ne passe pas en écoute streamer.
- **Prompt-side** : `Commence ta réponse par un filler court (euh, hm, alors, attends...)` dans le system prompt — moins fiable, sert la cohérence de la suite.

## 6. Bridge audio LiveKit → visitor_ws

Worker async (même process FastAPI ou sidecar — cf. §15) qui :

1. Joint la room comme **participant subscribe-only** (`can_subscribe=true, can_publish=false`).
2. Reçoit les pistes audio des participants (operator, invités, Shugu) — soit subscribe individuel + mix Bridge, soit **Egress room composite** LiveKit qui produit un mix Opus.
3. Format pivot : **Opus 48 kHz mono, 20 ms frames** — natif LiveKit (codec d'origine dans la room Docker locale), décodé out-of-the-box par Web Audio dans Chromium/Firefox. Pas de réencodage nécessaire pour visitor_ws si les viewers sont desktop ; cf. fallback AAC plus bas pour iOS Safari.
4. Wrappe chaque frame dans le `TTSChunk` existant (`core/protocols.py`) — `payload=opus_frame, seq=monotonic, final=False, mime="audio/ogg; codecs=opus"`. **Réutilisation du schéma** — pas de protocol binaire parallèle. `final=True` jamais émis sur le bridge live.
5. Publie sur le topic `stage` avec un type `voice.frame` (à ajouter au sérialiseur `_ws_serializer.py` — déjà fait du caching par `id(event)`, parfait pour fanout N viewers à coût ~1).
6. Côté frontend, `visitor_ws` consomme déjà ces events. Nouveau handler `AudioStageReceiver` : décode Opus via Web Audio AudioWorklet, route vers `AudioContext` mix avec le canal animation.

**Lip-sync VRM** : Shugu publie un `data_track` parallèle avec signal `voice.viseme` calculé en post-process sur les chunks PCM Piper (RMS + energy bands FFT, mapping vers 5-7 visèmes VRM standards). Piper ne fournit pas d'alignment viseme natif (contrairement à certains TTS cloud) — on calcule donc côté `tts_local.py` au moment où chaque chunk audio est produit. Le VRM ne représente que Shugu — on ne lip-sync pas operator/guests.

**Codec fallback** : si Opus MSE pose problème (iOS Safari historiquement KO), transcode AAC LC côté Bridge via PyAV (~3-5 ms/frame). Décision sur bench cross-browser Sprint E.

## 7. Modération v1 — Raise-hand

Bouton ✋ dans l'UI `visitor_ws`. Click → POST `/api/voice/raise-hand` avec `session_id` + `message` ≤140 chars. Pipeline :

1. **Filtrage** : `injection_detector.scan(message)`. Score ≥ threshold → reject 422, log audit.
2. **Rate limit** : 1 raise-hand / viewer / 5 min (Redis `raisehand:<ip_hash>`, TTL).
3. **Queue + admin notify** : Redis ZSET `raisehand:queue` (score=`received_ns`, cap 50, drop oldest) ; event `voice.admin` consommé par la page admin `/app/admin/voice` via `operator_ws`.
4. **Accept** : mint token LiveKit `guest-{ip_hash_short}-{ts}` (`can_publish=true, can_subscribe=true, ttl=15min`), push via `visitor_ws` → frontend bascule mode guest. **Refuse** : push event `refused`, clear côté client.
5. **Kick instant** : admin button → révoque le `jti` (Redis `jwt:revoked`) + `LiveKitAPI.remove_participant()`.

V2 (hors scope) : Shugu décide elle-même via tool_call `raise_hand_evaluator` (injection + sentiment + history).

## 8. Recording + training pipeline

LiveKit **Egress** est dispatché par le Worker `shugu-voice` au début de chaque session (mode `RoomCompositeEgress` → Opus + opt MP4 vidéo si avatars web canvas inclus). Cible :

- **Storage v1 (verrouillé)** : disque local du PC de dev, path **`data/voice_recordings/<session_id>/`** (relatif à la racine repo, le projet est mono-node single-PC). Une session = un dossier (audio Opus ou MP4 + manifeste JSON `metadata.json`).
- **Storage v2 (multi-node, hors scope)** : S3 ou compatible (Cloudflare R2 / Backblaze B2). Migration triggered uniquement si on déménage LiveKit vers un VPS ou multi-machine.

Migration Alembic — table `voice_sessions` (cf. §13) avec `training_flag` (default **`false`**, opt-in explicite) et `retention_until = started_at + 30j`. Cron `purge_voice_recordings` tourne 1×/jour via **APScheduler** wirée dans le lifespan FastAPI (`backend/shugu/voice/training_purge.py`) ; sur la machine Windows on évite la dépendance à un cron Linux. Supprime le dossier + flag DB pour les sessions où `retention_until < now() AND training_flag = false AND redacted = false`.

Consent : à l'arrivée du premier viewer dans une session live, le client `visitor_ws` reçoit un event `voice.recording_consent_required` → modal "ce stream est enregistré pour entraînement Shugu, opt-out = quitter la page". GDPR right-to-be-forgotten : route `DELETE /api/account/voice-recordings` (gated par auth user) qui scrub la session_id du recording (audio re-encodé sans le segment où l'user parle, métadonnée flag `redacted=true`).

## 9. Sécurité

- **Prompt injection** : `injection_detector.scan` côté raise-hand (§7) ET sur transcript STT guest avant injection contexte LLM.
- **Rate limiting** : raise-hand 1/5 min, mint guest 5/h global, JWT TTL 15 min côté guest.
- **JWT scopes** : claim `voice_role: operator|guest|viewer` dans `auth/jwt_tokens.py`. `viewer` n'a pas de token LiveKit (il lit `stage` via son cookie session).
- **Recording consent** : modal à la connexion en mode `live`, reset au toggle `private→live`.
- **GDPR** : `DELETE /api/account/voice-recordings`, suppression physique sous 72 h.
- **Internal endpoints** : `/internal/voice/*` protégés par HMAC `compare_digest` (cf. `internal_vip.py`), bind `127.0.0.1`.

## 10. Métriques observabilité

Métriques Prometheus exposées via `GET /metrics` (gated par `SHUGU_METRICS_ENABLED`) :

- `shugu_voice_e2e_latency_ms{leg=stt|llm_ttft|tts_ttfb|network}` — histogram, P50/P95/P99
- `shugu_voice_bargein_total{decision=stop|pivot|stubborn}` — counter
- `shugu_voice_fsm_state_seconds{state=...}` — histogram (durée par état)
- `shugu_voice_raisehand_total{outcome=accepted|refused|filtered}` — counter
- `shugu_voice_recording_bytes_total` — gauge (taille pool recordings actifs)
- `shugu_voice_training_pool_count` — gauge (sessions avec `training_flag=true` en stockage)
- `shugu_voice_session_active` — gauge (1 si session en cours)
- `shugu_voice_bridge_drops_total` — counter (frames Opus droppées si slow consumer `stage`)
- `shugu_voice_gpu_vram_used_mb{component=ollama|whisper}` — gauge, monitoring VRAM 7800 XT (16 GB total) pendant inférence ; alerte si >14 GB (risque OOM Vulkan)
- `shugu_voice_gpu_vram_total_mb` — gauge constant (16384) pour calculer un % côté Grafana
- `shugu_voice_websearch_calls_total{provider=tavily|brave,outcome=ok|err|ratelimit}` — counter (suivi free tier quota)

VRAM source : `rocm-smi` n'est pas dispo Windows ; on utilise **DXGI Adapter Memory Info** (via wmi/pyadl) ou simplement parsing de `nvidia-smi` non applicable → fallback heuristique en lisant les logs Ollama (`prompt eval`, `kv cache size`). À fixer Sprint A (probe une fois la stack installée).

Cost control : single-stream local — pas de coût marginal LLM/STT/TTS. Kill-switch global `voice_subsystem_enabled=false` câblé dès Sprint A pour stopper Ollama/Piper/whisper et libérer la VRAM si besoin de la GPU pour autre chose (rendu VRM lourd, etc).

Logs structlog : event `voice.fsm.transition` à chaque transition, `voice.bargein.decided` à chaque INTERRUPTED, `voice.session.start/end` avec `session_id` corrélé aux recordings.

## 11. Fichiers à créer

Liste sous l'hypothèse §15 question 4 = option (b) — `voice/livekit_agent.py` extends `vip_agent.py`, ce dernier reste pour le path VIP 1-on-1 privé existant.

| Path | Rôle |
|---|---|
| `backend/shugu/voice/__init__.py` | Package init |
| `backend/shugu/voice/livekit_agent.py` | **Worker LiveKit Agents Python** (refactor de `adapters/vip_agent.py`, option (b) — extends). Ajoute `mode=live\|private`, gère les multiples participants (operator + guests), wire les wrappers locaux STT/LLM/TTS, embarque la FSM (§4) |
| `backend/shugu/voice/audio_bridge.py` | Worker subscribe-only LiveKit room → `TTSChunk` → `EventBus.publish("stage", ...)` → `visitor_ws` |
| `backend/shugu/voice/recording.py` | LiveKit Egress dispatch + écriture metadata Postgres + chemins **local FS** sous `data/voice_recordings/<session_id>/` |
| `backend/shugu/voice/llm_local.py` | Wrapper httpx **OpenAI-compat streaming** (`POST localhost:11434/v1/chat/completions` avec `stream=true`), compatible llama-server (default) et Ollama (fallback), expose interface `LLMStreamAdapter` |
| `backend/shugu/voice/tts_local.py` | Wrapper **Piper subprocess streaming** (stdin texte → stdout PCM/WAV chunks), gère cold start + chunker prosodique consumer |
| `backend/shugu/voice/stt_local.py` | Wrapper **whisper.cpp subprocess streaming** (ou bindings Python `pywhispercpp`), build Vulkan, modèle `models/whisper/small-fr.bin` |
| `backend/shugu/voice/fsm.py` | State machine §4 (pure logic, testable unit avec fakes) |
| `backend/shugu/voice/chunker.py` | LLM stream → segments à frontière prosodique pour TTS |
| `backend/shugu/voice/fillers.py` | Bank de fillers acoustiques pré-rendus offline via Piper (cache disque `models/piper/fillers/<mood>/*.wav`), choix aléatoire selon mood |
| `backend/shugu/voice/web_search.py` | Tool wrapper Tavily / Brave free tier (httpx async, retry + rate-limit guard) |
| `backend/shugu/voice/raise_hand.py` | Service Redis ZSET + filtre injection_detector |
| `backend/shugu/voice/training_purge.py` | Job APScheduler quotidien purge 30j |
| `backend/shugu/routes/voice_admin.py` | Endpoints admin moderation : list raise-hand queue, accept/refuse, kick, toggle live/private |
| `backend/shugu/routes/voice_public.py` | `POST /api/voice/raise-hand`, `GET /api/voice/status` |
| `frontend/src/features/voice-room/VoiceRoom.tsx` | Composant operator + guest (LiveKit components) |
| `frontend/src/features/voice-room/RaiseHandButton.tsx` | Bouton viewer ✋ |
| `frontend/src/features/voice-room/AudioStageReceiver.ts` | Décodeur Opus → AudioContext, drive lip-sync existant |
| `frontend/src/features/voice-room/AdminPanel.tsx` | UI admin queue raise-hand, accept/deny, mute, kick |
| `frontend/src/app/admin/voice/page.tsx` | Route App Router host de l'AdminPanel |
| `infra/livekit/docker-compose.yml` | Compose LiveKit container local (image `livekit/livekit-server`, ports 7880/UDP, volumes config) |
| `infra/livekit/livekit.yaml` | Config server LiveKit (api_key/secret générés, redis off ou mono-node, UDP range, recording dir) |
| `models/whisper/small-fr.bin` | Modèle Whisper `small` quantisé (gitignored, fetché via script) |
| `models/piper/fr_FR-siwis-medium.onnx` | Voix Piper française ONNX (gitignored, fetché via script `scripts/fetch_voice_models.ps1`) |
| `models/piper/fr_FR-siwis-medium.onnx.json` | Config voix Piper (phonemizer, sample rate, etc) |
| `infra/llama/start-llama-server.ps1` | ✅ (déjà créé) PowerShell launcher llama-server avec flags Vulkan optimisés 7800 XT |
| `infra/llama/README.md` | Ops doc LLM backend (sera créé en sprint A.bis) |

## 12. Fichiers à modifier

| Path | Change |
|---|---|
| `backend/shugu/app.py` | Wire le `shugu-voice` Worker dispatch (process séparé), wire `audio_bridge` task dans le lifespan, register `voice_admin` + `voice_public` routes |
| `backend/shugu/routes/visitor_ws.py` | Étendre `_stream_stage` pour gérer le nouveau type d'event `voice.frame` (sérialisation cachée déjà OK) |
| `backend/shugu/routes/livekit_api.py` | Ajouter mint token `guest` (path différent du VIP existant), garder `vip` path pour backward compat tant que pas migré |
| `backend/shugu/auth/jwt_tokens.py` | Ajouter `voice_role` claim, helpers `issue_guest_token` |
| `backend/shugu/core/protocols.py` | Pas de change — `TTSChunk` réutilisé tel quel |
| `backend/shugu/core/event_bus.py` | Pas de change si throughput tient — sinon bump `max_queue` pour le topic `stage` |
| `backend/shugu/config.py` | ✅ Ajouté Sprint A + A.bis : `llm_base_url` (default `http://localhost:11434`), `llm_model` (default `gemma-4-26b-a4b-iq4_xs`, cosmétique), `whisper_bin`, `whisper_model`, `piper_bin`, `piper_voice`, `voice_recordings_dir`. Nommage backend-agnostique (llama-server ou Ollama). Reste : `voice_default_mode`, `voice_egress_enabled`, `tavily_api_key` / `brave_api_key` (optionnels, Sprint H). |
| `backend/pyproject.toml` | Ajouter `livekit-plugins-turn-detector`, `pywhispercpp` (ou `whispercpp` Python bindings), `apscheduler`, `aiortc` (si on transcode côté bridge). **Retrait** des deps cloud : pas de `livekit-plugins-deepgram` ni `livekit-plugins-cartesia` |
| `frontend/package.json` | Bump `@livekit/components-react` si besoin de la dernière API |
| `backend/shugu/adapters/vip_agent.py` | **Déprécier** — soit supprimé après migration, soit gardé en `voice_role=vip` mode private uniquement (à trancher §15) |

## 13. Migrations DB

Table `voice_sessions` (Alembic — `0006_voice_sessions.py` ou prochain index libre) :

```sql
CREATE TABLE voice_sessions (
    session_id      UUID PRIMARY KEY,                -- aligne sur §11 (recording.py)
    room_name       TEXT NOT NULL,
    started_at      TIMESTAMPTZ NOT NULL,
    ended_at        TIMESTAMPTZ,
    participants    JSONB NOT NULL DEFAULT '[]',     -- [{"role":"operator","identity":"shugu"}, ...]
    mode            TEXT NOT NULL,                    -- "live" | "private"
    duration_ms     BIGINT,
    recording_path  TEXT,                             -- ex: "data/voice_recordings/<uuid>/composite.opus"
    training_flag   BOOLEAN NOT NULL DEFAULT FALSE,
    retention_until TIMESTAMPTZ NOT NULL,
    redacted        BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE INDEX ix_voice_sessions_retention ON voice_sessions (retention_until)
    WHERE training_flag = FALSE AND redacted = FALSE;
CREATE INDEX ix_voice_sessions_started ON voice_sessions (started_at DESC);
```

Le `recording_path` pointe vers un fichier sous `data/voice_recordings/<session_id>/` (chemin relatif à la racine repo, résolu via `config.voice_recordings_dir`). Pas de table `voice_recordings_consent` v1 — le consent est ambient (modal à la connexion, pas signé per-message). Si on a besoin de prouver un consent légalement valide post-coup, on évolue v2 vers une table dédiée.

## 14. Sprint plan estimé

8 sprints adaptés au stack 100 % local Vulkan, chacun = livrable testable :

- **Sprint A — Local infra setup (~1 j)** ✅ **Mergé PR #97** : install composants locaux, smoke test CLI, `infra/livekit/docker-compose.yml` + `livekit.yaml`, `infra/llama/start-llama-server.ps1`, `backend/scripts/voice_smoke_test.py`. Latences documentées.
- **Sprint A.bis (PR ouverte le 2026-05-03) — pivot vers llama.cpp + lancement infra reproductible** : pivot LLM backend Ollama → llama.cpp natif. Mise à jour docs/specs/config : `llm_base_url` / `llm_model` au lieu de `ollama_base_url` / `ollama_model`. `infra/llama/README.md` créé. Build instructions Vulkan SDK + Ninja + VS2022 dans setup doc. Gemma 4 IQ4_XS (13.4 GB) verrouillé comme sweet spot 16GB VRAM.
- **Sprint B — LiveKit Agent worker (~1 j)** : `voice/livekit_agent.py` squelette qui rejoint la room Docker locale, écoute audio operator, transcrit (whisper non-streaming), répond text simple via llama-server (non-streaming), synthétise réponse Piper one-shot. End-to-end naïf, latence assumée ~700 ms. Test : poser une question au mic → entendre Shugu répondre dans la room.
- **Sprint C — Streaming pipeline (~1 j)** : passer llama-server en `stream=true`, brancher `chunker.py` (frontières prosodiques), Piper en streaming chunks via subprocess pipe, mesurer P50/P95 par leg. Cible latence chute à ~330-450 ms. Test : bench TTFB par leg, comparer Sprint B vs C.
- **Sprint D — Barge-in FSM + turn detection (~1 j)** : `fsm.py` (IDLE → LISTENING → THINKING → SPEAKING → INTERRUPTED → YIELDING / STUBBORN_SPEAKING), VAD interrupt + cancel TTS in-flight (kill subprocess Piper en cours), plugin turn-detector. Test unit FSM (toutes transitions) + E2E 3 scénarios (stop / pivot / stubborn).
- **Sprint E — Audio Bridge → visitor_ws (~1 j)** : `audio_bridge.py` worker subscribe-only LiveKit → audio mixé → `EventBus.publish("stage", ...)` → fanout `visitor_ws`, toggle live/private via Redis flag, frontend `AudioStageReceiver`. Test : viewers Chrome+Firefox entendent live, bench CPU bridge sous 50 viewers simulés (single-PC, scale réaliste).
- **Sprint F — Raise-hand UX + admin moderation (~1 j)** : `voice_public.py` (POST raise-hand + injection_detector) + `voice_admin.py` (queue, accept/deny, mute, kick) + frontend `RaiseHandButton` + `AdminPanel`. Test : E2E Playwright "raise hand → accept → guest parle → kick".
- **Sprint G — Recording local FS + cron purge (~0.5 j)** : LiveKit Egress vers `data/voice_recordings/<session_id>/`, table `voice_sessions`, APScheduler purge 30j wirée dans lifespan FastAPI, route GDPR `DELETE /api/account/voice-recordings`. Test : session 2 min → fichier + row DB, faux-clock test purge.
- **Sprint H — Web search tool + bench Qwen3.6-35B-A3B (~0.5 j)** : `voice/web_search.py` Tavily/Brave free tier + tool_call exposé au LLM ; télécharger `Qwen3.6-35B-A3B GGUF` ; bench latence offload CPU/GPU vs Gemma 4 26B-A4B IQ4_XS (TTFT, qualité réponse FR/EN, hallucinations) ; documenter le winner et figer le default dans config.

Total ~7-8 j + contingency 30 % → **viser 2 semaines** pour v1 complète.

## 15. Open questions / risques

1. **Whisper `small.en` vs `small` multilingue** : la voix Shugu cible le **FR** et l'operator parle FR — le modèle multilingue `small` est nécessaire pour le FR (`small.en` = English-only). À confirmer Sprint A : `small` (FR/EN switching) ou `medium` si la qualité `small` n'est pas suffisante (medium ~244 MB, latence ~150-200 ms, encore acceptable). **Default verrouillé : `small` multilingue**.
2. **Voice cloning Piper vs Coqui XTTS v2 (post-MVP)** : Piper voix `fr_FR-siwis-medium` est neutre, pas la voix "Shugu". Pour cloner une voix custom (samples existants), Coqui XTTS v2 est la voie open source ; bench latence + qualité hors scope v1 mais à planifier Sprint I.
3. **Turn detection latence réelle** : LiveKit End-of-Utterance annonce <50 ms inference, 100-200 MB RAM par instance. À bencher sous charge Sprint D, et fallback timeout VAD basique si l'EOU model alpha 2025-2026 n'est pas suffisamment stable.
4. **GDPR consent** : `training_flag` verrouillé default **`false`** (opt-in). Reste à trancher : modal viewer bloquante (no-consent = redirect) ou informative (no-consent = recording gardé mais pas dans pool training) ? Recommandation : **informative**.
5. **vip_agent.py — option (a)/(b)/(c)** ? Recommandation par défaut : **(b) coexiste** (`voice/livekit_agent.py` = public live/private, `vip_agent.py` = VIP 1-on-1 privé existant). À reconfirmer avant Sprint B.
6. **Modération Shugu auto-mod (v2, hors scope)** : v1 admin/mod accept/deny raise-hand manuellement ; v2 Shugu auto-mod (filtres injection + sentiment + history → mute/kick auto). Pas avant qu'on ait un baseline humain solide.
7. **VRAM ceiling** : Gemma 4 26B-A4B Q5_K_M ~8 GB + whisper `small` ~1 GB + KV cache q8_0 + buffers Vulkan ≈ 10-11 GB sur les 16 GB. Si on bench Qwen3.6-35B-A3B Q4 (~22 GB), il faudra offload CPU/GPU mixte (`num_gpu=N` Ollama) — latence à mesurer Sprint H. Pas un blocker MVP, juste une décision post-bench.

## 16. Références

**LiveKit & framework**
- LiveKit Agents framework (Python) — https://docs.livekit.io/agents/
- LiveKit AccessToken / Egress / AgentDispatch — https://docs.livekit.io/home/server/
- LiveKit Turn Detector plugin — https://docs.livekit.io/agents/build/turns/turn-detector/
- LiveKit self-hosted Docker quickstart — https://docs.livekit.io/home/self-hosting/local/

**LLM local (Ollama + AMD Vulkan)**
- Ollama AMD Windows Vulkan setup — https://github.com/ollama/ollama/blob/main/docs/gpu.md
- Ollama HTTP API (streaming chat) — https://github.com/ollama/ollama/blob/main/docs/api.md
- Gemma 4 release notes (2026-04-02) — https://blog.google/technology/developers/gemma-4-open-models/ (placeholder, à remplacer par lien officiel exact au moment du Sprint A)
- Gemma 4 26B-A4B model card sur Ollama — https://ollama.com/library/gemma4
- Qwen3.6 docs / model card — https://qwenlm.github.io/blog/qwen3.6/ (placeholder)
- Qwen3.6 35B-A3B sur Ollama — https://ollama.com/library/qwen3.6

**STT local**
- whisper.cpp GitHub + Vulkan backend — https://github.com/ggerganov/whisper.cpp
- whisper.cpp Vulkan build instructions — https://github.com/ggerganov/whisper.cpp/blob/master/README.md#vulkan
- Modèles whisper quantisés `.bin` — https://huggingface.co/ggerganov/whisper.cpp

**TTS local**
- Piper TTS GitHub — https://github.com/rhasspy/piper
- Voix Piper FR `fr_FR-siwis-medium` — https://huggingface.co/rhasspy/piper-voices/tree/main/fr/fr_FR/siwis/medium
- Coqui XTTS v2 (post-MVP voice cloning) — https://github.com/coqui-ai/TTS

**VAD / Turn detection**
- Silero VAD — https://github.com/snakers4/silero-vad

**Web search tools**
- Tavily API docs (free tier 1000 req/mois) — https://docs.tavily.com/
- Brave Search API — https://api.search.brave.com/app/documentation

**Inspiration produit**
- Vedal / Neuro-sama architecture talks (références produit, pas technique précise) — keynotes Twitch / interviews YouTube publiques

**Repo internes** : `backend/shugu/adapters/vip_agent.py`, `backend/shugu/routes/visitor_ws.py`, `backend/shugu/routes/livekit_api.py`, `backend/shugu/core/protocols.py`, `backend/shugu/adapters/injection_detector.py` — à lire avant Sprint A.
