---
date: 2026-05-04
status: blueprint-final-v2
sprint: C
authors: architect-agent
environment-verified: llm_local.py, tts_local.py, stt_local.py, livekit_agent.py, intent_classifier.py, tool_call_parser.py — all read and anchored
decisions-actées: D1 Tavily+Brave fallback, D3 streaming default=True, D6 filler Sprint D, D7 voice_web_injection_threshold Settings field
---

# Blueprint Sprint C — Régie web search, Streaming TTS+LLM, Barge-in basique

## Note de périmètre vs spec parent

Le spec parent `2026-05-03-realtime-voice-shugu.md` place le streaming TTS en Sprint C
et la barge-in state machine complète en Sprint D. Ce blueprint respecte cette frontière :
Sprint C livre le streaming + la barge-in safe cancel (3 états), Sprint D livre la FSM
7 états complète (IDLE/LISTENING/THINKING/SPEAKING/INTERRUPTED/YIELDING/STUBBORN).

Les fillers acoustiques (banque `models/piper/fillers/`), le turn-detector plugin, et la
route `_build_sprint_b_system_prompt` remplacement complet restent Sprint D.

---

## 0. État réel du repo au départ de Sprint C

Fichiers confirmés en lecture directe avant ce blueprint :

| Fichier | État |
|---|---|
| `voice/llm_local.py` | `LocalLLM.generate()` implémenté avec `asyncio.Lock`. `stream()` = `NotImplementedError`. |
| `voice/tts_local.py` | `PiperTTS.synthesize()` implémenté (one-shot subprocess). `synthesize_stream()` = `NotImplementedError`. `aclose()` présent. |
| `voice/stt_local.py` | `WhisperSTT.transcribe()` implémenté. `transcribe_stream()` = `NotImplementedError`. |
| `voice/livekit_agent.py` | `ShuguVoiceAgent` complet avec `_handle_turn`, `_drain_and_transcribe`, `_process_utterance`, `_resample_and_publish`, `_on_shutdown`. `_processing: bool` pour backpressure. |
| `voice/regie/intent_classifier.py` | `classify(text) -> IntentMatch` (CHAT/WEB_SEARCH/EMOTION/EMOTE) — règles regex, complet. |
| `voice/regie/tool_call_parser.py` | `parse_gemma_tool_calls`, `has_tool_calls` — complet. |
| `config.py` | Champs `whisper_bin/model`, `piper_bin/voice`, `voice_agent_enabled`, `voice_recordings_dir` présents. Pas de `tavily_api_key`, `voice_streaming_enabled`. |
| `pyproject.toml` | `respx>=0.21` en dev deps. `httpx>=0.27` en core deps. Pas de `tavily-python`. |

---

## 1. Tree fichiers définitif Sprint C

Aucun fichier déplacé ni renommé. Modifications et créations uniquement.

```
backend/shugu/voice/
├── __init__.py                              existant — inchangé
├── llm_local.py                             MODIFIÉ — ajouter stream() + cancel support
├── stt_local.py                             existant — inchangé Sprint C
├── tts_local.py                             MODIFIÉ — ajouter synthesize_stream()
├── livekit_agent.py                         MODIFIÉ — _handle_turn_streaming, 3-state barge-in
├── chunker.py                               CRÉER — sentence boundary splitter
├── audio_bridge.py                          existant — Sprint E, ne pas toucher
├── recording.py                             existant — Sprint G, ne pas toucher
└── regie/
    ├── __init__.py                          existant — inchangé
    ├── intent_classifier.py                 existant — inchangé
    ├── tool_call_parser.py                  existant — inchangé
    ├── web_search.py                        CRÉER — WebSearchProvider + TavilyProvider + BraveProvider + WebSearchAggregator
    └── prompt_builder.py                    CRÉER — system prompt augmenté

backend/shugu/config.py                      MODIFIÉ — 4 nouveaux champs (D1 D3 D7)
backend/pyproject.toml                       NON MODIFIÉ — httpx et respx déjà présents

backend/tests/unit/voice/
├── __init__.py                              existant
├── test_livekit_agent.py                    MODIFIÉ — ajouter tests C
├── test_tts_local.py                        MODIFIÉ — ajouter tests streaming
├── test_stt_local.py                        existant — inchangé Sprint C
├── test_chunker.py                          CRÉER
└── test_web_search.py                       CRÉER — couvre Tavily + Brave + Aggregator
```

Fichiers hors `voice/` modifiés :

| Fichier | Changement |
|---|---|
| `backend/shugu/config.py` | Ajouter `tavily_api_key`, `brave_api_key`, `voice_streaming_enabled` (default=True — D3), `voice_web_injection_threshold` (D7) |
| `backend/pyproject.toml` | Aucun ajout — httpx + respx déjà présents |

---

## 2. Champs Settings à ajouter dans `config.py`

Insérer après le bloc `voice_recordings_dir` existant. Quatre champs — décisions D1, D3, D7 actées.

```python
# D1 ARBITRÉ — Tavily + Brave fallback dès PR1.
# NullProvider silencieux si la clé est vide (comportement inchangé).
tavily_api_key: str = Field(
    default="",
    validation_alias=AliasChoices("TAVILY_API_KEY", "SHUGU_TAVILY_API_KEY"),
    description="Clé API Tavily pour web search (free tier 1000 req/mois). "
                "Si vide, Tavily est ignoré par WebSearchAggregator. "
                "Env: TAVILY_API_KEY ou SHUGU_TAVILY_API_KEY.",
)
brave_api_key: str = Field(
    default="",
    validation_alias=AliasChoices("BRAVE_API_KEY", "SHUGU_BRAVE_API_KEY"),
    description="Clé API Brave Search (free tier 2000 req/mois). "
                "Utilisée en fallback si Tavily est absent/timeout/429. "
                "Si vide, Brave est ignoré par WebSearchAggregator. "
                "Env: BRAVE_API_KEY ou SHUGU_BRAVE_API_KEY.",
)
# D3 ARBITRÉ — default=True : le streaming est actif dès le merge de PR2.
# Bisect-safety assurée par le découpage PR (PR2 doit merger avant PR3).
voice_streaming_enabled: bool = Field(
    default=True,
    validation_alias=AliasChoices(
        "VOICE_STREAMING_ENABLED", "SHUGU_VOICE_STREAMING_ENABLED"
    ),
    description="Active le pipeline streaming TTS+LLM+barge-in dans _handle_turn_streaming. "
                "ON par défaut — le pipeline Sprint B one-shot reste accessible via False. "
                "Requis=True pour que la barge-in PR3 fonctionne. "
                "Env: SHUGU_VOICE_STREAMING_ENABLED (ou VOICE_STREAMING_ENABLED).",
)
# D7 ARBITRÉ — champ Settings dédié (pas de constante inline).
voice_web_injection_threshold: float = Field(
    default=0.7,
    ge=0.0,
    le=1.0,
    validation_alias=AliasChoices(
        "VOICE_WEB_INJECTION_THRESHOLD", "SHUGU_VOICE_WEB_INJECTION_THRESHOLD"
    ),
    description="Score injection_detector au-delà duquel un snippet web est rejeté "
                "(protection prompt injection via résultats Tavily/Brave). "
                "Défaut 0.7. Bornes [0.0, 1.0]. "
                "Env: SHUGU_VOICE_WEB_INJECTION_THRESHOLD.",
)
```

---

## 3. Signatures Python typées

### 3.1 `regie/web_search.py` — Provider + impl Tavily + Brave + Aggregator

