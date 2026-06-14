# Shugu Mind — Roadmap d'exécution (cadrage des jalons M-2 → M-6 + M-V1 → M-V3)

> **Nature de ce document** : cadrage d'exécution (pas un plan TDD bite-sized). Il séquence les jalons restants, fixe leurs interfaces et leurs critères de fin, et identifie le chemin critique et les pistes parallélisables. **Chaque jalon est transformé en plan TDD détaillé juste-à-temps**, juste avant son exécution (comme `2026-06-14-mind-m0-m1-foundation.md`), pour éviter que le détail dérive par rapport au code réellement produit en amont.
>
> **Spec de référence** : `docs/superpowers/specs/2026-06-13-autonomous-mind-design.md`
> **Plan déjà détaillé** : `docs/superpowers/plans/2026-06-14-mind-m0-m1-foundation.md` (M-0 + M-1)

---

## 1. Graphe de dépendances et chemin critique

```
TRACK CERVEAU/GAMEPLAY (séquentiel — chemin critique)
  M-0 ──► M-1 ──► M-2 ──► M-3 ──► M-4 ──► M-5a ──► M-6
 brain  black-  arbiter cortex  game-   cortex  conso-
 family board           idle    adapter gaming  lidation
                                              └─► M-5b (navigate_to, OPTIONNEL pour O3)

TRACK VOIX TEMPS RÉEL (parallèle — n'attend que M-1)
  M-V0 ──► M-V1 ──► M-V2 ──► M-V3 (optionnel)
 baseline turn-det  STT+overlap  TTS expressif
 latence  sémantiq.

POINTS DE JONCTION :
  - M-V2 (voix = sense du Réflexe) consomme le Blackboard de M-1 et l'Arbiter de M-2.
    → M-V0/M-V1 peuvent démarrer dès M-1 ; M-V2 attend M-2.
  - M-6 (consolidation/smoke live) consomme TOUT, y compris le track voix.
```

**Chemin critique** : M-0 → M-1 → M-2 → M-3 → M-4 → M-5a → M-6 (7 jalons).
**Parallélisable dès que M-1 est mergé** : M-V0 et M-V1 (gros gain voix, indépendants du cortex/gameplay).
**Optionnel pour atteindre O3** (« Shugu joue 2 h seule ») : M-5b (navigate_to) — le cortex peut sortir du bourg avec `press_buttons` seul.

**Recommandation d'ordonnancement orchestrateur** :
1. Finir le chemin critique jusqu'à M-3 (Shugu prend des initiatives — O1 atteint, démontrable sans jeu).
2. **Lancer M-V1 en parallèle** dès M-1 mergé (meilleur ratio impact/effort de tout le projet côté ressenti).
3. Reprendre M-4/M-5a (gameplay) après M-3.
4. M-5b + M-V2/M-V3 selon le temps. M-6 en clôture.

---

## 2. Contrats d'interface entre jalons

Ce que chaque jalon **expose** (et que le suivant **consomme**). Ces contrats sont la colonne vertébrale qui permet de planifier en détail sans relire tout le code amont.

| Jalon | Expose | Consommé par |
|---|---|---|
| M-0 | `M3Brain.generate(...)→BrainResult`, `M3DirectorBrain.complete`, `ResilientDirectorBrain`, `mind/metrics.py` | M-1, M-3 (cortex), M-V2 |
| M-1 | `Blackboard.get/update/append_chat/append_speech/reset`, `MindState`, `build_prompt(..., mind_state=)`, event `mind.activity` sur topic `stage` | M-2, M-3, M-4, M-V2 |
| M-2 | `ActionIntent`, `ActionArbiter.submit(intent)`, flag `mind_arbiter_enabled` | M-3 (cortex y pousse), M-V2 (voix y pousse) |
| M-3 | `Cortex` (boucle asyncio), tools `say/set_activity/set_goals/write_note/remember/recall/set_face`, flag `mind_cortex_enabled` | M-4/M-5a (ajoutent les tools jeu) |
| M-4 | `GameAdapter` Protocol, `PyBoyGen1Adapter`, WS `/game/stream`, `mind.activity`→`GameScreen.tsx` | M-5a (cortex pilote), M-5b |
| M-5a | tools cortex `press_buttons`, compaction accordéon, critique anti-poisoning | M-5b (ajoute navigate_to) |
| M-V1 | turn-detector EOU branché dans le LiveKit Agent | M-V2 |
| M-V2 | `TriggerEvent(kind="voice")`, voix branchée au Réflexe + Blackboard | M-6 |

