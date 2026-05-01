# Pass 2 — Type design

Périmètre : `backend/shugu/{core,agent,senses,policy,world}` + auth/db/memory en
support. Mypy a déjà signalé 64 erreurs (`02-mypy.txt`) — ce rapport cible
exclusivement les *patterns qualitatifs* qui passent sous le radar de mypy mais
laissent passer des bugs réels.

## Résumé : 13 suggestions (8 high, 4 medium, 1 low)

## Findings par bénéfice / coût

### High value (gros gains, peu de coût)

- [ ] **Deux `Mood` Literal incompatibles, même nom, même import surface** —
  `world/types.py:32` (`"neutral","happy","angry","sad","relaxed","surprised"`)
  vs `core/body_control.py:72` (`"cheerful","focused","sleepy","playful","bored"`).
  En plus `core/mood.py:18` définit `MoodState(str, Enum)` avec encore le même
  vocabulaire que `body_control`. **Trois "moods", trois vocabulaires, deux
  Literal homonymes**. mypy ne détecte rien : `from ..core.body_control import Mood`
  vs `from ..world.types import Mood` typecheckent tous deux mais représentent
  des domaines disjoints. Un handler ambient qui enverrait `MoodSetAction(mood="cheerful")`
  serait rejeté à runtime par `_VALID_MOODS` (handlers.py:48) sans aucune
  alerte au build. Refacto : renommer en `WorldMood` / `AmbientMood` (ou
  `BodyMood`) + supprimer le Literal redondant côté `body_control` au profit
  d'un alias unique.

- [ ] **Deux `Emotion` Literal — sets divergents silencieux** —
  `core/protocols.py:26` (`["neutral","happy","angry","sad","relaxed"]`) et
  `core/body_control.py:71` (`["neutral","happy","sad","angry","relaxed"]`).
  Aujourd'hui les sets sont équivalents mais l'ordre diffère ; demain quelqu'un
  ajoute `"surprised"` côté `protocols` (cohérent avec Mood !) et oublie
  `body_control`. mypy reste muet, le BrainAdapter accepte une emotion que
  Pydantic rejettera plus tard. Refacto : un seul `Emotion` exporté depuis
  `core/protocols.py`, importé par `body_control`.

- [ ] **`WorldStoreLike.apply` perd le typage de l'action** —
  `agent/handlers.py:68` :
  `async def apply(self, action: object) -> object`. Le même Protocol existe
  en strict dans `agent/runner.py:140` :
  `async def apply(self, action: ActionUnion) -> WorldState`. Conséquence : les
  4 handlers (`handle_set_pose`, `handle_set_mood`, ...) appellent
  `await deps.world_store.apply(MoodSetAction(...))` sur un Protocol qui
  accepterait littéralement n'importe quoi (un `int`, un `dict`, un
  `MemberIdentity`). Si demain quelqu'un construit un `MoodSetAction` avec un
  champ renommé/disparu, le handler typecheck encore. Fix one-line : importer
  `ActionUnion`/`WorldState` (déjà allowlistés en L0 D4) et resserrer la
  signature.

- [ ] **Identités privilégiées constructibles vides — claim sécurité fausse** —
  `core/identity.py` documente *« Le type-system empêche un code visitor-path
  de forger une identité privilégiée »*. Or `OperatorIdentity()`,
  `MemberIdentity()`, `VIPIdentity()` ont **tous leurs champs avec defaults
  vides** (`user_id: str = ""`, `jti: str = ""`, etc.). N'importe quelle route
  peut construire `OperatorIdentity()` (zéro auth franchie) et le passer à un
  brain — `frozen=True` empêche la mutation, pas la construction. Les tests
  exploitent déjà ça (`VisitorIdentity()` 13 fois) ; le pattern est trivial à
  copier ailleurs. Refacto : retirer les defaults des champs load-bearing
  (`user_id`, `jti` au minimum) → la construction sans passer par les
  dépendances FastAPI devient un `TypeError` au moment de l'appel.

- [ ] **`ToolCall.params: dict[str, object]` mutable malgré `frozen=True`** —
  `agent/tool_call_parser.py:75`. Le pattern *frozen-mais-dict-mutable* a
  été corrigé partout ailleurs (`Tool.params_schema`, `SenseEvent.payload`,
  `PolicyMatrix.entries`) avec `MappingProxyType` + shallow-copy en
  `__post_init__`. Celui-ci a été oublié. Risque : un handler qui mute
  `tool_call.params["text"] = sanitized` modifie le ToolCall observé par les
  metrics + logs en aval → l'audit log diverge de ce qui a été dispatché. Le
  fix copie/colle existe déjà dans `Tool` ligne 71-79.

