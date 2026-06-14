# Spec — Shugu Mind : cerveau autonome Cortex + Réflexes sur MiniMax M3

> **Date** : 2026-06-13
> **Statut** : validé en brainstorming + review adversariale (3 reviewers non-auteurs, 10 bloquants / 14 majeurs intégrés)
> **Périmètre** : conception du cerveau autonome (type Neuro-sama) + gameplay autonome (type Gemini Plays Pokémon), en Strangler Fig au-dessus des briques existantes.
> **Précède** : plan d'implémentation `docs/superpowers/plans/2026-06-13-autonomous-mind-plan.md` (à produire via writing-plans).

---

## 1. Vision

Shugu devient un **streamer IA autonome** : il décide en continu quoi faire (parler, jouer, commenter, interpeller le chat), joue à des jeux rétro de manière autonome avec vision + lecture d'état, et garde la répartie au chat — le tout avec **MiniMax M3 comme unique modèle de cognition**.

### Objectifs mesurables

| # | Objectif | Critère de succès |
|---|---|---|
| O1 | Autonomie proactive | En l'absence de tout trigger externe, Shugu produit une initiative (parole, changement d'activité) au moins toutes les 60 s |
| O2 | Répartie chat vivante | Latence message chat → début audio TTS **p50 < 5,5 s** pendant une session de jeu active (voir §5.F1 pour le budget détaillé — la valeur dépend du debounce, tranchée ci-dessous) |
| O3 | Gameplay autonome | Shugu progresse seul dans Pokémon Rouge/Bleu (sortir du bourg, gagner un combat) sans intervention humaine sur une session de 2 h |
| O4 | Un seul cerveau | 100 % des appels de cognition passent par la famille `M3Brain` (fallback local uniquement sur erreur, mesuré par métrique) |
| O5 | Coût borné | Coût API < 5 $/heure de stream, cap dur configurable, mesuré en continu |

### Non-objectifs (hors scope de ce spec)

