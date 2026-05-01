# Pass 2 — Performance

Audit ciblé : FastAPI async + SQLAlchemy + Redis + WebSockets.
Hypothèse de charge : ~100 viewers concurrents (visitor_ws + world_ws), 1-3 operators, 1 picker stream actif.
Sources analysées : `backend/shugu/{pipeline,agent,routes,memory,world,core,db,auth}/`.

## Résumé : 12 hotspots identifiés

5 high impact (deux blocants à scale, trois fuites mémoire vivantes process), 4 medium, 3 low/micro-optims.
Le plus critique est le pool DB (5 connexions par défaut) et le fanout O(N×payload) sur `stage` qui sérialise base64 audio par client.

## Top findings (impact estimé)

### High impact (blocant à scale)

- [ ] **DB connection pool dimensionné par défaut (5)** — `backend/shugu/db/session.py:12` — `create_async_engine(...)` sans `pool_size`/`max_overflow` → SQLAlchemy default = 5 conn + 10 overflow. Sous 100+ users actifs avec workers (prep, picker._archive, ingestion, extraction, scene_editor_api, account/admin) qui ouvrent tous des sessions concurrentes via `session_scope()`, on sature le pool en quelques secondes → tous les `await session.execute(...)` empilent sur `pool_pre_ping=True` ping (latence supplémentaire) puis timeout `QueuePool limit reached`. Le picker `_archive` est fire-and-forget : un pool saturé fait grossir `_bg_tasks` indéfiniment. **Fix** : `create_async_engine(dsn, pool_size=20, max_overflow=20, pool_recycle=1800, pool_pre_ping=True)` + exposer via Settings (`db_pool_size`, `db_max_overflow`). **Gain** : élimine le goulot synchrone DB sur l'event loop, latence p99 backend × 5 sous charge.

- [ ] **`json.dumps(event)` répété par client sur le topic `stage` (fanout O(N))** — `backend/shugu/routes/visitor_ws.py:110`, `backend/shugu/routes/operator_ws.py:127`, `backend/shugu/routes/world_ws.py:243`, `backend/shugu/routes/operator_voice_ws.py:156` — chaque viewer a sa propre task `_stream_stage`/`_forward_loop` qui fait `await ws.send_text(json.dumps(event))`. Pour 100 viewers et 1 `performance.audio_chunk` (qui contient un blob base64 ~4-32KB), on sérialise 100× le même payload (CPU pur, GIL-bloquant). En streaming TTS, le picker émet ~10-30 chunks/s × 100 viewers = 1k-3k `json.dumps` de payloads volumineux par seconde → l'event loop est dominé par la sérialisation, latence WS ↑↑. **Fix** : pré-sérialiser dans le publisher (`event_bus.publish`/picker) ou ajouter un cache au niveau du fanout — convertir `event: dict` en `(payload_dict, payload_str)` puis envoyer la chaîne déjà encodée à chaque socket. Pattern simple : helper `send_cached_json(ws, event)` qui mémoïse `id(event) → str` pour la durée du fanout. **Gain** : CPU sérialisation /N (×100 viewers ≈ /100), event loop revient sous <50% sous burst audio.

- [ ] **Mémoire process : `_history_per_session` croît sans bound (un historique LLM par session_id ULID)** — `backend/shugu/pipeline/workers.py:71,105,147` — `self._history_per_session: dict[str, list[Turn]] = {}` indexé par `msg.session_id`. Chaque connexion visitor crée un nouveau ULID (`visitor_ws.py:80`), donc chaque déconnexion/reconnexion ajoute une entrée. La trim ligne 147 ne supprime QUE les vieux turns d'une session active, jamais l'entrée morte. Sur stream 24/7 avec 100 viewers churn moyen de 5min, on ajoute ~28k entrées/jour, chacune contenant les `visitor_history_turns × 2` Turn objects (chaque Turn = `role+content`, content arbitrairement long). **Fix** : `OrderedDict` + LRU `maxsize=2000` (move_to_end à chaque setdefault) ou TTL eviction (heartbeat watchdog qui drop les sessions sans activité > 30min). **Gain** : RAM bornée, GC pressure réduite, plus de leak silencieux post-uptime long.

- [ ] **Mémoire process : `_last_command_ts: dict[str, float]` au scope module** — `backend/shugu/routes/visitor_ws.py:46,254,262` — clé = `identity.ip_hash`. Une IP unique = une entrée définitive. Avec une distribution naturelle de visiteurs sur 6 mois on accumule ~10k-100k entrées. Pas catastrophique mais c'est un bug sémantique : la cooldown de 30s est conservée entre déconnexions (même IP qui revient 1h plus tard reste throttle si elle a tapé `!wave` dans la première session). **Fix** : remplacer par `cachetools.TTLCache(maxsize=10000, ttl=120)` (TTL > cooldown) ou `dict` + nettoyage périodique dans une task lifespan. **Gain** : RAM bornée + UX cooldown correcte.

