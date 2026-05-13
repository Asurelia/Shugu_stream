# Voice ↔ Body — Live Readiness Report (2026-05-13)

> **TL;DR — LE PIPELINE EST PRÊT POUR LE LIVE TEST.**
> Tous les modules dormants identifiés dans l'audit du 2026-05-08 sont désormais wirés.
> Bloquant restant : **action humaine** (smoke test 30 min, puis live test J0 30 min).
> Optionnel non-bloquant : dashboard Grafana D-10C (délégué à ruflo en parallèle).

---

## 1. Statut wiring runtime — vérification 2026-05-13

| Module | Audit 2026-05-08 | Statut réel 2026-05-13 | Source code |
|---|---|---|---|
| D-7 ViewerEventsProvider | ✅ wiré | ✅ wiré | `frontend/src/features/viewer/ViewerEventsProvider.tsx` |
| D-8 LiveKitProvider | ✅ wiré | ✅ wiré | `frontend/src/features/viewer/LiveKitProvider.tsx` |
| **D-9 bargeInHandler frontend** | ⚠️ semi-wiré (TODO L169) | ✅ **WIRÉ** | `ViewerEventsProvider.tsx:165` import + L175-178 appel `bargeInHandler(event)` |
| **D-2 AudioBridge backend** | ❌ NON WIRÉ | ✅ **WIRÉ (Option B coexistence)** | `livekit_agent.py:1104-1114` et `:1242-1246` — `LiveKitPublisher` + `AudioBridge` instanciés |
| **D-4 v3 cancel_speaking params** | ❌ params None | ✅ **WIRÉ** | `livekit_agent.py:1120-1132` et `:1252-1265` — `bridge=`, `event_bus=`, `session_id=`, `pipeline_metrics=` passés |
| **D-5 audio_clock_provider** | ❌ TODO `app.py:378` | ✅ **WIRÉ** | `app.py:465-467` — `make_workers(audio_clock_provider=_voice_runtime.chunk_started_at_ms)` |
| **D-10B metrics call sites** | À faire | ✅ **EXISTE** | `pipeline_metrics.py` (12 métriques) + `metrics.py` (`voice_turn_latency_seconds`) |
| **Test E2E backend integration** | À écrire | ✅ **EXISTE** | `backend/tests/integration/voice/test_voice_body_e2e.py` + 6 autres tests integration voice |
| **PR #111 umbrella** | À merger | ✅ **MERGÉE** | 2026-05-09 |
| **VB-A audio bomb fix** | À investiguer | ✅ **FIXÉ** | PR #129 (2026-05-09) — `NullFillerBank` + skip legacy track quand `voice_use_new_pipeline=True` |

### Historique des commits clés (depuis l'audit 2026-05-08)