- Branchement Twitch EventSub production (chantier séparé déjà cadré, l'adapter dev-mock suffit ici).
- Jeux GBA (Pokémon Émeraude) — viendra comme second `GameAdapter` (stable-retro/PyGBA), l'interface est conçue pour.
- Jeux PC natifs / capture d'écran OS.
- Multi-stream, multi-avatar.
- Génération vidéo/musique MiniMax (Hailuo, Music) — explorations futures.

---

## 2. Décisions verrouillées

| Décision | Choix | Justification |
|---|---|---|
| Stratégie de refonte | **Strangler Fig** — nouvelle couche au-dessus des briques existantes | ~700 fichiers Python testés conservés ; les bugs déjà corrigés (barge-in, audio bomb) ne reviennent pas |
| Rôle de MiniMax M3 | **M3 pour toute la cognition** (cortex, réflexe, extraction mémoire) | Répond à la douleur « trop de morceaux dispersés » : un modèle, une personnalité |
| Provider M3 | OpenAI-compat, base_url configurable. **Benchmark TTFB obligatoire en M-0** entre MiniMax direct (~40 s TTFB mesuré par des tiers) et SiliconFlow (~2,7 s) ; le réflexe exige TTFB < 3 s | La latence premier token est LE risque n°1 de « M3 pour tout » |
| Soupape de secours | Fallback **Ollama local (Gemma)** automatique si M3 échoue/timeout, **implémenté dès M-0** (la classe actuelle est un squelette `NotImplementedError`), + ultime repli canned déterministe | Un stream live ne peut pas mourir sur une panne API |
| Gameplay | **Émulateur rétro d'abord** (PyBoy 2.7, Pokémon Gen 1) derrière un **`GameAdapter` Protocol** extensible | Tour par tour = compatible latence LLM ; interface prête pour GBA/navigateur ensuite |
| Ordre des chantiers | **Cerveau d'abord, gameplay ensuite** | Fondation propre, le gameplay s'y branche au lieu d'être refactoré après coup |
| Architecture | **B — Cortex + Réflexes** : deux boucles M3 autour d'un Blackboard, arbitre de sortie unique | Pattern Neuro-sama réel ; le stream reste vivant pendant que le cortex réfléchit |

### Faits M3 vérifiés (recherche 2026-06-13)

- MiniMax M3 (sorti 2026-06-01) : entrée texte + **images + vidéo**, sortie **texte uniquement**. **Pas d'audio** → le pipeline voix local (whisper.cpp STT + Piper TTS) reste indispensable.
- API OpenAI-compatible (`/v1/chat/completions`), function calling via `tools`, streaming, contexte 1 M tokens.
- `thinking: "adaptive" | "disabled"` au niveau requête, même prix ; `reasoning_split` pour séparer le raisonnement (**à confirmer sur SiliconFlow en M-0** — extension MiniMax que le provider tiers peut ne pas implémenter).
- Prix : 0,30 $/M tokens input, 1,20 $/M output (≤ 512 K contexte). **Coût de facturation des images : non documenté publiquement → mesuré en M-0 via `usage.input_tokens` réel.**

### Faits code vérifiés contre le repo (review 2026-06-13)

Ces vérifications ont corrigé des fictions d'interface dans la v1 du spec :

- **Le `SayWorker` ne fait PAS parler** (`director/workers/say.py:88`) : il ne diffuse que le *ton* émotionnel (`scene.apply[say_emotion]`). Le texte parlé arrive « d'un autre canal ». Conséquence majeure sur §4.5.
- **Le chemin réel de la parole** passe par la `RedisQueue` (`pipeline/queue.py`) : un `QueuedMessage` (avec `text`, `session_id`, `nonce`, `author_role`, `precomputed_audio`, `tags`) → Picker serial → broadcast. `author_role` accepte déjà `"system"` (queue.py:21).
- **Précédent exact pour une parole d'origine système** : `AmbientScene` (`pipeline/ambient.py:208`) synthétise l'audio, construit un `QueuedMessage(precomputed_audio=…)` et appelle `enqueue_ready()` directement → Picker. **L'Arbiter suivra ce patron.**
- **`OllamaDirectorBrain.complete()` lève `NotImplementedError`** (`adapters/brain_director_ollama.py:48`) — squelette Phase E2.6. Le fallback doit être implémenté avant d'être promis.
- **Le timeout LLM du Director est hardcodé à 3,0 s** (`director/orchestrator.py:361`), aucun champ Settings — il faut l'exposer.
- **`build_prompt`** signature réelle : `build_prompt(state, trigger, persona=None, memory_facts=None) -> tuple[str, str]` (`director/prompt.py:113`).
- **`DirectorBrain` Protocol** : `async def complete(self, *, system: str, user: str) -> str` (`director/brain_provider.py:47`).
- **Le frontend** reçoit ses events via le topic `stage` (`shuguClient.ts`), PAS via `editor:broadcast` (canal interne). `ShuguEvent` n'a aucun type `mind.activity`. `GameScreen.tsx` n'existe pas.

---

## 3. Architecture cible

```
        ┌────────────── SENSES (services, pas LLM) ───────────────┐
        │ chat Twitch │ STT micro │ GameAdapter.observe() │ events │
        └──────────────────────────┬───────────────────────────────┘
                                   ▼
                  ┌─────────────────────────────────┐
                  │  BLACKBOARD (mind/blackboard.py)│  ← source de vérité unique
                  │  activité, état jeu, plan,      │
                  │  chat récent, paroles récentes  │
                  │  (référence le SceneStateStore) │
                  └───────┬───────────────┬─────────┘
            async get/upd │               │ async get/upd
              ┌───────────▼───┐   ┌───────▼────────┐
              │  CORTEX M3    │   │  RÉFLEXE M3    │  (= Director évolué)
              │  boucle 8-20s │   │  événementiel  │
              │  thinking on  │   │  thinking off  │
              │  vision+tools │   │  court         │
              └───────┬───────┘   └───────┬────────┘
                      │ ActionIntent      │ ActionIntent
              ┌───────▼───────────────────▼────────┐
              │  ACTION ARBITER (mind/arbiter.py)  │  ← Stage Director (Phase 3 roadmap)
              │  priorités, cooldowns, dédup       │
              └───┬──────────────┬─────────────┬───┘
          parole  │       corps  │       jeu   │
                  ▼              ▼             ▼
   ┌──────────────────────┐ ┌──────────┐ ┌──────────────┐
   │ TTS synth +          │ │ Workers  │ │ GameAdapter  │
   │ QueuedMessage →      │ │ existants│ │ .act()       │
   │ enqueue_ready →      │ │ (face/   │ │ (thread      │
   │ Picker serial → WS   │ │ anim/vfx)│ │  PyBoy)      │
   │ (patron AmbientScene)│ │ broadcast│ └──────────────┘
   └──────────────────────┘ └──────────┘
```

**Invariants préservés** (Phase 1, `docs/PHASE1-FOUNDATION.md`) :

1. *Toute parole passe par le Picker, unique dequeuer serial.* L'Arbiter synthétise l'audio puis `enqueue_ready()` un `QueuedMessage` — il ne court-circuite jamais le Picker (patron AmbientScene).
2. *Les senses sont des services Python, pas des agents LLM.* `GameAdapter` est un sense/effecteur pur, zéro appel LLM dedans. Le pathfinding (M-5b) est un BFS Python, pas un agent.
3. *Le barge-in et l'AudioBridge existants ne sont pas modifiés.*

**Nouveau module** : `backend/shugu/mind/` — la colonne vertébrale. Le package `director/` actuel est progressivement absorbé (Strangler) : son orchestrator devient le Réflexe, ses workers/state_store/triggers/debouncer/cache sont réutilisés tels quels.

---

## 4. Composants

### 4.1 Blackboard — `backend/shugu/mind/blackboard.py`

État partagé unique. **`get()` est `async`** : il agrège son propre état + un snapshot frais du `DirectorStateStore` existant (dont `get()` est une coroutine sous `asyncio.Lock`).

```python
@dataclass
class MindState:
    scene: SceneStateSnapshot           # snapshot copié depuis DirectorStateStore au moment du get()
    activity: Literal["idle", "chatting", "gaming"] = "idle"
    current_game: str | None = None
    plan: PlanState = field(default_factory=PlanState)
    mood: str = "neutral"
    recent_chat: list[ChatLine] = []     # FIFO trim 30 — provenance NON FIABLE (marqué dans le prompt)
    game_observation: GameObservationSummary | None = None
    recent_speech: list[SpeechRecord] = []  # FIFO trim 10 — texte + source (cortex|reflex)
    last_cortex_tick_at: datetime | None = None

@dataclass
class PlanState:
    primary: str = ""
    secondary: list[str] = []
    session_notes: str = ""              # knowledge base libre du cortex, cap 4 000 chars (FIFO paragraphe)

class Blackboard:
    async def get(self) -> MindState              # agrège + await state_store.get()
    async def update(self, patch: dict) -> MindState
    async def append_chat(self, line: ChatLine) -> None
    async def append_speech(self, record: SpeechRecord) -> None
    async def reset(self) -> None
```

Le `DirectorStateStore` n'est **pas dupliqué** : composition par référence. Les workers continuent de patcher le scene state comme aujourd'hui. Singleton `get_blackboard()`.

**Cycle de vie** : le Blackboard est **éphémère** (comme le `DirectorStateStore`) — aucune persistance entre redémarrages. `reset()` est appelé dans le lifespan startup avant le démarrage du Cortex, et à chaque flip `mind_cortex_enabled` False→True, pour qu'une session ne pollue jamais la suivante (goals/notes/mood résiduels purgés).

**Convention settings** : tous les réglages `mind_*` suivent le pattern du projet `AliasChoices("MIND_XXX", "SHUGU_MIND_XXX")` (cohérent avec `SHUGU_DIRECTOR_LLM_PROVIDER`, `SHUGU_VOICE_AGENT_ENABLED`, etc.).

**Changement d'activité → relais frontend** : `update()` détecte une transition de `activity` et publie un event `{"type": "mind.activity", "activity": …, "game": …}` sur le **topic `stage`** (celui que les viewers reçoivent réellement — pas `editor:broadcast`). Voir §4.7.

### 4.2 Famille M3Brain — `backend/shugu/adapters/brain_m3.py`

Deux classes, signatures distinctes et explicites (résout l'incompatibilité de la v1) :

```python
# Interface riche, utilisée par le Cortex
class M3Brain:
    async def generate(
        self, *,
        system: str,
        messages: list[Message],            # texte + images base64 (vision M3)
        tools: list[ToolSpec] | None = None,
        thinking: Literal["adaptive", "disabled"] = "disabled",
        max_tokens: int = 500,
        timeout_s: float = 8.0,
    ) -> BrainResult                        # .text, .tool_calls, .usage (in/out tokens)

# Adapteur conforme au Protocol DirectorBrain (complete(*, system, user) -> str)
# — utilisé par le Réflexe et l'extracteur mémoire (O4 : un seul cerveau)
class M3DirectorBrain:                       # implements DirectorBrain
    def __init__(self, inner: M3Brain) -> None: ...
    async def complete(self, *, system: str, user: str) -> str:
        result = await self._inner.generate(
            system=system,
            messages=[Message(role="user", content=user)],
            thinking="disabled",
            max_tokens=self._settings.director_max_tokens,
            timeout_s=self._settings.director_llm_timeout_s,
        )
        return result.text
```

- Settings : `mind_m3_base_url` (défaut SiliconFlow, surchargeable), `mind_m3_model` (`minimax-m3`), `mind_m3_api_key` (fallback sur `minimax_api_key`).
- **`make_director_brain()`** retourne `M3DirectorBrain` quand `director_llm_provider == "m3"` (nouvelle valeur du Literal). Aucune autre signature touchée.
- **Fallback chain** (dans `M3Brain.generate` et l'adapteur) : sur `TimeoutError`/5xx (seuil 2 consécutifs) → `OllamaBrain` (Gemma local) → si Ollama échoue aussi → **repli canned déterministe** (réponse pré-écrite, pas de LLM). Métrique `mind_brain_fallback_total{reason, tier}`. Retour M3 sondé toutes les 60 s.
- **Budget** : compteur de coût cumulé (heure glissante, `usage × prix`). Au-delà de `mind_cost_cap_hourly_usd` (défaut 5,0) : cadence cortex ×4 + réflexe en local. Métrique `mind_m3_cost_usd_total` + log warning.

### 4.3 Réflexe — évolution du Director (`director/orchestrator.py`)

Le Réflexe **EST** l'Orchestrator actuel, conservé avec ses optimisations (debouncer, canned, cache pgvector, rate limit, cap horaire). Changements ciblés :

1. **Brain** : `make_director_brain()` retourne `M3DirectorBrain`.
2. **Timeout configurable** : nouveau `director_llm_timeout_s: float = 5.0` dans `config.py` ; la constante `3.0` de `orchestrator.py:361` est remplacée par `settings.director_llm_timeout_s`. Les tests existants qui dépendaient de 3,0 s sont mis à jour.
3. **Debounce abaissé sous le mind** : nouveau réglage effectif `director_debounce_window_seconds = 0.8` quand `mind_cortex_enabled` (le cortex assure la cohérence des bursts via `recent_chat`, le réflexe n'a plus besoin d'une fenêtre de 3 s). Voir §5.F1 pour le budget de latence.
4. **Prompt** : `build_prompt` évolue vers `build_prompt(state, trigger, *, mind_state=None, memory_facts=None, persona=None)`. Quand `mind_state` est fourni, le plan cortex + activité + `recent_speech` sont injectés dans le system prompt. Priorité : `persona` explicite > `PERSONA_REFLEX` par défaut.
5. **Sortie via Arbiter** : derrière `mind_arbiter_enabled`. Sémantique précise du flag :
   - `mind_arbiter_enabled=False` (défaut migration) : comportement **strictement actuel** — `_dispatch_and_publish` appelle `worker.apply` + broadcast `editor:broadcast`. Zéro changement frontend.
   - `mind_arbiter_enabled=True` : le Réflexe **passe ses tags à l'Arbiter AVANT dispatch** ; l'Arbiter applique priorité/cooldown/dédup puis appelle **le même `_dispatch_and_publish`** (donc le broadcast `editor:broadcast`/`scene.tick` reste identique, le contrat frontend ne change pas). L'Arbiter est une **grille de pré-dispatch**, pas un remplacement du broadcast.

TriggerBus, kinds, wiring `publish_chat_trigger()` : inchangés.

### 4.4 Cortex — `backend/shugu/mind/cortex.py`

Boucle d'agence continue, le composant réellement nouveau. Task asyncio démarrée/arrêtée dans le **lifespan** (`app.py`), derrière `mind_cortex_enabled`.

```
loop:
    cadence = 8s si activity=="gaming" sinon 20s
    state = await blackboard.get()
    if state.activity == "gaming":
        obs = await game_adapter.observe()       # screenshot + état RAM
        await blackboard.update(game_observation=résumé(obs))
    context = assemble(state, obs?, await memory.recall(...), historique compressé)
    result = await m3_brain.generate(system=PERSONA_CORTEX, messages=context,
                                     tools=CORTEX_TOOLS, thinking="adaptive",
                                     max_tokens=settings.mind_cortex_max_tokens,  # défaut 500
                                     timeout_s=30)
    # RE-CHECK activité APRÈS le retour M3 (peut avoir changé pendant l'appel — F4)
    fresh = await blackboard.get()
    for call in result.tool_calls[:5]:
        if call.name in GAME_TOOLS and fresh.activity != "gaming":
            continue   # tool_call game périmé — l'activité a changé pendant l'appel
        dispatch(call)                            # → ActionIntent vers Arbiter
    await blackboard.update(plan=…, last_cortex_tick_at=now)
    maybe_compact()                               # via asyncio.create_task (non bloquant)
```

**Tools du cortex** (function calling M3) :

| Tool | Effet | Cible |
|---|---|---|
| `say(text, emotion)` | Parole longue / initiative | ActionIntent(speech, prio cortex) |
| `set_activity(activity, game?)` | Bascule idle/chatting/gaming, start/stop GameAdapter, publie `mind.activity` | Blackboard + lifecycle |
| `press_buttons(buttons, reason)` | Séquence d'inputs (max 10), validée | ActionIntent(game) → GameAdapter.act() |
| `navigate_to(x, y)` | Pathfinding BFS (M-5b, service Python sur collision map RAM) | GameAdapter |
| `set_goals(primary, secondary)` | Met à jour le plan | Blackboard.plan |
| `write_note(text)` | Append session_notes (cap 4 000 chars) | Blackboard.plan |
| `remember(text, subject)` / `recall(query)` | Mémoire long-terme (single-writer via MemoryAgent) | MemoryAgent |
| `set_face(slug)` / `play_anim(slug)` | Corps | ActionIntent(body) → workers |

**Réservation de tools** : `set_activity`, `set_goals`, `remember`, `press_buttons`, `navigate_to` sont **réservés au cortex**. Le réflexe n'expose que `say`/`set_face`. Le `recent_chat` injecté dans le cortex est **filtré par `injection_detector`** (patterns de manipulation de goals FR/EN ajoutés) et marqué « provenance non fiable » dans le contexte.

**Contexte gaming — leçons Gemini/Claude Plays Pokémon** :

- **RAM-first** : position, map id, party HP/PP, badges, inventaire, flag combat `0xD057` extraits par le `MemoryReader` et injectés en **texte structuré**. Le screenshot (PNG 160×144 ×3 nearest) accompagne, ne porte jamais seul une donnée critique.
- **Compaction accordéon** : clair sur ~30 derniers tours ; au-delà, résumé M3 (thinking off) **tous les 20 tours** (pic de contexte limité — cf. §10) ; reset complet ~100 tours avec réinjection goals + session_notes + résumé étagé. La compaction tourne en **`asyncio.create_task`** (non bloquant) ; si une compaction est encore en cours au tick suivant, le tick s'exécute sur l'ancien contexte (jamais d'attente).
- **Anti context-poisoning** : critique contexte-vierge toutes les **10–15 ticks gaming** (~80–120 s, pas 50) ; `mind_critic_enabled` défaut on.

Le cortex ne traite **pas** les messages chat individuels (travail du réflexe). Il lit `recent_chat` pour le *climat*.

### 4.5 ActionArbiter — `backend/shugu/mind/arbiter.py`

Sérialise les intentions des deux boucles. Incarnation du « Stage Director » (Phase 3 roadmap).

```python
@dataclass(frozen=True)
class ActionIntent:
    source: Literal["cortex", "reflex"]
    kind: Literal["speech", "body", "game"]
    payload: dict
    priority: int
    created_at: datetime
```

**Sortie speech — patron AmbientScene (vérifié `pipeline/ambient.py:208`)** :

L'Arbiter, pour une intention `speech`, fait exactement ce que fait AmbientScene pour une parole d'origine système :
1. Synthétise l'audio via l'adapteur TTS existant (Piper local, le texte est **déjà final** — pas de second appel LLM).
2. Construit un `QueuedMessage(msg_id=new_msg_id(), route="shugu_persona", text=…, author_role="system", priority_tier=…, session_id=mind_session, nonce=uuid, received_ns=…, precomputed_audio=…, precomputed_emotion=…, tags={…})`.
3. `await queue.enqueue_ready(msg)` → le **Picker serial** le diffuse (broadcast `performance.audio` + tags). Invariant 1 respecté.

**Sortie body** : `Worker.apply()` existants (via `_dispatch_and_publish`). **Sortie game** : `GameAdapter.act()` (voie séparée, pas de conflit avec la parole, appliquée immédiatement).

**Règles d'arbitrage** (politique codée, pas de LLM) :

1. Priorités speech : réponse réflexe chat (1) > parole cortex (2) > filler canned (4). Body = 3.
2. **Anti-collision parole** : une seule speech en file de synthèse ; une speech cortex de plus de 15 s est jetée (périmée) si une réflexe arrive. Le barge-in utilisateur existant reste prioritaire.
3. **Cooldowns** : parole cortex max 1/20 s en gaming ; dédup contre `recent_speech` (similarité par préfixe).
4. **Backpressure** : file d'intents `maxsize` borné ; purge des intents périmés (> 30 s) **à chaque enqueue** (O(n) trivial sur ≤ 20 items — pas de tâche de fond, donc pas d'accumulation en période de silence). Métrique `mind_arbiter_intents_total{outcome=dropped}`. Jamais de blocage de boucle.

### 4.6 GameAdapter — `backend/shugu/games/`

```python
@runtime_checkable
class GameAdapter(Protocol):
    slug: str
    display_name: str
    async def start(self) -> None
    async def stop(self) -> None
    async def observe(self) -> GameObservation       # lève GameAdapterError si l'émulateur est mort
    async def act(self, action: GameAction) -> ActResult
    async def save_checkpoint(self, slot: str) -> None
    async def load_checkpoint(self, slot: str) -> None

@dataclass(frozen=True)
class GameObservation:
    screenshot_png: bytes          # upscalé ×3 nearest
    state_text: str                # dump structuré RAM
    state: dict
    legal_actions: list[str]
    frame_id: int

@dataclass(frozen=True)
class GameAction:
    buttons: list[str]             # max 10, validée contre legal_actions
    hold_frames: int = 1
```

**`games/pyboy_gen1.py`** :

- PyBoy 2.7 headless (`window="null"`), **thread dédié**. PyBoy tourne à `speed=1` (temps réel, regardable).
- **Encodage JPEG hors thread émulateur** (résout le stall GIL) : le thread PyBoy ne fait que `tick()` + dépose le `screen.ndarray` brut (numpy, pas d'encode) dans une `queue.Queue(maxsize=1)` (drop-oldest). L'encode JPEG/PNG est fait côté asyncio via `run_in_executor` au moment où une frame est consommée (stream ou observe). Le GIL n'est pas tenu en continu dans le thread.
- État : `game_wrapper_pokemon_gen1` + `MemoryReader` maison (adresses Gen 1 publiques : datacrystal). Flag combat `0xD057`.
- ROM : chemin via `SHUGU_GAME_ROM_DIR`. **Jamais de ROM commerciale dans le repo ni en CI.** Tests d'intégration sur ROM homebrew libre (`backend/tests/fixtures/`).
- Save states auto toutes les 5 min + slots nommés pilotables par le cortex.
- **Pièges Windows** : (1) `SDL_VIDEODRIVER=offscreen` requis pour le headless fiable ; `start()` fait un health-check de l'init SDL avec message d'erreur clair si échec. (2) **Arrêt propre** : un `threading.Event` stop_flag est posé par `stop()`, suivi d'un `join(timeout=10)` AVANT la fin du lifespan ; un checkpoint d'urgence est écrit. Le thread n'est pas `daemon=True` (sinon les save states en cours d'écriture sont tronqués à la fin du process).

`games/registry.py` : `get_game_adapter(slug)` — registre extensible (futur `stable_retro_gba`, `browser_playwright`).

### 4.7 Affichage du jeu + relais d'activité

- **Backend stream** : endpoint **WebSocket binaire** `GET /game/stream` (FastAPI). Le frame brut est encodé JPEG (qualité 75) à la demande via `run_in_executor`. **Auth** : public-read (les frames sont déjà visibles sur le stream) mais **rate-limité par IP + max connexions concurrentes**, derrière `mind_game_enabled`. Pas de LiveKit, pas de MJPEG.
- **Endpoint debug (M-4)** : `POST /debug/game/act` — **operator JWT requis** (`require_operator()`) + feature flag `mind_game_debug_enabled=False` (même double-gate que `test_triggers_enabled`). Payload `{buttons: list[str], hold_frames: int}`.
- **Relais d'activité** : le Blackboard publie `mind.activity` sur le topic **`stage`** (§4.1). Ajout du type à `frontend/src/services/shuguClient.ts` (`ShuguEvent`) et dispatch dans `_client.tsx`/`ViewerEventsProvider`.
- **Frontend** : nouveau composant `frontend/src/features/gameScreen/GameScreen.tsx` — `<canvas>` overlay dans la page viewer, visible si `activity=="gaming"` (event `mind.activity`). `image-rendering: pixelated`.
- **OBS** : rien à changer (Browser Source capture déjà la page viewer).

### 4.8 Mémoire

Aucun nouveau pipeline. Cortex et réflexe utilisent `MemoryAgent.recall()`/`store()` via les tools `remember`/`recall`. Single-writer respecté. L'extracteur de facts et le compactor basculent sur `M3DirectorBrain` (O4). Pour ces usages internes (extraction, compaction), `complete()` est appelé avec `thinking=disabled`, `max_tokens=400`, `timeout_s=10` par défaut — le caller (compactor) peut surcharger selon ses propres réglages (`compactor_summary_count`), mais ne doit **jamais** hériter accidentellement du `max_tokens` du cortex.

---

## 5. Flux clés

**F1 — Message chat pendant le jeu** (budget de latence O2) :
`visitor_ws` → `publish_chat_trigger()` → TriggerBus → Réflexe (**debounce 0,8 s** sous le mind) → `M3DirectorBrain.complete` (TTFB SiliconFlow ~2,7 s, thinking off) → ActionIntent(speech, prio 1) → Arbiter → TTS synth (~0,4 s premier chunk Piper) → `enqueue_ready` → Picker → broadcast.
Budget p50 : 0,8 + 2,7 + 0,4 + marge ≈ **< 5,5 s** (O2). Si `mind_cortex_enabled=False`, le debounce reste à 3,0 s (comportement actuel). **La décision debounce est tranchée en §12.**
Note dropped-message : quand le timer debounce fire pendant qu'un tick tient le `_tick_lock`, le message suivant est désormais loggé en **WARNING** (pas DEBUG) + métrique, au lieu d'être perdu silencieusement.

**F2 — Tick cortex en gaming** : timer 8 s → `observe()` → M3 (thinking adaptive) → tool_calls `press_buttons(["up","up","a"])` + éventuellement `say("Je tente le combat !")` → re-check activité → Arbiter (game immédiat ; speech prio 2, cooldown 20 s).

**F3 — Initiative en idle** : cortex détecte (Blackboard) pas de chat depuis 90 s → `set_activity("gaming","pokemon_gen1")` (publie `mind.activity` sur `stage`) + `say("Personne ne parle… je lance Pokémon !")` → GameAdapter.start() → frontend reçoit `mind.activity` → `GameScreen` s'affiche.

**F4 — Panne M3** : 2 timeouts consécutifs → `M3Brain` bascule Ollama/Gemma (pré-chargé, §6) → métrique → cortex `set_activity("chatting")` (save state auto, jeu en pause) → réflexe continue en local (canned/say simple) → retour M3 sondé toutes les 60 s.

---

## 6. Gestion d'erreurs et dégradation

| Panne | Comportement |
|---|---|
| M3 timeout/5xx | Fallback Gemma local pré-chargé → si échec, repli canned déterministe ; jeu en pause ; reprise auto |
| M3 sans tool_call valide en gaming | Tick perdu, `mind_cortex_no_action` ; 3 consécutifs → re-prompt format ; 10 → activity=chatting + alerte |
| PyBoy crash/thread mort | `observe()` lève `GameAdapterError` → load dernier checkpoint ; 2 échecs → activity=chatting, jeu désactivé |
| Budget horaire dépassé | Cadence cortex ×4, réflexe local, log + métrique (O5) |
| Activité change pendant l'appel cortex | Re-check post-retour (§4.4) : les tool_calls `game` périmés sont ignorés |
| Arbiter file pleine | Drop intents > 30 s + métrique — jamais de blocage |
| Prompt / goal injection via chat | `build_prompt` échappe+cappe (vérifié) ; tools sensibles réservés au cortex ; `recent_chat` filtré par `injection_detector` (patterns goal-manipulation) + marqué non fiable ; critique anti-poisoning toutes les 10–15 ticks |
| Backpressure WS jeu | `queue.Queue(maxsize=1)`, drop-oldest (le spectateur perd une frame, jamais de lag accumulé) |

**Fallback Gemma — honnêteté opérationnelle** : le modèle Gemma local (`llm_model_path`, ~7–10 Go VRAM) est **pré-chargé au démarrage** (appel dummy) si `mind_fallback_preload=True`, sinon la première bascule fige le stream 30–60 s (cold start). Le prompt de fallback est **simplifié** (canned + `say` seulement, pas de tags inline complexes que Gemma ne suit pas de façon fiable). Qualité réelle du fallback : « stream vivant, répartie simple » — **pas** « qualité moindre mais complète ». Testé spécifiquement en M-0.

---

## 7. Observabilité

Métriques Prometheus (préfixe `mind_`), même registre que l'existant :

- `mind_cortex_tick_duration_seconds`, `mind_cortex_ticks_total{activity}`, `mind_cortex_no_action_total`
- `mind_m3_tokens_total{direction, loop}` ; `mind_m3_cost_usd_total` ; `mind_m3_vision_tokens_per_frame` (mesuré M-0)
- `mind_brain_fallback_total{reason, tier}` ; `mind_brain_ttfb_seconds` (histogram)
- `mind_arbiter_intents_total{source, kind, outcome}`
- `mind_game_actions_total{game}` ; `mind_game_checkpoint_total{kind}`
- Row Grafana « Mind » ajoutée au dashboard D-10C. **À vérifier en M-6** : les whitelists de labels du dashboard (`infra/grafana/dashboards/voice-body-pipeline.json`) acceptent-elles le préfixe `mind_` ? Sinon, étendre la whitelist.

Logs structlog : `mind.cortex`, `mind.arbiter`, `mind.brain_m3`, `games.pyboy_gen1`.

---

## 8. Tests

- **Unit** (mêmes conventions que `backend/tests/unit/`) :
  - Blackboard : `get()` async agrège le scene snapshot, trims FIFO, merge patch, publication `mind.activity` sur transition.
  - Arbiter : table de vérité priorités/cooldowns/péremption ; anti-collision ; **construction du `QueuedMessage` + `enqueue_ready` mockée** (vérifie le patron AmbientScene).
  - Cortex : `_StubBrain` (pattern existant) — tool_calls appliqués, re-check activité, compaction en create_task, re-prompt après no-action, bascule fallback.
  - M3Brain/M3DirectorBrain : httpx MockTransport — payload OpenAI-compat (tools, images base64, thinking), parsing, fallback 3 niveaux (M3→Ollama→canned), comptage coût + tokens vision.
  - GameAdapter : `FakeGameAdapter` in-memory pour tous les tests du cortex (aucune ROM).
- **Integration** (marker `integration`) : PyBoyGen1Adapter sur ROM homebrew libre — boot, observe(), act(), save/load, encode JPEG hors thread.
- **E2E manuel** (checklist ops) : session 30 min, F1–F4 rejoués, métriques Grafana vérifiées.
- Discipline : TDD réel, jamais modifier un test pour le faire passer, review non-auteur avant merge (`feedback_workflow_discipline`).

---

## 9. Plan de migration Strangler Fig

Chaque jalon = 1 PR squashée, feature-flaggée, démontrable, CI verte. **Réordonné** : Arbiter (M-2) AVANT Cortex (M-3) — un cortex sans arbitre serait un producteur sans consommateur.

| Jalon | Contenu | Effort | Démo |
|---|---|---|---|
| **M-0** | `M3Brain` + `M3DirectorBrain` + settings + **implémentation OllamaBrain** (plus squelette) + repli canned + benchmark TTFB **et coût vision** (`tools/bench_m3.py`) + pré-warm Gemma | M | Bench affichant TTFB/coût/tokens-vision par provider ; fallback testé |
| **M-1** | Blackboard (async) + `director_llm_timeout_s` + debounce abaissé + injection du `mind_state` dans `build_prompt` (le Director devient le Réflexe, brain=M3) + **trace confirmée du chemin parole** | M | Le chat répond via M3 avec conscience du plan, latence mesurée |
| **M-2** | ActionArbiter + bascule sortie réflexe dessus (`mind_arbiter_enabled`) + patron AmbientScene pour la parole | M | Le réflexe parle via l'Arbiter, dédup/cooldown actifs |
| **M-3** | Cortex idle/chatting : initiatives, goals, notes, mémoire, filtre injection — **produit dans l'Arbiter de M-2** | M | O1 : Shugu prend des initiatives seul |
| **M-4** | GameAdapter Protocol + PyBoyGen1Adapter + WS `/game/stream` + `/debug/game/act` (auth operator) + `mind.activity` sur `stage` + `GameScreen.tsx` | M | Le jeu tourne et s'affiche, piloté via endpoint debug authentifié |
| **M-5a** | Cortex gaming de base : observe/press_buttons/goals, compaction accordéon (create_task), critique anti-poisoning | L | Shugu joue seul (press_buttons), O3 partiel |
| **M-5b** | `navigate_to` BFS sur collision map RAM Gen 1 (parsing carte, warps, connexions) — **optionnel pour O3** | M | Navigation auto labyrinthes |
| **M-6** | Consolidation : extracteur mémoire → M3, suppression brains morts, vérif whitelist Grafana `mind_`, O4 vérifié, smoke live 30 min | M | Session live complète, GO/NO-GO |

Rollback à chaque jalon : flags `mind_*_enabled=false` → comportement actuel intact.

---

## 10. Coûts estimés (M3, prix 2026-06)

Hypothèses **conservatrices** (cortex `max_tokens=500`, `thinking=disabled` en gaming jusqu'à validation M-0 ; compaction à 20 tours pour borner le pic de contexte) :

| Poste | Hypothèse | Coût/h |
|---|---|---|
| Cortex gaming | ~450 ticks/h × ~12 K in (screenshot + RAM + historique ≤ 20 tours) + 500 out | ~1,62 $ in + 0,27 $ out ≈ **1,9 $** |
| Cortex idle/chatting | ~180 ticks/h × 2 K in + 150 out | ≈ **0,12 $** |
| Réflexe chat | ~150 appels/h × 2 K in + 150 out | ≈ **0,12 $** |
| Compaction + critique | ~25 appels/h × 8 K in | ≈ **0,06 $** |
| **Total ordre de grandeur** | gaming + idle simultanés impossibles → max ≈ | **~2,2 $/h** |

**Scénario pessimiste** (screenshot lourd, contexte gonflé à 30 K/tick si compaction inefficace) : jusqu'à **~4,5 $/h** — à 30 min du cap dur. D'où : (1) mesure du coût vision réel en M-0, (2) compaction agressive à 20 tours, (3) cap dur 5 $/h avec dégradation automatique. Le contexte 1 M tokens de M3 n'est **pas** une excuse pour ne pas compacter (qualité de jeu dégradée au-delà de ~100 K + coût input qui explose).

---

## 11. Risques

| Risque | Probabilité | Mitigation |
|---|---|---|
| TTFB M3 > 3 s chez tous les providers | Moyenne | Benchmark M-0 AVANT tout ; si > 3 s partout : décision utilisateur (réflexe local permanent vs accepter latence) |
| Vision M3 lit mal les écrans GameBoy | Haute (documenté) | RAM-first ; screenshot jamais seule source critique |
| Coût vision M3 non documenté fait sauter le cap | Moyenne | Mesure réelle `usage.input_tokens` en M-0 ; cortex conservatif ; compaction 20 tours |
| Context poisoning goals/notes (durée jusqu'à 7 min) | Moyenne | Critique 10–15 ticks + filtre injection sur `recent_chat` + cap notes + reset accordéon |
| Fallback Gemma muet (cold start ou format tags) | Moyenne | Pré-warm démarrage + prompt fallback simplifié (canned/say) + test M-0 |
| Ollama non implémenté (squelette actuel) | **Certaine sans action** | Implémenté en M-0, pas promis avant |
| Stall GIL (encode JPEG 30 fps) impacte TTS/WS | Moyenne | Encode hors thread (run_in_executor) + queue maxsize=1 |
| Endpoint debug game non authentifié | Moyenne | `require_operator()` + flag `mind_game_debug_enabled` |
| Incohérence cortex/réflexe | Moyenne | Blackboard + `recent_speech` + arbitre anti-collision ; observé en M-3 |
| ROMs : légalité | — | Fournies par l'utilisateur hors repo ; CI sur homebrew libre |

---

## 12. Questions tranchées (carte blanche)

1. **Nom du module** : `mind`.
2. **Le Director n'est pas réécrit** : il devient le Réflexe par évolution (5 changements ciblés §4.3) — cœur du Strangler Fig.
3. **Chemin de la parole** : patron AmbientScene (synth TTS + `QueuedMessage` + `enqueue_ready` → Picker serial). Pas d'interface fictive « queue de texte ». Le `say_emotion` worker reste ce qu'il est (ton émotionnel seulement).
4. **M3Brain dual résolu** : deux classes (`M3Brain.generate` riche pour le cortex, `M3DirectorBrain.complete` conforme au Protocol pour le réflexe/mémoire).
5. **Debounce vs O2** : sous `mind_cortex_enabled`, debounce réflexe abaissé à 0,8 s (le cortex gère la cohérence des bursts). O2 = p50 < 5,5 s, budget détaillé §5.F1. Hors mind, debounce reste 3,0 s.
6. **SilenceMonitor vs initiatives cortex** : quand `mind_cortex_enabled`, le `SilenceMonitor` du Director est **désactivé** — le cortex est le seul initiateur du silence (évite le doublon O1). Documenté ici.
7. **Ordre des jalons** : Arbiter (M-2) avant Cortex (M-3) — pas de producteur sans consommateur.
8. **Pas de sous-agents LLM** (pattern `define_agent` GPP) dans cette itération : le pathfinding est un BFS Python (M-5b). YAGNI — réévaluer après M-5 si le cortex bloque sur les labyrinthes.
9. **Vitesse émulateur** : temps réel (`speed=1`) — le stream doit être regardable.
10. **Le réflexe n'a pas la vision** : seuls `state_text` résumé + plan dans son prompt — appels courts, TTFB bas.