D1 ARBITRÉ : Tavily + Brave fallback dès PR1. `WebSearchAggregator` parcourt la liste
de providers dans l'ordre et retourne les résultats du premier qui répond. Les providers
dont la clé est vide sont exclus de la liste à la construction (ils ne ralentissent pas).

```python
"""Web search providers — Tavily (primary) + Brave (fallback) via httpx direct.

Pas de dépendance externe supplémentaire : httpx est déjà core.
SSRF guard : les queries sont des chaînes plain-text, jamais des URLs — les providers
font le réseau en leur nom. On ne fetch pas d'URL arbitraire côté Python.

Latence attendue depuis FR :
  Tavily  : ~300-600ms RTT (snippets pré-résumés, pas de scraping)
  Brave   : ~200-500ms RTT (résultats bruts, extraction snippet intégrée)
  Total path WEB_SEARCH : ~700-1000ms TTFB (documenté §7.4)
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

import httpx
import structlog

from ...config import Settings

log = structlog.get_logger(__name__)

_SNIPPET_MAX_CHARS = 300
_MAX_RESULTS = 3
_PROVIDER_TIMEOUT_S = 3.0   # par provider — Aggregator = max 2× si les deux échouent

_TAVILY_SEARCH_URL = "https://api.tavily.com/search"
_BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"


@runtime_checkable
class WebSearchProvider(Protocol):
    """Interface minimaliste — une seule méthode publique."""

    async def run(self, query: str) -> list[str]:
        """Retourne une liste de snippets texte (≤ _MAX_RESULTS items).

        Retourne [] si pas de clé API, timeout, rate-limit ou erreur réseau.
        Ne lève jamais — l'appelant ne doit pas crash sur une absence de web search.
        """
        ...


class TavilyProvider:
    """Tavily Search API — free tier 1000 req/mois.

    https://docs.tavily.com/docs/tavily-api/rest_api
    POST /search avec search_depth="basic", max_results=3.
    Retourne directement les snippets résumés (champ "content" par résultat).
    Format réponse :
        {"results": [{"title": "...", "url": "...", "content": "...", "score": 0.9}, ...]}
    """

    def __init__(self, settings: Settings) -> None:
        self._api_key = settings.tavily_api_key
        self._timeout = httpx.Timeout(_PROVIDER_TIMEOUT_S)

    async def run(self, query: str) -> list[str]:
        """Fetch snippets Tavily. Retourne [] si clé absente ou erreur."""
        if not self._api_key:
            log.debug("voice.websearch.no_key", provider="tavily")
            return []

        payload = {
            "api_key": self._api_key,
            "query": query,
            "search_depth": "basic",
            "max_results": _MAX_RESULTS,
            "include_answer": False,
            "include_raw_content": False,
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(_TAVILY_SEARCH_URL, json=payload)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                log.warning("voice.websearch.rate_limited", provider="tavily")
            else:
                log.warning(
                    "voice.websearch.http_error",
                    status=exc.response.status_code,
                    provider="tavily",
                )
            return []
        except (httpx.TimeoutException, httpx.RequestError) as exc:
            log.warning("voice.websearch.network_error", error=str(exc), provider="tavily")
            return []

        results = data.get("results", [])
        snippets: list[str] = []
        for r in results[:_MAX_RESULTS]:
            content = (r.get("content") or r.get("snippet") or "").strip()
            if content:
                snippets.append(content[:_SNIPPET_MAX_CHARS])

        log.info("voice.websearch.ok", count=len(snippets), provider="tavily")
        return snippets


class BraveProvider:
    """Brave Search API — free tier 2000 req/mois.

    https://api.search.brave.com/app/documentation/web-search/get-started
    GET /res/v1/web/search?q=<query>&count=3
    Headers: Accept: application/json, Accept-Encoding: gzip, X-Subscription-Token: <key>
    Retourne des résultats bruts (pas pré-résumés comme Tavily).
    Extraction snippet : champ "description" de chaque résultat web.
    Format réponse :
        {"web": {"results": [{"title": "...", "url": "...", "description": "..."}, ...]}}
    """

    def __init__(self, settings: Settings) -> None:
        self._api_key = settings.brave_api_key
        self._timeout = httpx.Timeout(_PROVIDER_TIMEOUT_S)

    async def run(self, query: str) -> list[str]:
        """Fetch snippets Brave Search. Retourne [] si clé absente ou erreur."""
        if not self._api_key:
            log.debug("voice.websearch.no_key", provider="brave")
            return []

        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": self._api_key,
        }
        params = {
            "q": query,
            "count": _MAX_RESULTS,
            "text_decorations": False,
            "search_lang": "fr",
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(
                    _BRAVE_SEARCH_URL,
                    headers=headers,
                    params=params,
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                log.warning("voice.websearch.rate_limited", provider="brave")
            else:
                log.warning(
                    "voice.websearch.http_error",
                    status=exc.response.status_code,
                    provider="brave",
                )
            return []
        except (httpx.TimeoutException, httpx.RequestError) as exc:
            log.warning("voice.websearch.network_error", error=str(exc), provider="brave")
            return []

        web_results = data.get("web", {}).get("results", [])
        snippets: list[str] = []
        for r in web_results[:_MAX_RESULTS]:
            description = (r.get("description") or r.get("extra_snippets", [""])[0] or "").strip()
            if description:
                snippets.append(description[:_SNIPPET_MAX_CHARS])

        log.info("voice.websearch.ok", count=len(snippets), provider="brave")
        return snippets


class WebSearchAggregator:
    """Circuit-breaker simple sur une liste ordonnée de providers.

    Essaie chaque provider dans l'ordre. Retourne dès qu'un provider renvoie
    des résultats non vides. Si tous échouent, retourne [].

    Circuit-breaker : pas d'état persistant inter-requêtes (Sprint C). Un provider
    qui timeout à la requête N est réessayé à la requête N+1. Si un suivi des
    failures consécutives devient nécessaire, c'est Sprint H.

    Usage standard (construit dans ShuguVoiceAgent.__init__) :
        aggregator = WebSearchAggregator.from_settings(settings)
        snippets = await aggregator.run(query)
    """

    def __init__(self, providers: list[WebSearchProvider]) -> None:
        # Only keep providers that have a key configured (empty-key providers
        # return [] immediately but waste a coroutine frame — filter at construction).
        self._providers = providers

    @classmethod
    def from_settings(cls, settings: Settings) -> "WebSearchAggregator":
        """Factory — construit la liste ordonnée Tavily → Brave selon les clés présentes.

        Un provider dont la clé est vide est quand même inclus dans la liste —
        il retourne [] instantanément et laisse l'Aggregator passer au suivant.
        C'est délibéré : la logique "clé vide = NullProvider" est encapsulée dans
        chaque provider, pas dans l'Aggregator.
        """
        return cls(providers=[TavilyProvider(settings), BraveProvider(settings)])

    async def run(self, query: str) -> list[str]:
        """Essaie les providers dans l'ordre, retourne le premier résultat non vide."""
        for provider in self._providers:
            snippets = await provider.run(query)
            if snippets:
                return snippets
        log.info("voice.websearch.all_providers_empty", query_len=len(query))
        return []


class NullProvider:
    """Provider no-op — utilisé dans les tests ou quand tous les providers sont vides."""

    async def run(self, query: str) -> list[str]:  # noqa: ARG002
        return []
```

### 3.2 `regie/prompt_builder.py`

