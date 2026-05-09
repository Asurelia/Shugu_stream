# Voice ↔ Body Pipeline — Live Test Ops Checklist

- **Cible** : 1ère session live audience-réelle de Shugu (Direction E du chantier voice-body)
- **Spec** : [`docs/specs/2026-05-08-voice-body-pipeline-design.md`](../specs/2026-05-08-voice-body-pipeline-design.md) §9
- **Pré-requis** : umbrella branch [PR #111](https://github.com/Asurelia/Shugu_stream/pull/111) mergée dans `main`

## 1. Pré-requis J-1 (24h avant le live)

### 1.1. Code

- [ ] Toutes les sub-PRs D-1 à D-9 mergées dans l'umbrella `claude/vigilant-elion-e3ea8b`
- [ ] D-10 metrics + E2E + Grafana mergé OU décision explicite de live test sans monitoring détaillé
- [ ] Umbrella PR #111 mergée dans `main`
- [ ] CI green sur `main` après merge umbrella
- [ ] **Smoke test local 30 min** : voice ↔ avatar, 0 freeze, 0 drift visible audible

### 1.2. Wiring runtime à VERIFIER (dette D-2/D-5/D-7/D-9)

Les sub-PRs D-2 à D-9 ont laissé du wiring runtime deferred. À auditer AVANT live :

- [ ] **D-2** : `AudioBridge` est-il instancié dans `ShuguVoiceAgent.__init__` (ou la factory `entrypoint()`) ?
  - Vérifier : `agent.set_publisher(LiveKitPublisher(settings, room))` puis wire `audio_bridge = AudioBridge(piper_tts, publisher)`
  - Vérifier : `agent.tts_stream` consommé via `bridge.publish_stream(sentences)` au lieu de `_resample_and_publish` legacy
- [ ] **D-4 v3** : `ShuguVoiceAgent` créé avec `bridge=`, `event_bus=`, `session_id=` (params kwarg-only ajoutés)
  - Sinon `cancel_speaking` reste sur le path E3 (sans push event au frontend)
- [ ] **D-5** : `app.py:make_workers(event_bus, audio_clock_provider=lambda: bridge.chunk_started_at_ms)`
  - Sans ce wiring, `audio_at_ms` reste absent des payloads → frontend applique immédiatement → drift §7.2 non garanti
  - TODO traceur déjà présent à `app.py:378`
- [ ] **D-7/D-8** : `<ViewerEventsProvider enabled={!!operator}>` monté à côté de `<LiveKitProvider>` dans `_client.tsx`
  - Devrait déjà être fait par D-8 — vérifier
- [ ] **D-8/D-9** : `bargeInHandler` wiré dans `ViewerEventsProvider.onInterrupt` (D-8 a un stub à `ViewerEventsProvider.tsx:169`)
  - Sinon D-9 fade-out + neutral n'est pas appelé sur barge-in

### 1.3. LiveKit prod

- [ ] LiveKit deployment validé (URL, token endpoint, capacity testée 5+ connexions)
- [ ] `SHUGU_LIVEKIT_URL`, `SHUGU_LIVEKIT_API_KEY`, `SHUGU_LIVEKIT_API_SECRET` env vars set en prod
- [ ] **`SHUGU_VIEWER_JWT_SECRET`** set en prod (32+ chars, généré via `python -c 'import secrets; print(secrets.token_urlsafe(32))'`)
  - Sans, `viewer_token` retourne 401 silencieux — D-3 review fix Medium-1
- [ ] Testé manuellement : `POST /api/voice/token` retourne `{token, expires_at, livekit_url}`
- [ ] Testé manuellement : `WS /ws/viewer/events` accepte le token via `Sec-WebSocket-Protocol`

### 1.4. Frontend

- [ ] Frontend buildé en prod (`npm run build`) sans warning bloquant
- [ ] `frontend/package.json` contient bien `livekit-client@^2.18`, `zod@^4.4`, `@pixiv/three-vrm`
- [ ] OBS scene avec frontend en navigateur tab → window capture validé (test à blanc)
- [ ] Audio output OBS validé (pas de feedback loop, pas de double track)
- [ ] **Backup audio** : musique d'attente automatique si voice tombe (à configurer dans OBS)

### 1.5. Hardware host

- [ ] CPU/GPU/RAM monitoring ouvert sur 2e écran (htop / Task Manager / MSI Afterburner)
- [ ] Disk space : ≥ 20 GB libre (audio recording OBS + log voice agent)
- [ ] Network : test ping vers LiveKit + Twitch <50ms p95
- [ ] **Backup machine** ou rollback plan si la primary host crash

## 2. Session live test J0 (durée cap 30 min)

### 2.1. Audience

- **1-3 testeurs invités** (pas de raid public encore)
- Pas de promotion réseaux sociaux
- Stream en mode "private" sur Twitch ou audience filtre

### 2.2. Goals

- **Goal #1** : 10 minutes de conversation continue sans freeze ni drift visible/audible
- **Goal #2** : Tester barge-in
  - 5× sur l'opérateur (toi qui parle au micro)
  - 5× sur transcription Twitch chat (si VAD écoute le chat)
- **Goal #3** : Tester un crash volontaire
  - Kill manuel du subprocess Piper (`taskkill /F /IM piper.exe`)
  - Vérifier que la stack se rétablit (filler bank ou reconnect)

### 2.3. KPI à mesurer pendant la session

| KPI | Cible spec | Source |
|---|---|---|
| Latence end-to-end (LLM start → avatar bouche) | <500ms p50, <800ms p95 | Mesure manuelle (chronomètre) ou Prometheus si D-10B mergé |
| Drift audio↔anim | <100ms p95 | Observation visuelle ou `director_audio_at_ms_distribution` |
| Barge-in cut-off | <200ms | Observation auditive (silence après détection) |
| Reconnects WS / LiveKit | 0 cible | Logs backend + Network DevTools |
| CPU host | <80% steady | Task Manager |
| GPU host | <80% steady | Task Manager / MSI Afterburner |
| RAM host | <16 GB | Task Manager |
| Tokens Gemma 4 / sec | mesurer baseline | Logs llama.cpp |

### 2.4. Ce qu'il NE faut PAS faire pendant la session

- ❌ Modifier le code en live (toute fix attend post-mortem)
- ❌ Promouvoir publiquement le stream
- ❌ Lancer un test de charge en parallèle
- ❌ Activer un nouveau plugin / extension navigateur

### 2.5. Recording

- [ ] OBS recording activé full session (audio + video)
- [ ] Logs backend redirigés vers fichier daté
- [ ] Logs frontend (DevTools console) capturés via screen recording 2e écran
- [ ] Métriques Prometheus exportées en fin de session (si D-10B mergé)

## 3. Commandes activation pipeline

### 3.1. Backend voice agent

```powershell
# Terminal 1 — Backend FastAPI
cd F:/Dev/Fork/Shugu_stream/backend
.\.venv\Scripts\Activate.ps1
$env:SHUGU_ENV = "production"
$env:SHUGU_VIEWER_JWT_SECRET = "<32+ chars>"
$env:SHUGU_LIVEKIT_URL = "wss://livekit.shugu.spoukie.uk"
$env:SHUGU_LIVEKIT_API_KEY = "..."
$env:SHUGU_LIVEKIT_API_SECRET = "..."
$env:VOICE_AGENT_ENABLED = "true"
uvicorn shugu.app:app --host 0.0.0.0 --port 8000

# Terminal 2 — LiveKit voice agent worker
cd F:/Dev/Fork/Shugu_stream/backend
python -m shugu.voice.livekit_agent
```

### 3.2. Frontend

```powershell
# Terminal 3 — Frontend Next.js
cd F:/Dev/Fork/Shugu_stream/frontend
npm run start  # mode prod (npm run build préalable requis)
```

### 3.3. Vérifications avant live

```powershell
# 1. Backend healthcheck
curl http://localhost:8000/api/health

# 2. Token bootstrap (avec auth user existante via cookie)
curl -X POST http://localhost:8000/api/voice/token `
  -H "Content-Type: application/json" `
  --cookie "session=<cookie>" `
  -d '{"session_id":"test-live"}'

# 3. WS viewer test (utilise wscat ou équivalent)
wscat -c "ws://localhost:8000/ws/viewer/events" `
  -s "<token-from-step-2>"
```

## 4. Post-mortem J+1

### 4.1. Document

Créer `docs/postmortems/2026-XX-XX-first-live-test-voice-body.md` avec :

- **Date + durée session** + audience
- **Goals atteints / ratés** (vs §2.2)
- **KPI mesurés** (vs §2.3)
- **Incidents** : timeline (mm:ss → action), root cause, mitigation
- **Decisions** : GO/NO-GO Sprint E2 (POC MTP drafter, POC Gemma 4 E4B audio encoder)
- **Action items** : issues GitHub créées pour chaque bug confirmé

### 4.2. Issues à créer

Une issue GitHub par bug confirmé. Template :

```
**Symptôme** : ...
**Reproduction** : ...
**Impact** : (blocker live | dégradation UX | nit)
**Spec ref** : §X.Y
**Suggestion fix** : ...
```

### 4.3. Décisions Sprint E2

Selon les findings, prioriser :

- [ ] **Activation MTP drafter Gemma 4** (3× speedup) — en attente PR #22747 llama.cpp stable
- [ ] **Migration STT Whisper → Gemma 4 E4B audio natif** — pipeline unifié, latence frame 40ms
- [ ] **Reconnect snapshot fetch /api/viewer/state** (TODO D-8 post-review)
- [ ] **Wiring runtime des modules dormants** si pas déjà fait (D-2, D-5, D-7 wirings)
- [ ] **Multi-viewer scaling** si audience >10 spectateurs prévus

## 5. Rollback plan

Si quelque chose casse en prod :

1. **Voice agent crash** : redémarrer Terminal 2 (livekit_agent.py). Filler bank prend le relais 2-3s.
2. **Frontend WS reconnect storm** : reload tab navigateur. Le `useViewerToken` refait un bootstrap propre.
3. **LiveKit room déconnecté** : auto-reconnect via `livekit-client`. Pas d'action requise.
4. **Backend down** : restart Terminal 1 (uvicorn). Connexions WS se reconnectent dans 4s (D-7 backoff).
5. **Catastrophic** : kill OBS audio output, switch sur backup music, terminer le stream proprement.

## 6. Références

- [Spec voice-body pipeline](../specs/2026-05-08-voice-body-pipeline-design.md)
- [Sprint D blueprint (voice base)](../specs/2026-05-04-sprint-d-filler-races-metrics-blueprint.md)
- [Sprint C blueprint (régie+barge-in)](../specs/2026-05-04-sprint-c-regie-streaming-bargein-blueprint.md)
- Umbrella [PR #111](https://github.com/Asurelia/Shugu_stream/pull/111)