---

## 3. Fiches de cadrage par jalon

### M-2 — ActionArbiter

- **But** : sérialiser les intentions de parole/corps/jeu en une sortie cohérente. Incarne le « Stage Director » (Phase 3 roadmap). Spec §4.5.
- **Dépend de** : M-1 (Blackboard).
- **Fichiers** : créer `backend/shugu/mind/arbiter.py` (`ActionIntent` dataclass, `ActionArbiter`) ; modifier `director/orchestrator.py` (router la sortie via l'arbiter quand `mind_arbiter_enabled`).
- **Interfaces clés** :
  - `ActionIntent(source, kind, payload, priority, created_at)`.
  - Sortie speech = **patron AmbientScene** (vérifié `pipeline/ambient.py:208`) : synth TTS → `QueuedMessage(author_role="system", precomputed_audio=…)` → `RedisQueue.enqueue_ready` → Picker serial. **Ne PAS inventer de « queue de texte ».**
  - Sortie body = `Worker.apply()` existants via `_dispatch_and_publish`.
  - Sémantique du flag : `mind_arbiter_enabled=False` → dispatch direct actuel (zéro changement frontend) ; `True` → l'arbiter applique priorité/cooldown/dédup PUIS appelle le même `_dispatch_and_publish` (broadcast `editor:broadcast` inchangé).
- **Règles d'arbitrage** : priorités (réflexe-chat 1 > cortex-parole 2 > body 3 > canned 4) ; anti-collision parole (1 speech en synthèse, cortex périmée >15 s jetée) ; cooldown parole cortex 1/20 s en gaming ; purge intents >30 s à chaque enqueue.
- **Tests** : table de vérité priorités/cooldowns/péremption ; construction `QueuedMessage` + `enqueue_ready` mockée (vérifier patron AmbientScene) ; anti-collision.
- **Risque** : interposer l'arbiter sans casser le broadcast `editor:broadcast` consommé par `_client.tsx`. Mitigation : l'arbiter est une grille PRÉ-dispatch, pas un remplacement (cf. spec §4.3 bloquant 4).
- **DoD** : le réflexe parle via l'arbiter (dédup/cooldown actifs), flag off = comportement identique à aujourd'hui, tests verts, ruff propre.

### M-3 — Cortex idle/chatting

- **But** : la boucle d'agence continue (initiatives, goals, notes, mémoire) — SANS jeu. Atteint O1. Spec §4.4.
- **Dépend de** : M-1 (Blackboard), M-2 (Arbiter — le cortex y pousse ses intents), M-0 (`M3Brain.generate` riche + tools).
- **Fichiers** : créer `backend/shugu/mind/cortex.py` (boucle asyncio), `backend/shugu/mind/tools.py` (déclarations `ToolSpec` + dispatch) ; modifier `app.py` (démarrage/arrêt de la task cortex dans le lifespan, gated `mind_cortex_enabled`) ; `config.py` (cadence settings) ; désactiver le `SilenceMonitor` du Director quand `mind_cortex_enabled` (spec §12.6).
- **Interfaces clés** :
  - Boucle : cadence 20 s en idle/chatting ; `state = await blackboard.get()` → `M3Brain.generate(system=PERSONA_CORTEX, messages=context, tools=CORTEX_TOOLS, thinking="adaptive")` → exécuter `result.tool_calls[:5]` → `blackboard.update(...)`.
  - Tools idle/chatting (PAS encore les tools jeu) : `say`, `set_activity`, `set_goals`, `write_note`, `remember`, `recall`, `set_face`, `play_anim`.
  - `recent_chat` filtré par `mind/chat_filter.py:is_goal_injection` (M-1 Task 15) + marqué « provenance non fiable » dans le contexte.
- **Tests** : `_StubBrain` (pattern existant) — tool_calls appliqués, re-check activité post-retour, re-prompt après no-action (3×), bascule cadence sous budget. `FakeGameAdapter` non requis ici (pas de jeu).
- **Risque** : doublon SilenceMonitor/cortex pour l'initiative → tranché (SilenceMonitor off sous cortex). Cohérence cortex/réflexe → `recent_speech` + arbitre.
- **DoD** : en idle sans chat, Shugu produit une initiative ≥ 1/60 s (O1) ; flag off = silencieux comme aujourd'hui.

### M-4 — GameAdapter + affichage

- **But** : faire tourner un jeu (PyBoy Gen 1) et l'afficher sur le stream, piloté manuellement (endpoint debug). Spec §4.6, §4.7.
- **Dépend de** : M-1 (`mind.activity`).
- **Fichiers** : créer `backend/shugu/games/{__init__,base,registry,pyboy_gen1,memory_reader}.py` ; route WS `/game/stream` + `POST /debug/game/act` (`routes/game.py`) ; frontend `frontend/src/features/gameScreen/GameScreen.tsx` + type `mind.activity` dans `services/shuguClient.ts` ; `config.py` (`mind_game_enabled`, `mind_game_debug_enabled`, `SHUGU_GAME_ROM_DIR`).
- **Interfaces clés** : `GameAdapter` Protocol (`start/stop/observe/act/save_checkpoint/load_checkpoint`), `GameObservation(screenshot_png, state_text, state, legal_actions, frame_id)`, `GameAction(buttons, hold_frames)`. Thread PyBoy + `queue.Queue(maxsize=1)`, encode JPEG **hors thread** via `run_in_executor`. RAM Gen 1 (datacrystal) : flag combat `0xD057`, position, party, badges.
- **Sécurité** : `/debug/game/act` → `require_operator()` + `mind_game_debug_enabled=False`. `/game/stream` public-read mais rate-limité par IP.
- **Windows** : `SDL_VIDEODRIVER=offscreen`, thread non-daemon, `stop()` via `threading.Event` + `join(10)` + checkpoint d'urgence.
- **Tests** : `FakeGameAdapter` in-memory ; intégration PyBoyGen1Adapter sur **ROM homebrew libre** (`tests/fixtures/`, JAMAIS de ROM commerciale).
- **DoD** : le jeu tourne, s'affiche dans le viewer quand `activity=="gaming"`, pilotable via l'endpoint debug authentifié.

### M-5a — Cortex gaming (base)

- **But** : Shugu joue seule via `press_buttons` + vision. O3 partiel. Spec §4.4.
- **Dépend de** : M-3 (cortex), M-4 (GameAdapter).
- **Fichiers** : étendre `mind/cortex.py` (cadence 8 s en gaming, `observe()` → contexte RAM-first + screenshot, tools `press_buttons`) ; `mind/compaction.py` (accordéon : résumé tous les 20 tours, reset ~100, `asyncio.create_task` non bloquant) ; `mind/critic.py` (anti context-poisoning toutes les 10-15 ticks).
- **Interfaces clés** : screenshot 160×144 ×3 nearest + `state_text` structuré (RAM-first, le screenshot ne porte jamais seul une donnée critique). Re-check activité APRÈS retour M3 (ignore tool_calls game périmés).
- **Tests** : `FakeGameAdapter` ; compaction déclenchée au bon tour ; tool_calls game ignorés si activité changée pendant l'appel.
- **Risque** : coût vision (mesuré M-0 via bench) ; context poisoning ; boucles répétitives (compaction + reset).
- **DoD** : sur une session, Shugu progresse seule (sortir du bourg, gagner un combat) — O3 démontrable.

### M-5b — navigate_to (BFS) — OPTIONNEL pour O3

- **But** : pathfinding automatique sur les labyrinthes. Spec §4.4 + §12.8.
- **Dépend de** : M-5a.
- **Fichiers** : `games/pathfinding.py` (parsing collision map RAM Gen 1, warps, connexions inter-cartes, BFS) ; tool cortex `navigate_to(x, y)`.
- **Note** : service Python pur, PAS un agent LLM (YAGNI sur les sous-agents type GPP `define_agent`). À ne lancer que si le cortex bute réellement sur la navigation en M-5a.
- **DoD** : le cortex délègue un déplacement multi-tiles et y arrive.

### M-6 — Consolidation + smoke live

- **But** : nettoyer, vérifier O4, valider en live. Spec §9.
- **Dépend de** : tout.
- **Contenu** : extracteur mémoire/compactor → `M3DirectorBrain` ; suppression des brains morts (anthropic/openai director si plus utilisés) ; `MindMetricsRecorder` Prometheus complet + row Grafana « Mind » (vérifier whitelist `mind_` dans `infra/grafana/dashboards/voice-body-pipeline.json`) ; smoke test 30 min (F1–F4 rejoués) ; décision GO/NO-GO.
- **DoD** : session live complète, métriques visibles, O4 vérifié (100 % cognition non temps-réel via M3).

---

## 4. Track voix temps réel (détail des fiches M-V)

### M-V0 — Baseline latence

- **But** : mesurer le budget voix-à-voix RÉEL du pipeline existant AVANT toute optimisation. Spec §13.6.
- **Dépend de** : rien (peut démarrer tout de suite, indépendant du cerveau).
- **Fichiers** : `voice/metrics.py` (ajouter `mind_voice_latency_seconds{stage}`) ; instrumenter `voice/livekit_agent.py` aux 4 étages (turn → STT → LLM → TTS).
- **DoD** : tableau de latence par étage sur une session de test → on sait où est le goulot réel.

### M-V1 — Détection sémantique de fin de parole ⭐ (plus gros levier)

- **But** : remplacer le VAD-silence par un turn-detector sémantique. Le plus gros gain ressenti de tout le projet voix. Spec §13.3.
- **Dépend de** : rien de bloquant (M-V0 recommandé pour mesurer le gain).
- **Fichiers** : `voice/turn_detector.py` (wrapper du modèle EOU de LiveKit Agents — **déjà dans le SDK**) ; câblage dans `voice/livekit_agent.py` (remplacer le endpointing VAD-silence) ; fallback VAD si modèle indispo ; `config.py` (`mind_voice_turn_detector_enabled`).
- **Interfaces clés** : LiveKit expose un turn-detector EOU (135M, ~50 ms CPU). Vérifier la version du SDK `livekit-agents` dans `backend/pyproject.toml` et l'API exacte (`turn_detection=` au niveau de l'AgentSession ou plugin dédié).
- **Tests** : unit sur le wrapper (mock du modèle → décision cut/wait) ; métrique `mind_voice_turn_detector_total{outcome}`.
- **Gain attendu** : −400 à −600 ms par réponse + −85 % d'interruptions involontaires.
- **DoD** : tour coupé sans attendre le timeout silence ; baseline M-V0 améliorée, mesurée.