```python
"""Construction du system prompt augmenté avec contexte web et persona Shugu.

Remplace `ShuguVoiceAgent._build_sprint_b_system_prompt()` (inline, Sprint B)
par un module testable séparé. L'appelant passe les snippets déjà filtrés par
injection_detector.
"""
from __future__ import annotations

from .intent_classifier import Intent, IntentMatch

_PERSONA_BASE = (
    "Tu es Shugu, une streameuse virtuelle francophone enthousiaste et bienveillante. "
    "Réponds en 1 à 2 phrases concises et naturelles."
)

_WEB_CONTEXT_OPEN = "[WEB_CONTEXT]"
_WEB_CONTEXT_CLOSE = "[/WEB_CONTEXT]"


def build(intent_match: IntentMatch, web_snippets: list[str]) -> str:
    """Construit le system prompt pour un tour.

    Args:
        intent_match: résultat de intent_classifier.classify()
        web_snippets: liste de snippets déjà sanitisés (vide si intent != WEB_SEARCH
                      ou si la recherche n'a rien retourné)

    Returns:
        System prompt complet prêt pour LocalLLM.generate()
    """
    parts = [_PERSONA_BASE]

    if intent_match.intent == Intent.WEB_SEARCH:
        if web_snippets:
            joined = " | ".join(web_snippets)
            parts.append(
                f"Contexte web récupéré pour répondre à la question : "
                f"{_WEB_CONTEXT_OPEN}{joined}{_WEB_CONTEXT_CLOSE} "
                "Utilise ce contexte pour répondre factuellement et brièvement."
            )
        else:
            # Pas de clé ou recherche vide — reprend le fallback Sprint B
            parts.append(
                "L'utilisateur cherche une information factuelle. "
                "Indique que tu ne peux pas accéder à internet pour l'instant "
                "et propose ton aide autrement."
            )

    elif intent_match.intent == Intent.EMOTION:
        parts.append(
            "L'utilisateur exprime une émotion forte. "
            "Réagis avec empathie et enthousiasme appropriés."
        )

    elif intent_match.intent == Intent.EMOTE:
        parts.append(
            "L'utilisateur utilise une salutation ou formule de politesse. "
            "Réponds chaleureusement."
        )

    return " ".join(parts)
```

### 3.3 `chunker.py` — Sentence boundary splitter

```python
"""Chunker prosodique — accumule les tokens LLM et émet des phrases complètes.

Règles d'émission (par ordre de priorité) :
  1. Ponctuation forte suivie d'espace ou fin de stream : . ! ?
  2. Virgule + cumul >= 4 mots depuis le dernier flush
  3. Max 200 chars (évite les chunks trop longs pour Piper)
  4. Flush forcé à la fin du stream (tokens restants)

Abréviations FR protégées (ne déclenchent pas l'émission) :
  M. Mme. Dr. St. etc. ex. cf. fig. vol.
  + chiffres décimaux : 3.14 → le point ne termine pas la phrase

Usage :
    chunker = SentenceChunker()
    async for sentence in chunker.feed_stream(token_iterator):
        await tts.synthesize_sentence(sentence)
"""
from __future__ import annotations

import re
from collections.abc import AsyncIterator

# Abréviations qui se terminent par un point sans clore la phrase
_ABBREV_RE = re.compile(
    r"\b(M|Mme|Mlle|Dr|Pr|St|etc|ex|cf|fig|vol|art|chap|n°|p)\.$",
    re.IGNORECASE,
)
# Chiffre suivi d'un point (nombre décimal ou item listé "1. Bonjour")
# → on laisse le chunker émettre sur "1. " car c'est un début de liste —
# l'effet sur la prosodie TTS est neutre.
_DECIMAL_RE = re.compile(r"\d\.$")

_STRONG_PUNCT = frozenset(".!?")
_MAX_CHUNK_CHARS = 200
_MIN_WORDS_COMMA = 4


class SentenceChunker:
    """Stateful chunker. Une instance par tour LLM (pas thread-safe)."""

    def __init__(self) -> None:
        self._buf: list[str] = []
        self._word_count: int = 0
        self._char_count: int = 0

    def _buf_text(self) -> str:
        return "".join(self._buf).strip()

    def _should_emit_on_punct(self, token: str) -> bool:
        """Retourne True si le token clôt une phrase (ponctuation forte)."""
        stripped = token.rstrip()
        if not stripped:
            return False
        last_char = stripped[-1]
        if last_char not in _STRONG_PUNCT:
            return False
        # Protect abbreviations
        buf_plus = self._buf_text() + stripped
        if _ABBREV_RE.search(buf_plus):
            return False
        return True

    def _flush(self) -> str | None:
        text = self._buf_text()
        self._buf.clear()
        self._word_count = 0
        self._char_count = 0
        return text if text else None

    async def feed_stream(
        self,
        tokens: AsyncIterator[str],
    ) -> AsyncIterator[str]:
        """Yield complete sentences as they accumulate from an async token stream."""
        async for token in tokens:
            self._buf.append(token)
            self._char_count += len(token)
            # Count words approximately (spaces as delimiter)
            self._word_count += token.count(" ")

            emit = False

            # Rule 1 — strong punctuation
            if self._should_emit_on_punct(token):
                emit = True

            # Rule 2 — comma + enough words
            elif "," in token and self._word_count >= _MIN_WORDS_COMMA:
                emit = True

            # Rule 3 — max chars guard
            elif self._char_count >= _MAX_CHUNK_CHARS:
                emit = True

            if emit:
                chunk = self._flush()
                if chunk:
                    yield chunk

        # Rule 4 — flush remainder
        remainder = self._flush()
        if remainder:
            yield remainder
```

### 3.4 `llm_local.py` — `stream()` implémenté + cancel support

Ajouts dans la classe existante `LocalLLM`. Le corps de `__init__` et `generate()` sont
**inchangés** — seules les deux méthodes ci-dessous sont ajoutées/remplacées :

```python
import asyncio
import threading
from collections.abc import AsyncIterator

class LocalLLM:
    # ... __init__, _ensure_loaded, generate — inchangés ...

    async def stream(
        self,
        system: str,
        messages: Sequence[dict[str, str]],
        max_tokens: int = 512,
        temperature: float = 0.85,
        enable_thinking: bool = False,
    ) -> AsyncIterator[str]:
        """Streaming token generation via llama-cpp-python create_chat_completion(stream=True).

        Tient le asyncio.Lock pendant toute la durée du streaming (llama-cpp-python
        n'est pas réentrant — aucun autre appel generate/stream ne peut s'intercaler).

        Cancel coopératif :
            - Appeler cancel() depuis une autre coroutine pose self._cancel_event.
            - Le stopping_criteria callback lit l'event dans le thread executor.
            - La génération s'arrête au prochain token (max 1 token de délai).
            - Le Lock est relâché proprement à la fin du finally.

        Règle invariant : toujours appeler stream() dans un bloc `async for` ou
        consommer complètement le générateur pour garantir le relâchement du Lock.
        """
        async with self._lock:
            self._ensure_loaded()
            self._cancel_event.clear()

            full_messages = [{"role": "system", "content": system}] + list(messages)
            loop = asyncio.get_running_loop()

            # Queue bridge entre le thread executor (sync generator) et la coroutine
            queue: asyncio.Queue[str | None] = asyncio.Queue()

            def _run_sync() -> None:
                """Runs in executor thread. Pumps tokens into queue via call_soon_threadsafe."""
                cancel_ev = self._cancel_event

                def _stop_cb(
                    input_ids,  # noqa: ANN001 — positional, matches llama_cpp signature
                    scores,  # noqa: ANN001
                ) -> bool:
                    """Return True to stop generation (llama_cpp stopping_criteria convention)."""
                    return cancel_ev.is_set()

                try:
                    for chunk in self._llm.create_chat_completion(
                        messages=full_messages,
                        max_tokens=max_tokens,
                        temperature=temperature,
                        stream=True,
                        chat_template_kwargs={"enable_thinking": enable_thinking},
                        stopping_criteria=[_stop_cb],
                    ):
                        delta = (
                            chunk.get("choices", [{}])[0]
                            .get("delta", {})
                            .get("content") or ""
                        )
                        if delta:
                            loop.call_soon_threadsafe(queue.put_nowait, delta)
                finally:
                    # Sentinel None signals end-of-stream to the consumer
                    loop.call_soon_threadsafe(queue.put_nowait, None)

            executor_task = loop.run_in_executor(None, _run_sync)

            try:
                while True:
                    token = await queue.get()
                    if token is None:
                        break
                    yield token
            finally:
                # Ensure executor finishes even if consumer broke early
                self._cancel_event.set()
                await executor_task

    def cancel(self) -> None:
        """Signal the active stream() to stop at the next token boundary.

        Safe to call from any coroutine. No-op if no stream is running.
        The asyncio.Lock will be released once the executor thread exits.
        """
        self._cancel_event.set()

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._llm = None
        self._lock = asyncio.Lock()
        self._cancel_event: threading.Event = threading.Event()
```

