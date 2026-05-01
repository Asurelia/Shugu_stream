# Pass 2 — Silent failures (Backend Python)

**Date** : 2026-05-01
**Commit audité** : branche `feat/phase8-2-observability-20260430-220425-001`
**Périmètre** : `backend/shugu/{adapters,pipeline,agent,routes,director,memory,core,scene_composer,senses,world,persona}`
**Méthode** : grep ciblé sur 6 anti-patterns + revue manuelle de chaque hit

---

## Résumé : 22 occurrences priorisées

**Inventaire brut** (ce que les regex ont trouvé) :

| Anti-pattern | Hits |
|---|---|
| `except …: pass` (toutes formes, pas que `except Exception`) | **18** |
| `except Exception: log…(); return None/""/{}/False` | **21** |
| `with suppress(Exception)` | **6** |
| `except: log; return ""` (caller ne sait pas si "" = vide légitime ou crash) | **5** |
| Bare `except:` (sans type) | **0 ✓** |
| `except BaseException` | **0 ✓** |

Bandit B110 a flaggé **5 / 18** `except: pass` — il rate les 13 autres car ils sont
typés (`except (OSError, …)`) ou s'appliquent à des exceptions précises. Les 13
restants ne sont pas tous des bugs : la plupart sont des cancellations légitimes,
mais **3** sont vraiment problématiques. Voir Cat. A.

**TL;DR du jugement** :
- **3 findings Catégorie A** — vrais bugs cachés (devraient crash ou faire remonter).
- **11 findings Catégorie B** — erreurs loggées mais pas tracées Sentry, retours silencieux qui rendent le debug impossible.
- **8 findings Catégorie C** — fallbacks légitimes mais à documenter / instrumenter.

---

## Catégorie A — Erreur qui devrait crash (ou minimum bubble up)

### A1. `routes/operator_voice_ws.py:155-158` — Send WS swallow sans visibilité opérateur

```python
async def send_event(ev: VoiceEvent) -> None:
    async with send_lock:
        try:
            await ws.send_text(json.dumps(...))
        except Exception:
            pass    # ← rien, pas même un log
```

**Problème** : c'est le SEUL `except: pass` du backend qui n'a même pas de log
(comparé à `editor_ws._safe_send_json` qui log au moins en debug). Si l'opérateur
parle pendant 30 minutes avec un WS half-broken, on rate **tous** les events
`voice.state.change` sans aucune trace.

**Hidden errors** : `RuntimeError("WebSocket is not connected")`, `ConnectionResetError`,
mais aussi `TypeError: ev.payload not serializable`, `OverflowError`, etc.

**Fix** : aligner sur `editor_ws._safe_send_json` — `log.debug("voice.send_failed", error=str(exc))`.

---

### A2. `pipeline/extraction_worker.py:191` & `pipeline/ingestion_worker.py:147` — `except (CancelledError, Exception): pass` au stop()

```python
self._task.cancel()
try:
    await self._task
except (asyncio.CancelledError, Exception):
    pass
```

**Problème** : la classe `Exception` capture **tout** (incluant les bugs d'`asyncio.shield`,
des `RuntimeError("Event loop is closed")`, des `MemoryError`). Si un worker crash
en finalisation (ex: corruption pgvector, deadlock SQLAlchemy), le `stop()`
prétend avoir réussi → l'app continue son lifespan en pensant tout est clean
alors que la mémoire L2 est dans un état corrompu.

**Hidden errors** : `MemoryError`, `RuntimeError("cannot reuse session after rollback")`,
exceptions de `SQLAlchemyError` levées au moment du await final, bugs custom
des subscribers.

**Fix** :
```python
try:
    await self._task
except asyncio.CancelledError:
    pass  # cancel attendu
except Exception as exc:
    log.exception("ingestion_worker.stop_failed", error=str(exc))
```
(idem pour `extraction_worker`)

---

### A3. `scene_composer/player.py:170` — `except (CancelledError, Exception): pass` au stop_current()

```python
try:
    await task
except (asyncio.CancelledError, Exception):
    pass
log.info("scene_player.stopped scene_id=%s", current)  # ← log SUCCESS quoi qu'il arrive
```

**Problème** : même pattern qu'A2 mais ici on **log success** (`scene_player.stopped`)
quoi qu'il arrive. Si le tick de scene crash en finalisation (dispose un asset
manquant, division par zéro dans une keyframe), l'opérateur voit `stopped` dans
les logs mais le worker était broken. Plus tard, une nouvelle `start_play()`
pourra démarrer alors que des ressources fuient.

