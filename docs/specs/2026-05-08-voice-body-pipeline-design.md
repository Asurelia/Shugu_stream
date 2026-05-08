# Spec — Voice ↔ Body Pipeline (Direction D + E)

- **Date** : 2026-05-08
- **Auteur** : Claude (Opus 4.7) en collaboration avec Sylvain
- **Status** : Approuvé brainstorming, en attente review utilisateur
- **Direction** : D = Reconnecter VRM/lipsync/emotes au pipeline voice end-to-end + E = premier live test
- **Sprints précédents (mergeds)** :
  - PRs #97-107 : Voice pipeline complet (Sprints A-D) — VAD → Whisper STT → llama.cpp Gemma 4 26B + régie web_search → Piper TTS streaming + barge-in state machine
  - PRs #108-110 : Observatory mos-A iter 2

## 1. Contexte & objectif

### 1.1. Problème

À la fin du Sprint D, la stack voice est complète côté backend (VAD → STT → LLM → régie → TTS Piper avec streaming sentence-par-sentence + barge-in détecté). Le director (orchestrator + workers `say`/`face`/`anim`/`vfx`/`camera`) est aussi en place et publie des events `scene.apply` sur l'event_bus.

**Mais le frontend VRM avatar est complètement déconnecté de cette stack** :

- Le PCM audio produit par Piper reste en mémoire backend, sans transport vers le browser.
- Les events `scene.apply` du director ne sont consommés par aucun client React (`emoteController` est dormant).
- Le composant `lipSync.ts` côté frontend est prêt à analyser un `HTMLAudioElement` ou `ArrayBuffer` mais aucun audio ne lui parvient.

Sans cette reconnexion, l'avatar reste muet et inerte pendant que la stack voice "parle dans le vide". **Bloquant absolu pour le premier live test.**

### 1.2. Objectif

Livrer un pipeline complet end-to-end où :

1. L'avatar VRM bouge la bouche en synchronisation avec l'audio TTS streaming.
2. L'expression faciale (`[say_emotion:joy]`, `[face:joy]`) s'applique au bon moment grâce à un timestamp `audio_at_ms` partagé.
3. Les animations corps (`[anim:wave]`) et VFX (`[vfx:sparkle]`) déclenchés par le director sont rendus côté frontend.
4. Le barge-in (utilisateur interrompt Shugu) coupe l'audio + reset l'expression neutre en < 250 ms.
5. La latence end-to-end "LLM start token → avatar bouge bouche" est < 500 ms p50, < 800 ms p95.

### 1.3. Non-objectifs (scope explicite)

- **Pas de migration Whisper → Gemma 4 E4B audio encoder** dans cette phase. Évalué en sprint E2 séparément.
- **Pas d'activation MTP drafter Gemma 4** dans cette phase (en attente PR #22747 llama.cpp stable). Sprint E2 séparément.
- **Pas de viewer multi-utilisateur scalable** (premier live = 1-3 testeurs invités). Hardening multi-spectateurs = phase ultérieure.
- **Pas de gestion de SceneState persistant côté frontend** (snapshots incrémentaux ne sont pas dans le scope D).

## 2. Architecture cible

### 2.1. Vue d'ensemble (flux nominal)

