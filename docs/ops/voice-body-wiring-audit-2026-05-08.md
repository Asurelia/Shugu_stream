# Voice ↔ Body — Wiring Runtime Audit (2026-05-08)

> **Pré-requis avant 1ère live test** — les modules dormants D-2/D-4 v3/D-5 doivent être wirés dans le runtime backend pour que la chaîne voice→body fonctionne réellement.

## TL;DR

| Module | Statut wiring | Effort | Bloquant live ? |
|---|---|---|---|
| **D-7 frontend ViewerEventsProvider** | ✅ DÉJÀ WIRÉ | 0 | — |
| **D-8 LiveKitProvider** | ✅ DÉJÀ WIRÉ | 0 | — |
| **D-9 bargeInHandler** | ⚠️ SEMI-WIRÉ (TODO `ViewerEventsProvider.tsx:169`) | 1h | OUI pour barge-in viewer |
| **D-2 AudioBridge backend** | ❌ NON WIRÉ | 4-6h (refactor path streaming) | OUI pour audio LiveKit côté frontend |
| **D-4 v3 cancel_speaking ext** | ❌ NON WIRÉ (params None) | 1h (dépend D-2) | OUI pour push voice.interrupt frontend |
| **D-5 audio_clock_provider** | ❌ NON WIRÉ (TODO `app.py:378`) | 30min (dépend D-2) | NON-bloquant (drift sans crash) |

Estimation totale : **6-8h de dev backend** + tests pour finir le wiring runtime.

## 1. Wiring déjà en place

### 1.1. Frontend : `_client.tsx:522-526`

```tsx
<LiveKitProvider enabled={voiceWiringActive}>
  <ViewerEventsProvider enabled={voiceWiringActive}>
    {children}
  </ViewerEventsProvider>
</LiveKitProvider>
```

`voiceWiringActive` est gated sur `!!operator` (login). Le `useViewerToken` hook (D-8) mutualise le JWT entre les 2 providers. Token refresh proactif T-60s actif.

**Rien à faire frontend.**

## 2. Wiring deferred — patches concrets

### 2.1. D-9 bargeInHandler — semi-wiré (1h)

**Fichier** : `frontend/src/features/viewer/ViewerEventsProvider.tsx:168-171`

Actuellement :
```tsx
onInterrupt: () => {
  scheduler.flush();
  // D-9 : appliquer une expression neutre + ramp-down audio. Stub.
},
```

**Patch** : importer `createBargeInHandler` (D-9 mergé) et l'instancier au mount, puis l'appeler dans `onInterrupt`.

```tsx
// En haut du fichier :
import { createBargeInHandler } from "./bargeInHandler";

// Dans le useEffect (après scheduler creation) :
const bargeInHandler = createBargeInHandler({ viewer, scheduler });

// Dans onInterrupt :
onInterrupt: (event) => {
  bargeInHandler(event);
},
```

**Test** : ajouter dans `ViewerEventsProvider.test.tsx` un test "voice.interrupt → fadeOutAndStopStreamingAudio + neutral + flush".

**Effort** : 1h.

### 2.2. D-2 AudioBridge — backend wiring (4-6h)

**Problème** : `livekit_agent.py:985` et `:1018` instancient `ShuguVoiceAgent` avec un `audio_source` legacy publié manuellement (pattern Sprint C). `AudioBridge` (D-2) attend un `LiveKitPublisher` (D-1) wrapping le même type d'audio source.

**Stratégies possibles** :

#### Option A (recommandée) — Migration complète vers AudioBridge

1. Remplacer `audio_source = rtc.AudioSource(...)` + manual publish_track par :
   ```python
   publisher = LiveKitPublisher(settings, ctx.room)
   bridge = AudioBridge(tts=tts, publisher=publisher)
   ```