### M-V2 — STT partiels rapides + overlap + voix=sense du Mind

- **But** : descendre sous 900 ms voix-à-voix (O6) et brancher la voix au cerveau. Spec §13.3, §13.4.
- **Dépend de** : M-V1, M-1 (Blackboard), M-2 (Arbiter).
- **Fichiers** : `voice/stt_streaming.py` (Moonshine/Parakeet/Deepgram — choix selon M-V0) ; overlap dans `voice/livekit_agent.py` (LLM sur partiels STT, TTS sur 1er token LLM, buffer sentence-aware) ; nouveau `TriggerEvent(kind="voice")` haute priorité (court-circuite le debounce) ; le tour vocal lit le `MindState` et écrit `append_speech`/`append_chat` ; hot-path LLM = **Gemma local** (latence), escalade M3 optionnelle avec filler (`voice/filler_bank.py`).
- **Tests** : overlap (LLM démarre avant fin STT) ; voix consciente (prompt contient le plan) ; voix écrit dans le Blackboard.
- **DoD** : voix-à-voix p50 < 900 ms mesuré (O6) ; Shugu parlée cohérente avec ce qu'elle fait.

### M-V3 — TTS expressif français (optionnel)

- **But** : voix plus vivante (rires, respirations). Spec §13.3.
- **Fichiers** : adapter TTS (MiniMax Speech-2.8 sound tags, WebSocket ; ou Cartesia Sonic ~90 ms) derrière flag, en remplacement/complément de Piper.
- **DoD** : voix plus expressive, latence préservée, A/B contre Piper.

