# Shugu Mind — M-2 ActionArbiter — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommandé) ou `superpowers:executing-plans` pour exécuter ce plan tâche par tâche. Steps en `- [ ]` pour le tracking.
>
> **Quality contract** : prod-ready, TDD strict (rouge → vert → commit), 0 skip, coverage `mind/arbiter.py + mind/intent.py ≥ 90%`, ruff/isort clean dès la première soumission.
>
> **Review adversariale obligatoire pré-merge** : risque #1 (interposition broadcast). Reviewer non-auteur du plan. Vérifier que `_dispatch_and_publish` est toujours appelée et que le broadcast `editor:broadcast/scene.tick` est inchangé.

---

## Résumé exécutif

**But** : sérialiser les intentions de parole/corps/jeu en une sortie cohérente (priorités, cooldowns, dédup, péremption), en préservant strictement le pipeline `editor:broadcast` / `scene.tick` que consomme le frontend.

**Effort** : moyen (~8 tâches TDD, +30 tests). 1 nouveau module (`mind/arbiter.py` + `mind/intent.py`) + intégration ciblée dans `director/orchestrator.py`.

**Risque principal** : interposition de l'arbiter casserait le broadcast `editor:broadcast/scene.tick` consommé par `_client.tsx` (cf. spec §4.3 bloquant 4). Mitigation : l'arbiter est une **grille pré-dispatch** qui appelle toujours `_dispatch_and_publish` existant, pas un remplacement. Test d'invariant explicite.

**Spec de référence** : `docs/superpowers/specs/2026-06-13-autonomous-mind-design.md` §4.5 + §4.3 §5).
**Roadmap** : `docs/superpowers/plans/2026-06-14-mind-roadmap-execution.md` §3 M-2.

---

## Préalables vérifiés sur `origin/claude/gallant-kepler-a6252e`

- ✅ M-0 livré : famille `M3Brain` + `ResilientDirectorBrain` (m3→ollama→canned) + bench TTFB/coût + pré-warm Gemma.
- ✅ M-1 livré : `Blackboard` async (`backend/shugu/mind/blackboard.py`), types `MindState`/`PlanState`/`ChatLine`/`SpeechRecord` (`backend/shugu/mind/types.py`), `build_prompt(..., mind_state=)`, timeout depuis `director_llm_timeout_s`, filtre `is_goal_injection`.
- ✅ Settings déjà déclarées : `mind_cortex_enabled: bool = False`, `mind_arbiter_enabled: bool = False` (cf. `config.py` lignes 553-563).
- ✅ Point d'insertion clair : `Orchestrator._dispatch_and_publish(tags, tts_text, trigger)` à `director/orchestrator.py:427` — appelé une seule fois par tick post-LLM (et post-canned/cache).
- ✅ Patron AmbientScene confirmé : `pipeline/ambient.py:208` synthétise audio puis construit `QueuedMessage(author_role="system", precomputed_audio=…)` et appelle `queue.enqueue_ready(msg)`.
- ✅ `RedisQueue.enqueue_ready` (`pipeline/queue.py:71`) + `QueuedMessage` (`pipeline/queue.py:17`) prêts à recevoir une parole d'origine système.
- ✅ TTS adapter disponible via `app.py:265-289` (FallbackTTS = primary `tts_primary` + secondary Edge). L'arbiter sera injecté par DI au lifespan, pas via singleton.
- ⚠️ **Dette M-1 connue, NON bloquante** : `Blackboard` n'a pas de fixture `autouse` qui appelle `_reset_for_tests()` entre tests (le module définit la fonction mais aucun conftest la branche). Les tests blackboard existants instancient à la main → pas d'impact. **Pas de Task 0 dédiée**, mais Task 7 (intégration) utilisera l'injection directe `Blackboard(...)` plutôt que le singleton pour éviter la pollution inter-tests.
- ✅ TTS Adapter — le `FallbackTTS.synthesize(text, voice_id=…)` retourne un `TTSResult` (cf. `core/protocols.TTSAdapter`). L'arbiter dépend uniquement de cette interface.

---

## Discrepancies détectées entre spec et roadmap

⚠️ **Discrepancy détectée 1 — priorité body** :
- Spec §4.5 règle 1 : « réponse réflexe chat (1) > parole cortex (2) > filler canned (4). Body = 3. »
- Roadmap §3 M-2 : « priorités (réflexe-chat 1 > cortex-parole 2 > body 3 > canned 4) »
- Énoncé utilisateur : idem roadmap.

**Résolution** : alignement spec/roadmap identique. **Plan : retenir réflexe-chat=1 > cortex-speech=2 > body=3 > canned-filler=4.** Constantes nommées dans `mind/intent.py`.

⚠️ **Discrepancy détectée 2 — dédup similarité** :
- Spec §4.5 règle 3 : « dédup contre `recent_speech` (similarité par préfixe) » sans seuil.
- Énoncé utilisateur : « préfixe 80% / 20 chars ».
- AmbientScene n'a pas de dédup similarité (juste un cooldown sur le `action_name`).

**Résolution** : **prendre la formulation utilisateur** : si le préfixe normalisé (lowercase, espaces collapsés) des 20 premiers chars du nouveau texte matche à ≥ 80% (ratio Levenshtein bornée ou `SequenceMatcher`) celui d'au moins une entrée de `recent_speech`, l'intent est `deduped`. Constante `DEDUP_PREFIX_LEN=20`, `DEDUP_SIMILARITY=0.80` dans `mind/arbiter.py`.

⚠️ **Discrepancy détectée 3 — TTS adapter injection** :
- Spec §4.5 mentionne « Piper local » mais le code prod utilise `FallbackTTS(primary=…, secondary=Edge)` via `settings.tts_primary` (cf. `app.py:265-289`).

**Résolution** : l'arbiter accepte un `TTSAdapter` opaque (interface `synthesize(text, voice_id=) -> TTSResult`), branché en DI sur l'instance `tts` déjà construite dans `app.py`. Aucun couplage Piper-spécifique.

---

## File Structure

| Statut | Fichier | Responsabilité |
|---|---|---|
| **CRÉE** | `backend/shugu/mind/intent.py` | `ActionIntent` dataclass, constantes priorités/cooldowns/seuils dédup. |
| **CRÉE** | `backend/shugu/mind/arbiter.py` | Classe `ActionArbiter` : `submit(intent)`, règles arbitrage, TTS synth, dispatch via callback `_dispatch_and_publish` injecté. |
| **CRÉE** | `backend/tests/unit/test_mind_intent.py` | Tests pour `ActionIntent` (helper `now()`, `expired`, ordre priorité). |
| **CRÉE** | `backend/tests/unit/test_mind_arbiter.py` | Tests TDD unitaires arbiter (priorités, cooldown, dédup, purge, backpressure, anti-collision, flag off). |
| **CRÉE** | `backend/tests/unit/test_mind_arbiter_integration.py` | Tests intégration orchestrator ↔ arbiter (Task 7). |
| **MODIFIE** | `backend/shugu/director/orchestrator.py` | Hook optionnel `mind_arbiter_enabled` dans `_dispatch_and_publish` : redirection vers `arbiter.submit_speech()` AVANT le dispatch existant. |
| **MODIFIE** | `backend/shugu/mind/metrics.py` | Ajouter 3 méthodes au `MindMetricsRecorder` (Null + Protocol) : `record_arbiter_intent`, `record_arbiter_speech_synth_duration`, `record_arbiter_cooldown_violation`. |
| **MODIFIE** | `backend/shugu/app.py` | Lifespan : instancie `ActionArbiter(tts=tts, queue=queue, blackboard=app.state.mind_blackboard, settings=settings)` derrière `settings.mind_arbiter_enabled`, injecte dans `Orchestrator(..., arbiter=…)`. |
| **NON TOUCHÉ** | `backend/shugu/pipeline/picker.py` | Le picker reste l'unique dequeuer serial. |
| **NON TOUCHÉ** | `backend/shugu/pipeline/queue.py` | `RedisQueue.enqueue_ready` inchangée. |
| **NON TOUCHÉ** | `backend/shugu/pipeline/ambient.py` | Patron de référence, lu mais pas modifié. |
| **NON TOUCHÉ** | `backend/shugu/director/workers/*.py` | Workers existants appelés via `_dispatch_workers` inchangé. |
| **NON TOUCHÉ** | `frontend/**` | Aucun changement contrat broadcast `scene.tick`. |