```
                                  ┌─────────────────────────────┐
                                  │  LLM Gemma 4 26B + régie    │
                                  │  output: text + [tags]      │
                                  └───────────────┬─────────────┘
                                                  │
                                  ┌───────────────▼─────────────┐
                                  │ director.orchestrator.tick()│
                                  │ tag_parser → Workers        │
                                  │   say / face / anim / vfx   │
                                  └───────┬──────────┬──────────┘
                                          │ (publish) │ (publish)
                                          ▼          ▼
                           ┌──────────────────────────────────┐
                           │  event_bus (in-proc / Redis)     │
                           └───────┬──────────────────┬───────┘
                                   │                  │
                                   ▼                  ▼
                  ┌────────────────────────┐  ┌──────────────────────┐
                  │  /viewer/events  (WS)  │  │  audio_bridge.py     │
                  │  scene.apply payloads  │  │  PiperTTS → LiveKit  │
                  │  + audio_at_ms tag     │  │  publish PCM track   │
                  └───────────┬────────────┘  └──────────┬───────────┘
                              │                          │
                              ▼                          ▼
   ┌──────────────────────────────────────────────────────────────────┐
   │  FRONTEND React                                                  │
   │  ┌──────────────────┐    ┌──────────────────────────────────┐   │
   │  │ ViewerWS client  │    │  @livekit/client subscriber       │   │
   │  │ (events)         │    │  audio track → HTMLAudioElement   │   │
   │  └────────┬─────────┘    └────────┬─────────────────────────┘   │
   │           │  schedule via         │  attachMediaElement         │
   │           │  audioCtx.currentTime │                              │
   │           ▼                       ▼                              │
   │  ┌──────────────────────────────────────────────────────────┐  │
   │  │  sceneApplyMapper                                         │  │
   │  │   say_emotion → emoteController.playEmotion(preset)       │  │
   │  │   face        → emoteController.playEmotion(preset)       │  │
   │  │   anim        → animationMixerManager.play(clip)          │  │
   │  │   vfx         → vfxLayer.trigger(slug)                    │  │
   │  └──────────────────────────────────────────────────────────┘  │
   │                       │                                          │
   │                       ▼                                          │
   │  ┌────────────────────────────────────────────────────────┐    │
   │  │  VRM avatar (vrmViewer)  +  lipSync analyser ↑ blendshape│  │
   │  └────────────────────────────────────────────────────────┘    │
   └──────────────────────────────────────────────────────────────────┘
```

### 2.2. Décisions de design

| Décision | Choix retenu | Justification |
|---|---|---|
| Transport audio | **LiveKit WebRTC** | Adapters `livekit_*.py` déjà mergeds (Sprint D PR3). Latence sub-300ms native, audio + sync timestamps fournis par WebRTC. |
| Transport events | **WebSocket dédié `/viewer/events`** | Découplage propre du transport audio. Pattern miroir de `editor_ws` existant. Si LiveKit tombe, les events scéniques continuent. |
| Synchronisation audio↔anim | **Timestamp `audio_at_ms`** | Précision sub-50ms via horloge LiveKit partagée. Frontend schedule via `AudioContext.currentTime`. |
| Mapping director events → frontend rendu | **Côté frontend** (`sceneApplyMapper.ts`) | Sépare backend (état logique) du moteur de rendu (VRM). Si on change de moteur d'avatar, backend reste inchangé. |
| Barge-in | **VAD backend → stop chain centralisée** | Aligne sur l'archi voice existante (PR #106 VADDriver). Une seule source de vérité pour l'interrupt. |
| Auth WS | **JWT à TTL court (5 min) + endpoint refresh** | TTL court limite la fenêtre de vol de token. Refresh-token rotation maintient les sessions longues sans réauth visible. Token signe le `session_id` autorisé pour empêcher cross-session manipulation. |

## 3. Composants

### 3.1. Backend (Python)