- [ ] **Picker `_bg_tasks` archive Postgres unbounded sous saturation DB pool** — `backend/shugu/pipeline/picker.py:62,86-90,157-160` — `self._spawn_bg(self._archive(...))` à chaque performance broadcast. `_archive` ouvre `session_scope()` ; si le pool DB est saturé (cf. finding #1), le task wait sur `acquire()` et reste dans `_bg_tasks`. Sous burst de 30 perfs/s pendant 30s → 900 tasks pendantes, chacune retient le `QueuedMessage` complet (incluant `precomputed_audio: bytes` jusqu'à plusieurs MB en mode blob non-streaming). **Fix** : (a) borner avec `asyncio.Semaphore(8)` autour de `_archive`, drop les archives en surplus avec un compteur métrique ; (b) basculer l'archivage sur une queue Redis dédiée + worker dédié (pattern `RQ`). **Gain** : RAM stable sous burst, pas de cascade quand DB lente.

### Medium impact

- [ ] **Sense queue agent : `_sense_queue_max=64` + drop oldest = perte de signaux importants sous raid** — `backend/shugu/agent/runner.py:192,266-268,549-559` — `deque(maxlen=64)` drop l'élément le plus ancien à chaque append au-delà. Avec un tick toutes les 500ms et 4 topics consommés (chat/voice/event/vision), un raid à 30 msgs/s remplit la queue en 2s ; les messages du début de la fenêtre (ceux qui ont déclenché le raid, donc les plus pertinents pour la réaction) sont droppés au profit des derniers entrants. La doctrine inverse (drop newest) est argumentée dans le docstring mais le commentaire est faux : drop_oldest ≠ "garde fresh", il garde la fin de fenêtre. **Fix** : (a) augmenter `sense_queue_max` à 256 (RAM négligeable, ~10kB), (b) implémenter un priority drop : drop d'abord les `sense.event`/`sense.vision` (signaux passifs), garder les `sense.chat`/`sense.voice` (signaux dirigés), (c) ajouter une métrique `agent.senses_dropped_total{kind=...}` pour observer en prod. **Gain** : qualité réaction agent en burst, pas de perte silencieuse de "tags" chat sous raid.

- [ ] **Picker poll non-blocking 200ms = 5 round-trips Redis/s à vide** — `backend/shugu/pipeline/picker.py:97-99` — `await self._queue.pop_ready()` (zpopmin) suivi de `await asyncio.sleep(0.2)` si vide. 5 ZPOPMIN/s × 1 picker × 24h = 432k commandes Redis/jour pour rien quand le stream est inactif. **Fix** : utiliser un `BLPOP`-like sur une LIST `shugu:queue:ready_signal` que les enqueueurs poussent en plus du `ZADD` (pattern wake-up : ready_signal est purement transitoire, le picker le drain et fait pop_ready). Ou plus simple : `asyncio.Event` poké par `enqueue_ready` côté in-process (mais nécessite RedisQueue → in-process trigger via pub/sub). **Gain** : -99% commandes Redis idle, latence pickup -50% (de ~100ms moyen à ~5ms).

- [ ] **`_bus_forward_loop` per-WS sans backpressure visible** — `backend/shugu/routes/visitor_ws.py:105`, `world_ws.py:232`, `operator_ws.py:123` — la queue subscribers du bus a `maxsize=256` (event_bus.py:37, event_bus_redis.py:144) : drop oldest si le client est lent (réseau saturé, browser frozen). Mais le drop est silencieux (pas de log par-client, juste `q.get_nowait/put_nowait`). En streaming TTS le client lent perd des chunks → audio glitch côté viewer, sans alerte côté serveur. **Fix** : (a) compteur `event_bus.dropped_total{topic=}` dans `InProcessEventBus.publish` quand QueueFull, (b) optionnellement fermer le WS du client lent après N drops consécutifs (typeof slow_consumer detection). **Gain** : observabilité production des slow clients, chemin de remédiation clair.

- [ ] **Visitor commands `_COMMAND_RE` + `_COMMAND_MAP` au scope module : OK, mais `_COMMAND_RE.match` puis dispatch O(1)** — `backend/shugu/routes/visitor_ws.py:33-46,239-243` — pattern correct (regex pré-compilée, dict O(1)). Le coût est `len(_COMMAND_MAP)`-bound sur le check d'existence (~8 entries) ; non-issue actuel mais à surveiller si le dict croît à >100 entries (passer alors par un set d'entries known). **Statut** : déjà optimisé, garde sous observation.

### Low impact / micro-optims

- [ ] **`asyncio.Lock()` global pour le fanout dispatch** — `backend/shugu/core/event_bus.py:17,23-25,37-47`, `event_bus_redis.py:79,144-158` — chaque `publish()` prend le lock pour copier `self._subs[topic]`, chaque `subscribe()`/teardown le prend aussi. Sous 100 viewers fréquemment connect/disconnect (mobile WS reconnect), le lock devient contended. La copy-under-lock + iter-out-of-lock est correcte ; le lock est juste utilisé pour la cohérence du dict de subs. **Fix** : `dict[str, tuple[asyncio.Queue, ...]]` + remplacement atomique (CoW pattern) — un publish peut alors itérer le tuple lock-free ; subscribe/unsubscribe paye un O(N) mais c'est rare. **Gain** : -1µs par publish à scale, négligeable mais propre.

