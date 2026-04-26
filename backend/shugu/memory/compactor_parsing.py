"""Construction et parsing de prompts LLM pour le Compactor — Mémoire PR 4.

Module responsable de :
1. Construction des system/user prompts pour le brain LLM.
2. Parsing robuste du JSON retourné par le LLM (gère les cas avec du texte
   enrobant le JSON).
3. Validation et normalisation des summaries extraits.

Extraite de `compactor.py` pour respecter la limite de 400 lignes par module.
"""
from __future__ import annotations

import json
from typing import Any

import structlog

from .types import MemoryItem

log = structlog.get_logger(__name__)


class ParseError(Exception):
    """Erreur de parsing de la réponse LLM — non-récupérable pour ce run."""


def build_system_prompt(target_count: int) -> str:
    """Construit le system prompt pour la compression de facts.

    Args:
        target_count: Nombre de facts résumés demandés.

    Returns:
        System prompt string.
    """
    return (
        "Tu es un assistant de mémoire pour un streamer IA. "
        "Ton rôle est de condenser une liste de faits sur un sujet en un "
        f"résumé compact de {target_count} faits maximum. "
        "Préserve les nuances importantes, les préférences et la confiance. "
        "Fusionne les faits redondants. Garde les faits les plus récents en cas "
        "de contradiction. "
        "Réponds UNIQUEMENT avec du JSON valide, sans texte autour, "
        "au format exact : "
        '{"summary_facts": [{"predicate": "...", "object": "...", "confidence": 0.0}, ...]}'
        " où confidence est un float entre 0.0 et 1.0."
    )


def build_user_prompt(subject_key: str, facts: list[MemoryItem]) -> str:
    """Construit le user prompt avec la liste des facts à condenser.

    Args:
        subject_key: Clé du sujet (ex: `viewer:alice`).
        facts:       Liste de MemoryItem en ordre chronologique.

    Returns:
        User prompt string avec les facts formatés.
    """
    lines = [f"Sujet : {subject_key}", "", "Facts à condenser (ordre chronologique) :"]
    for i, fact in enumerate(facts, start=1):
        ts = fact.created_at.strftime("%Y-%m-%d")
        lines.append(
            f"{i}. [{ts}] confidence={fact.confidence:.2f} — {fact.text}"
        )
    return "\n".join(lines)


def parse_summary_response(raw: str) -> list[dict]:
    """Parse la réponse JSON du LLM en liste de spec de facts.

    Stratégie robuste :
    1. Tente de parser le JSON directement.
    2. Si échec, cherche le premier objet JSON dans la réponse (le LLM
       entoure parfois le JSON de texte de courtoisie).
    3. Valide la structure : `summary_facts` est une liste de dicts avec
       au moins `predicate` et `object`.
    4. Clamp confidence dans [0.0, 1.0].

    Args:
        raw: Réponse brute du LLM.

    Returns:
        Liste de dicts validés `{"predicate": str, "object": str, "confidence": float}`.

    Raises:
        ParseError: Si la réponse n'est pas parseable ou structurellement invalide.
    """
    raw = (raw or "").strip()
    if not raw:
        raise ParseError("Réponse LLM vide")

    # Tentative 1 : parse direct.
    parsed = _try_parse_json(raw)

    # Tentative 2 : extraction du premier bloc JSON si le direct a échoué.
    if parsed is None:
        parsed = _extract_json_block(raw)

    if parsed is None:
        raise ParseError(f"Réponse non-JSON (head='{raw[:100]}')")

    # Validation structure.
    if not isinstance(parsed, dict):
        raise ParseError(f"JSON attendu comme objet, reçu {type(parsed).__name__}")

    facts_raw = parsed.get("summary_facts")
    if not isinstance(facts_raw, list):
        raise ParseError(
            "'summary_facts' manquant ou non-liste dans la réponse JSON"
        )

    result: list[dict] = []
    for i, item in enumerate(facts_raw):
        if not isinstance(item, dict):
            log.warning("compactor_parsing.skip_non_dict", index=i, item=repr(item))
            continue
        predicate = item.get("predicate")
        obj = item.get("object")
        if not predicate or not obj:
            log.warning(
                "compactor_parsing.skip_missing_fields",
                index=i,
                item=repr(item),
            )
            continue
        # Clamp confidence.
        confidence = float(item.get("confidence", 0.75))
        confidence = max(0.0, min(1.0, confidence))

        result.append({
            "predicate": str(predicate).strip(),
            "object": str(obj).strip(),
            "confidence": confidence,
        })

    return result


def _try_parse_json(text: str) -> object | None:
    """Tente un parse JSON direct. Retourne None si échec."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _extract_json_block(text: str) -> object | None:
    """Cherche et parse le premier bloc JSON (entre { }) dans un texte.

    Gère le cas où le LLM ajoute du texte avant/après le JSON
    (ex: "Voici le résumé : {...}").
    """
    start = text.find("{")
    if start == -1:
        return None

    # Cherche la fermeture correspondante en comptant les accolades.
    depth = 0
    for i, ch in enumerate(text[start:], start=start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                candidate = text[start : i + 1]
                return _try_parse_json(candidate)

    return None


__all__ = [
    "ParseError",
    "build_system_prompt",
    "build_user_prompt",
    "parse_summary_response",
]
