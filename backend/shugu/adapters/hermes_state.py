"""Reader for `~/.hermes/` state — same format the upstream `hermes-hud` TUI consumes.

Upstream project (reference only, NOT a Python dep): https://github.com/joeynyc/hermes-hud
We don't import from it — Python 3.11+ + Textual is too much surface for our
backend. Instead, we read the directory layout directly with `pathlib` and
surface a typed snapshot through `/api/hermes/state`.

Safety: the directory may not exist in dev (Windows, fresh install). All
read functions return sane defaults with `available=False` in that case, so
the frontend always has *something* to render.

Format expectations (best-effort, tolerant to partial data):
  ~/.hermes/
    ├── memory/                   # JSONL or MD per-conversation
    │   ├── recent.jsonl
    │   └── <session_id>.md
    ├── skills/                   # one MD file per acquired skill
    ├── tools/
    │   └── usage.jsonl           # append-only log
    ├── projects/                 # directories tracked
    │   └── *.yaml or *.json
    ├── corrections.log           # one entry per learning moment
    ├── health.json               # last-known API/service health
    └── growth/                   # snapshot diffs
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Optional

import structlog


log = structlog.get_logger(__name__)


Tab = Literal[
    "overview", "memory", "skills", "tools", "projects",
    "health", "growth", "corrections", "cron",
]


@dataclass(slots=True)
class HermesSnapshot:
    """One tab's worth of state. `data` is deliberately loose — each tab
    decides its own shape; the frontend renders from `tab` + `data` keys."""
    tab: Tab
    available: bool
    data: dict = field(default_factory=dict)
    fetched_at: float = 0.0
    error: Optional[str] = None


def _default_hermes_dir() -> Path:
    # Honor the env override used by hermes-hud upstream, if present.
    override = os.environ.get("HERMES_HOME")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".hermes"


class HermesStateReader:
    """Caches tab snapshots for 5s to avoid hammering the disk on every poll.

    The reader is thread-safe in practice (we call it from asyncio tasks only,
    each tab has its own lock-free cache entry, and stat() is atomic enough
    for our purposes)."""

    CACHE_TTL_S = 5.0

    def __init__(self, hermes_dir: Optional[Path] = None):
        self._dir = hermes_dir or _default_hermes_dir()
        self._cache: dict[str, HermesSnapshot] = {}

    @property
    def root(self) -> Path:
        return self._dir

    def available(self) -> bool:
        return self._dir.exists() and self._dir.is_dir()

    def _is_safe_inside_root(self, path: Path) -> bool:
        """True if `path` is a regular file physically inside `self._dir`.

        Blocks two attack vectors visible from the operator-only endpoint:
          1. Symlinks inside ~/.hermes/skills/ pointing at /etc/shadow etc.
             (possible if a compromised Hermes or a mistaken `ln -s` exists).
          2. Path traversal via any `..` segments in a filename we somehow
             accept through glob (defence-in-depth: glob normally doesn't).
        `resolve()` follows symlinks and normalizes, so `is_relative_to` on
        the resolved form is the correct check.
        """
        try:
            resolved = path.resolve()
            root = self._dir.resolve()
            return resolved.is_relative_to(root) and not path.is_symlink()
        except (OSError, RuntimeError):
            return False

    def _safe_read_text(self, path: Path, *, max_bytes: int = 8192) -> str:
        """Bounded, symlink-safe read. Returns '' when the path is unsafe."""
        if not self._is_safe_inside_root(path):
            return ""
        try:
            with path.open("rb") as f:
                return f.read(max_bytes).decode("utf-8", "replace")
        except OSError:
            return ""

    async def snapshot(self, tab: Tab) -> HermesSnapshot:
        """Return cached snapshot if <5s old, else re-read."""
        now = time.monotonic()
        cached = self._cache.get(tab)
        if cached and (now - cached.fetched_at) < self.CACHE_TTL_S:
            return cached

        # Offload disk I/O to a thread so we don't stall the event loop.
        snap = await asyncio.to_thread(self._read_tab, tab)
        snap.fetched_at = now
        self._cache[tab] = snap
        return snap

    async def overview(self) -> dict:
        """Convenience: gather a tiny multi-tab overview in one pass."""
        tabs: list[Tab] = ["memory", "skills", "tools", "projects", "health"]
        results = await asyncio.gather(*[self.snapshot(t) for t in tabs], return_exceptions=True)
        out: dict[str, Any] = {"available": self.available(), "root": str(self._dir)}
        for tab, res in zip(tabs, results):
            if isinstance(res, HermesSnapshot):
                out[tab] = {"available": res.available, **(res.data or {})}
            else:
                out[tab] = {"available": False, "error": str(res)}
        return out

    # ─── Per-tab readers ─────────────────────────────────────────────────────

    def _read_tab(self, tab: Tab) -> HermesSnapshot:
        if not self.available():
            return HermesSnapshot(tab=tab, available=False, data={
                "hint": f"~/.hermes/ not found at {self._dir}. Install hermes or set HERMES_HOME.",
            })
        try:
            if tab == "overview":
                return HermesSnapshot(tab=tab, available=True, data=self._read_overview())
            if tab == "memory":
                return HermesSnapshot(tab=tab, available=True, data=self._read_memory())
            if tab == "skills":
                return HermesSnapshot(tab=tab, available=True, data=self._read_skills())
            if tab == "tools":
                return HermesSnapshot(tab=tab, available=True, data=self._read_tools())
            if tab == "projects":
                return HermesSnapshot(tab=tab, available=True, data=self._read_projects())
            if tab == "health":
                return HermesSnapshot(tab=tab, available=True, data=self._read_health())
            if tab == "growth":
                return HermesSnapshot(tab=tab, available=True, data=self._read_growth())
            if tab == "corrections":
                return HermesSnapshot(tab=tab, available=True, data=self._read_corrections())
            if tab == "cron":
                return HermesSnapshot(tab=tab, available=True, data=self._read_cron())
        except Exception as exc:
            log.warning("hermes_state.read_error", tab=tab, error=str(exc))
            return HermesSnapshot(tab=tab, available=False, error=str(exc))
        return HermesSnapshot(tab=tab, available=False, error=f"unknown tab {tab!r}")

    def _read_overview(self) -> dict:
        """High-level counters — deliberately not the full data of each tab."""
        return {
            "root": str(self._dir),
            "memory_files": _count_files(self._dir / "memory", pattern="*"),
            "skills_count": _count_files(self._dir / "skills", pattern="*.md"),
            "projects_count": _count_files(self._dir / "projects", pattern="*"),
            "tools_usage_entries": _count_lines(self._dir / "tools" / "usage.jsonl"),
            "corrections_entries": _count_lines(self._dir / "corrections.log"),
            "has_health": (self._dir / "health.json").exists(),
        }

    def _read_memory(self) -> dict:
        mem_dir = self._dir / "memory"
        recent_entries: list[dict] = []
        recent_file = mem_dir / "recent.jsonl"
        if recent_file.exists():
            recent_entries = _tail_jsonl(recent_file, limit=20)
        sessions = sorted(
            (p.name for p in mem_dir.glob("*.md") if p.is_file()),
            reverse=True,
        )[:20] if mem_dir.exists() else []
        return {"recent": recent_entries, "sessions": sessions, "count": len(sessions)}

    def _read_skills(self) -> dict:
        skills_dir = self._dir / "skills"
        if not skills_dir.exists():
            return {"skills": [], "count": 0}
        skills = []
        for md in sorted(skills_dir.glob("*.md")):
            # Symlink protection: skip any entry that escapes ~/.hermes/.
            if not self._is_safe_inside_root(md):
                continue
            try:
                stat = md.stat()
                head = self._safe_read_text(md, max_bytes=300)
                skills.append({
                    "name": md.stem,
                    "updated_at": stat.st_mtime,
                    "summary": head.splitlines()[0][:160] if head else "",
                })
            except OSError:
                continue
        return {"skills": skills, "count": len(skills)}

    def _read_tools(self) -> dict:
        usage_file = self._dir / "tools" / "usage.jsonl"
        entries = _tail_jsonl(usage_file, limit=30) if usage_file.exists() else []
        # Count per-tool in the tail as a rough "recent activity" summary.
        counts: dict[str, int] = {}
        for ent in entries:
            name = str(ent.get("tool") or ent.get("name") or "unknown")
            counts[name] = counts.get(name, 0) + 1
        return {"recent": entries, "counts": counts}

    def _read_projects(self) -> dict:
        proj_dir = self._dir / "projects"
        if not proj_dir.exists():
            return {"projects": [], "count": 0}
        projects: list[dict] = []
        for p in sorted(proj_dir.iterdir()):
            if p.is_dir():
                projects.append({"name": p.name, "type": "directory"})
            elif p.is_file():
                projects.append({"name": p.stem, "type": p.suffix.lstrip(".")})
        return {"projects": projects[:40], "count": len(projects)}

    def _read_health(self) -> dict:
        health_file = self._dir / "health.json"
        if not self._is_safe_inside_root(health_file):
            return {"known": False}
        try:
            content = json.loads(self._safe_read_text(health_file, max_bytes=32_768) or "null")
            return {"known": True, **(content if isinstance(content, dict) else {"raw": content})}
        except (OSError, json.JSONDecodeError) as exc:
            return {"known": False, "error": str(exc)}

    def _read_growth(self) -> dict:
        growth_dir = self._dir / "growth"
        if not growth_dir.exists():
            return {"snapshots": [], "count": 0}
        snaps = sorted(
            (p for p in growth_dir.iterdir() if p.is_file()),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )[:10]
        return {
            "snapshots": [
                {"name": s.name, "updated_at": s.stat().st_mtime, "size": s.stat().st_size}
                for s in snaps
            ],
            "count": len(snaps),
        }

    def _read_corrections(self) -> dict:
        log_file = self._dir / "corrections.log"
        if not log_file.exists():
            return {"entries": [], "count": 0}
        entries = _tail_text(log_file, limit=30)
        return {"entries": entries, "count": len(entries)}

    def _read_cron(self) -> dict:
        cron_file = self._dir / "cron.json"
        if not self._is_safe_inside_root(cron_file):
            return {"jobs": [], "count": 0}
        try:
            data = json.loads(self._safe_read_text(cron_file, max_bytes=32_768) or "null")
            if isinstance(data, dict) and "jobs" in data:
                return {"jobs": data["jobs"][:40], "count": len(data["jobs"])}
            if isinstance(data, list):
                return {"jobs": data[:40], "count": len(data)}
        except (OSError, json.JSONDecodeError):
            pass
        return {"jobs": [], "count": 0}


# ─── File helpers ───────────────────────────────────────────────────────────


def _count_files(path: Path, pattern: str) -> int:
    if not path.exists():
        return 0
    try:
        return sum(1 for p in path.glob(pattern) if p.is_file())
    except OSError:
        return 0


def _count_lines(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        with path.open("rb") as f:
            return sum(1 for _ in f)
    except OSError:
        return 0


def _tail_jsonl(path: Path, *, limit: int) -> list[dict]:
    """Read the last `limit` non-empty JSON lines. Tolerant to malformed rows."""
    try:
        lines = _read_last_lines(path, limit * 2)
    except OSError:
        return []
    out: list[dict] = []
    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        try:
            obj = json.loads(ln)
            if isinstance(obj, dict):
                out.append(obj)
        except json.JSONDecodeError:
            continue
        if len(out) >= limit:
            break
    return out[-limit:]


def _tail_text(path: Path, *, limit: int) -> list[str]:
    try:
        return [ln.rstrip() for ln in _read_last_lines(path, limit) if ln.strip()]
    except OSError:
        return []


def _read_last_lines(path: Path, n: int) -> list[str]:
    """Read the last `n` lines without loading the whole file in memory.
    Good enough for logs; exact for small files, approximate for huge ones."""
    buf_size = 4096
    with path.open("rb") as f:
        f.seek(0, 2)
        size = f.tell()
        if size == 0:
            return []
        data = bytearray()
        pos = size
        while pos > 0 and data.count(b"\n") <= n:
            step = min(buf_size, pos)
            pos -= step
            f.seek(pos)
            data[0:0] = f.read(step)
        lines = data.decode("utf-8", "replace").splitlines()
        return lines[-n:] if len(lines) > n else lines


def _read_head(path: Path, *, n_bytes: int) -> str:
    try:
        with path.open("rb") as f:
            return f.read(n_bytes).decode("utf-8", "replace")
    except OSError:
        return ""