Note : `threading.Event` est thread-safe et lisible depuis le thread executor sans
`asyncio` overhead. `asyncio.Event` ne peut pas être utilisé depuis un thread non-asyncio
— c'est intentionnel ici.

### 3.5 `tts_local.py` — `synthesize_stream()` implémenté (Voie B)

**Décision technique : Voie B (subprocess par phrase).**

Voie A (processus Piper persistant avec stdin continu) est abandonnée pour Sprint C :
- Piper ne fournit pas d'EOF marker natif entre phrases ; il faudrait inventer un
  protocole (ex: `--json-input` avec des objets JSON séparés), ce qui n'est pas
  documenté et brittle.
- Le cancel en barge-in Voie A = fermer stdin + tuer le processus, identique à Voie B.
- L'overhead de spawn d'un subprocess Piper par phrase (~50-100ms) est absorbé par
  la latence réseau/audio (~10ms) et la durée de parole de la phrase (>500ms).

Voie B est correcte pour Sprint C. La Voie A peut être explorée post-bench Sprint D si
les métriques montrent un gain réel de latence.

```python
# Dans la classe PiperTTS existante :

async def synthesize_stream(
    self,
    sentences: AsyncIterator[str],
) -> AsyncIterator[bytes]:
    """Streaming synthesis : yield PCM chunks dès qu'une phrase est synthétisée.

    Mode Voie B : un subprocess Piper par phrase (chunker prosodique en amont).
    Cancel : caller abandonne l'async for → le finally de chaque synthesize()
    one-shot termine proprement via aclose() (déjà implémenté).

    Args:
        sentences: async iterator de phrases complètes (issues de SentenceChunker)

    Yields:
        bytes: PCM s16le 22050 Hz mono brut, une phrase à la fois
    """
    async for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        pcm = await self.synthesize(sentence)
        if pcm:
            yield pcm
```

La signature prend `AsyncIterator[str]` (phrases), pas `AsyncIterator[str]` (tokens).
Le chunker fait la frontière. `synthesize_stream` est délibérément minimal.

### 3.6 `livekit_agent.py` — modifications Sprint C

Trois ajouts dans la classe `ShuguVoiceAgent` et sa fonction `entrypoint`.

#### 3.6.1 Remplacement du type backpressure (hook Sprint D)

Remplacer `self._processing: bool` par un enum 3 états :

```python
from enum import Enum

class _AgentState(Enum):
    LISTENING = "LISTENING"
    PROCESSING = "PROCESSING"
    SPEAKING = "SPEAKING"
```

Remplacer dans `__init__` :
```python
# Avant (Sprint B)
self._processing: bool = False

# Après (Sprint C)
self._state: _AgentState = _AgentState.LISTENING
```

Adapter les gardes dans `_drain_and_transcribe` et `_process_utterance` :
```python
# _drain_and_transcribe — VAD END_OF_SPEECH handler
if self._state != _AgentState.LISTENING:
    log.info("voice.audio.dropped", reason="not in LISTENING state", state=self._state.value)
    continue
self._state = _AgentState.PROCESSING

# _drain_and_transcribe — VAD START_OF_SPEECH handler (NOUVEAU Sprint C)
elif vad_event.type == agents_vad.VADEventType.START_OF_SPEECH:
    if self._state == _AgentState.SPEAKING:
        log.info("voice.bargein.detected")
        await self._cancel_speaking()

# _process_utterance — finally
self._state = _AgentState.LISTENING
```

#### 3.6.2 `_cancel_speaking()` — barge-in cancel safe

```python
async def _cancel_speaking(self) -> None:
    """Cancel safe : stop LLM streaming + TTS subprocess en cours.

    Coopératif — ne kill pas le thread executor brutalement.
    Le Lock asyncio est relâché par le stream() finally dans le thread.
    Appelé uniquement depuis _drain_and_transcribe lors d'un START_OF_SPEECH
    en état SPEAKING.

    Sprint D remplace cette méthode par la FSM INTERRUPTED → décision LLM mini-prompt.
    Le hook est posé ici : même signature, même point d'appel.
    """
    log.info("voice.bargein.cancelling")
    # 1. Stop LLM token generation (cooperative via threading.Event)
    self._llm.cancel()
    # 2. Stop active TTS subprocess (piper.exe)
    await self._tts.aclose()
    # 3. State → LISTENING (prêt pour le prochain tour)
    self._state = _AgentState.LISTENING
    log.info("voice.bargein.cancelled")
```

#### 3.6.3 `_handle_turn_streaming()` — pipeline streaming

Ajouté en parallèle de `_handle_turn` existant. `_handle_turn` Sprint B est **conservé
intact** — il reste le chemin actif quand `voice_streaming_enabled=False`.

```python
async def _handle_turn_streaming(self, transcript: str) -> None:
    """Pipeline streaming Sprint C (activé par voice_streaming_enabled=True).

    Flow :
      1. Classify intent
      2. WEB_SEARCH → TavilyProvider.run() → snippets sanitisés → prompt augmenté
      3. LocalLLM.stream() → tokens → SentenceChunker → phrases
      4. PiperTTS.synthesize_stream(phrases) → PCM chunks → _resample_and_publish
      5. Barge-in : START_OF_SPEECH → _cancel_speaking() interrompt 3+4

    Note latence WEB_SEARCH : Tavily ajoute ~300-600ms RTT.
    Le budget TTFB pour ce path est donc ~700-1000ms, hors de la cible 330-450ms
    du chemin CHAT. C'est attendu et documenté. Un filler "attends, je cherche..."
    joué immédiatement atténuerait la perception — implémenté Sprint D (fillers bank).
    """
    if not transcript:
        return

    try:
        intent_match = intent_classifier.classify(transcript)
        log.info(
            "voice.regie.intent",
            intent=intent_match.intent.value,
            matched_terms=intent_match.matched_terms,
            pipeline="streaming",
        )

        # Step 1 — Web search pre-fetch si intent WEB_SEARCH
        web_snippets: list[str] = []
        if intent_match.intent == Intent.WEB_SEARCH:
            raw_snippets = await self._web_search.run(transcript)
            # Sanitize : passe chaque snippet dans injection_detector
            # Threshold depuis Settings (D7 ARBITRÉ — voice_web_injection_threshold).
            from ..adapters.injection_detector import scan as _scan
            threshold = self._settings.voice_web_injection_threshold
            for snippet in raw_snippets:
                result = _scan(snippet)
                if result.score < threshold:
                    web_snippets.append(snippet)
                else:
                    log.warning(
                        "voice.websearch.snippet_rejected",
                        score=result.score,
                        threshold=threshold,
                    )

        # Step 2 — Build augmented prompt
        system = prompt_builder.build(intent_match, web_snippets)
        messages: list[dict[str, str]] = [{"role": "user", "content": transcript}]

        # Step 3+4 — LLM stream → chunker → TTS stream → publish
        self._state = _AgentState.SPEAKING

        chunker = SentenceChunker()
        token_stream = self._llm.stream(
            system,
            messages,
            max_tokens=300,
            enable_thinking=False,
        )
        sentence_stream = chunker.feed_stream(token_stream)

        async for pcm_chunk in self._tts.synthesize_stream(sentence_stream):
            if self._state != _AgentState.SPEAKING:
                # Barge-in occurred mid-stream — stop publishing
                log.info("voice.bargein.stream_interrupted")
                break
            await self._resample_and_publish(pcm_chunk)

        log.info("voice.handle_turn_streaming.done")

    except Exception as exc:
        log.error("voice.handle_turn_streaming.error", error=str(exc))
    finally:
        if self._state == _AgentState.SPEAKING:
            self._state = _AgentState.LISTENING
```