**Hidden errors** : exceptions des workers (`sound`, `light`, `move`) qui
remontent au lieu d'être loggées par leur propre handler.

**Fix** : split `except CancelledError` (silence) vs `except Exception as exc`
(log.exception + ne pas log "stopped").

---

## Catégorie B — Erreur loggée mais pas tracée (silent fallback / Sentry blind)

### B1. `adapters/stt_streaming.py:128-130` — `return ""` sur tout crash STT

```python
try:
    text = await asyncio.to_thread(_run)
except Exception as exc:
    log.exception("stt.transcribe_error", error=str(exc))
    return ""
return text
```

**Problème** : `""` est aussi le retour légitime quand l'audio est silencieux.
Le caller (voice_duplex:222) ne peut pas distinguer "rien dit" vs "Whisper a
crashé". Pire — les bugs faster-whisper comme CUDA OOM, un fichier modèle
corrompu ou un format PCM cassé sont silencieusement convertis en silence
côté visiteur. L'opérateur croit que son micro déconne.

**Fix** : `raise STTError("transcribe failed: ...") from exc` et que
`voice_duplex._turn_drive` distingue `STTError` (bug → message état d'erreur
au client) vs transcript vide (silence audio normal).

---

### B2. `adapters/stt_livekit_adapter.py:91-99` — Idem que B1, mais retourne un `SpeechEvent` vide

```python
text = ""
try:
    text = await self._whisper.transcribe_pcm16(...)
except Exception as exc:
    log.warning("stt_lk.transcribe_failed", error=str(exc))

return SpeechEvent(type=FINAL_TRANSCRIPT, alternatives=[SpeechData(text=text or "", ...)])
```

**Problème** : on émet un `FINAL_TRANSCRIPT` vide après crash. LiveKit le
considère comme un transcript valide. Aucun way pour l'app de distinguer
"je n'ai rien entendu" vs "Whisper s'est planté".

**Fix** : ne pas émettre de SpeechEvent du tout en cas de crash, ou émettre
un type distinct `transcribe_error`.

---

### B3. `adapters/hermes_state.py:282-284` — `cron.json` corrompu = liste vide silencieuse

```python
try:
    data = json.loads(self._safe_read_text(cron_file, ...) or "null")
    if isinstance(data, dict) and "jobs" in data:
        return {"jobs": data["jobs"][:40], ...}
    if isinstance(data, list):
        return {"jobs": data[:40], ...}
except (OSError, json.JSONDecodeError):
    pass
return {"jobs": [], "count": 0}
```

**Problème** : `cron.json` corrompu (JSON cassé) **et** "fichier existe mais
n'est ni dict ni list" tombent sur le même retour vide silencieux. L'admin
qui regarde `/hermes/state` voit "0 cron jobs" et croit que c'est legit alors
qu'on a un parse error.

**Fix** : log.warning("hermes_state.cron_parse_failed", ...) avant le `pass`,
et idéalement renvoyer `{"jobs": [], "error": "parse failed"}` pour que
le frontend différencie.

---

### B4. `adapters/hermes_state.py:166-168` — `available=False` masque la nature de l'erreur

```python
except Exception as exc:
    log.warning("hermes_state.read_error", tab=tab, error=str(exc))
    return HermesSnapshot(tab=tab, available=False, error=str(exc))
```

