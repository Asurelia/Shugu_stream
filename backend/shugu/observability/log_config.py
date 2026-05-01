"""Configuration structlog — Phase 8.2 observabilité.

Fournit ``configure_logging(format)`` pour basculer entre :
- Mode ``"json"``   : JSON Lines (JSONL) pour Loki/Grafana en production.
- Mode ``"pretty"`` : console colorée pour le développement local.

Le format est contrôlé par ``Settings.log_format`` (env SHUGU_LOG_FORMAT).
La fonction est idempotente — on peut l'appeler plusieurs fois sans effet
cumulatif (structlog écrase sa configuration globale à chaque appel).

Usage dans app.py lifespan
--------------------------
    from shugu.observability.log_config import configure_logging
    configure_logging(settings.log_format)
    log = structlog.get_logger("lifespan")
    log.info("shugu.starting")

Usage en tests
--------------
    configure_logging("json")
    captured = capsys.readouterr()
    parsed = json.loads(captured.out.strip())
"""
from __future__ import annotations

import logging
import sys
from typing import Literal

import structlog

LogFormat = Literal["json", "pretty"]


def configure_logging(log_format: LogFormat = "json") -> None:
    """Configure structlog globalement selon le format demandé.

    Paramètres
    ----------
    log_format :
        ``"json"``   → JSONRenderer (JSONL, Loki-friendly, production).
        ``"pretty"`` → ConsoleRenderer (couleurs, dev local).

    Les deux modes incluent :
    - Merge des contextvars structlog (request_id, user_id, etc.)
    - Ajout du niveau de log (info, warning, error…)
    - Timestamp ISO UTC
    """
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]

    if log_format == "json":
        processors = [
            *shared_processors,
            structlog.processors.JSONRenderer(),
        ]
    else:
        processors = [
            *shared_processors,
            structlog.dev.ConsoleRenderer(colors=True),
        ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=False,
    )


__all__ = ["configure_logging", "LogFormat"]
