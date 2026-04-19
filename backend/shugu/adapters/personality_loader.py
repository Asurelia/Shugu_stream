"""Hot-reloadable personality documents from markdown files.

- YAML frontmatter (between `---` markers) for metadata (voice_id, style hints).
- Body is the system prompt.
- mtime polled lazily on `get()` — no watchfiles, no threads.
"""
from __future__ import annotations

import re
from pathlib import Path
from ..core.protocols import PersonalityDoc


_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Very small yaml-ish frontmatter parser — handles `key: value` pairs only."""
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    header = m.group(1)
    body = text[m.end():]
    meta: dict[str, str] = {}
    for line in header.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip().strip('"').strip("'")
    return meta, body


class MarkdownPersonalityLoader:
    """Polls file mtime; refreshes cache on change. Thread-safe? No, but we're asyncio."""

    def __init__(self, personality_dir: Path, poll_every_s: int = 5):
        self._dir = Path(personality_dir)
        self._poll = poll_every_s
        self._cache: dict[str, PersonalityDoc] = {}
        self._last_check: dict[str, float] = {}

    def _path(self, persona: str) -> Path:
        return self._dir / f"{persona}.md"

    def get(self, persona: str) -> PersonalityDoc:
        import time
        now = time.monotonic()
        if persona in self._cache and (now - self._last_check.get(persona, 0)) < self._poll:
            return self._cache[persona]

        path = self._path(persona)
        if not path.exists():
            raise FileNotFoundError(f"personality not found: {path}")
        mtime = path.stat().st_mtime
        cached = self._cache.get(persona)
        if cached and cached.mtime == mtime:
            self._last_check[persona] = now
            return cached

        meta, body = _parse_frontmatter(path.read_text(encoding="utf-8"))
        doc = PersonalityDoc(
            system_prompt=body.strip(),
            voice_id=meta.get("voice_id", ""),
            style_hints={k: v for k, v in meta.items() if k != "voice_id"},
            mtime=mtime,
        )
        self._cache[persona] = doc
        self._last_check[persona] = now
        return doc