**Problème** : pas un bug per se (l'erreur est dans le payload), mais
`except Exception` est trop large. Un bug de typo dans `_read_overview()`
(AttributeError) sera loggé identique à un fichier manquant (FileNotFoundError).
L'opérateur ne peut pas savoir s'il faut redéployer ou créer un fichier.

**Fix** : split `except (OSError, json.JSONDecodeError) as exc:` (= file
issues, swallow) vs `except Exception as exc: log.exception(...); raise`
(= bug code, propage en 500).

---

### B5. `adapters/brain_hermes_tools.py:109-111` — LLM crash retourne `""`

```python
try:
    assistant_msg = await self._call_llm(messages)
except BrainError as exc:
    log.warning("hermes.llm_failed", error=str(exc))
    return ""
```

**Problème** : Hermes retourne `""` au caller. Le caller
(`pipeline/hermes_task.py:85`) wrap déjà ça, mais ici dans `run_once()` (cf.
`operator_voice_ws.py:171`) un `""` retourné = "Hermes répond rien" mais
l'opérateur ne sait pas que sa clé OpenAI vient d'expirer.

**Fix** : re-raise `BrainError` — laisser le caller décider (il peut wrapper
en TTS d'erreur "le cerveau a un souci"). Le `log.warning` ne suffit pas.

---

### B6. `adapters/brain_hermes_tools.py:197-199` — Tool rejected = `{"ok": False}` muet

```python
try:
    call = await parse_call_async(name, args, registry=get_registry())
except Exception as exc:
    log.warning("hermes.tool_rejected", name=name, args=args, error=str(exc))
    return {"ok": False, "error": f"rejected: {exc}"}
```

**Problème** : `except Exception` capture **TOUT** dans `parse_call_async` —
incluant les bugs du registry lui-même (ex: handler crashé pendant un import
lazy), pas seulement les rejections de validation. Le LLM va voir `{"ok": False,
"error": "rejected: ..."}` et croire qu'il a mal formulé l'args, alors que
c'est un bug de runtime du backend.

**Hidden errors** : `ImportError` sur lazy load, `RuntimeError("loop closed")`,
`KeyError` sur registry.

**Fix** : narrow le catch à `(ValidationError, ParseError, ToolUnknownError)`,
et `raise` sur le reste (un `log.exception` + 500 vaut mieux qu'un faux
"rejected" qui pollue le contexte LLM).

---

### B7. `adapters/moderation_basic.py:95-97` — Ban check crash = "allowed"

```python
try:
    async with session_scope() as session:
        row = ... # check Postgres ban table
    if row is not None and row > now:
        return ModerationVerdict(allowed=False, ...)
except Exception as exc:
    log.warning("moderation.ban_check_failed", error=str(exc))
return ModerationVerdict(allowed=True)   # ← FAIL OPEN
```

**Problème** : SI Postgres est down, on **fail open** silencieusement →
les bans ne sont plus enforced. L'opérateur ne saura pas que son ban policy
ne fonctionne plus. Aussi `except Exception` capte les `IntegrityError` de
SQLAlchemy = vrais bugs.

**Fix** : selon politique sécu — soit fail-closed (raise → user reçoit
"service indisponible"), soit warn + métrique Prometheus dédiée
`moderation_fail_open_total`. Loguer `log.error` pas `warning` (c'est un
incident, pas un avertissement).

---

### B8. `pipeline/voice_duplex.py:220-222` — STT crash → `text = ""`

```python
try:
    text = (await self._stt.transcribe_pcm16(pcm)).strip()
except asyncio.CancelledError:
    raise
except Exception as exc:
    log.warning("voice.stt_failed", error=str(exc))
    text = ""

if not text:
    log.info("voice.empty_transcript")  # ← MÊME path que silence légitime
    await self._set_state_async(VoiceState.IDLE)
    return
```

**Problème** : crash STT → opérateur voit "voice.empty_transcript", pense
que son micro n'a rien capté, retente, recrash. Aucun feedback à l'opérateur
que la STT est broken. C'est exactement le "fallback à valeur par défaut
qui cache un crash" mentionné dans le brief.

**Fix** : envoyer un `VoiceEvent("error", {"reason": "stt_failed"})` au client
WS avant le `return`. L'opérateur voit "STT en panne, retry…" plutôt qu'un
silence apparent.

---

### B9. `routes/auth.py:131` & `routes/account.py:443` — Logout swallow `AuthError`

```python
for token, ttype in (...):
    if not token:
        continue
    try:
        payload = await jwt_tokens.verify(...)
        remaining = max(payload.exp - int(time.time()), 60)
        await jwt_tokens.revoke(payload.jti, ttl_s=remaining, redis=redis)
    except AuthError:
        pass
_clear_cookies(response)
return {"ok": True}
```

**Problème** : si le `verify()` échoue pour une **autre** raison qu'un token
expiré (ex: `RedisConnectionError` qui hérite de AuthError dans certains
codepaths, ou bug dans la signature secret rotation), on ne revoque pas le
JTI mais on retourne `{"ok": True}`. L'utilisateur croit être logout alors
que son refresh token reste valide jusqu'à expiration naturelle.

**Fix** : log au moins `log.info("auth.logout_skip_revoke", reason=...)`
pour avoir une trace en cas d'incident. Ou mieux : matcher uniquement
`(AuthError.TokenExpired, AuthError.InvalidSignature)` — les vrais cas
"token déjà invalide", pas tout `AuthError`.

---

### B10. `pipeline/picker.py:172-173` — `except TimeoutError: pass` sans log

```python
try:
    await asyncio.wait_for(
        self._interrupt_event.wait(), timeout=wait_ms / 1000.0,
    )
except asyncio.TimeoutError:
    pass
```

**Problème** : ici c'est **OK** sémantiquement (le timeout = "personne n'a
interrompu, on continue"). Mais si quelqu'un refactore plus tard et qu'une
autre exception remonte `TimeoutError` (ex: un `aiohttp.ClientTimeout` qui
hérite), elle sera silently swallowed. Defensive coding suggère d'isoler
le scope de ce `pass`.

**Fix** : pas critique, mais commentaire explicite + `# noqa: BLE001` pour
documenter l'intention. Acceptable en l'état si bien commenté.

---

### B11. `pipeline/picker.py:190-191` — `performance.truncate` publish failure swallow

```python
except asyncio.CancelledError:
    if not end_published:
        try:
            await self._event_bus.publish("stage", {
                "type": "performance.truncate", ...
            })
        except Exception:
            pass
    raise
```

**Problème** : si la dernière chance de notifier le client (`performance.truncate`)
échoue, on l'ignore complètement. Le frontend reste bloqué sur `speaking=true`
pour toujours. C'est exactement le bug que le commentaire ligne 195 dit qu'il
faut éviter.

**Fix** : `except Exception as pub_exc: log.error("picker.cancel_truncate_failed",
perf_id=perf_id, error=str(pub_exc))` — au moins on saura POURQUOI un client
est resté stuck.

---

## Catégorie C — Fallback légitime mais à documenter / instrumenter

### C1. `adapters/tts_fallback.py:52-54` — Primary TTS fail → fallback secondary

```python
async def synthesize(self, text, *, voice_id):
    try:
        return await self._primary.synthesize(...)
    except TTSError as exc:
        log.warning("tts.primary_failed_fallback", error=str(exc))
        return await self._secondary.synthesize(...)
```

**Verdict** : **légitime** — c'est tout l'objet de ce module. Mais :
- Pas de métrique Prometheus `tts_fallback_total` (à ajouter pour alerter
  si MiniMax claque souvent).
- Si **secondary** crash aussi, l'erreur remonte brute en `TTSError`. OK
  mais vérifier que les callers (workers, picker) la gèrent.
- À documenter explicitement dans les contrats : "ce service peut substituer
  silencieusement la voix" — sinon l'opérateur croit entendre ElevenLabs alors
  qu'on lui sert Edge-TTS.

---

### C2. `adapters/brain_hermes_tools.py:96-98` — Persona fallback `hermes_public` → `shugu`

```python
try:
    persona = self._personality.get("hermes_public")
except Exception:  # pragma: no cover — fresh install without the file
    log.warning("hermes.persona_fallback_to_shugu")
    persona = self._personality.get("shugu")
```

**Verdict** : `pragma: no cover` indique que c'est un fallback "fresh install".
**Mais `except Exception` est trop large** — un bug futur dans `personality.get`
(parser YAML cassé) ferait tomber sur le shugu persona sans que l'opérateur
sache. Et `get("shugu")` peut **lui aussi** lever — alors on aurait une
exception non-typée.

**Fix** : narrow à `KeyError` / `FileNotFoundError`. Ajouter une métrique.

---

### C3. `pipeline/hermes_task.py:79-80` — Ack TTS fail = silent, le user croit Hermes ignore

```python
try:
    ack_tts = await tts.synthesize(ack_phrase, voice_id="")
    ack_msg = QueuedMessage(...)
    await queue.enqueue_ready(ack_msg)
except TTSError as exc:
    log.warning("hermes_task.ack_tts_failed", error=str(exc))
    # Pas de fallback texte → silence côté visiteur
```

**Verdict** : légitime que ça ne crash pas (l'ack est cosmétique), mais le
visiteur n'a aucun feedback que sa requête est en cours. Si la suite (étape 2,
3, 4) prend 8s, il pense que c'est cassé.

**Fix** : émettre un `performance.text_only` (sans audio) avec le texte d'ack —
au moins le UI montre "Hermes réfléchit…" en plain text.

---

### C4. `core/event_bus.py:30-34` — Drop oldest sur queue pleine, sans métrique

```python
except asyncio.QueueFull:
    try:
        q.get_nowait()
        q.put_nowait(event)
    except asyncio.QueueEmpty:
        pass
```

**Verdict** : légitime (drop-oldest documenté). **Mais aucun compteur**.
Un slow consumer qui fait perdre 50% des events sur le bus est invisible.

**Fix** : `recorder.record_bus_drop(topic)` à côté du `q.get_nowait()`.

---

### C5. `core/event_bus_redis.py:241-244` — `with suppress(Exception)` au cleanup

```python
finally:
    self._reader_ready.clear()
    with suppress(Exception):
        await pubsub.unsubscribe()
    with suppress(Exception):
        await pubsub.aclose()
```

**Verdict** : légitime au cleanup d'un Redis pubsub déjà mort, mais
`suppress(Exception)` masque tout. Si `aclose()` lève `RuntimeError("loop
already running")`, on a un bug de concurrence qu'on ne verra jamais.

**Fix** : narrow à `(redis.ConnectionError, redis.RedisError, OSError,
asyncio.CancelledError)`. Loguer en debug le reste.

---

### C6. `director/orchestrator.py:331-335` — Memory recall fail = facts vides

```python
try:
    recalled = await self._memory_agent.recall(RecallQuery(...))
    memory_facts = [item.text for item in recalled if item.text]
except Exception as exc:
    log.warning("director.orchestrator_memory_recall_failed",
                extra={"sender": sender, "error": repr(exc)})
```

**Verdict** : légitime que le director continue sans memory facts (le LLM
peut générer un tick sans). Mais `except Exception` masque les bugs du
memory agent (deadlock pgvector, embedder OOM). Un dégât silencieux du
système de mémoire = qualité agent dégradée invisible.

**Fix** : narrow à `(MemoryError, RecallError)` si les types existent
(sinon les créer). Ajouter compteur Prometheus.

---

### C7. `persona/loader.py:60-66` — Persona doc fail → neutral fallback

```python
try:
    doc = await memory.persona_get()
except Exception as exc:
    log.warning("persona_loader.load_failed",
                error=repr(exc), fallback="neutral_default")
    doc = {}
```

**Verdict** : commenté correctement, mais un PersonaState neutre permanent
à cause d'un bug DB persistera à chaque boot, jamais corrigé.

**Fix** : déjà ok pour fallback transitoire, mais ajouter une **alerte**
Prometheus (`persona_load_failures_total`) — au-delà de N échecs, c'est
plus un fallback c'est un crash.

---

### C8. `agent/runner.py:387-393` — Tick LLM fail = drop senses silencieusement

```python
try:
    thought, _final_world = await self._loop.tick(perception)
except Exception as exc:
    log.warning("agent_runner.tick_failed senses=%d error=%r",
                len(senses), exc)
    return None
```

**Verdict** : commenté ligne 33 ("une exception LLM sur un tick n'affecte pas
les ticks suivants"). Mais les senses du tick sont **perdus** sans replay.
Un bug LLM persistant = l'agent "voit rien" sans qu'on s'en rende compte
côté metrics.

**Fix** : compteur Prometheus `agent_tick_failures_total{kind=...}`. Si on
a 100% de fails sur 1 minute, alerter. Le code lui-même est OK.

---

## Conclusion

Le backend Python est **objectivement bien fait** : 0 bare-except, 0
`except BaseException`, presque tous les `except Exception` ont au moins
un log structlog avec contexte (`error=str(exc)`, identifiers).

Les **vrais risques restants** sont :
1. **Catégorie A** : 3 `except (CancelledError, Exception): pass` qui
   doivent être splittés (player.py:170, extraction_worker.py:191,
   ingestion_worker.py:147) + un `except: pass` sans log (operator_voice_ws.py:157).
2. **Catégorie B** : la "mer de `log.warning + return ""`" qui rend la
   distinction "résultat vide légitime" vs "crash interne" impossible
   — particulièrement critique dans la chaîne **STT → voice_duplex →
   Hermes → operator UX**, où un crash backend devient un silence
   apparent côté opérateur.
3. **Catégorie C** : tous les fallbacks légitimes manquent de **métriques
   Prometheus dédiées**. Phase 8.2 vient d'ajouter le squelette
   observability — c'est le moment d'instrumenter les fallbacks (TTS,
   memory, persona, bus drop, agent tick) avec des compteurs explicites
   pour qu'un dégât silencieux devienne une alerte.

**Aucune des Catégories A/B ne nécessite de refactoring lourd** — ce sont
des fixes ciblés (3-5 lignes par site) en suivant les patterns déjà
en place dans le code (`log.exception` + raise spécialisé).