| Fichier | Action | Responsabilité |
|---|---|---|
| `backend/shugu/voice/audio_bridge.py` | Implémenter (vide actuellement) | Subscriber sur `voice.tts.chunks` → publish vers LiveKit room audio track. Tag chaque chunk avec `chunk_started_at_ms` (horloge LiveKit). |
| `backend/shugu/voice/livekit_publisher.py` | Créer | Wrapper `LocalAudioTrack` LiveKit. Expose `publish_pcm(pcm, sample_rate=22050)` et `unpublish()` (pour barge-in). |
| `backend/shugu/director/event_bus.py` | Étendre | Ajouter `audio_at_ms` au payload de `scene.apply` quand `kind ∈ {say_emotion, face}`. Calcul = `now_ms - chunk_started_at_ms` du publisher courant. |
| `backend/shugu/app.py` | Ajouter route | Convention repo : REST sous `/api/`, WebSockets sous `/ws/`. `WS /ws/viewer/events` (auth JWT, broadcast `scene.apply` + `voice.interrupt`). REST `GET /api/viewer/state` (snapshot SceneState pour reconnect). REST `POST /api/voice/token` + `POST /api/voice/token/refresh`. **Auth WS** : recommander `Sec-WebSocket-Protocol: <jwt>` (echo via `ws.accept(subprotocol=...)`) plutôt que query-string `?token=<jwt>` qui se retrouve loggué par uvicorn/nginx — la query-string reste supportée mais devrait être réservée au dev/test. |
| `backend/shugu/voice/regie/interrupt_handler.py` | Créer | Listener `voice.interrupt` (publié par VADDriver) → enchaîne `PiperTTS.aclose()`, `livekit_publisher.unpublish()`, push `{action:"interrupt"}` sur `/viewer/events`. Debounce 200ms anti-faux-positifs. |
| `backend/shugu/auth/viewer_token.py` | Créer | Issue + refresh JWT spécifique viewer (claim `session_id`, TTL 5min). Pattern miroir de `auth/jwt_tokens.py` existant. |
| `backend/shugu/director/workers/{face,anim,vfx,camera}.py` | Vérifier (pas de modif fonctionnelle) | Confirmer publish `scene.apply` avec format normalisé. |
| Tests | Créer | `test_audio_bridge.py`, `test_livekit_publisher.py`, `test_interrupt_handler.py`, `test_viewer_token.py`, `test_viewer_events_ws.py`, `tests/integration/test_viewer_events_e2e.py`. TDD obligatoire. |

### 3.2. Frontend (TypeScript / React)

| Fichier | Action | Responsabilité |
|---|---|---|
| `frontend/src/features/livekit/LiveKitClient.ts` | Créer | Wrapper `livekit-client` Room + lifecycle. Expose `connect(token, url)`, `onAudioTrack(cb)`, `disconnect()`. **NB** : le package npm s'appelle `livekit-client` (déjà dans `frontend/package.json` v2.18+), PAS `@livekit/client`. |
| `frontend/src/features/livekit/LiveKitProvider.tsx` | Créer | Context React qui gère session LiveKit + token fetch (`/api/voice/token` — préfixe `/api/` pattern repo). Gestion auto-resume `AudioContext` derrière user gesture. |
| `frontend/src/features/viewer/ViewerEventsClient.ts` | Créer | Wrapper WS `/viewer/events` avec reconnect exponentiel (200/500/1000/2000ms cap) + heartbeat. Token refresh proactif T-60s avant expiration. Expose `onSceneApply(cb)` + `onInterrupt(cb)`. |
| `frontend/src/features/viewer/sceneApplyMapper.ts` | Créer | Mapping pur. Tables const : `SAY_EMOTION_TO_VRM_PRESET`, `FACE_TO_VRM_PRESET`, `ANIM_TO_CLIP_NAME`. Validation Zod sur l'event reçu. |
| `frontend/src/features/viewer/sceneScheduler.ts` | Créer | Convertit `audio_at_ms` + LiveKit audio currentTime → `setTimeout` ou `audioCtx.currentTime`. Ring buffer pour events arrivés en avance. |
| `frontend/src/features/emoteController/emoteController.ts` | Étendre | Ajouter `applyDirectorAction(action: ViewerAction)` qui consomme la sortie du mapper. API existante intacte. |
| `frontend/src/features/vrmViewer/AnimationMixerManager.ts` | Vérifier (potentiellement existant suite Sprint Phase A admin merges) ; sinon créer avec API `play(clipName: string, opts?: { loop?: boolean, fadeMs?: number })` | Pilote animations VRM corps depuis `anim` worker. PR D-1 inclut ce check en pré-travail. |
| `frontend/src/features/viewer/VFXLayer.tsx` | Créer (placeholder) | MVP : overlay React qui log les vfx slugs + 1-2 effets simples (sparkle, fade). Extension progressive. |
| `frontend/src/components/vrmViewer.tsx` | Étendre | Au mount : connecter LiveKitProvider + ViewerEventsClient ; brancher mapper + scheduler. |
| Tests | Créer | Vitest pour `sceneApplyMapper`, `sceneScheduler`, `ViewerEventsClient`. Playwright E2E pour `voice → bouge bouche → emoteController.playEmotion called`. |