- [ ] **`subject: str` namespacé non typé — load-bearing privacy** — Convention
  documentée mais non enforcée : `"visitor:<ip_hash>"`, `"vip:<username>"`,
  `"shugu"`, `"operator"`. Utilisée comme **clé de scoping privacy/recall** dans
  `senses/types.py:49`, `memory/types.py:51,70`, `memory/models.py:189`,
  `core/protocols.py:188`, `persona/state.py:74`. Un bug qui passerait
  `username` brut au lieu de `f"vip:{username}"` mélangerait les namespaces
  recall (un viewer accède aux facts d'un autre) et mypy ne verrait rien —
  les deux sont `str`. Refacto pragmatique : `Subject = NewType("Subject", str)`
  + une fabrique `Subject.visitor(ip_hash)`, `Subject.vip(username)`. Coût
  faible, blast radius (mauvais scoping mémoire) sévère.

- [ ] **`MemoryItem.confidence: float` et `embedding: list[float]` —
  invariants documentés, jamais enforced** — `memory/types.py:53,57` :
  docstring dit `confidence ∈ [0, 1]` et `len(embedding) == MEMORY_EMBED_DIM`.
  Aucune validation au constructeur (dataclass simple). Source = code amont
  (extractors, embedders) qui peut bug silencieusement → on persiste des
  rows DB invalides (`Vector(1024)` accepte un `list[float]` de la mauvaise
  taille uniquement à l'INSERT, par crash explicit). Fix : `__post_init__`
  qui clamp `confidence` à `[0,1]` ou raise, et asserte la dim si embedding
  fourni. C'est de la défense en profondeur côté DTO — le constraint DB ne
  protège pas le code en mémoire (decay-loop, ranker, etc.).

- [ ] **Handler reçoit `dict` non typé issu d'un parser regex** —
  `agent/tool_call_parser.py:139` produit
  `ToolCall(name=name, params=dict(_ATTR_RE.findall(...)))`. Tous les `params`
  sont des `str` (regex output). Mais dans `handlers.py:118,142,167,201` on
  fait `params.get("text", "")` puis `str(text).strip()` — la coercion
  défensive est partout parce qu'on n'a aucune garantie. Le LLM qui produit
  `<tool name="set_mood" mood=""/>` (vide) ou omet `mood` est traité pareil.
  Refacto à coût modéré : générer un `params: Mapping[str, str]` (figé) +
  pour les 4 handlers connus, parser via Pydantic `BodyMoodCall`/etc.
  (déjà existants dans `body_control.py`). Cela centralise les bornes
  (`min_length=1`, `enum`) au lieu de les répartir dans 4 handlers + un
  `_VALID_MOODS` séparé.

### Medium value

- [ ] **Pas de `NewType` pour les IDs load-bearing** — Bundle :
  `user_id`, `jti`, `session_id`, `ip_hash`, `prop_id`, `scene_id`, `slug`,
  `id` ULID, `subject` (cf. finding séparé). Tous typés `str` partout. Le
  bug typique : `OperatorIdentity(username="Spoukie", jti="Spoukie", ...)`
  passe — username et jti sont interchangeables côté types. Idem
  `PropSpawnAction(prop_id=scene_id, ...)`. Refacto pragmatique : ajouter
  3-4 `NewType` (UserId, SessionId, IpHash, Slug) dans un seul fichier
  `core/ids.py`, migrer progressivement les call-sites les plus risqués
  (auth, identity, prop/scene). Ne pas viser une couverture totale — viser
  les frontières où l'ordre des arguments est ambigu.

- [ ] **`SenseEvent.payload: Mapping[str, object]` — schéma per-kind absent** —
  `senses/types.py:50`. Le commentaire (ligne 11-14) reconnaît la dette :
  *« Une refonte vers un closed sum par kind est possible plus tard »*. Le
  prompt LLM (`llm_thinker.build_prompt`) sérialise `s.payload` brut dans le
  contexte LLM — un payload chat malformé (`{"texte": "..."}` au lieu de
  `{"text"}`) traverse silencieusement. Refacto ciblé : 4 dataclasses
  `ChatPayload`, `VoicePayload`, `EventPayload`, `VisionPayload` + un union
  discriminé sur `kind`. Garder `payload: Mapping` pour la sérialisation bus
  reste possible avec une factory `SenseEvent.from_chat(text, ...)` qui
  contraint au build. C'est l'endroit où le LLM consomme le plus de bruit
  silencieux.

- [ ] **`PersonalityDoc.style_hints: dict` — pas de `MappingProxyType`** —
  `core/protocols.py:79`. Pattern frozen-mais-dict identique à `Tool` &
  consorts. La dataclass elle-même n'est pas `frozen=True` → tous ses champs
  sont mutables (`doc.system_prompt = "<inject>"` accepté). Le PersonalityLoader
  cache les docs et les sert à de multiples brains : une mutation côté un
  consumer fuit sur tous les autres. Fix : `frozen=True, slots=True` +
  `__post_init__` proxy sur `style_hints`. Cohérent avec le reste du codebase.

- [ ] **`RegistryEntry.payload: dict` — frozen + nested mutable** —
  `core/registry.py:48`. `frozen=True` mais `payload` est un dict obtenu via
  shallow-copy (`dict(row.payload or {})` ligne 147). Si `row.payload`
  contient un sub-dict (typique JSONB), la mutation côté un consumer
  (`entry.payload["camera"]["angle"] = 90`) leak entre tous les lecteurs du
  cache TTL. Les listeners admin `bust()` ne voient pas la modification
  → état divergent entre nodes/process. Fix : deep-copy + MappingProxyType,
  ou pivot vers Pydantic `BaseModel` immuable.

### Low value (joli mais optionnel)

- [ ] **`BrainAdapter.respond` typée `-> AsyncIterator[BrainDelta]`, mais
  c'est un async generator** — `core/protocols.py:88`. Subtilité : un
  `async def f() -> AsyncIterator[X]` qui contient `yield` est mal typé
  (devrait être `AsyncGenerator[X, None]` ou utiliser `@asynccontextmanager`
  selon le pattern). mypy 1.x peut accepter mais pyright strict râle. Pas
  bug-générateur — seulement gêne pour les futurs adapters qui voudraient
  utiliser `asend`. Skipper sauf si un adapter le demande explicitement.

---

**Notes méthodo :**

Volontairement skippés (cosmétique pure ou couvert par mypy) :
- `dict[str, Any]` générique non scopé (trop large, le brief le demande
  scopé — fait via finding `SenseEvent.payload`).
- Les Optional sans guard (mypy `--strict` les attrape).
- `Callable[..., Any]` (mypy le verrait avec strict).
- Action variants non exhaustifs : déjà un `Union` propre + `match` —
  `reducers.apply` lève `TypeError` sur le wildcard.