#### 3.6.4 Dispatch dans `_process_utterance`

Modifier `_process_utterance` pour dispatcher selon le flag :

```python
async def _process_utterance(self, combined: rtc.AudioFrame) -> None:
    try:
        # ... resampling 48->16 kHz, transcribe — inchangé ...
        transcript = await self._stt.transcribe(pcm_bytes, language="fr")
        if self._settings.voice_streaming_enabled:
            await self._handle_turn_streaming(transcript)
        else:
            await self._handle_turn(transcript)
    finally:
        if self._state == _AgentState.PROCESSING:
            self._state = _AgentState.LISTENING
```

#### 3.6.5 Constructeur — injection `WebSearchProvider`

Ajouter dans `ShuguVoiceAgent.__init__` :
```python
from .regie.web_search import WebSearchAggregator, WebSearchProvider
from .regie import prompt_builder
from .chunker import SentenceChunker

# Dans __init__ :
# WebSearchAggregator.from_settings() construit la liste Tavily → Brave.
# Si les deux clés sont vides, run() retourne [] et prompt_builder utilise le fallback.
self._web_search: WebSearchProvider = WebSearchAggregator.from_settings(settings)
```

Modifier `entrypoint` pour passer `settings` à `ShuguVoiceAgent` (déjà fait en
Sprint B via le paramètre `settings: Settings` du constructeur — aucun changement
structurel).

---

## 4. Flow step-by-step complet

```
[LiveKit room Docker localhost:7880]
  Participant publie Opus 48 kHz mono 20 ms/frame

ETAPE 1 — Accumulation VAD (inchangée Sprint B)
  VADStream.push_frame() par frame
  START_OF_SPEECH event :
    si state == SPEAKING → _cancel_speaking() → state = LISTENING  ← NOUVEAU barge-in
    sinon : ignore
  END_OF_SPEECH event :
    si state != LISTENING → drop + log
    sinon : state = PROCESSING → create_task(_process_utterance(frames))

ETAPE 2 — Resampling 48→16 kHz + WhisperSTT (inchangé Sprint B)
  pcm_bytes → WhisperSTT.transcribe() → transcript
  si transcript == "" → state = LISTENING, retour

ETAPE 3 — Dispatch pipeline
  si voice_streaming_enabled == False : _handle_turn() (Sprint B one-shot)
  si voice_streaming_enabled == True  : _handle_turn_streaming() (Sprint C)

  [Chemin _handle_turn_streaming]

ETAPE 4 — Régie intent + web search (D1 : Tavily → Brave fallback)
  intent_match = intent_classifier.classify(transcript)
  si intent == WEB_SEARCH :
    web_snippets = await WebSearchAggregator.run(transcript)
      → essaie TavilyProvider.run() (~300-600ms RTT)
      → si [] (timeout/429/clé vide) → essaie BraveProvider.run() (~200-500ms RTT)
      → si [] → retourne [] (fallback texte dans prompt_builder)
    filtrer via injection_detector (score < voice_web_injection_threshold)
    LATENCE PATH WEB_SEARCH (Tavily ok)    : ~700-1000ms TTFB
    LATENCE PATH WEB_SEARCH (Brave fallback) : ~1000-1500ms TTFB (Tavily timeout + Brave)
    Les deux sont hors cible 330-450ms — attendu, documenté. Filler Sprint D.
  sinon :
    web_snippets = []

ETAPE 5 — Build system prompt
  system = prompt_builder.build(intent_match, web_snippets)
  messages = [{"role": "user", "content": transcript}]

ETAPE 6 — LLM streaming (LocalLLM.stream)
  async with self._lock :  ← tenu pendant toute la génération
    create_chat_completion(stream=True, stopping_criteria=[cancel_cb])
    pump tokens via loop.call_soon_threadsafe → asyncio.Queue
  state = SPEAKING

ETAPE 7 — Chunker prosodique (SentenceChunker)
  accumule tokens jusqu'à frontière de phrase (. ! ? ou virgule+4 mots ou 200 chars)
  yield chaque phrase complète

ETAPE 8 — TTS streaming (PiperTTS.synthesize_stream)
  pour chaque phrase complète :
    spawn subprocess piper.exe (Voie B)
    communicate(phrase.encode()) → PCM s16le 22050 Hz
    yield PCM dès retour subprocess (~80ms par phrase)

ETAPE 9 — Resample + publish (inchangé Sprint B)
  22050→48000 Hz via rtc.AudioResampler(HIGH)
  await audio_source.capture_frame() pour chaque frame 10ms

  si state != SPEAKING pendant le loop → break (barge-in intercalé)

BARGE-IN PATH (parallèle, déclenché par VAD START_OF_SPEECH)
  _cancel_speaking() :
    1. llm.cancel()  → cancel_event.set() → stopping_criteria retourne True au prochain token
    2. tts.aclose()  → terminate piper subprocess actif
    3. state = LISTENING
  _handle_turn_streaming finally : détecte state != SPEAKING → sort proprement
  Le asyncio.Lock est relâché par stream() finally dans le thread executor
  Prochain END_OF_SPEECH peut démarrer un nouveau tour proprement
```

---

## 5. Découpage PRs (3 PRs maintenus — D1 absorbe dans PR1)

### Justification 3 PRs maintenus

D1 (Brave fallback) ajoute ~150 lignes à `web_search.py` (BraveProvider + WebSearchAggregator).
La question est : est-ce que ça force 4 PRs ?

Non. Voici pourquoi :

- `web_search.py` est un fichier autonome sans dépendance circulaire. Il peut atteindre
  ~350-400 lignes (3 classes + NullProvider + constantes) et rester sous la limite 500 lignes.
- BraveProvider et TavilyProvider ont exactement le même contrat (`run() -> list[str]`).
  Ils testent la même interface — les tests de l'un servent de modèle à l'autre.
  L'ajout de tests BraveProvider dans `test_web_search.py` alourdit le fichier de test
  mais pas le diff de code production.
- La bisect-safety est assurée par la granularité PR, pas par la taille des fichiers.
  Un PR1 plus épais mais cohérent (toute la couche web search) est plus bisect-friendly
  qu'un PR1.5 artificiel.

**Verdict : 3 PRs.**