## 4. Schémas events

### 4.1. `scene.apply` (backend → frontend, WS `/viewer/events`)

```json
{
  "type": "scene.apply",
  "kind": "say_emotion" | "face" | "anim" | "vfx" | "camera" | "outfit",
  "id": "joy",
  "ts": "2026-05-08T14:23:11.456Z",
  "audio_at_ms": 1240,
  "session_id": "voice-sess-abc123"
}
```

- `audio_at_ms` : offset depuis le début de la chunk audio TTS courante. Présent uniquement quand `kind ∈ {say_emotion, face}`. Absent pour `anim`/`vfx` purement scéniques (appliqués immédiatement à réception).
- `session_id` : pour discriminer entre plusieurs sessions concurrentes (live + replay debug). **Validé contre le claim JWT du token** — le backend rejette tout event qui mentionne un `session_id` ≠ `token.session_id`.

### 4.2. `voice.interrupt` (barge-in)

```json
{
  "type": "voice.interrupt",
  "session_id": "voice-sess-abc123",
  "reason": "vad_detected" | "manual" | "shutdown",
  "ts": "2026-05-08T14:23:13.001Z"
}
```

### 4.3. `tts.chunk_started` (LiveKit data channel — debug optionnel)

```json
{
  "type": "tts.chunk_started",
  "session_id": "voice-sess-abc123",
  "chunk_idx": 7,
  "sentence": "Salut tout le monde !",
  "started_at_livekit_ms": 12450
}
```

## 5. Flows

### 5.1. Flow nominal "Shugu dit 'Salut tout le monde !' avec joie"

```
t=0     LLM produit "[say_emotion:joy] [face:joy] Salut tout le monde !"
t=10ms  tag_parser → SayWorker.apply("joy") → publish scene.apply{kind:"say_emotion",id:"joy"}
t=12ms  tag_parser → FaceWorker.apply("joy") → publish scene.apply{kind:"face",id:"joy"}
t=15ms  text "Salut tout le monde !" → SentenceChunker → PiperTTS.synthesize_stream()
t=80ms  Piper → PCM bytes (~22 KB pour cette phrase)
t=82ms  audio_bridge.publish_pcm() → LiveKit room audio track
        chunk_started_at_livekit_ms = 12450
        backend tag les events précédents avec audio_at_ms calculés (=0 pour ces 2)
t=85ms  /viewer/events broadcast :
          {kind:"say_emotion",id:"joy",audio_at_ms:0}
          {kind:"face",id:"joy",audio_at_ms:0}
t=90ms  Frontend reçoit events → sceneScheduler.schedule()
        audio actuel pas encore commencé → délai = ~50-100ms (LiveKit pre-buffer)
t=140ms Frontend audio playback démarre + scheduler exécute :
          emoteController.playEmotion(VRMExpressionPresetName.Happy)
        lipSync analyser commence à driver les blendshapes au volume audio
t=140ms→2.5s   Avatar parle "Salut tout le monde !" avec expression joy
t=2.5s  Audio fini → idle, expression reste joy (jusqu'au prochain face/say)
```

### 5.2. Flow barge-in "user interrompt à t=1.2s"

```
t=1.2s  VADDriver détecte parole user (frame > vad_threshold)
t=1.21s VADDriver publie voice_event{type:"speech_detected"}
t=1.22s interrupt_handler reçoit → debounce 200ms attente confirmation STT
t=1.42s STT confirme transcript → enchaîne :
          a) PiperTTS.aclose() (kill subprocess si actif)
          b) livekit_publisher.unpublish_audio_track()
          c) /viewer/events broadcast {type:"voice.interrupt", reason:"vad_detected"}
t=1.45s Frontend reçoit interrupt :
          a) audio source ramp-down 50ms (no click) via gainNode.linearRampToValueAtTime
          b) emoteController.playEmotion(neutral)
          c) sceneScheduler.flush() (drop tous events pending)
t=1.50s Avatar silencieux + expression neutre, prêt pour la nouvelle entrée user
```