---

## 5. Protocole de planification juste-à-temps

Pour chaque jalon, AVANT de le déléguer à ruflo :
1. Relire le code réellement produit par les jalons amont (signatures exactes — elles peuvent avoir dévié des « Note exécutant »).
2. Générer le plan TDD bite-sized via `superpowers:writing-plans`, en s'appuyant sur la fiche de cadrage correspondante (§3/§4) + les contrats d'interface (§2).
3. Review adversariale du plan si le jalon est gros/risqué (M-2, M-4, M-5a, M-V2 le méritent ; M-V1, M-5b non).
4. Déléguer à `ruflo-autopilot:autopilot-coordinator`, scope = ce jalon uniquement.
5. Vérifier le rapport (tests réellement verts, ruff, aucun test bidouillé) AVANT merge — review par agent frais non-auteur.

---

## 6. Synthèse pour l'orchestrateur

- **En cours** : M-0 (ruflo, arrière-plan).
- **Prêt à planifier en détail dès M-0 mergé** : M-1 (déjà détaillé), puis M-2.
- **À lancer en parallèle dès M-1 mergé** : M-V1 (⭐ meilleur ratio impact/effort, indépendant).
- **Décision en attente** : M-V0 doit choisir le STT streaming pour M-V2 (Moonshine local vs Deepgram cloud) — trancher après la mesure de baseline.