| Commit | Date | Apport |
|---|---|---|
| `5193803` | 2026-05-08 | feat(voice): voice-body pipeline complete (Direction D + E) — **wiring massif** |
| `c6ab3d3` | 2026-05-09 | chore(ops): voice-body runtime setup toolkit |
| `19d0668` | 2026-05-09 | perf(ops): switch ollama → llama-server natif Vulkan AMD (#127) |
| `66335e2` | 2026-05-09 | feat(voice): migration Option A — activate new pipeline via flag (#128) |
| `22b0156` | 2026-05-09 | fix(voice): VB-A audio bomb — NullFillerBank + skip legacy track (#129) |

**Conclusion** : l'audit `voice-body-wiring-audit-2026-05-08.md` est **périmé**. Ne plus l'utiliser comme référence d'état — il reste valable comme **archive du gap d'origine** (utile pour comprendre la décision Option B coexistence vs Option A migration totale).

---

## 2. Métriques Prometheus disponibles (13 métriques)

Inventaire exact depuis le code (`pipeline_metrics.py` + `metrics.py`) :

### 2.1. Pipeline metrics (D-1 → D-5) — `pipeline_metrics.py`

| Métrique | Type | Labels | Cible SLO |
|---|---|---|---|
| `voice_publisher_chunks_published_total` | Counter | — | — |
| `voice_publisher_chunks_dropped_total` | Counter | — | drop rate <1% |
| `voice_publisher_publish_duration_ms` | Histogram (5,10,25,50,100,200,500,1k,5k) | — | <100ms moyen |
| `voice_bridge_sentences_published_total` | Counter | — | — |
| `voice_bridge_sentences_skipped_total` | Counter | `reason` ∈ {empty, tts_empty, tts_failed, publish_failed, cancelled_pre_synth, cancelled_post_synth, stream_iterator_failed, unknown} | skip rate <5% |
| `voice_bridge_publish_sentence_duration_ms` | Histogram (50,100,250,500,1k,2.5k,5k,10k,30k) | — | <3s typique |
| `voice_cancel_speaking_total` | Counter | `reason` ∈ {barge_in, shutdown, external, unknown} | — |
| `voice_cancel_speaking_duration_ms` | Histogram (ms) | — | **<200ms p95** §7.2 |
| `director_audio_at_ms_distribution` | Histogram (0,10,25,50,100,200,500,1k,2k) | `kind` ∈ {say_emotion, face, unknown} | **<100ms p95** §7.2 |
| `viewer_ws_connections_total` | Counter | — | — |
| `viewer_ws_disconnects_total` | Counter | `reason` ∈ {client_close, auth_failed, rate_limited, server_error, unknown} | — |
| `viewer_token_refresh_total` | Counter | `outcome` ∈ {success, expired_grace, auth_failed, missing_token, unknown} | — |

### 2.2. Voice turn metrics — `metrics.py`

| Métrique | Type | Labels | Cible SLO |
|---|---|---|---|
| `voice_turn_latency_seconds` | Histogram (0.005, 0.025, 0.1, 0.25, 0.5, 1, 2.5, 5) | `stage` ∈ {stt, intent, websearch, llm_first_token, sentence_first, tts_first_frame, audio_first}, `intent` ∈ {chat, web_search, emotion, emote, unknown} | **TTFB voice 0.2-0.3s p50** (stage=audio_first) |

Toutes les métriques sont exposées via `GET /metrics` (gated par `SHUGU_METRICS_ENABLED`).

---

## 3. Checklist live test — actions humaines

### 3.1. Pré-requis J-1 (24h avant le live)

#### 3.1.1. Environnement (vérifier ENV vars en prod)

- [ ] `SHUGU_LIVEKIT_URL` set
- [ ] `SHUGU_LIVEKIT_API_KEY` set
- [ ] `SHUGU_LIVEKIT_API_SECRET` set
- [ ] **`SHUGU_VIEWER_JWT_SECRET`** set (32+ chars, `python -c 'import secrets; print(secrets.token_urlsafe(32))'`)
- [ ] `SHUGU_VOICE_USE_NEW_PIPELINE=true` (active la pipeline AudioBridge, fix VB-A audio bomb)
- [ ] `SHUGU_METRICS_ENABLED=true` (pour observer les métriques pendant le live)
- [ ] `SHUGU_VOICE_METRICS_ENABLED=true`

#### 3.1.2. Validation routes

- [ ] `POST /api/voice/token` → 200 + `{token, expires_at, livekit_url}`
- [ ] `WS /ws/viewer/events` accepte token via `Sec-WebSocket-Protocol`
- [ ] `GET /metrics` retourne les 13 métriques voice/pipeline (vérifier au moins `voice_publisher_chunks_published_total` présent)

#### 3.1.3. Frontend prod build

- [ ] `npm run build` sans warning bloquant
- [ ] OBS scene avec frontend en navigateur tab → window capture validé
- [ ] Audio output OBS : pas de feedback loop, pas de double track (VB-A fix vérifié)
- [ ] Backup audio (musique d'attente OBS si voice tombe)

#### 3.1.4. Hardware host

- [ ] CPU/GPU/RAM monitoring ouvert sur 2e écran
- [ ] Disk space ≥ 20 GB libre
- [ ] Network : ping LiveKit + Twitch <50ms p95
- [ ] Backup machine ou rollback plan

### 3.2. Smoke test local 30 min (J-1)

**Objectif** : valider la chaîne voice → avatar en isolation avant audience.

- [ ] Lancer backend local (`uvicorn shugu.app:app`) + worker LiveKit (`livekit-agents start backend/shugu/voice/livekit_agent.py`)
- [ ] Lancer frontend local (`cd frontend && npm run dev` → port 3005)
- [ ] Se loguer en tant qu'operator → vérifier `voiceWiringActive=true` dans logs frontend
- [ ] **Test conversation 5 min** : parler au mic, vérifier que :
  - [ ] L'avatar VRM parle (audio LiveKit reçu)
  - [ ] La face de l'avatar bouge en sync avec l'audio (D-5 audio_at_ms wiring)
  - [ ] Pas de freeze, pas de drift visible/audible
- [ ] **Test barge-in 5 min** : couper l'avatar mid-sentence, vérifier que :
  - [ ] L'audio s'arrête en <200ms (fade-out 50ms côté frontend)
  - [ ] L'avatar revient à neutral
  - [ ] Le scheduler flush bien les events pending
- [ ] **Test 20 min continu** : conversation libre avec questions web_search, emotion shifts, scene changes
  - [ ] 0 freeze
  - [ ] 0 crash backend
  - [ ] 0 crash worker LiveKit
- [ ] **Vérifier métriques** : `curl localhost:8000/metrics | grep voice_` doit montrer des observations non-zéro

### 3.3. Live test J0 — audience réelle (30 min cap)

**Pré-requis** : smoke test J-1 GREEN.

- [ ] 1-3 testeurs invités (private link Twitch ou OBS direct)
- [ ] OBS recording activé (backup audio + vidéo)
- [ ] Monitor terminal `curl localhost:8000/metrics` en permanence sur 2e écran
- [ ] **30 min max** — couper proprement même si tout va bien
- [ ] Post-live : exporter `GET /metrics` snapshot, archiver dans `docs/ops/live-tests/2026-05-XX-snapshot.txt`

### 3.4. Go/No-Go critères

**GO si** :
- Smoke test 30 min : 0 freeze, 0 crash, conversation fluide
- TTFB voice p50 <300ms observé (via `voice_turn_latency_seconds{stage="audio_first"}`)
- Barge-in p95 <300ms observé (via `voice_cancel_speaking_duration_ms`) — léger overshoot acceptable hors prod

**NO-GO si** :
- Audio coupé, double-track, ou silence prolongé >5s
- Crash worker LiveKit pendant le smoke
- TTFB voice p50 >500ms (probable goulot Whisper STT ou LLM Vulkan)

---

## 4. Post-live actions

Si live GO :
- [ ] Marquer le chantier voice-body **MVP livré** dans le handover suivant
- [ ] Archiver l'audit 2026-05-08 + ce report dans `docs/archives/` (référence historique)
- [ ] Décider prochain chantier (Phase 2.3 MemoryAgent, ou Régie R.1, ou autre)

Si live NO-GO :
- [ ] Capturer le crash/freeze (log backend + log worker + métriques)
- [ ] Issue GitHub avec repro stepfix
- [ ] Décider sprint correctif vs accepter MVP partiel

---

## 5. Optionnel non-bloquant — D-10C Grafana dashboard

Délégué à ruflo-autopilot en parallèle (commit dédié). Voir :
- Spec : `docs/superpowers/specs/2026-05-13-d10c-grafana-dashboard-design.md`
- Plan : `docs/superpowers/plans/2026-05-13-d10c-grafana-dashboard-plan.md`

L'absence du dashboard ne bloque PAS le live test — le `curl /metrics` brut suffit pour monitorer la 1ère live en mode terminal sur 2e écran. Grafana c'est du confort d'observabilité prod pour la suite.

---

## 6. Annexe — Pourquoi cet audit a-t-il dérivé ?

Leçon pour les futurs chantiers multi-PRs :

L'audit `2026-05-08` listait 6-8h de wiring restant. Le commit `5193803` (2026-05-08, "voice-body pipeline complete") a fait tout le wiring d'un coup, et les PRs suivantes (#128, #129) ont activé + fixé les régressions. Mais le doc audit n'a jamais été marqué comme "résolu".

**Pattern à appliquer** : sur tout sprint d'intégration, ajouter une checklist dans le doc audit avec dates `[ ] / [x]` à cocher au fur et à mesure des merges. Sans ça, un doc de gap devient une carte au trésor périmée en quelques jours.

Mémoire candidate à ajouter : `feedback_audit_doc_lifecycle.md` — "Un audit/spec listant un gap doit être marqué résolu dès que les commits referent le résolvent. Sinon, n'importe quelle reprise de chantier perd 30+ min à vérifier état réel vs doc."