## 6. Error handling, edge cases, fail modes

### 6.1. Backend

| Scénario | Comportement | Justification |
|---|---|---|
| Piper subprocess timeout / crash | `synthesize_stream` skip la phrase + log `voice.tts.timeout` (déjà en place). `audio_bridge` envoie `tts.chunk_skipped` event. Frontend reçoit l'event suivant sans audio entre-temps. | Pattern existant. Pas de retry — la phrase est perdue, mieux qu'un blocage. |
| LiveKit room déconnecté pendant publish | `livekit_publisher.publish_pcm()` tente reconnect (3 essais exponentiels 200/400/800ms). Échec → log + drop audio. `/viewer/events` continue à émettre les events scéniques. | Audio est best-effort, events sont la vérité scénique. |
| `/viewer/events` WS client déconnecté | Backend détecte ConnectionClosed → cleanup subscription event_bus. Pas de buffering : un client qui rejoint reçoit l'état courant via REST `/viewer/state` (snapshot SceneState). | Pas de queue persistante = pas de fuite mémoire. |
| Worker `apply()` raise une exception | Pattern existant : `Worker.base` catch + log + return `StateDelta(patch={})`. Pas de propagation. | Garde le pipeline robuste. |
| `audio_at_ms` calculé négatif | Clamp à 0 + warning log. Frontend applique immédiatement sans schedule. | Drift acceptable au démarrage, mieux que freeze. |
| VADDriver false-positive interrupt | `interrupt_handler` debounce 200ms : si `voice.interrupt` n'est pas suivi de `stt.transcript_started` dans ce délai, on ignore l'interrupt. | Évite les "Shugu coupe sa phrase pour rien". |
| Auth WS `/viewer/events` | Token JWT en query param OR header `Sec-WebSocket-Protocol`. Validation via `auth/dependencies.py` existant. Token signé inclut `session_id` autorisé. | Empêche cross-session spoofing. |
| Token expiré pendant session | Frontend détecte 401 sur refresh → reconnect avec nouveau token (full handshake). Si refresh échoue (auth invalide) → notification user "session expirée, reload". | Pas de silent failure mid-stream. |

### 6.2. Frontend

| Scénario | Comportement |
|---|---|
| LiveKit client déconnecté | Reconnect auto via `@livekit/client` (built-in). Pendant la reconnect : `lipSync.analyser` voit silence → blendshapes à 0. Expression reste sur la dernière valeur. |
| `/viewer/events` WS déconnecté | `ViewerEventsClient` reconnect exponentiel (200/500/1000/2000ms cap). Au reconnect : fetch `/viewer/state` snapshot + apply au mapper pour resync l'expression actuelle. |
| Event reçu pour un `kind` inconnu | `sceneApplyMapper` log `viewer.unknown_kind` + return no-op. Pas d'erreur fatale. |
| Event avec `id` hors whitelist | Log + return no-op. |
| `audio_at_ms` reçu après que l'audio soit déjà passé (event en retard > 500ms) | `sceneScheduler.schedule()` détecte `delta < -500` → apply immédiatement (best-effort) + log `viewer.late_event`. |
| Event arrivé avant l'audio (cas nominal) | Schedule via `setTimeout(fn, delta_ms)`. Si `delta_ms < 16ms`, apply au prochain `requestAnimationFrame`. |
| `voice.interrupt` reçu pendant lecture audio | Force fade-out 50ms via `gainNode.gain.linearRampToValueAtTime(0, ctx.currentTime + 0.05)` puis `bufferSource.stop()`. |
| Browser refuse `AudioContext` (autoplay policy) | Provider expose `requireUserGesture: true` flag → afficher overlay "Click to start" qui appelle `audioContext.resume()`. |