2. Modifier `ShuguVoiceAgent._handle_turn_streaming` pour utiliser `bridge.publish_stream(sentence_iterator)` au lieu de `audio_source.capture_frame` direct.
3. Le `LiveKitPublisher.publish_pcm` gère le découpage 10ms frames → on peut supprimer la logique de découpage manuelle dans `_handle_turn_streaming`.

**Risque** : régression sur le path filler bank qui utilise aussi `audio_source` (vérifier `_filler_bank.cancel()` et la publication des fillers).

#### Option B (minimale) — Coexistence

1. Créer le `publisher` + `bridge` en parallèle au `audio_source` legacy.
2. `bridge` reste inactif (pas appelé par `_handle_turn_streaming`) mais wiré pour D-4 v3 (`agent.set_publisher(publisher)` permet le `unpublish` sur barge-in).
3. Migration AudioBridge complète reportée à un PR ultérieur.

**Risque** : double track LiveKit (legacy `shugu-voice` + nouvelle `shugu-voice-tts` D-1). Le frontend (D-6) filtre par source, donc devrait choisir la nouvelle, mais à vérifier.

**Recommandation** : commencer par Option B pour débloquer D-4 v3 et tester en live, puis Option A en sprint séparé.

**Effort Option B** : 2-3h. Effort Option A : 4-6h + tests régression filler bank.