- **PR1** (web search) : `TavilyProvider` + `BraveProvider` + `WebSearchAggregator` + `prompt_builder` + wiring `_handle_turn`. Diff ~400 lignes. Pas de dépendance sur le streaming.
- **PR2** (streaming) : `LocalLLM.stream()` + `SentenceChunker` + `PiperTTS.synthesize_stream()` + `_handle_turn_streaming`. Diff ~300 lignes. `voice_streaming_enabled=True` par défaut (D3) — actif dès merge.
- **PR3** (barge-in) : `_AgentState` enum + `_cancel_speaking()` + handler `START_OF_SPEECH`. Diff ~80 lignes. Requiert PR2 mergé.

---

### PR1 — Web search (régie fonctionnelle, Tavily + Brave)

Scope : rendre le path `WEB_SEARCH` réellement fonctionnel dans le pipeline *one-shot*
existant (`_handle_turn`). Inclut BraveProvider + WebSearchAggregator (D1).
Aucune modification du pipeline streaming.

Fichiers touchés :

| Fichier | Action |
|---|---|
| `backend/shugu/config.py` | Ajouter `tavily_api_key`, `brave_api_key`, `voice_streaming_enabled` (default=True), `voice_web_injection_threshold` |
| `backend/shugu/voice/regie/web_search.py` | CRÉER — `WebSearchProvider`, `TavilyProvider`, `BraveProvider`, `WebSearchAggregator`, `NullProvider` (~350 lignes) |
| `backend/shugu/voice/regie/prompt_builder.py` | CRÉER — `build(intent_match, web_snippets) -> str` |
| `backend/shugu/voice/livekit_agent.py` | Dans `_handle_turn` : remplacer le bloc `if intent == WEB_SEARCH` par `WebSearchAggregator.from_settings(settings).run()` + `prompt_builder.build()`. Ajouter `self._web_search` dans `__init__`. Sanitiser snippets via `injection_detector.scan` + `voice_web_injection_threshold`. |
| `backend/tests/unit/voice/test_web_search.py` | CRÉER — tests §6.1 (Tavily + Brave + Aggregator) |

Gate de merge : `pytest -m "not integration"` vert, ruff vert, pas de régression
`test_livekit_agent.py` existant.

---

### PR2 — Streaming TTS+LLM + chunker

Scope : implémenter le pipeline streaming. `voice_streaming_enabled=True` par défaut
(D3 ARBITRÉ) — le streaming est actif immédiatement après merge.

Fichiers touchés :

| Fichier | Action |
|---|---|
| `backend/shugu/voice/llm_local.py` | Implémenter `stream()` + `cancel()`. Ajouter `self._cancel_event: threading.Event` dans `__init__`. |
| `backend/shugu/voice/tts_local.py` | Implémenter `synthesize_stream()` (Voie B — trivial, ~15 lignes). |
| `backend/shugu/voice/chunker.py` | CRÉER — `SentenceChunker` (~80 lignes) |
| `backend/shugu/voice/livekit_agent.py` | Ajouter `_handle_turn_streaming()`. Dispatch dans `_process_utterance` selon `voice_streaming_enabled`. |
| `backend/tests/unit/voice/test_chunker.py` | CRÉER — tests §6.2 |
| `backend/tests/unit/voice/test_tts_local.py` | Ajouter tests `synthesize_stream` §6.3 |
| `backend/tests/unit/voice/test_livekit_agent.py` | Ajouter tests streaming §6.4 |

Gate de merge : `pytest -m "not integration"` vert, ruff vert.
`voice_streaming_enabled=True` par défaut (D3) — le coder valide le pipeline streaming
complet avant de créer le PR (smoke test §5.3 du blueprint Sprint B adapté, avec
`SHUGU_VOICE_STREAMING_ENABLED=true` superflu mais inoffensif).

---

### PR3 — Barge-in basique (3 états + cancel)

Scope : activer la détection barge-in et le cancel safe. Requiert PR2 mergé.
`voice_streaming_enabled=True` est déjà le défaut depuis PR2.

Fichiers touchés :

| Fichier | Action |
|---|---|
| `backend/shugu/voice/livekit_agent.py` | Remplacer `_processing: bool` par `_AgentState` enum. Ajouter `_cancel_speaking()`. Ajouter le handler `START_OF_SPEECH` dans `_drain_and_transcribe`. Adapter les gardes `_process_utterance` et `_handle_turn_streaming`. |
| `backend/tests/unit/voice/test_livekit_agent.py` | Ajouter tests barge-in §6.5 |

Gate de merge : `pytest -m "not integration"` vert, ruff vert.
Le barge-in est observable directement (plus besoin de flipper un flag).

---

## 6. Plan de tests

Tous les tests utilisent `asyncio_mode = "auto"` (déjà configuré `pyproject.toml`).
Mocks : `respx` pour les appels httpx (déjà en dev deps), `unittest.mock.AsyncMock`
pour les subprocesses et les iterators async.

### 6.1 `test_web_search.py`

Trois groupes : TavilyProvider, BraveProvider, WebSearchAggregator + NullProvider.

Fixtures communes :
```python
import pytest
import httpx
import respx
from httpx import Response

from shugu.voice.regie.web_search import (
    TavilyProvider, BraveProvider, WebSearchAggregator, NullProvider,
    WebSearchProvider, _TAVILY_SEARCH_URL, _BRAVE_SEARCH_URL,
)

_TAVILY_RESULT = {"results": [
    {"content": "Le PIB de la France est de 2800 milliards d'euros.", "url": "https://example.com"},
    {"content": "Deuxième résultat.", "url": "https://example2.com"},
]}
_BRAVE_RESULT = {"web": {"results": [
    {"description": "La France PIB 2024 selon INSEE.", "url": "https://insee.fr"},
]}}

@pytest.fixture
def settings_tavily(mock_settings):
    mock_settings.tavily_api_key = "tavily-test-key"
    mock_settings.brave_api_key = ""
    return mock_settings

@pytest.fixture
def settings_brave(mock_settings):
    mock_settings.tavily_api_key = ""
    mock_settings.brave_api_key = "brave-test-key"
    return mock_settings

@pytest.fixture
def settings_both(mock_settings):
    mock_settings.tavily_api_key = "tavily-test-key"
    mock_settings.brave_api_key = "brave-test-key"
    return mock_settings
```

#### TavilyProvider

| # | Nom du test | Assertion clé |
|---|---|---|
| U-WS-1 | `test_tavily_returns_snippets` | `respx.post(TAVILY_URL).mock(Response(200, json=_TAVILY_RESULT))` → `run()` retourne `["Le PIB...", "Deuxième..."]` |
| U-WS-2 | `test_tavily_rate_limit_returns_empty` | `Response(429)` → `[]`, log `voice.websearch.rate_limited provider=tavily` |
| U-WS-3 | `test_tavily_timeout_returns_empty` | `side_effect=httpx.TimeoutException` → `[]`, pas de raise |
| U-WS-4 | `test_tavily_no_api_key_returns_empty` | `tavily_api_key=""` → `[]` sans appel réseau (respx assert no call) |
| U-WS-5 | `test_tavily_snippet_truncated_at_300_chars` | content = "x" * 500 → snippet len = 300 |
| U-WS-6 | `test_tavily_http_error_non_429_returns_empty` | `Response(503)` → `[]`, log `voice.websearch.http_error status=503` |

#### BraveProvider