### 6.3. Sécurité

- **JWT à TTL court (5 min)** + **endpoint `POST /voice/token/refresh`** pour rotation. Frontend refresh à T-60s avant expiration.
- **Validation `session_id`** : claim signé dans le token, vérifié à chaque event inbound.
- **Validation des messages reçus** : Pydantic backend (déjà pattern). Zod frontend sur `ViewerEvent` discriminated union avant dispatch au mapper.
- **Rate limit `/viewer/events`** : 1 connexion par token, max 5 connexions par user. Pattern `auth/rate_limit.py` existant.
- **Security headers** : middleware FastAPI équivalent Helmet (CSP `connect-src` whitelist LiveKit + WS, X-Frame-Options DENY, Strict-Transport-Security). Lib `secure-headers` ou `starlette-security-headers`.

## 7. Tests

### 7.1. Pyramide

| Niveau | Coverage | Outils |
|---|---|---|
| Unit | `livekit_publisher.publish_pcm` (mock Room), `interrupt_handler.debounce`, `audio_bridge` chunk_started_at calc, `sceneApplyMapper` (chaque kind→preset), `sceneScheduler` (delta calculé), JWT validation (TTL + session_id binding) | pytest + Vitest |
| Integration | `tag → worker → event_bus → /viewer/events broadcast` ; `Piper → audio_bridge → LiveKit publish` ; barge-in chain end-to-end avec VADDriver mocké | pytest async + LiveKit test server |
| E2E | Scénario complet : "Backend dit 'Salut' avec joy → frontend voit playEmotion(Happy) appelé + lipSync.volume > 0 + audio playable" | Playwright + LiveKit cloud sandbox ou local |
| Race tests | `voice.interrupt` arrive pendant que `audio_bridge` push une chunk ; reconnect WS pendant qu'un event arrive | pytest + asyncio.Event (pattern PR #106) |

### 7.2. Métriques cibles (à valider avant live test)

- Latence `LLM token → avatar bouge bouche` : **< 500 ms p50, < 800 ms p95**
- Drift `audio ↔ expression` : **< 100 ms p95**
- Barge-in cut-off : **< 200 ms** entre détection VAD et silence audio
- Reconnect resilience : 0 freeze visible pour drop WS < 2s

## 8. Sous-PRs

| PR | Scope | Critère DONE |
|---|---|---|
| **D-1** | Backend `livekit_publisher.py` + tests | unit tests verts, mock Room valide signal flow |
| **D-2** | Backend `audio_bridge.py` impl + branchement Piper | integration test Piper→bridge→publisher OK |
| **D-3** | Backend route `WS /viewer/events` + JWT auth + tests | client peut se connecter avec token valide, refusé sans |
| **D-4** | Backend `interrupt_handler.py` + branchement VAD | barge-in chain stop subprocess + push event en < 200ms |
| **D-5** | Backend `audio_at_ms` enrichment dans event_bus + Worker tests | event publié avec audio_at_ms calculé correctement |
| **D-6** | Frontend `LiveKitProvider` + audio consumer + lipSync attach | audio LiveKit → blendshapes lipsync OK en local |
| **D-7** | Frontend `ViewerEventsClient` + `sceneApplyMapper` + extension `emoteController` | event WS → emoteController.playEmotion appelé avec preset mappé correct |
| **D-8** | Frontend `sceneScheduler` (sync audio_at_ms) + extension vrmViewer | drift mesuré < 100ms p95 sur jeu de 10 phrases |
| **D-9** | Frontend barge-in handling (fade-out + reset expression + scheduler.flush) | interrupt reçu → silence audio + neutral expression en < 250ms |
| **D-10** | E2E Playwright + Prometheus metrics + dashboard Grafana | métriques cibles validées sur 50 itérations |

**Estimation** : ~5-7 jours de dev (séquentiel partial : D-1/D-2/D-3 parallélisables, D-6/D-7 parallélisables).