- [ ] **`InProcessEventBus.subscriber_count` sous lock** — `backend/shugu/core/event_bus.py:49-51` — appelé hors du hot path mais avec lock + `len()` ; si jamais une métrique Prometheus l'appelle régulièrement, contention possible. Trivial à refactor en lecture lock-free (la dict est read-mostly). **Statut** : à fixer si jamais utilisé en hot path métrique.

- [ ] **`json.dumps` du snapshot world initial à chaque connexion world_ws** — `backend/shugu/routes/world_ws.py:147-155` — `_state_to_snapshot_dict(state)` + `json.dumps(snapshot)` exécuté pour chaque viewer à chaque connexion. Le world_state ne change pas entre deux connexions rapprochées : un client reload Ctrl+R = nouveau snapshot recalculé. **Fix** : cache du snapshot sérialisé invalidé sur `WorldStateStore.apply()` (ajouter un compteur de version + cache `(version, str)`). **Gain** : -50µs par reconnexion sous burst de reconnect (raid de bots).

## Complexité algorithmique

- `InProcessEventBus.publish`: O(N) où N = #subscribers du topic. Acceptable mais voir hotspot #2 pour le coût constant.
- `AmbientDaemon._weighted_pick`: O(K) avec K=11 actions hardcoded — non-issue.
- `WorldStateStore.apply`: O(F) où F = #fields WorldState (5) — non-issue.
- `Picker._broadcast_streaming`: O(C) where C=#chunks streamés × 2 (1 publish + 1 base64) — l'overhead réel est CPU base64 + json.dumps × N viewers (cf. hotspot #2).
- `MemoryAgent.recall` cosine search: O(log V) côté pgvector HNSW — OK tant que l'index est présent, sinon O(V) full scan — dépend de la migration (à vérifier dans `alembic/`).

## Database optimizations

Non analysées en profondeur ici (hors scope perf hot path), mais signaux à confirmer Pass 3 :

- `MemoryFact` : index sur `(subject, compacted_at, is_compacted_summary)` pour les filtres de `list_subjects_above_threshold` et `list_active_facts` (`memory/agent.py:520-558`).
- `MemoryEpisodeRow` : index `(subject, ts DESC, archived)` pour `recall_episodes` (`memory/agent.py:445-458`).
- `Performance` insert : pas d'index visible dans les checks ; OK si table append-only sans recall (à vérifier).
- pgvector HNSW : confirmer `hnsw.ef_search` runtime sur les workloads cosine, sinon full scan.

## Implementation Priority (impact / effort)

1. **DB pool sizing** (effort: 5min, impact: critique) — finding #1.
2. **JSON pre-serialize fanout** (effort: 1-2h, impact: critique sous burst audio) — finding #2.
3. **Sense queue policy** (effort: 30min, impact: qualité agent sous raid) — finding #6.
4. **Picker BLPOP wake-up** (effort: 1h, impact: cost Redis idle) — finding #7.
5. **Bound `_history_per_session`** (effort: 30min, impact: leak slow) — finding #3.
6. **Bound `_last_command_ts`** (effort: 15min, impact: leak slow + UX) — finding #4.
7. **Picker archive semaphore** (effort: 30min, impact: cascade DB) — finding #5.
8. **Drop counter visibility** (effort: 30min, impact: observabilité) — finding #8.

## Notes méthodologiques

- Pas de `time.sleep` ni `requests.` ni `open()` sync découverts dans les hot paths async (le seul `path.open("rb")` est dans `adapters/hermes_state.py` et est correctement wrappé en `asyncio.to_thread`, ligne 123).
- Toutes les regex sont pré-compilées au scope module (vérifié — pas de `re.compile()` dans des handlers).
- Les tasks `create_task` sont systématiquement référencées (set + done_callback discard) dans picker, operator_ws, voice_duplex, scene_player. Pas de leak de coroutine.
- `WorldStateStore.apply` est correctement sérialisé via `asyncio.Lock` ; le pattern shield contre cancellation est correct (review #49).
- L'Embedder fastembed est correctement wrappé en `asyncio.to_thread` (memory/embedder.py:127,138).
- Pas de N+1 SQLAlchemy détecté dans les chemins critiques (les recall/list utilisent SELECT ... WHERE IN(...) ou un seul SELECT par appel ; pas de boucle await execute).
- Le director Orchestrator `tick()` a un rate-limit 2s + cap horaire — bon design anti-burst LLM.
- Pas de DB query dans les WS message handlers (visitor/operator/world/editor) — les inserts se font dans les workers downstream via la queue Redis.