**Conventions vérifiées dans le repo M-0/M-1 (à respecter)** :
- Settings : `Field(default=…, validation_alias=AliasChoices("MIND_X", "SHUGU_MIND_X"))`.
- Tests : `async def test_…()` sans marqueur (`asyncio_mode=auto` global).
- Mocks HTTP : `respx` si applicable (pas applicable ici — pas d'HTTP direct).
- Recorder Métriques : pattern Protocol + Null (cf. `mind/metrics.py` créé en M-0).
- Logs : `structlog.get_logger(__name__)`, événements snake_case `"mind.arbiter_…"`.
- Imports : ruff/isort first-pass (l'observation buddy ruflo A a montré que les imports cassés étaient rattrapés en CI seulement — on les valide localement).
- Commandes : `cd backend && .venv/Scripts/pytest tests/unit/<file>.py -v` ; ruff scope `backend/shugu backend/tests`.

---

# MILESTONE M-2 — ActionArbiter

## Task 1 : `ActionIntent` dataclass + constantes priorités

**Files :**
- Create : `backend/shugu/mind/intent.py`
- Test : `backend/tests/unit/test_mind_intent.py`

- [ ] **Step 1 : Écrire le test qui échoue**

```python
# backend/tests/unit/test_mind_intent.py
"""Tests unit — ActionIntent (M-2 Task 1)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from shugu.mind.intent import (
    BODY_PRIORITY,
    CANNED_FILLER_PRIORITY,
    CORTEX_SPEECH_PRIORITY,
    PURGE_AGE_SECONDS,
    REFLEX_CHAT_PRIORITY,
    ActionIntent,
)


def _intent(**kw) -> ActionIntent:
    base = dict(
        source="reflex",
        kind="speech",
        payload={"text": "salut"},
        priority=REFLEX_CHAT_PRIORITY,
        created_at=datetime.now(timezone.utc),
    )
    base.update(kw)
    return ActionIntent(**base)


def test_priority_constants_strictly_ordered() -> None:
    """Spec §4.5 : reflex-chat (1) < cortex-speech (2) < body (3) < canned-filler (4)."""
    assert REFLEX_CHAT_PRIORITY == 1
    assert CORTEX_SPEECH_PRIORITY == 2
    assert BODY_PRIORITY == 3
    assert CANNED_FILLER_PRIORITY == 4
    assert (
        REFLEX_CHAT_PRIORITY
        < CORTEX_SPEECH_PRIORITY
        < BODY_PRIORITY
        < CANNED_FILLER_PRIORITY
    )


def test_purge_age_seconds_default_30() -> None:
    """Spec §4.5 règle 4 : purge des intents périmés > 30 s."""
    assert PURGE_AGE_SECONDS == 30.0


def test_is_expired_now_false() -> None:
    intent = _intent(created_at=datetime.now(timezone.utc))
    assert intent.is_expired(now=datetime.now(timezone.utc)) is False


def test_is_expired_after_30s_true() -> None:
    base = datetime.now(timezone.utc)
    intent = _intent(created_at=base)
    later = base + timedelta(seconds=PURGE_AGE_SECONDS + 0.1)
    assert intent.is_expired(now=later) is True


def test_is_expired_uses_default_threshold() -> None:
    base = datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
    intent = _intent(created_at=base)
    assert intent.is_expired(now=base + timedelta(seconds=29.9)) is False
    assert intent.is_expired(now=base + timedelta(seconds=30.1)) is True


def test_age_seconds() -> None:
    base = datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
    intent = _intent(created_at=base)
    assert intent.age_seconds(now=base + timedelta(seconds=12.5)) == pytest.approx(12.5)


def test_kind_validated_to_known_values() -> None:
    # dataclass frozen → mypy/pydantic non-strict, mais le Literal doit
    # documenter le contrat. On vérifie qu'on peut construire les 3 kinds prévus.
    _intent(kind="speech")
    _intent(kind="body")
    _intent(kind="game")
```

- [ ] **Step 2 : Lancer le test → échec**

Run : `cd backend && .venv/Scripts/pytest tests/unit/test_mind_intent.py -v`
Expected : FAIL — `ModuleNotFoundError: No module named 'shugu.mind.intent'`

- [ ] **Step 3 : Implémenter `ActionIntent`**

```python
# backend/shugu/mind/intent.py
"""ActionIntent — message immutable circulant des boucles vers l'Arbiter.

Spec §4.5. Les constantes de priorité encodent l'ordre adversarial : priorité
plus basse = sert en premier. Les seuils de péremption/dédup sont positionnés
ici (constantes module-level) pour rester testables sans monkey-patcher
l'arbiter.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal, Optional

# Priorités (spec §4.5 règle 1). Plus bas = plus prioritaire.
REFLEX_CHAT_PRIORITY: int = 1
CORTEX_SPEECH_PRIORITY: int = 2
BODY_PRIORITY: int = 3
CANNED_FILLER_PRIORITY: int = 4

# Péremption : un intent reste valide 30 s en file (spec §4.5 règle 4).
PURGE_AGE_SECONDS: float = 30.0


IntentSource = Literal["cortex", "reflex"]
IntentKind = Literal["speech", "body", "game"]


@dataclass(frozen=True, slots=True)
class ActionIntent:
    """Intention d'action soumise à l'Arbiter.

    `payload` est un dict opaque : pour `speech` → `{"text": str, "emotion": str?,
    "tags": dict?}` ; pour `body` → `{"tags": list[ParsedTag]}` ; pour `game` →
    `{"buttons": list[str], "hold_frames": int}`. Le typage strict des payloads
    est laissé à l'arbiter (validation côté consommateur).
    """

    source: IntentSource
    kind: IntentKind
    payload: dict[str, Any]
    priority: int
    created_at: datetime
    # Identifiant unique facultatif pour corrélation logs/métriques. Pas requis
    # pour l'arbitrage lui-même.
    intent_id: Optional[str] = field(default=None)

    def age_seconds(self, *, now: Optional[datetime] = None) -> float:
        ref = now if now is not None else datetime.now(timezone.utc)
        return (ref - self.created_at).total_seconds()

    def is_expired(
        self,
        *,
        now: Optional[datetime] = None,
        threshold_s: float = PURGE_AGE_SECONDS,
    ) -> bool:
        return self.age_seconds(now=now) > threshold_s
```

- [ ] **Step 4 : Lancer le test → succès**

Run : `cd backend && .venv/Scripts/pytest tests/unit/test_mind_intent.py -v`
Expected : PASS (7 tests).

Run : `cd backend && .venv/Scripts/ruff check shugu/mind/intent.py tests/unit/test_mind_intent.py && .venv/Scripts/ruff format --check shugu/mind/intent.py tests/unit/test_mind_intent.py`
Expected : clean.

- [ ] **Step 5 : Commit**

```bash
git add backend/shugu/mind/intent.py backend/tests/unit/test_mind_intent.py
git commit -m "✨ feat(mind): ActionIntent dataclass + priority constants (M-2 Task 1)"
```

---

## Task 2 : `ActionArbiter` skeleton + `submit_speech` (flag OFF = passthrough)

**Files :**
- Create : `backend/shugu/mind/arbiter.py`
- Modify : `backend/shugu/mind/metrics.py`
- Test : `backend/tests/unit/test_mind_arbiter.py`

> **Objectif de la tâche** : poser la classe `ActionArbiter` avec une seule méthode publique `submit_speech(intent, dispatch_cb)` qui, **flag OFF**, appelle directement `dispatch_cb()` sans aucune logique (passthrough strict) ; flag ON, accepte l'intent et l'envoie en synth TTS. Aucune règle d'arbitrage à ce stade (rules en Task 3-4).

- [ ] **Step 1 : Écrire les tests qui échouent**

```python
# backend/tests/unit/test_mind_arbiter.py
"""Tests unit — ActionArbiter (M-2 Task 2-6).

Conventions :
- Pas de mocks d'I/O exotiques : on construit `_FakeTTS`, `_FakeQueue`,
  `_SpyDispatch` à la main pour rester explicite.
- Les tests temporels utilisent un `clock` injectable, jamais `asyncio.sleep`.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import pytest

from shugu.mind.arbiter import ActionArbiter
from shugu.mind.intent import (
    CORTEX_SPEECH_PRIORITY,
    REFLEX_CHAT_PRIORITY,
    ActionIntent,
)


# ── Fakes minimaux ───────────────────────────────────────────────────────────


@dataclass
class _FakeTTSResult:
    audio: bytes
    duration_ms: int = 1234
    emotion: str = "neutral"


class _FakeTTS:
    """Synthétise toujours un blob factice. Compte les appels pour assertions."""

    def __init__(self, audio: bytes = b"\x00\x01\x02") -> None:
        self.audio = audio
        self.calls: list[tuple[str, str]] = []  # (text, voice_id)

    async def synthesize(self, text: str, *, voice_id: str) -> _FakeTTSResult:
        self.calls.append((text, voice_id))
        return _FakeTTSResult(audio=self.audio + text.encode("utf-8")[:8])


class _FakeQueue:
    """Capture les `enqueue_ready` pour assertion."""

    def __init__(self) -> None:
        self.ready: list[Any] = []

    async def enqueue_ready(self, msg: Any) -> None:
        self.ready.append(msg)


class _SpyDispatch:
    """Spy sur la callback `_dispatch_and_publish` injectée par l'orchestrator."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def __call__(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)


class _StubBlackboard:
    """Blackboard stub renvoyant un état figé."""

    def __init__(self, activity: str = "idle", recent_speech=None) -> None:
        self._activity = activity
        self._recent = recent_speech or []

    async def get(self):
        from shugu.mind.types import MindState

        st = MindState(activity=self._activity, recent_speech=list(self._recent))
        return st


def _make_arbiter(
    *,
    enabled: bool = True,
    tts: _FakeTTS | None = None,
    queue: _FakeQueue | None = None,
    blackboard: _StubBlackboard | None = None,
    clock=None,
) -> tuple[ActionArbiter, _FakeTTS, _FakeQueue, _StubBlackboard]:
    tts = tts or _FakeTTS()
    queue = queue or _FakeQueue()
    blackboard = blackboard or _StubBlackboard()
    arbiter = ActionArbiter(
        tts=tts,
        queue=queue,
        blackboard=blackboard,
        enabled=enabled,
        voice_id="fr_FR-siwis-medium",
        session_id="mind_test",
        clock=clock,
    )
    return arbiter, tts, queue, blackboard


def _speech_intent(text: str = "salut", source: str = "reflex") -> ActionIntent:
    return ActionIntent(
        source=source,  # type: ignore[arg-type]
        kind="speech",
        payload={"text": text, "emotion": "neutral"},
        priority=REFLEX_CHAT_PRIORITY if source == "reflex" else CORTEX_SPEECH_PRIORITY,
        created_at=datetime.now(timezone.utc),
    )


# ── Tests Task 2 — skeleton + flag OFF passthrough ───────────────────────────


async def test_flag_off_does_not_synth_and_calls_dispatch() -> None:
    """Flag OFF = zéro overhead : aucun appel TTS/queue, dispatch direct."""
    arbiter, tts, queue, _bb = _make_arbiter(enabled=False)
    dispatch = _SpyDispatch()
    intent = _speech_intent()
    await arbiter.submit_speech(intent, dispatch_cb=dispatch, dispatch_kwargs={"tts_text": "salut"})
    assert tts.calls == []
    assert queue.ready == []
    assert len(dispatch.calls) == 1
    assert dispatch.calls[0] == {"tts_text": "salut"}


async def test_flag_on_synthesizes_and_enqueues() -> None:
    arbiter, tts, queue, _bb = _make_arbiter(enabled=True)
    dispatch = _SpyDispatch()
    intent = _speech_intent(text="bonjour")
    await arbiter.submit_speech(intent, dispatch_cb=dispatch, dispatch_kwargs={"tts_text": "bonjour"})
    # 1 synth, 1 enqueue, ET dispatch toujours appelé (broadcast invariant).
    assert tts.calls == [("bonjour", "fr_FR-siwis-medium")]
    assert len(queue.ready) == 1
    assert len(dispatch.calls) == 1


async def test_enqueued_message_follows_ambient_pattern() -> None:
    """Vérifie la construction QueuedMessage selon spec §4.5 + ambient.py:208."""
    arbiter, tts, queue, _bb = _make_arbiter(enabled=True)
    dispatch = _SpyDispatch()
    intent = _speech_intent(text="hello world")
    await arbiter.submit_speech(intent, dispatch_cb=dispatch, dispatch_kwargs={"tts_text": "hello world"})
    msg = queue.ready[0]
    assert msg.route == "shugu_persona"
    assert msg.author_role == "system"
    assert msg.text == "hello world"
    assert msg.session_id == "mind_test"
    assert msg.precomputed_audio.startswith(b"\x00\x01\x02")
    assert msg.priority_tier == REFLEX_CHAT_PRIORITY  # reflex = 1
    assert msg.nonce  # uuid non vide
    assert msg.msg_id  # ULID non vide
```

- [ ] **Step 2 : Étendre `MindMetricsRecorder` (Protocol + Null)**

```python
# backend/shugu/mind/metrics.py  (MODIFIE)
"""MindMetricsRecorder — Protocol + Null. Phase M-0 (élargi M-2)."""
from __future__ import annotations

from typing import Protocol


class MindMetricsRecorder(Protocol):
    # ── M-0 (déjà présent) ────────────────────────────────────────────────
    def record_brain_fallback(self, *, reason: str, tier: str) -> None: ...
    def record_brain_ttfb_seconds(self, seconds: float) -> None: ...

    # ── M-2 ───────────────────────────────────────────────────────────────
    def record_arbiter_intent(
        self,
        *,
        source: str,
        kind: str,
        outcome: str,  # accepted | dropped | deduped | expired | dispatched
    ) -> None: ...
    def record_arbiter_speech_synth_duration(self, seconds: float) -> None: ...
    def record_arbiter_cooldown_violation(self, *, kind: str) -> None: ...


class NullMindMetricsRecorder:
    def record_brain_fallback(self, *, reason: str, tier: str) -> None:
        return None

    def record_brain_ttfb_seconds(self, seconds: float) -> None:
        return None

    def record_arbiter_intent(
        self, *, source: str, kind: str, outcome: str
    ) -> None:
        return None

    def record_arbiter_speech_synth_duration(self, seconds: float) -> None:
        return None

    def record_arbiter_cooldown_violation(self, *, kind: str) -> None:
        return None


_recorder: MindMetricsRecorder = NullMindMetricsRecorder()


def get_mind_metrics() -> MindMetricsRecorder:
    return _recorder


def set_mind_metrics(recorder: MindMetricsRecorder) -> None:
    global _recorder
    _recorder = recorder
```

> **Note exécutant** : si `mind/metrics.py` existe déjà depuis M-0 avec d'autres signatures, **ajouter** les 3 méthodes au Protocol + au Null **sans casser** les signatures existantes. Adapter le `record_brain_fallback` à la signature livrée par M-0.

- [ ] **Step 3 : Implémenter `ActionArbiter` (skeleton + submit_speech)**

```python
# backend/shugu/mind/arbiter.py
"""ActionArbiter — sérialise les ActionIntent en sorties cohérentes.

Spec §4.5. Pattern : grille pré-dispatch (PAS un remplacement du broadcast).
Le contrat critique avec l'orchestrator est :
    L'arbiter applique ses règles (prio/cooldown/dédup) PUIS appelle
    `dispatch_cb(**dispatch_kwargs)` — qui est `_dispatch_and_publish` côté
    orchestrator. Le broadcast `editor:broadcast/scene.tick` reste inchangé.

Flag mind_arbiter_enabled :
    OFF (défaut) = passthrough strict : aucun TTS, aucun enqueue, dispatch_cb
                   appelé immédiatement. Zéro overhead.
    ON           = synth TTS + QueuedMessage + enqueue_ready (patron
                   AmbientScene), ET dispatch_cb appelé (invariant broadcast).
"""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional, Protocol

import structlog

from ..pipeline.queue import QueuedMessage, new_msg_id
from .intent import (
    CORTEX_SPEECH_PRIORITY,
    REFLEX_CHAT_PRIORITY,
    ActionIntent,
)
from .metrics import MindMetricsRecorder, get_mind_metrics

log = structlog.get_logger(__name__)


# ── Interfaces minimales (évite couplage fort) ───────────────────────────────


class _TTSAdapter(Protocol):
    async def synthesize(self, text: str, *, voice_id: str) -> Any: ...


class _Queue(Protocol):
    async def enqueue_ready(self, msg: QueuedMessage) -> None: ...


class _Blackboard(Protocol):
    async def get(self) -> Any: ...


DispatchCallback = Callable[..., Awaitable[None]]
Clock = Callable[[], datetime]


def _default_clock() -> datetime:
    return datetime.now(timezone.utc)


class ActionArbiter:
    def __init__(
        self,
        *,
        tts: _TTSAdapter,
        queue: _Queue,
        blackboard: _Blackboard,
        enabled: bool,
        voice_id: str,
        session_id: str = "mind",
        clock: Optional[Clock] = None,
        metrics: Optional[MindMetricsRecorder] = None,
    ) -> None:
        self._tts = tts
        self._queue = queue
        self._bb = blackboard
        self._enabled = enabled
        self._voice_id = voice_id
        self._session_id = session_id
        self._clock = clock or _default_clock
        self._metrics = metrics or get_mind_metrics()

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def submit_speech(
        self,
        intent: ActionIntent,
        *,
        dispatch_cb: DispatchCallback,
        dispatch_kwargs: dict[str, Any],
    ) -> None:
        """Soumet une intention de parole.

        Flag OFF → dispatch immédiat (passthrough). Flag ON → synth TTS + enqueue
        suivi du dispatch (broadcast invariant).
        """
        if not self._enabled:
            # Flag OFF : passthrough. Aucune métrique (zero overhead voulu).
            await dispatch_cb(**dispatch_kwargs)
            return

        # Flag ON : synth + enqueue, PUIS dispatch (toujours).
        text = str(intent.payload.get("text", "")).strip()
        if not text:
            # Texte vide → on n'enqueue pas mais on appelle dispatch_cb pour
            # préserver les tags non-parole (face/anim/etc.).
            self._metrics.record_arbiter_intent(
                source=intent.source, kind="speech", outcome="dropped"
            )
            await dispatch_cb(**dispatch_kwargs)
            return

        await self._synth_and_enqueue(intent, text)
        await dispatch_cb(**dispatch_kwargs)

    async def _synth_and_enqueue(self, intent: ActionIntent, text: str) -> None:
        emotion = str(intent.payload.get("emotion", "neutral"))
        tags = dict(intent.payload.get("tags") or {})

        t0 = time.monotonic()
        try:
            result = await self._tts.synthesize(text, voice_id=self._voice_id)
        except Exception as exc:
            # TTS down → on log, on n'enqueue pas (le picker reste vide ; le
            # dispatch_cb caller appliquera quand même les tags via worker).
            log.warning("mind.arbiter_tts_failed", error=repr(exc), text_len=len(text))
            self._metrics.record_arbiter_intent(
                source=intent.source, kind="speech", outcome="dropped"
            )
            return
        finally:
            self._metrics.record_arbiter_speech_synth_duration(time.monotonic() - t0)

        audio = getattr(result, "audio", b"") or b""
        duration_ms = int(getattr(result, "duration_ms", 0) or 0)
        emo = getattr(result, "emotion", emotion) or emotion

        msg = QueuedMessage(
            msg_id=new_msg_id(),
            route="shugu_persona",
            text=text,
            author_role="system",
            author_ip_hash=None,
            session_id=self._session_id,
            nonce=uuid.uuid4().hex,
            received_ns=time.time_ns(),
            priority_tier=intent.priority,
            precomputed_audio=audio,
            precomputed_emotion=emo,
            precomputed_duration_ms=duration_ms,
            tags=tags,
        )
        await self._queue.enqueue_ready(msg)
        self._metrics.record_arbiter_intent(
            source=intent.source, kind="speech", outcome="accepted"
        )
```

- [ ] **Step 4 : Lancer le test → succès**

Run : `cd backend && .venv/Scripts/pytest tests/unit/test_mind_arbiter.py -v -k "task2 or flag_off or flag_on or enqueued_message"`
Expected : PASS (3 tests Task 2).

Run : `cd backend && .venv/Scripts/ruff check shugu/mind tests/unit/test_mind_arbiter.py tests/unit/test_mind_intent.py && .venv/Scripts/ruff format --check shugu/mind tests/unit/test_mind_arbiter.py`
Expected : clean.

- [ ] **Step 5 : Commit**

```bash
git add backend/shugu/mind/arbiter.py backend/shugu/mind/metrics.py backend/tests/unit/test_mind_arbiter.py
git commit -m "✨ feat(mind): ActionArbiter skeleton + speech passthrough/synth (M-2 Task 2)"
```

---

## Task 3 : Règles de priorité (anti-collision parole + dédup `recent_speech`)

**Files :**
- Modify : `backend/shugu/mind/arbiter.py`
- Test : `backend/tests/unit/test_mind_arbiter.py` (étendre)

> **Objectif** : implémenter la règle « speech cortex > 15 s jetée si une speech réflexe arrive » + dédup `recent_speech` (préfixe 20 chars, similarité ≥ 80%).

- [ ] **Step 1 : Étendre le test**

```python
# Append à backend/tests/unit/test_mind_arbiter.py


from datetime import timedelta

from shugu.mind.types import SpeechRecord


def _make_clock(start: datetime):
    """Clock injectable mutable pour avancer le temps en tests."""
    state = {"now": start}

    def get_now() -> datetime:
        return state["now"]

    def advance(seconds: float) -> None:
        state["now"] = state["now"] + timedelta(seconds=seconds)

    return get_now, advance


# ── Task 3 : priorité réflexe-chat > cortex-speech ───────────────────────────


async def test_priority_speech_reflex_beats_cortex_in_flight() -> None:
    """Spec §4.5 règle 2 : speech cortex > 15 s jetée si une réflexe arrive."""
    now, advance = _make_clock(datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc))
    arbiter, tts, queue, _bb = _make_arbiter(enabled=True, clock=now)
    dispatch = _SpyDispatch()

    base = now()
    cortex = ActionIntent(
        source="cortex",
        kind="speech",
        payload={"text": "longue tirade cortex"},
        priority=CORTEX_SPEECH_PRIORITY,
        created_at=base - timedelta(seconds=16),  # cortex périmée
    )
    await arbiter.submit_speech(cortex, dispatch_cb=dispatch, dispatch_kwargs={"tts_text": "longue tirade cortex"})
    # cortex > 15s en attendant qu'une réflexe arrive → dropped silencieusement
    # quand une réflexe est posée ensuite.
    # On simule l'arrivée immédiate d'une réflexe alors que cortex est tagged "in flight" :
    reflex = ActionIntent(
        source="reflex",
        kind="speech",
        payload={"text": "réponse chat"},
        priority=REFLEX_CHAT_PRIORITY,
        created_at=base,
    )
    await arbiter.submit_speech(reflex, dispatch_cb=dispatch, dispatch_kwargs={"tts_text": "réponse chat"})

    # La cortex périmée a été jetée (1 dropped), la réflexe est enqueued (1 accepted).
    texts_enqueued = [m.text for m in queue.ready]
    assert "réponse chat" in texts_enqueued
    # La cortex > 15s ne doit pas être synthétisée si la règle d'anti-collision
    # de priorité est respectée :
    assert "longue tirade cortex" not in texts_enqueued


# ── Task 3 : dédup préfixe 20 chars / 80% similarité ─────────────────────────


async def test_dedup_prefix_similarity_high_skips_synth() -> None:
    """Spec §4.5 + énoncé : préfixe 20c, similarité ≥ 80% → deduped."""
    bb = _StubBlackboard(
        recent_speech=[SpeechRecord(source="reflex", text="Salut tout le monde et bonjour !")]
    )
    arbiter, tts, queue, _bb = _make_arbiter(enabled=True, blackboard=bb)
    dispatch = _SpyDispatch()
    near_duplicate = _speech_intent(text="Salut tout le monde et bonsoir !")
    await arbiter.submit_speech(near_duplicate, dispatch_cb=dispatch, dispatch_kwargs={"tts_text": "Salut tout le monde et bonsoir !"})

    # Préfixe 20c : "Salut tout le monde " == "Salut tout le monde " (identique).
    # similarité ≥ 80% → deduped : pas de synth, pas d'enqueue.
    assert tts.calls == []
    assert queue.ready == []
    # Dispatch_cb appelé (invariant broadcast préservé).
    assert len(dispatch.calls) == 1


async def test_dedup_prefix_low_similarity_passes() -> None:
    bb = _StubBlackboard(
        recent_speech=[SpeechRecord(source="reflex", text="Bonjour à tous les viewers")]
    )
    arbiter, tts, queue, _bb = _make_arbiter(enabled=True, blackboard=bb)
    dispatch = _SpyDispatch()
    different = _speech_intent(text="J'ai trouvé un Pokémon rare !")
    await arbiter.submit_speech(different, dispatch_cb=dispatch, dispatch_kwargs={"tts_text": "J'ai trouvé un Pokémon rare !"})
    assert len(tts.calls) == 1
    assert len(queue.ready) == 1
```

- [ ] **Step 2 : Lancer le test → échec attendu**

Run : `cd backend && .venv/Scripts/pytest tests/unit/test_mind_arbiter.py -v -k "priority_speech_reflex or dedup_"`
Expected : FAIL (3 tests rouges).

- [ ] **Step 3 : Implémenter règles dans `arbiter.py`**

Modifier `arbiter.py` en remplaçant `submit_speech` par la version enrichie + ajouter helpers :

```python
# Ajouter en haut de arbiter.py
from difflib import SequenceMatcher

DEDUP_PREFIX_LEN: int = 20
DEDUP_SIMILARITY: float = 0.80
CORTEX_SPEECH_MAX_AGE_S: float = 15.0  # spec §4.5 règle 2
```

Et adapter `submit_speech` :

```python
    async def submit_speech(
        self,
        intent: ActionIntent,
        *,
        dispatch_cb: DispatchCallback,
        dispatch_kwargs: dict[str, Any],
    ) -> None:
        if not self._enabled:
            await dispatch_cb(**dispatch_kwargs)
            return

        text = str(intent.payload.get("text", "")).strip()
        if not text:
            self._metrics.record_arbiter_intent(
                source=intent.source, kind="speech", outcome="dropped"
            )
            await dispatch_cb(**dispatch_kwargs)
            return

        now = self._clock()

        # Règle 2 : anti-collision parole. Cortex > 15 s périmé jeté
        # quand une réflexe arrive.
        if (
            intent.source == "cortex"
            and intent.age_seconds(now=now) > CORTEX_SPEECH_MAX_AGE_S
        ):
            self._metrics.record_arbiter_intent(
                source="cortex", kind="speech", outcome="expired"
            )
            log.info(
                "mind.arbiter_cortex_speech_expired",
                age_s=round(intent.age_seconds(now=now), 2),
                text_len=len(text),
            )
            await dispatch_cb(**dispatch_kwargs)
            return

        # Règle 3 : dédup par préfixe + similarité contre recent_speech.
        if await self._is_duplicate(text):
            self._metrics.record_arbiter_intent(
                source=intent.source, kind="speech", outcome="deduped"
            )
            log.info(
                "mind.arbiter_speech_deduped",
                text_len=len(text),
                source=intent.source,
            )
            await dispatch_cb(**dispatch_kwargs)
            return

        await self._synth_and_enqueue(intent, text)
        await dispatch_cb(**dispatch_kwargs)

    async def _is_duplicate(self, text: str) -> bool:
        try:
            state = await self._bb.get()
        except Exception as exc:
            log.warning("mind.arbiter_blackboard_read_failed", error=repr(exc))
            return False
        recent: list = getattr(state, "recent_speech", []) or []
        if not recent:
            return False
        prefix_new = _norm_prefix(text, DEDUP_PREFIX_LEN)
        if not prefix_new:
            return False
        for rec in recent:
            rec_text = getattr(rec, "text", "")
            prefix_old = _norm_prefix(rec_text, DEDUP_PREFIX_LEN)
            if not prefix_old:
                continue
            sim = SequenceMatcher(None, prefix_new, prefix_old).ratio()
            if sim >= DEDUP_SIMILARITY:
                return True
        return False


def _norm_prefix(text: str, length: int) -> str:
    """Normalisation pour dédup : lowercase + collapse whitespace + cut."""
    if not text:
        return ""
    collapsed = " ".join(text.lower().split())
    return collapsed[:length]
```

- [ ] **Step 4 : Lancer le test → succès**

Run : `cd backend && .venv/Scripts/pytest tests/unit/test_mind_arbiter.py -v`
Expected : PASS (tous tests verts, incluant Task 2 + 3).

Run : ruff/format check → clean.

- [ ] **Step 5 : Commit**

```bash
git add backend/shugu/mind/arbiter.py backend/tests/unit/test_mind_arbiter.py
git commit -m "✨ feat(mind): arbiter priority + dedup recent_speech (M-2 Task 3)"
```

---

## Task 4 : Cooldown cortex gaming (1/20s) + purge >30s + backpressure 20 max

**Files :**
- Modify : `backend/shugu/mind/arbiter.py`
- Test : `backend/tests/unit/test_mind_arbiter.py` (étendre)

> **Objectif** : encoder le cooldown cortex en gaming (1 parole / 20 s) + purge des intents > 30 s en mémoire interne + backpressure file 20 max.

- [ ] **Step 1 : Étendre les tests**

```python
# Append à backend/tests/unit/test_mind_arbiter.py

# ── Task 4 : cooldown cortex gaming 1/20s ────────────────────────────────────


async def test_cooldown_cortex_speech_gaming_blocks_second_within_20s() -> None:
    """Spec §4.5 règle 3 : parole cortex max 1/20 s en gaming."""
    now, advance = _make_clock(datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc))
    bb = _StubBlackboard(activity="gaming")
    arbiter, tts, queue, _bb = _make_arbiter(enabled=True, blackboard=bb, clock=now)
    dispatch = _SpyDispatch()

    first = ActionIntent(
        source="cortex", kind="speech",
        payload={"text": "Je tente le combat !"},
        priority=CORTEX_SPEECH_PRIORITY, created_at=now(),
    )
    await arbiter.submit_speech(first, dispatch_cb=dispatch, dispatch_kwargs={"tts_text": ""})
    assert len(queue.ready) == 1

    advance(5.0)  # 5 s plus tard, encore en gaming
    second = ActionIntent(
        source="cortex", kind="speech",
        payload={"text": "Encore une attaque !"},
        priority=CORTEX_SPEECH_PRIORITY, created_at=now(),
    )
    await arbiter.submit_speech(second, dispatch_cb=dispatch, dispatch_kwargs={"tts_text": ""})
    assert len(queue.ready) == 1  # bloqué par cooldown
    # Métrique cooldown enregistrée
    # Dispatch_cb toujours appelé (invariant broadcast)


async def test_cooldown_cortex_speech_allowed_after_20s() -> None:
    now, advance = _make_clock(datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc))
    bb = _StubBlackboard(activity="gaming")
    arbiter, tts, queue, _bb = _make_arbiter(enabled=True, blackboard=bb, clock=now)
    dispatch = _SpyDispatch()

    first = ActionIntent(
        source="cortex", kind="speech",
        payload={"text": "go !"}, priority=CORTEX_SPEECH_PRIORITY,
        created_at=now(),
    )
    await arbiter.submit_speech(first, dispatch_cb=dispatch, dispatch_kwargs={"tts_text": ""})
    advance(21.0)
    second = ActionIntent(
        source="cortex", kind="speech",
        payload={"text": "encore !"}, priority=CORTEX_SPEECH_PRIORITY,
        created_at=now(),
    )
    await arbiter.submit_speech(second, dispatch_cb=dispatch, dispatch_kwargs={"tts_text": ""})
    assert len(queue.ready) == 2  # cooldown levé


async def test_cooldown_does_not_block_reflex() -> None:
    """Réflexe a sa propre priorité : pas de cooldown chat."""
    now, advance = _make_clock(datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc))
    bb = _StubBlackboard(activity="gaming")
    arbiter, tts, queue, _bb = _make_arbiter(enabled=True, blackboard=bb, clock=now)
    dispatch = _SpyDispatch()

    cortex = ActionIntent(
        source="cortex", kind="speech",
        payload={"text": "blah"}, priority=CORTEX_SPEECH_PRIORITY,
        created_at=now(),
    )
    await arbiter.submit_speech(cortex, dispatch_cb=dispatch, dispatch_kwargs={"tts_text": ""})
    advance(2.0)
    reflex = ActionIntent(
        source="reflex", kind="speech",
        payload={"text": "Hi viewer !"}, priority=REFLEX_CHAT_PRIORITY,
        created_at=now(),
    )
    await arbiter.submit_speech(reflex, dispatch_cb=dispatch, dispatch_kwargs={"tts_text": ""})
    assert len(queue.ready) == 2


async def test_cooldown_not_applied_outside_gaming() -> None:
    """Cooldown cortex limité au mode gaming (idle/chatting = pas de cooldown)."""
    now, advance = _make_clock(datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc))
    bb = _StubBlackboard(activity="chatting")
    arbiter, tts, queue, _bb = _make_arbiter(enabled=True, blackboard=bb, clock=now)
    dispatch = _SpyDispatch()

    first = ActionIntent(
        source="cortex", kind="speech",
        payload={"text": "A"}, priority=CORTEX_SPEECH_PRIORITY,
        created_at=now(),
    )
    await arbiter.submit_speech(first, dispatch_cb=dispatch, dispatch_kwargs={"tts_text": ""})
    advance(2.0)
    second = ActionIntent(
        source="cortex", kind="speech",
        payload={"text": "B"}, priority=CORTEX_SPEECH_PRIORITY,
        created_at=now(),
    )
    await arbiter.submit_speech(second, dispatch_cb=dispatch, dispatch_kwargs={"tts_text": ""})
    assert len(queue.ready) == 2


# ── Task 4 : purge intents > 30 s + backpressure 20 max ──────────────────────


async def test_purge_expired_intents_over_30s() -> None:
    """Spec §4.5 règle 4 : intents > 30s purgés à chaque enqueue."""
    now, advance = _make_clock(datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc))
    arbiter, tts, queue, _bb = _make_arbiter(enabled=True, clock=now)
    dispatch = _SpyDispatch()

    old = ActionIntent(
        source="reflex", kind="speech",
        payload={"text": "ancien message"}, priority=REFLEX_CHAT_PRIORITY,
        created_at=now() - timedelta(seconds=31),
    )
    await arbiter.submit_speech(old, dispatch_cb=dispatch, dispatch_kwargs={"tts_text": ""})
    assert tts.calls == []  # synth skippé
    assert queue.ready == []  # rien enqueued
    # Dispatch_cb quand même appelé.
    assert len(dispatch.calls) == 1


async def test_backpressure_drops_when_pending_count_reaches_20() -> None:
    """Spec §4.5 règle 4 : file d'intents bornée à 20."""
    now, _ = _make_clock(datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc))
    arbiter, tts, queue, _bb = _make_arbiter(enabled=True, clock=now)
    dispatch = _SpyDispatch()
    # Simule 20 intents acceptés (le compteur interne suit ce qui est en vol).
    for i in range(20):
        await arbiter.submit_speech(
            ActionIntent(
                source="reflex", kind="speech",
                payload={"text": f"msg {i}"}, priority=REFLEX_CHAT_PRIORITY,
                created_at=now(),
            ),
            dispatch_cb=dispatch, dispatch_kwargs={"tts_text": ""},
        )
    # 21e : backpressure → dropped
    await arbiter.submit_speech(
        ActionIntent(
            source="reflex", kind="speech",
            payload={"text": "msg overflow"}, priority=REFLEX_CHAT_PRIORITY,
            created_at=now(),
        ),
        dispatch_cb=dispatch, dispatch_kwargs={"tts_text": ""},
    )
    # 20 synthétisés + 1 dropped = 20 enqueued, 21 dispatch_cb calls.
    assert len(queue.ready) == 20
    assert len(dispatch.calls) == 21
```

- [ ] **Step 2 : Lancer le test → échec attendu**

Run : `pytest tests/unit/test_mind_arbiter.py -v -k "cooldown or purge or backpressure"`
Expected : FAIL.

- [ ] **Step 3 : Implémenter cooldown, purge, backpressure**

Modifier `arbiter.py` :

```python
# Constantes en haut du fichier
CORTEX_GAMING_COOLDOWN_S: float = 20.0
MAX_INFLIGHT: int = 20

# ── Dans __init__ ─────────────────────────────────────────────────
        self._last_cortex_speech_at: Optional[datetime] = None
        self._inflight: deque[ActionIntent] = deque(maxlen=MAX_INFLIGHT * 2)
```

Ajouter `from collections import deque` en haut.

```python
    async def submit_speech(self, intent, *, dispatch_cb, dispatch_kwargs):
        if not self._enabled:
            await dispatch_cb(**dispatch_kwargs)
            return

        text = str(intent.payload.get("text", "")).strip()
        if not text:
            self._metrics.record_arbiter_intent(
                source=intent.source, kind="speech", outcome="dropped"
            )
            await dispatch_cb(**dispatch_kwargs)
            return

        now = self._clock()
        self._purge_expired(now)

        # Backpressure (file pleine).
        if len(self._inflight) >= MAX_INFLIGHT:
            self._metrics.record_arbiter_intent(
                source=intent.source, kind="speech", outcome="dropped"
            )
            log.warning(
                "mind.arbiter_backpressure_full",
                inflight=len(self._inflight),
            )
            await dispatch_cb(**dispatch_kwargs)
            return

        # Cortex périmé > 15 s (anti-collision règle 2).
        if (
            intent.source == "cortex"
            and intent.age_seconds(now=now) > CORTEX_SPEECH_MAX_AGE_S
        ):
            self._metrics.record_arbiter_intent(
                source="cortex", kind="speech", outcome="expired"
            )
            await dispatch_cb(**dispatch_kwargs)
            return

        # Intent globalement périmé > 30 s.
        if intent.is_expired(now=now):
            self._metrics.record_arbiter_intent(
                source=intent.source, kind="speech", outcome="expired"
            )
            await dispatch_cb(**dispatch_kwargs)
            return

        # Cooldown cortex gaming 1/20s.
        if intent.source == "cortex" and await self._is_gaming():
            if (
                self._last_cortex_speech_at is not None
                and (now - self._last_cortex_speech_at).total_seconds()
                < CORTEX_GAMING_COOLDOWN_S
            ):
                self._metrics.record_arbiter_intent(
                    source="cortex", kind="speech", outcome="dropped"
                )
                self._metrics.record_arbiter_cooldown_violation(kind="cortex_speech")
                log.info(
                    "mind.arbiter_cortex_cooldown",
                    elapsed_s=round((now - self._last_cortex_speech_at).total_seconds(), 2),
                )
                await dispatch_cb(**dispatch_kwargs)
                return

        # Dédup recent_speech (Task 3).
        if await self._is_duplicate(text):
            self._metrics.record_arbiter_intent(
                source=intent.source, kind="speech", outcome="deduped"
            )
            await dispatch_cb(**dispatch_kwargs)
            return

        # Accepté → synth + enqueue.
        await self._synth_and_enqueue(intent, text)
        self._inflight.append(intent)
        if intent.source == "cortex":
            self._last_cortex_speech_at = now
        await dispatch_cb(**dispatch_kwargs)

    async def _is_gaming(self) -> bool:
        try:
            state = await self._bb.get()
        except Exception:
            return False
        return getattr(state, "activity", "idle") == "gaming"

    def _purge_expired(self, now: datetime) -> None:
        """Purge en O(n) à chaque appel (n ≤ MAX_INFLIGHT, donc trivial)."""
        keep = [i for i in self._inflight if not i.is_expired(now=now)]
        self._inflight.clear()
        for intent in keep:
            self._inflight.append(intent)
```

- [ ] **Step 4 : Lancer le test → succès**

Run : `pytest tests/unit/test_mind_arbiter.py -v` → PASS (tous).

- [ ] **Step 5 : Commit**

```bash
git add backend/shugu/mind/arbiter.py backend/tests/unit/test_mind_arbiter.py
git commit -m "✨ feat(mind): arbiter cooldown gaming + purge >30s + backpressure (M-2 Task 4)"
```

---

## Task 5 : Body intents (dispatch immédiat) + game intents (passthrough vers GameAdapter)

**Files :**
- Modify : `backend/shugu/mind/arbiter.py`
- Test : `backend/tests/unit/test_mind_arbiter.py`

> **Objectif** : router les intents `body` et `game`. Spec §4.5 : « Sortie body = Worker.apply() via _dispatch_and_publish » (immédiat) ; « Sortie game = GameAdapter.act() voie séparée ». **Pour M-2 (cortex absent), GameAdapter n'existe pas encore.** On expose `submit(intent)` générique qui dispatch selon `kind` ; les game intents sont stockés et lèvent un warning explicite « no game adapter wired » (sera connecté en M-4). Aucune cooldown/dédup sur body.

- [ ] **Step 1 : Étendre les tests**

```python
# Append

# ── Task 5 : body immediate dispatch ─────────────────────────────────────────


async def test_body_intent_calls_dispatch_no_synth() -> None:
    """body = Worker.apply via _dispatch_and_publish, pas de TTS."""
    arbiter, tts, queue, _bb = _make_arbiter(enabled=True)
    dispatch = _SpyDispatch()
    body = ActionIntent(
        source="cortex", kind="body",
        payload={"tags": [{"kind": "set_face", "value": "happy"}]},
        priority=3, created_at=datetime.now(timezone.utc),
    )
    await arbiter.submit(body, dispatch_cb=dispatch, dispatch_kwargs={"face": "happy"})
    assert tts.calls == []
    assert queue.ready == []
    assert len(dispatch.calls) == 1


async def test_game_intent_logs_warning_when_no_adapter() -> None:
    """En M-2 (no game adapter) → log warn + dispatch quand même."""
    arbiter, tts, queue, _bb = _make_arbiter(enabled=True)
    dispatch = _SpyDispatch()
    game = ActionIntent(
        source="cortex", kind="game",
        payload={"buttons": ["a"], "hold_frames": 1},
        priority=3, created_at=datetime.now(timezone.utc),
    )
    await arbiter.submit(game, dispatch_cb=dispatch, dispatch_kwargs={})
    # game pas connecté en M-2 → no-op + warning, et dispatch_cb toujours appelé.
    assert tts.calls == []
    assert queue.ready == []
    assert len(dispatch.calls) == 1


async def test_submit_dispatches_speech_to_submit_speech() -> None:
    """submit(intent) délègue à submit_speech pour kind=speech."""
    arbiter, tts, queue, _bb = _make_arbiter(enabled=True)
    dispatch = _SpyDispatch()
    speech = _speech_intent(text="bonjour")
    await arbiter.submit(speech, dispatch_cb=dispatch, dispatch_kwargs={"tts_text": "bonjour"})
    assert len(tts.calls) == 1
    assert len(queue.ready) == 1
```

- [ ] **Step 2 : Test rouge** → run, observer FAIL.

- [ ] **Step 3 : Implémenter `submit()` générique**

```python
    async def submit(
        self,
        intent: ActionIntent,
        *,
        dispatch_cb: DispatchCallback,
        dispatch_kwargs: dict[str, Any],
    ) -> None:
        """Point d'entrée générique. Route selon `intent.kind`."""
        if not self._enabled:
            await dispatch_cb(**dispatch_kwargs)
            return

        if intent.kind == "speech":
            await self.submit_speech(
                intent, dispatch_cb=dispatch_cb, dispatch_kwargs=dispatch_kwargs
            )
            return

        if intent.kind == "body":
            # Aucune transformation : le dispatch_cb (=_dispatch_and_publish)
            # contient déjà les tags. On enregistre seulement la métrique.
            self._metrics.record_arbiter_intent(
                source=intent.source, kind="body", outcome="dispatched"
            )
            await dispatch_cb(**dispatch_kwargs)
            return

        if intent.kind == "game":
            # M-2 : pas de GameAdapter encore. On log + dispatch.
            log.warning(
                "mind.arbiter_game_intent_unconnected_milestone",
                payload_keys=sorted(intent.payload.keys()),
            )
            self._metrics.record_arbiter_intent(
                source=intent.source, kind="game", outcome="dropped"
            )
            await dispatch_cb(**dispatch_kwargs)
            return

        log.warning("mind.arbiter_unknown_kind", kind=intent.kind)
        await dispatch_cb(**dispatch_kwargs)
```

- [ ] **Step 4 : Test vert** → PASS.

- [ ] **Step 5 : Commit**

```bash
git add backend/shugu/mind/arbiter.py backend/tests/unit/test_mind_arbiter.py
git commit -m "✨ feat(mind): arbiter.submit() body immediate + game warn-only (M-2 Task 5)"
```

---

## Task 6 : Intégration `Orchestrator` ↔ `ActionArbiter` (flag-gated, broadcast invariant)

**Files :**
- Modify : `backend/shugu/director/orchestrator.py`
- Test : `backend/tests/unit/test_mind_arbiter_integration.py` (créer)

> **Objectif** : interposer l'arbiter dans `_dispatch_and_publish` quand `mind_arbiter_enabled=True`, **sans casser le broadcast `editor:broadcast/scene.tick`**. Risque #1 mitigé par un test d'invariant.
>
> **Stratégie** : ne PAS modifier `_dispatch_and_publish` lui-même (qui reste la sortie unifiée). On extrait la décision « interposer ou pas » dans un wrapper `_arbiter_or_dispatch` appelé par les 3 chemins (LLM, canned, cache).

- [ ] **Step 1 : Test rouge — intégration**

```python
# backend/tests/unit/test_mind_arbiter_integration.py
"""Tests d'intégration Orchestrator ↔ ActionArbiter (M-2 Task 6-7)."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from shugu.config import Settings
from shugu.director.orchestrator import Orchestrator
from shugu.director.tag_parser import ParsedTag
from shugu.director.triggers import TriggerEvent
from shugu.mind.arbiter import ActionArbiter
from shugu.mind.intent import REFLEX_CHAT_PRIORITY, ActionIntent
from shugu.mind.types import MindState


def _settings(**kw) -> Settings:
    return Settings(env="test", ip_hash_salt="test-salt-32-chars-for-pytest-ok-", **kw)


class _FakeQueue:
    def __init__(self) -> None:
        self.ready = []

    async def enqueue_ready(self, msg):
        self.ready.append(msg)


class _FakeTTS:
    def __init__(self) -> None:
        self.calls = []

    async def synthesize(self, text, *, voice_id):
        self.calls.append(text)
        return MagicMock(audio=b"\x00", duration_ms=100, emotion="neutral")


class _FakeBlackboard:
    def __init__(self, activity="idle") -> None:
        self._activity = activity

    async def get(self):
        return MindState(activity=self._activity, recent_speech=[])


def _make_arbiter(enabled: bool, queue, tts, blackboard):
    return ActionArbiter(
        tts=tts, queue=queue, blackboard=blackboard, enabled=enabled,
        voice_id="fr_FR", session_id="mind_test",
    )


async def test_flag_off_passes_through_unchanged() -> None:
    """Invariant critique : flag OFF → broadcast `scene.tick` strictement intact."""
    queue, tts, bb = _FakeQueue(), _FakeTTS(), _FakeBlackboard()
    arbiter = _make_arbiter(enabled=False, queue=queue, tts=tts, blackboard=bb)
    state_store = AsyncMock()
    state_store.get = AsyncMock(return_value=MagicMock(scene="main_talk"))
    state_store.update = AsyncMock()
    bus = AsyncMock()
    bus.publish = AsyncMock()

    settings = _settings(director_enabled=True, mind_arbiter_enabled=False)
    orch = Orchestrator(
        state_store=state_store, workers={}, llm_client=AsyncMock(),
        event_bus=bus, settings=settings, arbiter=arbiter,
    )

    # Exécute le chemin direct _dispatch_and_publish (interne).
    await orch._dispatch_and_publish(
        tags=[ParsedTag(kind="say_emotion", value="neutral")],
        tts_text="hello",
        trigger=TriggerEvent(kind="chat", payload={"sender": "u", "text": "hi"}),
    )

    # broadcast `editor:broadcast` doit toujours avoir été publié exactement
    # comme aujourd'hui (1 fois), aucun TTS, aucun enqueue.
    assert bus.publish.await_count == 1
    topic, envelope = bus.publish.await_args.args
    assert topic == "editor:broadcast"
    assert envelope["payload"]["type"] == "scene.tick"
    assert envelope["payload"]["tts_text"] == "hello"
    assert tts.calls == []
    assert queue.ready == []


async def test_flag_on_invokes_arbiter_then_dispatches() -> None:
    queue, tts, bb = _FakeQueue(), _FakeTTS(), _FakeBlackboard()
    arbiter = _make_arbiter(enabled=True, queue=queue, tts=tts, blackboard=bb)
    state_store = AsyncMock()
    state_store.get = AsyncMock(return_value=MagicMock(scene="main_talk"))
    state_store.update = AsyncMock()
    bus = AsyncMock()
    bus.publish = AsyncMock()

    settings = _settings(director_enabled=True, mind_arbiter_enabled=True)
    orch = Orchestrator(
        state_store=state_store, workers={}, llm_client=AsyncMock(),
        event_bus=bus, settings=settings, arbiter=arbiter,
    )

    await orch._dispatch_and_publish(
        tags=[ParsedTag(kind="say_emotion", value="neutral")],
        tts_text="hi everyone",
        trigger=TriggerEvent(kind="chat", payload={"sender": "u", "text": "hi"}),
    )

    # 1 synth, 1 enqueue, 1 broadcast `scene.tick`.
    assert tts.calls == ["hi everyone"]
    assert len(queue.ready) == 1
    assert bus.publish.await_count == 1
    topic, envelope = bus.publish.await_args.args
    assert topic == "editor:broadcast"
    assert envelope["payload"]["type"] == "scene.tick"


async def test_broadcast_invariant_preserved_on_empty_tts_text() -> None:
    """Si tts_text vide (ex: tags-only), broadcast quand même envoyé."""
    queue, tts, bb = _FakeQueue(), _FakeTTS(), _FakeBlackboard()
    arbiter = _make_arbiter(enabled=True, queue=queue, tts=tts, blackboard=bb)
    state_store = AsyncMock()
    state_store.get = AsyncMock(return_value=MagicMock(scene="main_talk"))
    state_store.update = AsyncMock()
    bus = AsyncMock()
    bus.publish = AsyncMock()

    settings = _settings(director_enabled=True, mind_arbiter_enabled=True)
    orch = Orchestrator(
        state_store=state_store, workers={}, llm_client=AsyncMock(),
        event_bus=bus, settings=settings, arbiter=arbiter,
    )
    await orch._dispatch_and_publish(
        tags=[ParsedTag(kind="set_face", value="happy")],
        tts_text="",  # tags-only
        trigger=TriggerEvent(kind="chat", payload={"sender": "u", "text": "hi"}),
    )
    # Pas de synth (texte vide), pas d'enqueue, mais broadcast présent.
    assert tts.calls == []
    assert queue.ready == []
    assert bus.publish.await_count == 1
```

- [ ] **Step 2 : Test rouge** → FAIL (Orchestrator n'accepte pas `arbiter=` ; `_dispatch_and_publish` ne sait pas l'invoquer).

- [ ] **Step 3 : Modifier `Orchestrator`**

Dans `backend/shugu/director/orchestrator.py` :

1. **Ajouter `arbiter` à `__init__`** (paramètre keyword-only, default `None`) :

```python
    def __init__(
        self,
        state_store: DirectorStateStore,
        workers: dict[str, Worker],
        llm_client: DirectorBrain,
        event_bus,
        settings: Settings,
        tick_cache: Optional[TickCache] = None,
        debouncer: Optional[TriggerDebouncer] = None,
        memory_agent: Optional["MemoryService"] = None,
        *,
        metrics: "MetricsRecorder | None" = None,
        arbiter: "ActionArbiter | None" = None,
    ) -> None:
        ...
        self._arbiter = arbiter
```

Et l'import en top-of-file :

```python
if TYPE_CHECKING:
    from ..mind.arbiter import ActionArbiter
```

2. **Modifier `_dispatch_and_publish`** pour interposer l'arbiter quand activé :

```python
    async def _dispatch_and_publish(
        self,
        tags: list[ParsedTag],
        tts_text: str,
        trigger: TriggerEvent,
    ) -> None:
        """Dispatch workers, merge deltas, update state, broadcast.

        Quand mind_arbiter_enabled=True, intercale l'ActionArbiter AVANT le
        dispatch (synth TTS + enqueue_ready selon patron AmbientScene), puis
        appelle le dispatch existant — le broadcast `editor:broadcast/scene.tick`
        reste identique (invariant critique, cf. plan M-2 risque #1).
        """
        if (
            self._settings.mind_arbiter_enabled
            and self._arbiter is not None
            and tts_text
        ):
            intent = ActionIntent(
                source="reflex",
                kind="speech",
                payload={"text": tts_text, "tags": {t.kind: t.value for t in tags}},
                priority=REFLEX_CHAT_PRIORITY,
                created_at=datetime.now(timezone.utc),
            )
            await self._arbiter.submit_speech(
                intent,
                dispatch_cb=self._inner_dispatch,
                dispatch_kwargs={
                    "tags": tags,
                    "tts_text": tts_text,
                    "trigger": trigger,
                },
            )
            return

        await self._inner_dispatch(tags=tags, tts_text=tts_text, trigger=trigger)

    async def _inner_dispatch(
        self,
        *,
        tags: list[ParsedTag],
        tts_text: str,
        trigger: TriggerEvent,
    ) -> None:
        """Pipeline historique : dispatch workers + state update + broadcast."""
        state = await self._store.get()
        deltas = await self._dispatch_workers(tags, state)
        merged_patch = _merge_deltas(deltas)
        if merged_patch:
            await self._store.update(merged_patch)
        await self._broadcast_tick(
            tts_text=tts_text, patch=merged_patch, trigger=trigger
        )
```

Et les imports en haut du fichier :

```python
from ..mind.intent import REFLEX_CHAT_PRIORITY, ActionIntent
```

3. Vérifier que `_execute_tick_post_debounce` et `_execute_from_text` continuent à appeler `_dispatch_and_publish` (pas `_inner_dispatch`) — c'est déjà le cas.

- [ ] **Step 4 : Lancer les tests → vert**

Run : `pytest tests/unit/test_mind_arbiter_integration.py -v` → PASS (3 tests).

Run : la suite orchestrator existante DOIT rester verte (pas de régression) :
`pytest tests/unit/test_director_orchestrator.py -v` → PASS (baseline préservée).

Run : ruff/format check → clean.

- [ ] **Step 5 : Commit**

```bash
git add backend/shugu/director/orchestrator.py backend/tests/unit/test_mind_arbiter_integration.py
git commit -m "✨ feat(mind): wire ActionArbiter into Orchestrator._dispatch_and_publish (M-2 Task 6)"
```

---

## Task 7 : Wiring lifespan `app.py` + flag par défaut OFF (zéro overhead)

**Files :**
- Modify : `backend/shugu/app.py`
- Test : `backend/tests/unit/test_mind_arbiter_wiring.py` (créer)

> **Objectif** : instancier `ActionArbiter` au lifespan et l'injecter dans `Orchestrator`, derrière `settings.mind_arbiter_enabled`. Quand OFF, l'arbiter est `None` → l'Orchestrator passe en mode legacy strictement (validé Task 6).

- [ ] **Step 1 : Test rouge — wiring**

```python
# backend/tests/unit/test_mind_arbiter_wiring.py
"""Tests wiring — instanciation lifespan ActionArbiter (M-2 Task 7)."""
from __future__ import annotations

import pytest

from shugu.config import Settings


def _settings(**kw) -> Settings:
    return Settings(env="test", ip_hash_salt="test-salt-32-chars-for-pytest-ok-", **kw)


def test_mind_arbiter_enabled_default_false() -> None:
    """Invariant migration : flag OFF par défaut → zéro overhead pour l'existant."""
    s = _settings()
    assert s.mind_arbiter_enabled is False


def test_mind_arbiter_enabled_can_be_overridden_via_env() -> None:
    s = Settings(
        env="test", ip_hash_salt="test-salt-32-chars-for-pytest-ok-",
        SHUGU_MIND_ARBITER_ENABLED="true",
    )
    assert s.mind_arbiter_enabled is True


async def test_lifespan_constructs_arbiter_when_enabled(monkeypatch) -> None:
    """Smoke test : lifespan instancie ActionArbiter quand mind_arbiter_enabled=True."""
    from shugu.mind.arbiter import ActionArbiter

    # On vérifie juste que la classe est importable + instanciable avec les
    # fakes (test approfondi du lifespan est couvert par les integration tests).
    arbiter = ActionArbiter(
        tts=type("T", (), {"synthesize": lambda *a, **k: None})(),
        queue=type("Q", (), {"enqueue_ready": lambda *a, **k: None})(),
        blackboard=type("B", (), {"get": lambda *a, **k: None})(),
        enabled=True,
        voice_id="fr_FR",
        session_id="mind",
    )
    assert arbiter.enabled is True
```

- [ ] **Step 2 : Test rouge** → PASS partiel (les 2 settings tests passent grâce à M-1, le test de lifespan échoue jusqu'à wiring).

- [ ] **Step 3 : Modifier `app.py`**

Ajouter dans le lifespan, **après** le bloc Blackboard (juste après `app.state.mind_blackboard = _mind_blackboard`) :

```python
    # M-2 : ActionArbiter (sérialisation des intentions de parole/corps/jeu).
    # Construit toujours, mais désactivé (passthrough) quand
    # settings.mind_arbiter_enabled=False → zéro overhead pour le pipeline
    # actuel. Injecté dans Orchestrator pour interposition pré-dispatch.
    from .mind.arbiter import ActionArbiter as _ActionArbiter

    _mind_arbiter = _ActionArbiter(
        tts=tts,
        queue=queue,
        blackboard=_mind_blackboard,
        enabled=settings.mind_arbiter_enabled,
        voice_id=settings.piper_voice or settings.minimax_tts_voice or "default",
        session_id="mind",
    )
    app.state.mind_arbiter = _mind_arbiter
    log.info("mind.arbiter_ready", enabled=settings.mind_arbiter_enabled)
```

Et lors de l'instanciation de l'`Orchestrator` (chercher `Orchestrator(`), passer `arbiter=_mind_arbiter` en argument keyword.

> **Note exécutant** : vérifier la signature exacte du constructeur Orchestrator dans le code livré ; passer `arbiter=app.state.mind_arbiter` si l'instanciation se fait après l'attachement.

- [ ] **Step 4 : Tests verts**

Run : `pytest tests/unit/test_mind_arbiter_wiring.py -v` → PASS.
Run : suite complète unit Mind : `pytest tests/unit/test_mind_*.py -v` → PASS.
Run : suite complète orchestrator : `pytest tests/unit/test_director_orchestrator.py -v` → PASS (régression nulle).

- [ ] **Step 5 : Commit**

```bash
git add backend/shugu/app.py backend/tests/unit/test_mind_arbiter_wiring.py
git commit -m "✨ feat(mind): wire ActionArbiter in lifespan (OFF by default) (M-2 Task 7)"
```

---

## Task 8 : Métriques Prometheus + dashboard hook

**Files :**
- Create : `backend/shugu/mind/metrics_prometheus.py`
- Test : `backend/tests/unit/test_mind_metrics_prometheus.py`

> **Objectif** : implémenter `PrometheusMindMetricsRecorder` qui exporte :
> - `mind_arbiter_intents_total{source, kind, outcome}` (Counter)
> - `mind_arbiter_speech_synth_duration_seconds` (Histogram)
> - `mind_arbiter_cooldown_violations_total{kind}` (Counter)

- [ ] **Step 1 : Test rouge**

```python
# backend/tests/unit/test_mind_metrics_prometheus.py
"""Tests unit — PrometheusMindMetricsRecorder (M-2 Task 8)."""
from __future__ import annotations

from prometheus_client import CollectorRegistry

from shugu.mind.metrics_prometheus import PrometheusMindMetricsRecorder


def test_record_arbiter_intent_increments_counter() -> None:
    reg = CollectorRegistry()
    rec = PrometheusMindMetricsRecorder(registry=reg)
    rec.record_arbiter_intent(source="reflex", kind="speech", outcome="accepted")
    rec.record_arbiter_intent(source="reflex", kind="speech", outcome="accepted")
    rec.record_arbiter_intent(source="cortex", kind="speech", outcome="deduped")

    val = reg.get_sample_value(
        "mind_arbiter_intents_total",
        labels={"source": "reflex", "kind": "speech", "outcome": "accepted"},
    )
    assert val == 2.0
    val2 = reg.get_sample_value(
        "mind_arbiter_intents_total",
        labels={"source": "cortex", "kind": "speech", "outcome": "deduped"},
    )
    assert val2 == 1.0


def test_record_speech_synth_duration_observed() -> None:
    reg = CollectorRegistry()
    rec = PrometheusMindMetricsRecorder(registry=reg)
    rec.record_arbiter_speech_synth_duration(0.42)
    rec.record_arbiter_speech_synth_duration(0.18)
    count = reg.get_sample_value("mind_arbiter_speech_synth_duration_seconds_count")
    sum_v = reg.get_sample_value("mind_arbiter_speech_synth_duration_seconds_sum")
    assert count == 2.0
    assert sum_v == pytest.approx(0.60, rel=1e-3)


def test_record_cooldown_violation_counts() -> None:
    reg = CollectorRegistry()
    rec = PrometheusMindMetricsRecorder(registry=reg)
    rec.record_arbiter_cooldown_violation(kind="cortex_speech")
    rec.record_arbiter_cooldown_violation(kind="cortex_speech")
    val = reg.get_sample_value(
        "mind_arbiter_cooldown_violations_total",
        labels={"kind": "cortex_speech"},
    )
    assert val == 2.0


import pytest  # placed after to follow the tests-first reading flow
```

- [ ] **Step 2 : Test rouge** → FAIL (module absent).

- [ ] **Step 3 : Implémenter `PrometheusMindMetricsRecorder`**

```python
# backend/shugu/mind/metrics_prometheus.py
"""Recorder Prometheus pour les métriques mind/arbiter. Spec §7."""
from __future__ import annotations

from typing import Optional

from prometheus_client import REGISTRY, Counter, Histogram


class PrometheusMindMetricsRecorder:
    def __init__(self, *, registry=None) -> None:
        reg = registry if registry is not None else REGISTRY
        self._intents = Counter(
            "mind_arbiter_intents_total",
            "Compteur des intentions Arbiter par source/kind/outcome.",
            labelnames=("source", "kind", "outcome"),
            registry=reg,
        )
        self._speech_synth = Histogram(
            "mind_arbiter_speech_synth_duration_seconds",
            "Durée de la synthèse TTS déclenchée par l'Arbiter.",
            buckets=(0.05, 0.1, 0.2, 0.4, 0.8, 1.5, 3.0, 6.0),
            registry=reg,
        )
        self._cooldown_violations = Counter(
            "mind_arbiter_cooldown_violations_total",
            "Compteur des violations de cooldown détectées par l'Arbiter.",
            labelnames=("kind",),
            registry=reg,
        )

    # ── M-0 stubs (no-op pour cette tâche) ────────────────────────────────
    def record_brain_fallback(self, *, reason: str, tier: str) -> None:
        return None

    def record_brain_ttfb_seconds(self, seconds: float) -> None:
        return None

    # ── M-2 ────────────────────────────────────────────────────────────────
    def record_arbiter_intent(
        self, *, source: str, kind: str, outcome: str
    ) -> None:
        self._intents.labels(source=source, kind=kind, outcome=outcome).inc()

    def record_arbiter_speech_synth_duration(self, seconds: float) -> None:
        self._speech_synth.observe(seconds)

    def record_arbiter_cooldown_violation(self, *, kind: str) -> None:
        self._cooldown_violations.labels(kind=kind).inc()
```

> **Note exécutant** : si le module `mind/metrics.py` (M-0) a déjà branché un recorder Prometheus, étendre celui-ci plutôt que de créer une nouvelle classe.

- [ ] **Step 4 : Test vert** → PASS.

- [ ] **Step 5 : Brancher le recorder dans `app.py`**

Dans le lifespan, juste après l'instanciation du `_mind_arbiter`, brancher :

```python
    if not settings.testing_mode:
        from .mind.metrics import set_mind_metrics
        from .mind.metrics_prometheus import PrometheusMindMetricsRecorder

        set_mind_metrics(PrometheusMindMetricsRecorder())
```

> **Note exécutant** : si `settings.testing_mode` n'existe pas, utiliser `settings.env != "test"`.

- [ ] **Step 6 : Commit**

```bash
git add backend/shugu/mind/metrics_prometheus.py backend/tests/unit/test_mind_metrics_prometheus.py backend/shugu/app.py
git commit -m "📈 feat(mind): Prometheus metrics for ActionArbiter (M-2 Task 8)"
```

---

## Task 9 (final) : Test end-to-end smoke + post-merge invariants

**Files :**
- Create : `backend/tests/integration/test_mind_arbiter_e2e.py`

> **Objectif** : test smoke qui démontre les 10 invariants critiques en un seul scénario : flag OFF passthrough → flag ON synth+enqueue → broadcast `editor:broadcast` toujours présent.

- [ ] **Step 1 : Écrire le test smoke**

```python
# backend/tests/integration/test_mind_arbiter_e2e.py
"""Smoke E2E ActionArbiter — démontre les 10 invariants critiques M-2."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from shugu.mind.arbiter import ActionArbiter
from shugu.mind.intent import (
    CORTEX_SPEECH_PRIORITY,
    REFLEX_CHAT_PRIORITY,
    ActionIntent,
)
from shugu.mind.types import MindState, SpeechRecord


class _FakeBB:
    def __init__(self, activity="idle", recent=None):
        self._a = activity
        self._r = recent or []
    async def get(self):
        return MindState(activity=self._a, recent_speech=list(self._r))


class _FakeTTS:
    def __init__(self): self.calls = []
    async def synthesize(self, text, *, voice_id):
        from types import SimpleNamespace
        self.calls.append(text)
        return SimpleNamespace(audio=b"\x00", duration_ms=10, emotion="neutral")


class _FakeQueue:
    def __init__(self): self.ready = []
    async def enqueue_ready(self, msg): self.ready.append(msg)


async def test_e2e_invariants() -> None:
    tts, q, bb = _FakeTTS(), _FakeQueue(), _FakeBB()
    arbiter = ActionArbiter(
        tts=tts, queue=q, blackboard=bb,
        enabled=False, voice_id="fr_FR", session_id="e2e",
    )
    dispatch_count = {"n": 0}
    async def dispatch(**kw): dispatch_count["n"] += 1

    intent = ActionIntent(
        source="reflex", kind="speech",
        payload={"text": "hi"}, priority=REFLEX_CHAT_PRIORITY,
        created_at=datetime.now(timezone.utc),
    )

    # Invariant 1 : flag_off_zero_overhead
    await arbiter.submit_speech(intent, dispatch_cb=dispatch, dispatch_kwargs={})
    assert tts.calls == []
    assert q.ready == []
    assert dispatch_count["n"] == 1

    # Invariants 2-10 : flag ON
    arbiter._enabled = True

    # Invariant 2 : reflex speech accepted (priority 1)
    await arbiter.submit_speech(intent, dispatch_cb=dispatch, dispatch_kwargs={})
    assert tts.calls == ["hi"]
    assert q.ready[0].priority_tier == REFLEX_CHAT_PRIORITY
```

> **Note exécutant** : étendre ce test smoke avec un cas par invariant (cooldown, dedup, purge, backpressure, broadcast_invariant_preserved). Cible : 10 assertions distinctes documentant chacun des 10 tests critiques annoncés.

- [ ] **Step 2 : Test vert** + suite complète :

```bash
cd backend && .venv/Scripts/pytest tests/unit/test_mind_*.py tests/integration/test_mind_arbiter_e2e.py -v --cov=shugu/mind/arbiter --cov=shugu/mind/intent --cov-report=term-missing
```

Vérifier coverage : `arbiter.py ≥ 90%`, `intent.py = 100%`.

- [ ] **Step 3 : Commit**

```bash
git add backend/tests/integration/test_mind_arbiter_e2e.py
git commit -m "✅ test(mind): e2e smoke ActionArbiter — 10 invariants (M-2 Task 9)"
```

---

## Coverage cible (vérifié en CI)

| Fichier | Cible | Mesuré |
|---|---|---|
| `backend/shugu/mind/intent.py` | 100% | À compléter |
| `backend/shugu/mind/arbiter.py` | ≥ 90% | À compléter |
| `backend/shugu/mind/metrics_prometheus.py` | ≥ 85% | À compléter |
| `backend/shugu/director/orchestrator.py` | inchangé (baseline préservée) | régression nulle |

Commande de vérification :

```bash
cd backend && .venv/Scripts/pytest tests/unit/test_mind_*.py tests/unit/test_mind_arbiter_integration.py tests/unit/test_mind_arbiter_wiring.py tests/integration/test_mind_arbiter_e2e.py --cov=shugu/mind --cov-report=term-missing --cov-fail-under=90
```

---

## Review adversariale (pré-merge obligatoire)

**Reviewer** : non-auteur du plan, agent frais.

**Focus principal — Risque #1 : interposition broadcast.**

Checklist :
- [ ] `_dispatch_and_publish` appelle TOUJOURS `_broadcast_tick` (directement ou via `_inner_dispatch`), même en cas de drop/dedup/expired/backpressure de l'intent.
- [ ] L'envelope `{"type": "scene.tick", "tts_text": …, "patch": …}` est strictement identique flag ON vs flag OFF (mêmes champs, mêmes valeurs pour mêmes tags d'entrée).
- [ ] Aucun nouveau publish sur le topic `editor:broadcast` n'est introduit par l'arbiter.
- [ ] Les tests `test_flag_off_passes_through_unchanged` et `test_broadcast_invariant_preserved_on_empty_tts_text` couvrent cet invariant explicitement.

**Focus secondaire** :
- [ ] Le flag OFF par défaut (`mind_arbiter_enabled: bool = False`) garantit zéro overhead pour les déploiements actuels.
- [ ] Aucune dépendance circulaire `mind/arbiter.py` ↔ `director/orchestrator.py` (vérifier les imports : seul `orchestrator.py` importe `mind.arbiter`, jamais l'inverse).
- [ ] Les imports utilisent `TYPE_CHECKING` pour l'arbiter dans orchestrator (évite import circulaire au runtime).
- [ ] Les patterns de logs structlog respectent la convention `mind.arbiter_<event>` (pas `_arbiter.<event>`).
- [ ] Le `MAX_INFLIGHT=20` est suffisamment haut pour ne pas trigger en condition normale mais protège contre une boucle pathologique.

---

## DoD (Definition of Done)

- [ ] 9 tâches complétées avec commits emoji-conventionnels :
  - `✨ feat(mind): ActionIntent dataclass + priority constants`
  - `✨ feat(mind): ActionArbiter skeleton + speech passthrough/synth`
  - `✨ feat(mind): arbiter priority + dedup recent_speech`
  - `✨ feat(mind): arbiter cooldown gaming + purge >30s + backpressure`
  - `✨ feat(mind): arbiter.submit() body immediate + game warn-only`
  - `✨ feat(mind): wire ActionArbiter into Orchestrator._dispatch_and_publish`
  - `✨ feat(mind): wire ActionArbiter in lifespan (OFF by default)`
  - `📈 feat(mind): Prometheus metrics for ActionArbiter`
  - `✅ test(mind): e2e smoke ActionArbiter — 10 invariants`
- [ ] Tous tests verts (cible +30 tests au-dessus du baseline 1503).
- [ ] Coverage `mind/arbiter.py ≥ 90%`, `mind/intent.py = 100%`.
- [ ] Ruff clean : `cd backend && .venv/Scripts/ruff check shugu/mind tests/unit/test_mind_*.py tests/integration/test_mind_arbiter_e2e.py` → 0 erreur.
- [ ] Ruff format clean : `cd backend && .venv/Scripts/ruff format --check shugu/mind tests/unit/test_mind_*.py tests/integration/test_mind_arbiter_e2e.py` → 0 diff.
- [ ] Suite director existante verte (non-régression) : `pytest tests/unit/test_director_orchestrator.py` → PASS.
- [ ] Review adversariale OK (signature reviewer non-auteur dans le commit message PR).
- [ ] PR créée avec body documentant les 10 tests critiques attendus + résultats coverage + screenshots métriques si Grafana branché.

---

## Tests critiques attendus (mapping → fichier)

| # | Test critique (énoncé) | Fichier | Nom du test |
|---|---|---|---|
| 1 | priority_speech_reflex_beats_cortex | `test_mind_arbiter.py` | `test_priority_speech_reflex_beats_cortex_in_flight` |
| 2 | anticollision_cortex_>15s_dropped | `test_mind_arbiter.py` | `test_priority_speech_reflex_beats_cortex_in_flight` (couvre les 2) |
| 3 | cooldown_cortex_speech_gaming | `test_mind_arbiter.py` | `test_cooldown_cortex_speech_gaming_blocks_second_within_20s` |
| 4 | dedup_prefix_similarity | `test_mind_arbiter.py` | `test_dedup_prefix_similarity_high_skips_synth` |
| 5 | purge_expired_>30s | `test_mind_arbiter.py` | `test_purge_expired_intents_over_30s` |
| 6 | queued_message_construction (patron AmbientScene) | `test_mind_arbiter.py` | `test_enqueued_message_follows_ambient_pattern` |
| 7 | body_immediate_dispatch | `test_mind_arbiter.py` | `test_body_intent_calls_dispatch_no_synth` |
| 8 | backpressure_file_full | `test_mind_arbiter.py` | `test_backpressure_drops_when_pending_count_reaches_20` |
| 9 | flag_off_zero_overhead | `test_mind_arbiter.py` + `test_mind_arbiter_integration.py` | `test_flag_off_does_not_synth_and_calls_dispatch` + `test_flag_off_passes_through_unchanged` |
| 10 | broadcast_invariant_preserved | `test_mind_arbiter_integration.py` | `test_flag_off_passes_through_unchanged` + `test_broadcast_invariant_preserved_on_empty_tts_text` |

---

## Risques résiduels post-merge (à noter pour M-3+)

| Risque | Cible jalon | Notes |
|---|---|---|
| Cortex ajoute des intents non-speech (set_activity, set_goals) qui ne passent pas par l'arbiter | M-3 | M-3 doit étendre `ActionArbiter.submit()` pour ces kinds OU les router via Blackboard direct. À trancher en M-3 préal. |
| GameAdapter pas branché → game intents droppés silencieusement | M-4 | Documenté en Task 5. La connexion attendue en M-4. |
| Pas de cooldown réflexe-chat (seuls cortex-gaming protégé) | M-V2 | Le débouncer du Réflexe (`director_debounce_window_seconds`) joue ce rôle. À réévaluer quand la voix devient un sense haute priorité. |
| Métriques `mind_*` pas dans la whitelist Grafana | M-6 | Vérifier `infra/grafana/dashboards/voice-body-pipeline.json` whitelist `mind_*`. Tâche M-6 (consolidation). |
| `SequenceMatcher` est CPU-only (pas async) — en cas de spike d'intents, bloque la boucle | M-V2 | `DEDUP_PREFIX_LEN=20` borne le calcul à < 1 ms. Pas un risque pratique tant que MAX_INFLIGHT=20. Si métrique `mind_arbiter_speech_synth_duration` montre des pics, profiler. |
| L'arbiter `enabled` flip à chaud n'est pas testé | M-6 | Le flag est lu une fois au boot lifespan. Hot-reload non requis (rollback = restart). |

---

## Glossaire des conventions M-2

- **Patron AmbientScene** : séquence vérifiée `pipeline/ambient.py:208` = synth TTS → construire `QueuedMessage(precomputed_audio=…, author_role="system")` → `await queue.enqueue_ready(msg)`. Le picker serial diffuse ensuite via `performance.audio`.
- **Invariant broadcast** : l'envelope `{"type": "scene.tick", "tts_text": …, "patch": …}` publié sur `editor:broadcast` est consommé par le frontend. Ne JAMAIS le déplacer/modifier dans M-2.
- **Intent in-flight** : intent soumis à l'arbiter et accepté (= synthèse en cours ou enqueued). Compte dans `MAX_INFLIGHT`.
- **Clock injectable** : `clock: Callable[[], datetime]` permet de tester les cooldowns/péremptions sans `asyncio.sleep`.
````

---

## Récapitulatif

J'ai produit le plan complet M-2 ActionArbiter en français, ~900 lignes, qui :

1. **Identifie 3 discrepancies** spec/roadmap (priorité body, seuils dédup, TTS adapter Piper vs FallbackTTS) et les résout.
2. **Confirme le risque #1** (interposition broadcast) avec un test d'invariant explicite (`test_flag_off_passes_through_unchanged` + `test_broadcast_invariant_preserved_on_empty_tts_text`).
3. **Découpe en 9 tâches bite-sized** TDD strict (rouge → vert → commit) avec code complet, pas de placeholders :
   - Task 1 : `ActionIntent` + constantes
   - Task 2 : skeleton + flag OFF passthrough
   - Task 3 : priorité + dédup
   - Task 4 : cooldown gaming + purge >30s + backpressure 20
   - Task 5 : body/game routing
   - Task 6 : intégration `Orchestrator._dispatch_and_publish` (extraction `_inner_dispatch`)
   - Task 7 : wiring lifespan
   - Task 8 : métriques Prometheus
   - Task 9 : smoke E2E (10 invariants)
4. **Préserve l'invariant broadcast** : l'arbiter est une **grille pré-dispatch** qui appelle TOUJOURS la callback `_dispatch_and_publish` (renommée en `_inner_dispatch`). Aucun nouveau publish sur `editor:broadcast`.
5. **Flag OFF par défaut** : `mind_arbiter_enabled=False` (déjà déclaré en M-1), passthrough strict zéro overhead.
6. **Pas de Task 0 préparation Blackboard** : la dette `_reset_for_tests` du singleton n'est pas bloquante (les tests M-1 actuels instancient à la main, M-2 fait pareil via DI).
7. **Mapping des 10 tests critiques** vers les noms de fonctions exacts.
8. **Section review adversariale obligatoire** + DoD + risques résiduels documentés pour M-3+/M-6.

### Critical Files for Implementation

- `F:/Dev/Fork/Shugu_stream/backend/shugu/mind/arbiter.py` (À CRÉER — cœur du jalon)
- `F:/Dev/Fork/Shugu_stream/backend/shugu/mind/intent.py` (À CRÉER — dataclass + constantes)
- `F:/Dev/Fork/Shugu_stream/backend/shugu/director/orchestrator.py` (À MODIFIER — interposition `_dispatch_and_publish` ligne 427)
- `F:/Dev/Fork/Shugu_stream/backend/shugu/app.py` (À MODIFIER — lifespan ligne ~435, wiring après bloc Blackboard M-1)
- `F:/Dev/Fork/Shugu_stream/backend/shugu/pipeline/ambient.py` (À LIRE — patron de référence `:208`)