## 9. Plan ops live test E (après D-10 mergé)

### 9.1. Pré-requis check (J-1)

- [ ] Toutes les PRs D-1 à D-10 mergées sur `main`, CI green
- [ ] Smoke test local 30 min : voice ↔ avatar, 0 freeze, 0 drift visible
- [ ] LiveKit prod deployment validé (URL, token endpoint, capacity)
- [ ] OBS scene avec frontend en navigateur tab → window capture validé
- [ ] Backup audio configuré (si voice tombe : musique d'attente automatique)

### 9.2. Session live test (J0, durée cap 30 min)

- [ ] Audience cible : 1-3 testeurs invités (pas de raid public encore)
- [ ] Goal #1 : 10 minutes de conversation continue sans freeze ni drift visible
- [ ] Goal #2 : tester barge-in 5 fois sur l'opérateur, 5 fois sur transcription Twitch chat
- [ ] Goal #3 : tester un crash volontaire (kill Piper subprocess) → vérifier resilience
- [ ] Recorder full session (OBS) pour post-mortem

### 9.3. KPI à mesurer pendant la session

- Latence end-to-end (LLM start → avatar mouvement bouche) : p50/p95/p99
- Nombre de barge-ins déclenchés / faux-positifs
- Nombre de reconnects WS/LiveKit
- Drift audio↔anim moyen
- CPU/GPU/RAM machine host
- Tokens Gemma 4 / sec

### 9.4. Post-mortem (J+1)

- [ ] Doc `docs/postmortems/2026-XX-XX-first-live-test.md` avec findings
- [ ] Issues GitHub créées pour chaque bug confirmé
- [ ] Décision GO/NO-GO Sprint E2 (POC MTP drafter Gemma 4 + POC Gemma 4 E4B audio encoder en remplacement Whisper)

## 10. Hors scope explicite

Repris ici pour clôturer toute ambiguïté :

- **Migration STT Whisper → Gemma 4 E4B audio natif** : à évaluer en Sprint E2 séparé. Bénéfices potentiels : pipeline unifié, latence frame 40ms vs 160ms (Gemma 3n) ou 30ms (Whisper streaming actuel). Risque : dépendance ML supplémentaire à host.
- **Activation MTP drafter Gemma 4 dans llama.cpp** : en attente PR #22747 stable. Sprint E2.
- **Multi-viewer scalable** : architecture actuelle suppose 1-3 spectateurs. Pour scale réel (>50 viewers), il faudra hub LiveKit / SFU dédié + queue Redis pour `/viewer/events` broadcast.
- **Persistence SceneState côté frontend** : MVP fait fetch snapshot à reconnect. Pas de cache local.
- **i18n** : whitelists d'émotions et de slugs anim sont anglais (joy/sad/angry…) — traduction UI hors scope.

## 11. Références

- [PR #106 — VADDriver extract + race tests asyncio.Event](https://github.com/Asurelia/Shugu_stream/pull/106)
- [PR #107 — AgentSession Voie A adapters STT/TTS/LLM](https://github.com/Asurelia/Shugu_stream/pull/107)
- [PR #108 — Observatory page + SSE skeleton](https://github.com/Asurelia/Shugu_stream/pull/108)
- [Sprint D blueprint](2026-05-04-sprint-d-filler-races-metrics-blueprint.md)
- [Sprint C blueprint (régie/streaming/barge-in)](2026-05-04-sprint-c-regie-streaming-bargein-blueprint.md)
- [Realtime voice Shugu (spec initial)](2026-05-03-realtime-voice-shugu.md)
- [llama.cpp Issue #22747 — MTP drafters feature request](https://github.com/ggml-org/llama.cpp/issues/22747)
- [Accelerating Gemma 4: faster inference with multi-token prediction drafters — Google Blog](https://blog.google/innovation-and-ai/technology/developers-tools/multi-token-prediction-gemma-4/)
- [@livekit/client SDK reference](https://docs.livekit.io/client-sdk-js/)