> **VB-A audio bomb fix — ✅ FIXÉ (2026-05-09, PR #129)** : Quand `voice_use_new_pipeline=True`
> (migration Option A active), la track legacy `shugu-voice` n'est plus publiée et le
> `FillerBank` est forcé à `NullFillerBank` (même logique que le path AgentSession,
> lignes 1090-1095). Le bridge crée lazily sa propre track `shugu-voice-tts` au premier
> `publish_sentence`. Résout la cacophonie double-track frontend.
> Ré-activer fillers via bridge = sprint séparé (VB-filler).

### 2.3. D-4 v3 cancel_speaking — params instanciation (1h après D-2)

**Fichier** : `livekit_agent.py:985-989` et `:1018-1022`

Actuellement :
```python
agent = ShuguVoiceAgent(
    stt, llm, tts, settings, audio_source,
    filler_bank=filler_bank,
    metrics=voice_metrics,
)
```

**Patch** : ajouter les 3 kwargs D-4 v3 :
```python
event_bus = ctx.proc.userdata.get("event_bus")  # ou équivalent — vérifier comment c'est passé
session_id = f"voice-sess-{ctx.room.name}-{int(time.time())}"

agent = ShuguVoiceAgent(
    stt, llm, tts, settings, audio_source,
    filler_bank=filler_bank,
    metrics=voice_metrics,
    bridge=bridge,           # D-2 wiring
    event_bus=event_bus,     # pour push voice.interrupt sur editor:broadcast
    session_id=session_id,   # pour le claim viewer-token + filter
)
```

**Test** : `cancel_speaking` doit publier l'event `voice.interrupt` avec `session_id` correct.

**Effort** : 1h après D-2.

### 2.4. D-5 audio_clock_provider — `app.py:378` (30min après D-2)

**Fichier** : `backend/shugu/app.py:378` (TODO traceur déjà présent)

Actuellement :
```python
app.state.director_workers = make_workers(event_bus)
```

**Patch** : passer le callable lambda. Mais le `bridge` est dans le worker LiveKit (process séparé !), pas dans le process FastAPI principal. **C'est le piège architectural** : `app.py` lifespan tourne dans le serveur web, mais `livekit_agent.py` tourne dans un worker subprocess (`livekit agents` framework).

**2 options** :

#### Option a — Bridge accessible via Redis ou IPC

Le `bridge.chunk_started_at_ms` doit être propagé du worker LiveKit vers le serveur FastAPI. Pattern envisageable : Redis pub/sub où le worker publie `chunk_started_at_ms` à chaque chunk, et le serveur lit depuis Redis dans le callable :

```python
def get_chunk_started_at_ms_from_redis() -> int | None:
    raw = redis.get("voice:current_chunk_started_at_ms")
    return int(raw) if raw else None

app.state.director_workers = make_workers(
    event_bus,
    audio_clock_provider=get_chunk_started_at_ms_from_redis,
)
```

#### Option b — Workers dans le worker LiveKit aussi

Faire tourner `make_workers` à l'intérieur du worker LiveKit (cohabite avec le bridge), pas dans `app.py`. Refactor plus large.

**Recommandation** : Option a pour MVP. Pattern Redis simple. Drift §7.2 acceptable.

**Effort** : 30min (Option a) après D-2.

## 3. Tests d'intégration manquants avant live

Aucun test E2E pytest backend n'exerce la chaîne complète `voice agent → bridge → publisher → LiveKit room → director event_bus → /ws/viewer/events`. Les unit tests existants couvrent chaque composant isolément.

**Recommandation** : avant live test, ajouter un test d'intégration dans `backend/tests/integration/voice/test_e2e_pipeline.py` qui :
1. Mock LiveKit Room avec capture des published tracks
2. Démarre un `ShuguVoiceAgent` avec bridge + event_bus mocks
3. Émule un transcript user simulé
4. Vérifie que le bridge publie bien des frames audio
5. Vérifie que le director publie bien des `scene.apply` events
6. Vérifie le format envelope `editor:broadcast` (D-3 filter)

C'est essentiellement le scope D-10C (Playwright frontend) côté backend.

## 4. Plan recommandé

### Sprint « voice-body integration » dédié (1-2 jours)

1. **D-9 frontend wiring** (1h) — déboule par PR `feat/voice-d9-wiring-bargein` (très court)
2. **D-2 backend Option B** (2-3h) — déboule par PR `feat/voice-d2-wiring-bridge`
3. **D-4 v3 params + D-5 Redis clock** (1.5h) — déboule par PR `feat/voice-d4-d5-wiring-runtime`
4. **Test E2E backend integration** (2-3h) — déboule par PR `feat/voice-integration-e2e-test`
5. **D-10B Prometheus call sites** (1h) — déboule par PR `feat/voice-d10b-metrics-wiring`
6. **D-10C Playwright + Grafana** (3-4h) — déboule par PR `feat/voice-d10c-playwright-grafana`

Total : **2 jours de dev**, 6 PRs, mergeable séquentiellement dans l'umbrella.

### Smoke test post-merge umbrella (J-1 du live)

Suivre `docs/ops/voice-body-live-test-checklist.md` §1.5 — 30 min de conversation locale avec audience interne.

### 1ère live test (J0)

Suivre `docs/ops/voice-body-live-test-checklist.md` §2 — 30 min cap, 1-3 testeurs invités.

## 5. Décision GO/NO-GO live test sans D-2/D-4 v3 wiring

**NO-GO** sans le wiring backend. Raison :
- L'avatar VRM ne recevra **aucun audio** (le frontend `LiveKitProvider` est wiré mais aucun track n'est publié par le backend sur la nouvelle pipeline `LiveKitPublisher`)
- Aucun event `scene.apply` ne sera enrichi (path Sprint C original n'utilise pas `make_workers` enrichi par D-5)
- `voice.interrupt` ne sera pas pushé au frontend (D-4 v3 inactif sans `event_bus` injecté)

Le **path Sprint C legacy fonctionne** (audio via track manuel, avatar parle), mais **sans** l'expression sync (face/anim alignée), **sans** le barge-in viewer-side, **sans** le drift §7.2 garanti.

**Recommandation** : finir le sprint integration AVANT le 1ère live, sinon le live ne valide pas le chantier voice-body.

## Annexe — Mémoire ruflo associée

- `shugu-voice-body-D-spec-ref` (namespace `shugu-mos`) — paths spec + sub-PRs + métriques cibles
- `shugu-voice-body-D-brief-conventions` — leçons agents (checkout reset, API EventBus AsyncIterator, etc.)