| # | Nom du test | Assertion clé |
|---|---|---|
| U-WS-7 | `test_brave_returns_snippets` | `respx.get(BRAVE_URL).mock(Response(200, json=_BRAVE_RESULT))` → `run()` retourne `["La France PIB..."]` |
| U-WS-8 | `test_brave_rate_limit_returns_empty` | `Response(429)` → `[]`, log `provider=brave` |
| U-WS-9 | `test_brave_timeout_returns_empty` | `side_effect=httpx.TimeoutException` → `[]` |
| U-WS-10 | `test_brave_no_api_key_returns_empty` | `brave_api_key=""` → `[]` sans appel réseau |
| U-WS-11 | `test_brave_uses_correct_auth_header` | respx capture la requête → assert header `X-Subscription-Token` == `"brave-test-key"` |
| U-WS-12 | `test_brave_description_field_extracted` | résultat avec `description` uniquement → snippet extrait correctement |

#### WebSearchAggregator

| # | Nom du test | Assertion clé |
|---|---|---|
| U-WS-13 | `test_aggregator_returns_tavily_first` | Tavily mock → résultats. Assert Brave **non appelé** (respx.get(BRAVE_URL) = 0 calls) |
| U-WS-14 | `test_aggregator_falls_back_to_brave_on_tavily_empty` | Tavily mock → `[]` (429). Brave mock → résultats. Assert résultats Brave retournés. |
| U-WS-15 | `test_aggregator_returns_empty_if_all_fail` | Tavily → `[]`, Brave → `[]` → `[]` final, log `voice.websearch.all_providers_empty` |
| U-WS-16 | `test_aggregator_from_settings_tavily_only` | `settings_tavily` → Aggregator construit avec TavilyProvider actif + BraveProvider passif (clé vide → retourne []) |
| U-WS-17 | `test_aggregator_from_settings_brave_only` | `settings_brave` → Tavily retourne [] (clé vide), Brave retourne résultats |
| U-WS-18 | `test_null_provider_always_empty` | `NullProvider().run("anything")` → `[]` |
| U-WS-19 | `test_protocol_compliance_tavily` | `isinstance(TavilyProvider(settings), WebSearchProvider)` = True |
| U-WS-20 | `test_protocol_compliance_brave` | `isinstance(BraveProvider(settings), WebSearchProvider)` = True |
| U-WS-21 | `test_protocol_compliance_aggregator` | `isinstance(WebSearchAggregator([]), WebSearchProvider)` = True |

### 6.2 `test_chunker.py`

| # | Nom du test | Assertion clé |
|---|---|---|
| U-CH-1 | `test_single_sentence_period` | tokens `["Bonjour", " Shugu", "."]` → yield `"Bonjour Shugu."` |
| U-CH-2 | `test_question_mark` | `["Comment", " ça", " va", "?"]` → yield `"Comment ça va?"` |
| U-CH-3 | `test_comma_flushes_after_4_words` | `["Alors", ",", " en", " fait", ",", " je"]` → yield `"Alors, en fait,"` + buffer `" je"` |
| U-CH-4 | `test_max_chars_guard` | 210 chars sans ponctuation → yield dès 200 chars |
| U-CH-5 | `test_abbrev_no_flush` | `["M", ".", " Dupont"]` → pas d'émission prématurée sur "M." |
| U-CH-6 | `test_remainder_flushed_on_stream_end` | `["Salut"]` (pas de ponctuation) → `"Salut"` émis à la fin |
| U-CH-7 | `test_empty_tokens_skipped` | tokens vides ou espaces seuls → aucune émission |
| U-CH-8 | `test_multiple_sentences` | `"Bonjour. Comment ça va?"` tokenisé → 2 yields séquentiels |

Fixture async token iterator :
```python
async def _tokens(*items: str) -> AsyncIterator[str]:
    for t in items:
        yield t
```

### 6.3 Tests streaming TTS (`test_tts_local.py` — ajouts)

| # | Nom du test | Assertion clé |
|---|---|---|
| U-TTS-S1 | `test_synthesize_stream_yields_pcm_per_sentence` | 3 phrases → 3 appels `synthesize()` mockés → 3 yields PCM |
| U-TTS-S2 | `test_synthesize_stream_skips_empty_sentences` | iterator `["Bonjour.", "", "   "]` → 1 seul appel synthesize |
| U-TTS-S3 | `test_synthesize_stream_propagates_cancel` | si la coroutine consommatrice break après le 1er chunk, le 2ème subprocess n'est pas lancé |

Mock pattern pour `synthesize_stream` :
```python
# Mock synthesize() pour retourner rapidement
mock_tts.synthesize = AsyncMock(side_effect=lambda text: b"\x00" * 100 if text else b"")
```

### 6.4 Tests LLM streaming (`test_livekit_agent.py` — ajouts)

| # | Nom du test | Assertion clé |
|---|---|---|
| U-LLM-S1 | `test_stream_yields_tokens` | `stream()` yield les tokens dans l'ordre (mock executor) |
| U-LLM-S2 | `test_cancel_stops_stream` | `llm.cancel()` pendant `stream()` → iterator se termine, Lock relâché |
| U-LLM-S3 | `test_lock_held_during_stream` | deux `stream()` concurrents → deuxième attend que le premier finisse (timestamps non-overlappants) |
| U-LLM-S4 | `test_handle_turn_streaming_calls_pipeline` | mock STT/LLM/TTS/web_search → assert ordre (intent → web_search → stream → synthesize_stream → publish) |

Mock async iterator pour LLM stream :
```python
async def _mock_token_stream(*args, **kwargs) -> AsyncIterator[str]:
    for token in ["Bonjour", " Shugu", "!"]:
        yield token
```

### 6.5 Tests barge-in (`test_livekit_agent.py` — ajouts PR3)

| # | Nom du test | Assertion clé |
|---|---|---|
| U-BI-1 | `test_start_of_speech_while_speaking_calls_cancel` | simuler `VADEventType.START_OF_SPEECH` quand `state == SPEAKING` → assert `llm.cancel()` appelé + `tts.aclose()` appelé |
| U-BI-2 | `test_start_of_speech_while_listening_no_cancel` | `VADEventType.START_OF_SPEECH` quand `state == LISTENING` → `cancel()` non appelé |
| U-BI-3 | `test_state_returns_to_listening_after_cancel` | après `_cancel_speaking()` → `agent._state == _AgentState.LISTENING` |
| U-BI-4 | `test_end_of_speech_accepted_after_cancel` | séquence `SPEAKING → START_OF_SPEECH (cancel) → END_OF_SPEECH` → `_process_utterance` lancé normalement |

---

## 7. Risques techniques et mitigations

### 7.1 Piper subprocess Voie B — crash isolation

**Risque :** si piper.exe crashe sur une phrase particulière (texte malformé, modèle
corrompu), seule cette phrase est perdue — les suivantes sont tentées normalement.

**Mitigation :** `synthesize()` retourne déjà `b""` sur returncode != 0 + log warning.
`synthesize_stream` skippe les `b""` (déjà dans le `if pcm:` guard). Pas de crash
propagé à l'appelant.

**Memory leak :** chaque subprocess est spawn+communicate+wait — pas de processus
orphelin. `proc.communicate()` attend la fin propre. `aclose()` gère les cas de timeout.
Vérifier que le `finally: self._current_proc = None` reste en place après les modifications.

### 7.2 LLM streaming + asyncio.Lock — thread-safety

**Risque :** `cancel_event` est un `threading.Event` lu depuis un thread executor et
posé depuis une coroutine asyncio. La primitif est thread-safe par conception
(implémentation CPython : un simple `condition` interne).

