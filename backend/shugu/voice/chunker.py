"""Chunker prosodique — accumule les tokens LLM et émet des phrases complètes.

Règles d'émission (par ordre de priorité) :
  1. Ponctuation forte suivie d'espace ou fin de stream : . ! ?
  2. Virgule + cumul >= 4 mots depuis le dernier flush
  3. Max 200 chars (évite les chunks trop longs pour Piper)
  4. Flush forcé à la fin du stream (tokens restants)

Abréviations FR protégées (ne déclenchent pas l'émission) :
  M. Mme. Mlle. Dr. Pr. St. etc. ex. cf. fig. vol.

Limites acceptées Sprint C :
  - "M. Dupont" → pas d'émission prématurée sur "M." (regex abbrev)
  - "3.14" ou "1. Bonjour" : le point décimal et les listes numériques
    peuvent déclencher une émission (effet sur TTS neutre en pratique)
  - Backpressure : aucune limite de queue — mesurer Sprint D si nécessaire.
"""
from __future__ import annotations

import re
from collections.abc import AsyncIterator

# Abréviations françaises qui se terminent par un point sans clore la phrase
_ABBREV_RE = re.compile(
    r"\b(M|Mme|Mlle|Dr|Pr|St|etc|ex|cf|fig|vol|art|chap|p)\.$",
    re.IGNORECASE,
)

_STRONG_PUNCT = frozenset(".!?")
_MAX_CHUNK_CHARS = 200
_MIN_WORDS_COMMA = 4


class SentenceChunker:
    """Stateful chunker. One instance per LLM turn (not thread-safe)."""

    def __init__(self) -> None:
        self._buf: list[str] = []
        self._word_count: int = 0
        self._char_count: int = 0

    def _buf_text(self) -> str:
        return "".join(self._buf).strip()

    def _should_emit_on_punct(self, token: str) -> bool:
        """Return True if token closes a sentence (strong punctuation).

        Called AFTER the token has been appended to self._buf, so _buf_text()
        already includes the current token. We check the full buffer text
        (not buf + token separately) to avoid double-appending.
        """
        stripped = token.rstrip()
        if not stripped:
            return False
        last_char = stripped[-1]
        if last_char not in _STRONG_PUNCT:
            return False
        # Protect abbreviations: _buf_text() already contains the current token
        buf_text = self._buf_text()
        if _ABBREV_RE.search(buf_text):
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
        """Yield complete sentences accumulated from an async token stream.

        Consumes the full token stream and emits sentences as they become
        complete according to the four emission rules above.
        """
        async for token in tokens:
            self._buf.append(token)
            self._char_count += len(token)
            # Approximate word count by counting space transitions
            self._word_count += token.count(" ")

            emit = False

            # Rule 1 — strong punctuation closes a sentence
            if self._should_emit_on_punct(token):
                emit = True

            # Rule 2 — comma + enough accumulated words
            elif "," in token and self._word_count >= _MIN_WORDS_COMMA:
                emit = True

            # Rule 3 — max chars guard prevents oversized TTS chunks
            elif self._char_count >= _MAX_CHUNK_CHARS:
                emit = True

            if emit:
                chunk = self._flush()
                if chunk:
                    yield chunk

        # Rule 4 — flush any remainder after stream ends
        remainder = self._flush()
        if remainder:
            yield remainder
