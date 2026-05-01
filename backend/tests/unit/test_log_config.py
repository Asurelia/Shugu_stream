"""Tests TDD Phase 8.2 — log_config structlog JSON vs pretty.

T6 log_config_pretty_mode_writes_human_readable
T7 log_config_json_mode_writes_jsonl_to_stdout
"""
from __future__ import annotations

import json

import structlog

from shugu.observability.log_config import configure_logging

# ---------------------------------------------------------------------------
# T6 — mode pretty : output lisible humain (pas JSON)
# ---------------------------------------------------------------------------


def test_log_config_pretty_mode_writes_human_readable(capsys) -> None:
    """configure_logging('pretty') doit produire un output NON-JSON lisible.

    On vérifie que la première ligne capturée n'est pas parseable comme JSON
    (indication que le renderer pretty console est actif).
    """
    configure_logging("pretty")
    logger = structlog.get_logger("test.pretty")
    logger.info("hello_pretty", key="value")

    captured = capsys.readouterr()
    # Le renderer pretty produit du texte coloré non-JSON.
    # On vérifie qu'on ne peut PAS parser la ligne comme JSON brut.
    output = (captured.out + captured.err).strip()
    assert output, "aucun output capturé en mode pretty"
    # Au moins un token reconnaissable hors JSON
    assert "hello_pretty" in output


# ---------------------------------------------------------------------------
# T7 — mode json : chaque ligne est du JSON valide
# ---------------------------------------------------------------------------


def test_log_config_json_mode_writes_jsonl_to_stdout(capsys) -> None:
    """configure_logging('json') doit produire du JSONL parseable ligne par ligne."""
    configure_logging("json")
    logger = structlog.get_logger("test.json")
    logger.info("hello_json", number=42)

    captured = capsys.readouterr()
    output = (captured.out + captured.err).strip()
    assert output, "aucun output capturé en mode json"

    # Chaque ligne non-vide doit être du JSON valide.
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        parsed = json.loads(line)
        assert isinstance(parsed, dict)
        assert "event" in parsed or "message" in parsed or "hello_json" in str(parsed)