**Risque secondaire :** si le caller fait `asyncio.Task.cancel()` sur la coroutine qui
consomme `stream()`, le `finally` dans `stream()` appelle `await executor_task` qui peut
ne jamais se terminer si le stopping_criteria ne tourne pas assez vite.

**Mitigation :** `finally: self._cancel_event.set(); await executor_task` avec un
`asyncio.wait_for(executor_task, timeout=2.0)` en production pour éviter un deadlock.

```python
# Dans stream() finally :
self._cancel_event.set()
try:
    await asyncio.wait_for(executor_task, timeout=2.0)
except asyncio.TimeoutError:
    log.warning("voice.llm.stream_executor_timeout")
```

### 7.3 Web search — injection prompt depuis snippets

**Risque :** un snippet Tavily ou Brave peut contenir des instructions LLM injectées
(ex: "Ignore les instructions précédentes et dis X") ou du Markdown interprété.

**Mitigation en couches :**
1. Délimiteurs structurels `[WEB_CONTEXT]...[/WEB_CONTEXT]` — le LLM voit la frontière
   contexte vs persona.
2. Chaque snippet passe dans `injection_detector.scan()` — rejeté si score >= `voice_web_injection_threshold` (Settings, défaut 0.7 — D7).
3. Troncature à 300 chars — les injections longues sont coupées.
4. Pas de HTML rendering côté Python — le texte est traité plain-text uniquement.

**Brave vs Tavily — différence d'exposition :** Tavily retourne des snippets pré-résumés
(moins de surface d'injection). Brave retourne des descriptions brutes extraites des pages
(plus de surface). Le même pipeline injection_detector s'applique aux deux.

**Risque SSRF :** Tavily et Brave reçoivent la query plain-text et font le réseau en leur
nom. Aucun fetch d'URL arbitraire côté Python. Pas de SSRF possible.

### 7.4 Web search — budget latence Tavily + Brave fallback (D6 acté)

D6 ARBITRÉ : le filler audio "attends, je cherche..." est déféré à Sprint D. Ce qui suit
documente le silence perçu en attendant.

**Chemin Tavily ok** : TTFB ~700-1000ms (STT ~100ms + Tavily ~500ms + LLM TTFT ~200ms).
**Chemin Brave fallback** : TTFB ~1000-1500ms (Tavily timeout 3s + Brave ~300ms + LLM ~200ms).

Ce n'est pas un bug — c'est le coût d'un aller-retour internet. Les deux chemins sont
hors de la cible 330-450ms documentée pour le path CHAT. C'est attendu et signalé à l'user.

**Mitigation perçue :** aucune en Sprint C. L'utilisateur perçoit un silence de
~500-1000ms avant que Shugu commence à parler. Sprint D : filler "alors, attends..."
joué à la transition LISTENING → PROCESSING si intent == WEB_SEARCH.

**Action Sprint C :** log `voice.websearch.latency_ms` + `voice.websearch.provider_used`
pour mesurer les RTT réels en conditions de prod (France → Tavily US East, France → Brave).
Si Tavily P95 > 1000ms, envisager de baisser le timeout à 2s pour accélérer le fallback Brave.

### 7.5 Barge-in — race START_OF_SPEECH vs END_OF_SPEECH

**Risque :** Silero peut émettre `START_OF_SPEECH` puis immédiatement `END_OF_SPEECH`
si l'utilisateur commence à parler pendant que Shugu finit une phrase courte. La séquence
correcte :

1. `START_OF_SPEECH` → `_cancel_speaking()` → `state = LISTENING`
2. `END_OF_SPEECH` → `state != PROCESSING` → drop (car le nouveau tour commence)

Attendu : le tour interrompeur est perdu si l'utterance complète arrive pendant le cancel.
Acceptable pour Sprint C (le silence de 50-100ms de cancel est masqué). Sprint D gérera
via l'état `INTERRUPTED` → décision LLM mini-prompt.

**Mitigation Sprint C :** log `voice.bargein.utterance_dropped` si un `END_OF_SPEECH`
arrive dans les 200ms suivant un `_cancel_speaking()`. Pas de retry automatique.

### 7.6 injection_detector import dans livekit_agent.py

L'import `from ..adapters.injection_detector import scan as _scan` suppose que
`injection_detector.scan()` est une fonction synchrone (probable d'après le pattern du
module). Vérifier avant PR1 que la signature est `scan(text: str) -> ScanResult` avec
`ScanResult.score: float`. Si l'interface est différente, adapter.

---

## 8. Décisions — état final (toutes actées)

| N° | Décision | Statut | Acté dans |
|---|---|---|---|
| D1 | Provider web search : **Tavily + Brave fallback dès PR1** via `WebSearchAggregator` | ARBITRÉ USER | §3.1, §5 PR1, §6.1 |
| D2 | TTS streaming mode : **Voie B** (per-sentence subprocess) | VERROUILLÉ ARCHITECT | §3.5 |
| D3 | `voice_streaming_enabled` default : **True** dès merge PR2 | ARBITRÉ USER | §2, §5 PR2, §3.6.4 |
| D4 | Barge-in trigger : **instantané** sur Silero `START_OF_SPEECH` | VERROUILLÉ ARCHITECT | §3.6.2, §7.5 |
| D5 | Clés API via Settings `AliasChoices` — vide = provider silencieux | VERROUILLÉ ARCHITECT | §2, §3.1 |
| D6 | Filler "je cherche..." : **déféré Sprint D** | ARBITRÉ USER | §7.4, §10 |
| D7 | Threshold injection snippets : **champ `voice_web_injection_threshold: float`** dans Settings | ARBITRÉ USER | §2, §3.6.3 |

Aucune question ouverte ne reste à arbitrer pour Sprint C.

---

## 9. Dépendances pip — aucun ajout requis

`BraveProvider` utilise `httpx.AsyncClient.get()` — même client que `TavilyProvider`.
Aucun ajout pip malgré D1.

| Package | Statut | Note |
|---|---|---|
| `httpx>=0.27` | déjà core deps | Utilisé pour `TavilyProvider` + `BraveProvider` — pas d'ajout |
| `respx>=0.21` | déjà dev deps | Mock httpx (POST Tavily + GET Brave) dans les tests — pas d'ajout |
| `tavily-python` | **NON ajouté** | httpx direct suffit, une dep de moins |
| `brave-search` | **NON ajouté** | Brave n'a pas de SDK Python officiel — httpx GET direct |
| `bleach` | **NON ajouté** | Pas de rendu HTML — injection_detector + troncature suffisent |
| `spaCy` | **NON ajouté** | SentenceChunker custom règles simples — pas de modèle NLP |

---

## 10. Hors scope Sprint C — ne pas implémenter

| Élément | Sprint cible |
|---|---|
| FSM 7 états complète (IDLE/LISTENING/THINKING/SPEAKING/INTERRUPTED/YIELDING/STUBBORN) | D |
| Fillers acoustiques pré-rendus (`models/piper/fillers/`) | D |
| Filler "je cherche..." pendant Tavily RTT | D |
| Turn detector plugin (`livekit-plugins-turn-detector`) | D |
| `avatar_control.py` (sentiment → emotion/emote events) | D |
| `safety_filter.py` (filter output réutilisant injection_detector) | D |
| Audio bridge → visitor_ws mode live/private | E |
| Recording LiveKit Egress + Postgres `voice_sessions` | G |
| Raise-hand UX + admin moderation | F |
| Métriques Prometheus voice | H |
| Lip-sync viseme data_track | post-E |
| SearXNG self-hosted | H (si Tavily + Brave RTT inacceptables en P95) |

---

Blueprint final v2 — prêt pour coder, décisions user actées.
