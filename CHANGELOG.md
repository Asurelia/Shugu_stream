# Changelog

## v4.1 — Hermes/voice operator/desktop subsystem removal (2026-05-03)

- feat: remove Hermes voice operator and virtual desktop subsystem (#91 backend, #92 frontend)
  - Deleted `brain_hermes.py`, `brain_hermes_tools.py`, `hermes_state.py`, `hermes_task.py`, `hermes_state_api.py`
  - Deleted `voice_duplex.py`, `operator_voice_ws.py`
  - Replaced with multi-provider director brains: `brain_director_minimax.py`, `brain_director_anthropic.py`, `brain_director_ollama.py`, `brain_director_openai.py`
  - Frontend: removed `HermesStateWindow.tsx`, `OperatorVoicePanel.tsx`, voice WS client
- docs: align AGENTS.md, ARCHITECTURE.md, DEPLOY.md with Hermes-free codebase (#93)

## v4.0 — Agent incarné temps réel (2026-04)

### Vision

Shugu passe de **relais narratif** (Hermes → FilterBrain → Shugu parle) à
**agent incarné** : Hermes (MiniMax M2.7) pilote directement un avatar VRM
via tool_calls typés, parle en streaming TTS MiniMax WebSocket, entend en
streaming STT faster-whisper avec barge-in, manipule un bureau virtuel
visible sur le stream, le tout habillé en design "Celestial Veil".

### 9 phases livrées

1. **Silence texte public** — les visiteurs ne voient plus jamais les
   messages texte de Shugu ; la voix TTS + l'animation transmettent tout.
   Opérateur garde un toggle debug captions.
2. **Stream ambient autonome** — AmbientDaemon Poisson-timed émet des
   micro-events et des storyboards silencieux même sans viewers. Mood
   state Markov conditionné par le silence.
3. **TTS streaming MiniMax WebSocket** — latence TTFB /3, MSE côté client
   avec lip-sync preserved via MediaElementSource.
4. **Hermes body control tool_calls** — 8 tools body.* + HermesEmbodiedBrain
   avec tool-use loop, fallback regex XML natif MiniMax. 15 rate-limit rules.
5. **Voice duplex opérateur** — /ws/operator/voice, faster-whisper local
   (tiny/base/small/medium/large), VAD webrtcvad, barge-in <500ms via
   `asyncio.Event`. State machine lock-clean (turn tasks trackés).
6. **Bureau virtuel + Hermes HUD** — 7 tools desktop.*, surface glassmorphe
   React avec animation char-par-char sur append. Hermes HUD lit
   `~/.hermes/` (format joeynyc/hermes-hud) et expose 9 onglets.
7. **UX Celestial Veil** — Plus Jakarta Sans + Inter, palette surface/glass/
   halo rose/cyan, suppression des bordures 1px, gradients sur CTA.
8. **Rate limit + observability** — SlidingRateLimiter par tool_name, Metrics
   p50/p90/p99 TTFB, interrupts, barge_ins. `/api/admin/metrics`.

### Bonus

- **Quota tracker MiniMax** — Plans Plus/Max/Ultra, fallback auto vers
  Edge-TTS quand le budget daily TTS est épuisé.
- **Storyboards ambient** — séquences pré-chorégraphiées avec cues timés,
  zéro appel LLM ni TTS quota.
- **Preservation `<think>` blocks** — corrigé l'ancien bug où les thoughts
  MiniMax étaient strippés avant stockage en history (dégradation qualité).
- **Sampling MiniMax recommandé** — temperature=1.0, top_p=0.95, top_k=40
  (au lieu de 0.8 qui rendait Shugu fade).

### Sécurité — barrières ajoutées

- **`body_control._check_public_safe_name`** : blacklist 21 tokens sensibles
  (`.env`, `token`, `api_key`, `password`, `.pem`, etc.), path traversal
  bloqué, hidden files bloqués.
- **`desktop.show_image` URL** : reject cleartext `http://`, require HTTPS
  ou chemin public relatif.
- **MiniMax WS URL** : enforce `wss://`, refus de connexion en cleartext
  (évite de leak le Bearer token).
- **HermesStateReader anti-symlink** : `Path.resolve().is_relative_to(root)`
  avant tout read, + check `is_symlink()`. Empêche un symlink dans
  `~/.hermes/skills/` de leak `/etc/shadow` via l'endpoint opérateur.
- **Voice WS frame cap** : reject >1024 bytes/frame, rate cap 120 frames/s.
- **Operator JWT HS256** : cookies httpOnly + refresh rotation via jti
  revocation.
- **Type-level visitor→Hermes isolation** : `HermesAgentBrain` et
  `HermesEmbodiedBrain` lèvent TypeError sans `OperatorIdentity` en entrée.

### Bugfixes post-review

Identifiés par review cloud (/ultrareview) + audit local parallèle :

1. **Race condition lock VoiceDuplex** — `_finalize_turn` faisait
   `release/acquire` dans un `async with` extérieur → RuntimeError potentiel
   sur cancellation. Refactor : travail lourd (STT, Hermes) spawn en
   tasks séparées trackées, lock scoped aux décisions de state uniquement.
2. **Tasks orphelines asyncio** — `picker._archive`, operator_ws delegate
   et embodied lancés sans ref conservée → CPython 3.11+ weak-ref GC
   pouvait les tuer mi-exécution. Fix : set `_bg_tasks` + add_done_callback.
3. **Cap frame audio WebSocket** — `/ws/operator/voice` acceptait des
   payloads arbitraires → DoS potentiel. Fix : reject >1024 bytes, cap
   120 frames/s, cap text control 2048 bytes.
4. **Symlink following HermesStateReader** — `skills_dir.glob + read_text`
   suivaient les symlinks. Fix : `_is_safe_inside_root()` + `_safe_read_text`
   bounded 8KB.
5. **FallbackTTS primary blob skipped** — quand primary n'avait pas
   `synthesize_stream` (ElevenLabs), `synthesize_stream()` skippait direct
   au secondary au lieu de wrapper le blob primary. Fix : else branch +
   conversion single-chunk.
6. **Quota charge sans `is_final`** — MiniMax peut close gracefully sans
   flag `is_final=true` → TTS delivré mais quota jamais chargé. Fix :
   charger au premier chunk yielded, pas en attendant is_final.
7. **Generator aclose FallbackTTS** — WS MiniMax leak si stream abort mid-
   way. Fix : `contextlib.aclosing()` sur chaque async generator.
8. **websockets InvalidStatus deprecated** — `websockets.InvalidStatusCode`
   deprecated en 13.x, renommé en 14+. Fix : try/except import des deux.
9. **Picker `performance.end` skipped** — sur exception non-TTSError
   (asyncio.TimeoutError, CancelledError, event_bus publish fail),
   `performance.end` n'était jamais publié → client coincé speaking=true.
   Fix : publish dans `finally` + `performance.truncate` + `run()` survit
   aux crashes per-message.
10. **Barge-in setup race** — `self._current_perf_id = perf_id;
    self._interrupt_event.clear()` : interrupt entre les deux était set
    puis effacé. Fix : clear AVANT l'assign.
11. **Mood lock + broadcast** — `body.mood` mutait `ambient._mood.current`
    sans lock + `ambient.py` loggeait `mood.change` sans broadcast sur
    event_bus. Fix : `Mood.set()` + `AmbientDaemon.set_mood()` lock-protected,
    broadcast `mood.change` sur stage.
12. **timed_cue setTimeout leak** — les setTimeouts schedulés pour les cues
    timés ne étaient pas cancelled sur `performance.truncate`/`end` →
    ghost events sur la performance suivante. Fix : `cueTimersRef` tracké
    avec `clearCueTimers()` sur truncate/end.
13. **Route voice unconditionally mounted** — `operator_voice_ws.router`
    inclus même si `voice_duplex_enabled=False` → crash `_deps is None` à
    la première connexion. Fix : `if voice_duplex_enabled:` autour de
    `include_router`.
14. **Duplicate `fontFamily` dans tailwind config** — le 2e écrasait le
    1er → les classes `font-display`/`font-body` n'étaient pas générées.
    Fix : merger.
15. **StreamingAudioPlayer kick `seq===0` fragile** — dépendait d'un seq
    exact au lieu du premier chunk non vide. Fix : flag `started` interne,
    `play()` auto sur le premier chunk.

### Modèle par défaut ajusté pour KVM 2 Hostinger

- Whisper STT : `small` → `base` (~140 MB, ~1.5 GB RAM, ~0.8s latence).
  `small` reste possible via `STT_MODEL=small` si RAM disponible.

### Breaking changes

Aucun pour les clients externes (APIs `/ws/*` et `/api/*` inchangées).

En interne, la signature du `PrepWorker._process` a changé côté historique
(raw response préservée au lieu de strip_think avant append). Le `Picker`
a gagné `interrupt()` et `set_metrics()`. `MiniMaxTTS.__init__` accepte
désormais un `quota: QuotaTracker` optionnel.

### Sources externes consultées

- [MiniMax-M2 tool_calling_guide](https://huggingface.co/MiniMaxAI/MiniMax-M2/blob/main/docs/tool_calling_guide.md)
- [MiniMax Speech-2.8 streaming WebSocket](https://platform.minimax.io/docs/guides/speech-t2a-websocket)
- [joeynyc/hermes-hud — format `~/.hermes/`](https://github.com/joeynyc/hermes-hud)
- [OpenRoom — pattern CharacterAppAction + WindowManager](https://github.com/user/OpenRoom)
- [Open-LLM-VTuber — voice interruption pattern](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber)
- [moeru-ai/airi — Neuro-sama-like self-hosted](https://github.com/moeru-ai/airi)
- [Hostinger KVM 2 specs](https://www.vpsbenchmarks.com/hosters/hostinger/plans/kvm-2)
