# Shugu v4 — Architecture

> Agent incarné live : Hermes (MiniMax M2.7) pilote un avatar VRM via tool_calls,
> parle en streaming TTS MiniMax WS, entend en streaming STT faster-whisper,
> manipule un bureau virtuel visible sur le stream, le tout dans un design
> glassmorphe "Celestial Veil".

## Contenu

1. [Vue d'ensemble](#vue-densemble)
2. [Flux de données](#flux-de-données)
3. [Composants backend](#composants-backend)
4. [Composants frontend](#composants-frontend)
5. [Protocoles inter-services](#protocoles-inter-services)
6. [Sécurité — surfaces de confiance](#sécurité--surfaces-de-confiance)
7. [Observabilité](#observabilité)
8. [Points d'extension](#points-dextension)

---

## Vue d'ensemble

Shugu v4 est un pipeline serial de performances live, orchestré par un backend
FastAPI + Redis et un frontend Next.js. Une "performance" = un événement joué
sur scène (voix + animation + effet bureau), et il y en a **une seule à la
fois** garantie par le `Picker`. Les sources de performances sont :

| Source | Origine | Priorité |
|---|---|---|
| Opérateur mode Shugu | Chat texte opérateur | 0 (priorité max) |
| Opérateur mode Hermes embodied | Chat texte / voix opérateur | 0 |
| Visiteur | Chat public texte | 1 |
| Visiteur `!command` | Chat public commande | 2 |
| Ambient daemon | Autonome, sans input | 3 (plus basse) |
| Storyboard | Sélection pondérée mood | 3 |

## Flux de données

### Message public (visiteur → audience)

```
visiteur chat
    ↓ WebSocket /ws/visitor
BasicModeration (rate, profanité, injection)
    ↓ QueuedMessage(route=shugu_persona, priority=1)
RedisQueue.pending
    ↓ PrepWorker dequeue
ShuguPersonaBrain (MiniMax M2.7, préserve <think>)
    ↓ response
Moderation egress + extract_emotion + extract_tags
    ↓ strip_think (pour TTS uniquement, raw conservé en history)
RedisQueue.ready (precomputed_audio vide si tts_streaming=True)
    ↓ Picker dequeue
performance.start → TTS stream (MiniMax WS) → performance.audio_chunk (×N)
    → performance.end
    ↓ InProcessEventBus "stage"
fanout sur tous les /ws/visitor + /ws/operator connectés
    ↓ client
MediaSource decode + AnalyserNode volume → LipSync JawOpen
timed_cues setTimeouts → SceneManager / AnimationMixer / EmoteOverlay
```

### Message opérateur mode Hermes embodied (privé → audience)

```
opérateur chat (target=hermes) ou voix
    ↓ /ws/operator OR /ws/operator/voice (PCM 16kHz, frames 20ms)
         └ voice: webrtcvad segmentation → faster-whisper transcript
HermesEmbodiedBrain.run_once(text, identity, priority=0)
    ↓ MiniMax M2.7 + tools schema (8 body + 7 desktop)
    ↓ tool_calls[]
BodyRouter.dispatch(call) pour chaque tool_call
    ├── body.say/gesture/emote  → RedisQueue.ready (priority=0)
    └── body.scene/look/expression/shot/mood  → event_bus direct
    └── desktop.*                → event_bus direct (state client-side)
    ↓
Picker joue body.say/gesture avec le même pipeline que les visiteurs
    ↓
clients reçoivent tout sur /ws/visitor et /ws/operator
```

### Barge-in (opérateur interrompt Hermes)

```
Hermes TTS streaming en cours
    ↓ chunks audio envoyés au client
opérateur reparle → frames PCM au serveur
    ↓ webrtcvad détecte speech
VoiceDuplex.on_frame → >=150ms continu → _trigger_barge_in_locked
    ↓ Picker.interrupt(reason=operator_voice)
_interrupt_event.set()
    ↓
_broadcast_streaming check entre chaque chunk → break
    ↓ performance.truncate sur event_bus
client → StreamingAudioPlayer.abort() + clearCueTimers
    ↓ performance.end publié (même chemin via finally)
```

## Composants backend

### Couche core (`backend/shugu/core/`)

- **`protocols.py`** — Protocols (typing.Protocol) : `BrainAdapter`,
  `TTSAdapter`, `TTSStreamAdapter`, `STTAdapter`, `ModerationLayer`,
  `PersonalityLoader`, `EventBus`. Dataclasses : `Turn`, `BrainDelta`,
  `TTSResult`, `TTSChunk`, `ModerationVerdict`, `PersonalityDoc`.
- **`identity.py`** — `VisitorIdentity` (ip_hash) vs `OperatorIdentity`
  (username, jti, session_id). **Barrière de type** : `HermesAgentBrain` et
  `HermesEmbodiedBrain` rejettent tout appel sans `OperatorIdentity`.
- **`mood.py`** — Markov chain `MoodState` conditionné par temps depuis
  dernier input humain. Méthodes `step()` (probabiliste) + `set()` (forcé par
  body.mood tool_call).
- **`quota.py`** — `QuotaTracker` Redis-backed. Plans `plus/max/ultra`. TTS
  daily chars + LLM 5h bucket. Charge **après succès** uniquement.
- **`body_control.py`** — Schémas Pydantic avec discriminated union : 8
  body.* + 7 desktop.*. Whitelists clips/scenes/expressions/moods/layouts/
  tabs. `_check_public_safe_name()` bloque 21 tokens sensibles, traversal,
  hidden files.
- **`ambient_scene.py` / `ambient_bank.py`** — Storyboards pré-chorégraphiés
  (cues timés, audio local optionnel, weight + mood_bias).
- **`observability.py`** — `SlidingRateLimiter` 15 règles par défaut +
  `Metrics` (body/desktop per-min, TTFB p50/p90/p99, barge_ins, interrupts).
- **`event_bus.py`** — `InProcessEventBus` asyncio. Topic "stage" = tout ce
  qui va aux clients. Tous les events du fichier `protocols.py`.
- **`viewer_count.py`** — broadcaste `viewer.count` quand les connexions WS
  changent (1s debounce).

### Couche pipeline (`backend/shugu/pipeline/`)

- **`queue.py`** — `RedisQueue` pending + ready zset. Priorité composite
  `priority_tier * 1e13 + received_ns`. `QueuedMessage.timed_cues` pour
  cues synchronisés avec l'audio.
- **`workers.py`** — `PrepWorker` : pending → brain → egress → push ready.
  Skip TTS si `tts_streaming=True` (le Picker stream). Préserve les
  `<think>` en history.
- **`picker.py`** — Dequeue ready → publish `performance.start`/audio*/end.
  Streaming path si primary TTS supporte + pas d'audio pré-computé. Barge-in
  via `asyncio.Event`. `_bg_tasks` set pour éviter GC. **Publie toujours
  `performance.end` dans `finally`** même si exception non-TTSError.
- **`ambient.py`** — `AmbientDaemon` Poisson timer. Micro-events + 25%
  storyboards. Mood lock-protected. `mark_human_input()` depuis les WS.
- **`body_router.py`** — Dispatcher des tool_calls Hermes :
  - `body.say/gesture/emote` → enqueue ready priority=0
  - `body.scene/look_at/expression/shot` → event bus direct
  - `body.mood` → `AmbientDaemon.set_mood()` avec lock
  - `desktop.*` → event bus direct (state côté client)
  - Rate limit par tool_name (snapshot exposé via /api/admin/metrics)
- **`voice_duplex.py`** — State machine 5 états. **Lock-clean** : work
  lourd (STT, Hermes) spawn en tasks trackées dans `_turn_tasks`, lock
  seulement pour décisions de state + publication. Cancel-safe.
- **`hermes_task.py`** — Legacy delegation (mode non-embodied). ACK +
  Hermes raw + FilterBrain résumé → broadcast. Conservé derrière un flag.

### Couche adapters (`backend/shugu/adapters/`)

- **`brain_shugu.py`** — `ShuguPersonaBrain` MiniMax via HTTP chat. Temp 1.0,
  top_p 0.95, top_k 40. Préserve `<think>`, strip seulement côté worker.
- **`brain_hermes.py`** — `HermesAgentBrain` legacy. OpenAI-compat chat vers
  port 8642. `OperatorIdentity` requis (TypeError sinon).
- **`brain_hermes_tools.py`** — `HermesEmbodiedBrain`. Boucle tool-use max
  12 hops. Parse `tool_calls[]` OpenAI style + fallback regex XML
  `<minimax:tool_call>`. Tool results en format MiniMax (role=tool,
  content=[{name,type,text}]).
- **`brain_filter.py`** — `FilterBrain` safety-net (temp 0.7). Strippe
  `<think>` + `<tool_call>` avant filtering.
- **`personality_loader.py`** — Hot-reload markdown files + mtime polling.
  Frontmatter YAML simple (`voice_id: xxx`).
- **`tts_minimax.py`** — `synthesize` (blob) + `synthesize_stream` (WS).
  Enforce `wss://` (reject cleartext). Charge quota **au premier chunk**,
  pas sur is_final (MiniMax peut close sans le flag). `_WSInvalidStatus`
  compat 13.x/14.x.
- **`tts_edge.py`** — Fallback gratuit Microsoft. Stream natif via
  `edge_tts.Communicate.stream()`.
- **`tts_elevenlabs.py`** — Blob only. Duration estimate via parse MP3
  header (réutilisé partout).
- **`tts_fallback.py`** — Primary → secondary. 4 chemins (stream/blob × 2).
  `contextlib.aclosing()` sur chaque generator pour fermer proprement les
  WS en cas d'erreur. Le primary blob-only est bien **wrappé** en final
  chunk (pas skipped).
- **`stt_streaming.py`** — `FasterWhisperSTT` lazy-load model. `is_speech()`
  VAD helper pour webrtcvad. `transcribe_pcm16()` offloaded via
  `asyncio.to_thread`.
- **`injection_detector.py`** — Heuristiques anti-prompt-injection. Log-only
  pour l'instant + auto-ban si score élevé.
- **`moderation_basic.py`** — Rate limit + profanity + length + bans.
  Visitors only (operator bypass).
- **`hermes_state.py`** — Lit `~/.hermes/` pour HermesStateWindow.
  **Anti-symlink** : `_is_safe_inside_root()` + bounded `_safe_read_text()`.
  Cache 5s TTL.

### Couche routes (`backend/shugu/routes/`)

- **`visitor_ws.py`** — `/ws/visitor`. Anonymous. `!commands` (wave, dance,
  etc.) short-circuitent LLM/TTS. Propage `mark_human_input()` à l'ambient.
- **`operator_ws.py`** — `/ws/operator`. JWT cookie/query. Bascule embodied
  vs delegation selon flag. `_spawn_bg()` trackés (anti-GC).
- **`operator_voice_ws.py`** — `/ws/operator/voice`. Bi-dir bytes+JSON.
  Frame cap 1024 bytes, rate cap 120 frames/s, text cap 2048 bytes.
  **Route montée seulement si `voice_duplex_enabled=True`** (sinon 404).
- **`admin.py`** — `/api/admin/{stats,quota,metrics,performances,bans}`.
- **`auth.py`** — JWT access/refresh, login, logout, me.
- **`hermes_state_api.py`** — `/api/hermes/state{,/tab}`. Opérateur only.
- **`health.py`** — `/healthz` public.

## Composants frontend

### Couche features (`frontend/src/features/`)

- **`messages/audioStreamer.ts`** — `StreamingAudioPlayer` basé sur MSE
  `audio/mpeg`. Auto-start sur **premier chunk non vide** (`started` flag),
  pas sur `seq===0`. Lip-sync via `attachMediaElement` du LipSync existant.
- **`voice/operatorVoice.ts`** — Client WS voice. `getUserMedia` + AudioContext
  16kHz + AudioWorklet `pcm16-worklet.js`. Start/stop cleanup.
- **`desktop/desktopState.tsx`** — Context + reducer. 11 actions. `nextZ` +
  `nextOffset` (pattern OpenRoom). `pendingAppend` pour animation typing.
- **`desktop/DesktopWindow.tsx`** — Une fenêtre. Animation char-par-char 45
  chars/sec avec cursor pulse. **No user drag** — Hermes only.
- **`desktop/VirtualDesktop.tsx`** — Surface asymétrique right-center 44vw.
  Invisible si rien ouvert.
- **`desktop/HermesStateWindow.tsx`** — 9 onglets. Polling 3s `/api/hermes/
  state/{tab}`.
- **`animations/AnimationMixerManager.ts`** — Idle loop + one-shot crossfade.
  Supporte Mixamo FBX retarget + VRMA natif.
- **`scenes/SceneManager.ts`** — Cooldown 10s anti-thrash. Camera, bg, idle
  anim, avatar transform.
- **`lipSync/lipSync.ts`** — RMS analyser. `attachMediaElement()` pour
  streaming (reuse l'analyser avec MediaElementSource).
- **`vrmViewer/{viewer,model}.ts`** — Three.js + three-vrm. Breathing,
  cinematic idle, procedural look-at. `startStreamingSpeak()` pour streaming.

### Couche components (`frontend/src/components/`)

- **`LiveHUD.tsx`** / **`Brand.tsx`** — Top chips en Celestial Veil (glass,
  halo, gradient, typo display).
- **`ChatFeed.tsx`** — Panel Twitch-style. Filter `role=assistant` sauf debug
  captions. No 1px border — ghost border via inset shadow.
- **`ChatInput.tsx`** / **`VisitorLogin.tsx`** — Inputs stream.
- **`OperatorPanel.tsx`** — Top-right collapse. Segmented Shugu/Hermes.
  Toggle debug captions.
- **`OperatorVoicePanel.tsx`** — Bouton mic ON/OFF + indicateur état live.
- **`EmoteOverlay.tsx`** — Imperative handle push(emote) → pop 2D emoji.
- **`SpeakingRing.tsx`** / **`Sparkles.tsx`** / **`LoadingScreen.tsx`**
  — Accessoires visuels.

## Protocoles inter-services

### WebSocket `/ws/visitor` et `/ws/operator`

Client → serveur :
- `{type: "ping", t}` / `{type: "chat.send", text, nonce, target?}`

Serveur → client (topic "stage") :
- `performance.start` / `performance.audio` (blob) / `performance.audio_begin`
  (streaming header) / `performance.audio_chunk` / `performance.truncate` /
  `performance.end`
- `scene.change` / `look.hint` / `expression.set` / `shot.change` / `mood.change`
- `desktop.window_open/close/file_edit/image_show/arrange`
- `hermes_state.window_open/close`
- `viewer.count`
- `error.moderation` / `queue.rejected` / `hermes_task.acknowledged`

### WebSocket `/ws/operator/voice`

Client → serveur :
- Binary : PCM16 mono 16kHz, frames 20ms (640 bytes). **Rejet si > 1024.**
- `{type: "ping"}` / `{type: "mic.close"}`

Serveur → client :
- `voice.ready` / `voice.state.change` / `voice.transcript.final` /
  `voice.barge_in` / `voice.closed`

### REST `/api/*`

- `POST /auth/login` / `GET /auth/me` / `POST /auth/logout`
- `GET /api/admin/{stats,quota,metrics,performances,bans}`
- `POST /api/admin/bans` / `DELETE /api/admin/bans/{ip_hash}`
- `GET /api/hermes/state` / `GET /api/hermes/state/{tab}`
- `GET /healthz`

## Sécurité — surfaces de confiance

| Surface | Confiance | Barrières |
|---|---|---|
| `/ws/visitor` | Anonyme | Rate limit + moderation + injection detect + auto-ban |
| `/ws/operator*` | JWT HS256 | cookie httpOnly + refresh rotation + jti revocation |
| `HermesAgentBrain.__init__` | Type-level | `isinstance(OperatorIdentity)` requis |
| `body_control.file_name` | Content-level | Regex ASCII + 21 tokens blacklist + path traversal |
| `desktop.show_image` URL | Content-level | Reject `http://`, require `https://` ou chemin public |
| `HermesStateReader` | Filesystem | Anti-symlink via `.resolve().is_relative_to()` |
| `operator_voice_ws` binary | Transport | Frame cap 1024 bytes + rate cap 120/s |

## Observabilité

### Métriques exposées via `GET /api/admin/metrics`

```json
{
  "queue": {"pending": 0, "ready": 0},
  "rate_limits": {
    "body.scene": {"used": 2, "cap": 5, "window_s": 60}, ...
  },
  "metrics": {
    "body_events_per_min": 12,
    "desktop_events_per_min": 3,
    "tts_ttfb": {"count": 10, "p50_ms": 820, "p90_ms": 1240, "p99_ms": 1800},
    "stream_interrupts_total": 2,
    "barge_ins_total": 1
  }
}
```

### Logs structurés (structlog JSON)

Chaque composant critique log des events JSON avec contexte :

- `picker.stream_done` `{perf_id, bytes, real_duration_ms, estimate_ms}`
- `picker.stream_interrupted` `{perf_id, bytes}`
- `picker.play_error` `{perf_id, error}`
- `body_router.body.say` `{chars, emotion, tags}`
- `body_router.rate_limited` `{name, retry_after_s}`
- `voice.turn_start` `{reason, bytes}`
- `voice.stt_failed` / `voice.hermes_error`
- `ambient.storyboard` `{slug, duration_ms, cues, mood, audio_path}`
- `ambient.mood` `{from, to}`
- `quota.tts_warning/exhausted` `{used, cap}`

## Points d'extension

1. **Nouveau tool_call `body.*` ou `desktop.*`** : ajouter schema dans
   `body_control.py`, handler dans `body_router.py`, event type dans
   `shuguClient.ts`, handler dans `index.tsx`. ~30 lignes.
2. **Nouveau storyboard ambient** : un entry dans `ambient_bank.py`,
   éventuellement un `.mp3` dans `frontend/public/ambient/`.
3. **Nouvelle personality** : markdown dans `backend/shugu/personalities/`,
   `personality_loader.get("name")` y accède.
4. **TTS supplémentaire** : impl `TTSAdapter` + `TTSStreamAdapter`, plug
   dans `app.py` lifespan. `FallbackTTS` les chaîne automatiquement.
5. **Sandbox réelle E2B (phase 9 future)** : remplacer `VirtualDesktop.tsx`
   par iframe E2B, traduire `desktop.*` events en commandes shell/xdotool.
   Protocole inchangé.
