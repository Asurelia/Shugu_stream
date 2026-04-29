"""Sérialisation PersonaState ↔ dict JSON-compatible.

Transforme un `PersonaState` (frozen dataclasses) en `dict` JSON-compatible
pour `MemoryService.persona_set()`, et reconstruit un `PersonaState` depuis
le `dict` retourné par `MemoryService.persona_get()`.

Conventions :
    - `datetime` → string ISO 8601 avec timezone (ex: "2026-04-29T12:00:00+00:00").
    - `MappingProxyType` → `dict` ordinaire.
    - `tuple` → `list` (JSON ne distingue pas).
    - Champs manquants en `from_dict` : valeurs par défaut sûres
      (running_gags → (), relationships manquant → {}, mood_arc vide → [neutre]).

Régression P1 review #62 : tous les casts numériques utilisent `_safe_float`
qui swallow ValueError/TypeError + log warning + fallback. Sans ça, un doc
corrompu (`{"energy": "high"}` après edit manuel ou data legacy) levait
ValueError jusqu'au caller, abortant `load_persona_state()` et tout le boot.
Sémantique safe : doc partiellement corrompu → reset le champ touché + garde
le reste. L'agent boot toujours.

Ce module n'importe rien de `shugu.*` externe.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from .state import MAX_ARC_LEN, MoodArcEntry, PersonaState, ViewerRelationship

log = logging.getLogger(__name__)


def _safe_float(value: object, default: float, *, field_name: str) -> float:
    """Cast `value` en float avec fallback safe sur défaut + warning log.

    Régression P1 review #62 : `from_dict` appelait `float(d.get("energy", 0.5))`
    qui levait ValueError sur `{"energy": "high"}` ou similaire. Le caller
    `load_persona_state` ne catch que les erreurs `persona_get()`, pas les
    erreurs de désérialisation — résultat : tout le boot agent était abortable
    par un doc persona corrompu.

    Cette helper :
    - Catch (ValueError, TypeError) — couvre str non-numérique, None, dict, list.
    - Log un warning avec `field_name` pour audit (ne loggue PAS la valeur
      brute pour éviter de polluer les logs avec des secrets potentiels).
    - Retourne le `default` fourni par le caller (sémantique field-specific).

    Paramètres :
        value      : valeur brute du dict (peut être n'importe quel type).
        default    : valeur de repli si le cast échoue.
        field_name : nom du champ pour le warning log (ex: "energy", "trust").

    Retour :
        Float coercé en cas de succès, `default` sinon.
    """
    try:
        return float(value)  # type: ignore[arg-type]
    except (ValueError, TypeError):
        log.warning(
            "persona.serialization.invalid_numeric field=%s type=%s — falling back to default %r",
            field_name,
            type(value).__name__,
            default,
        )
        return default

# ── Sérialisation ────────────────────────────────────────────────────────────


def to_dict(state: PersonaState) -> dict:
    """Sérialise un PersonaState en dict JSON-compatible.

    Toutes les datetimes sont converties en strings ISO 8601 (UTC, offset +00:00).
    Les tuples sont convertis en listes. Le MappingProxyType est sérialisé
    en dict ordinaire.

    Retourne :
        dict avec les clés "mood_arc", "energy", "relationships".

    Usage :
        d = to_dict(state)
        await memory.persona_set(d)
    """
    return {
        "mood_arc": [_entry_to_dict(e) for e in state.mood_arc],
        "energy": state.energy,
        "relationships": {
            subject: _relationship_to_dict(rel)
            for subject, rel in state.relationships.items()
        },
    }


def from_dict(d: dict) -> PersonaState:
    """Reconstruit un PersonaState depuis un dict JSON (ex: résultat de persona_get).

    Gestion des champs manquants ou invalides :
        - `mood_arc` absent ou vide → [MoodArcEntry("neutral", now_utc, "init")].
        - `energy` absent → 0.5.
        - `relationships` absent → {}.
        - `running_gags` absent dans un viewer → ().

    Les datetimes sont parsées depuis ISO 8601 ; si le fuseau est absent,
    UTC est assumé (defensive — les dates stockées par to_dict sont toujours UTC).

    Paramètres :
        d : dict brut retourné par MemoryService.persona_get().

    Retourne :
        PersonaState cohérent, prêt à l'emploi.

    Usage :
        raw = await memory.persona_get()
        state = from_dict(raw)
    """
    # ── mood_arc ──────────────────────────────────────────────────────────────
    raw_arc = d.get("mood_arc", [])
    if isinstance(raw_arc, list) and raw_arc:
        mood_arc = tuple(_entry_from_dict(e) for e in raw_arc if isinstance(e, dict))
    else:
        mood_arc = ()

    # Garantit au moins une entrée neutre (ne jamais exposer un arc vide)
    if not mood_arc:
        mood_arc = (MoodArcEntry(
            state="neutral",
            since=datetime.now(tz=timezone.utc),
            reason="init",
        ),)

    # Cap de sécurité au rechargement (defensive, au cas où la DB contiendrait
    # un arc plus long que MAX_ARC_LEN — migration future ou corruption).
    mood_arc = mood_arc[-MAX_ARC_LEN:]

    # ── energy ────────────────────────────────────────────────────────────────
    # Régression P1 review #62 : _safe_float swallow ValueError/TypeError
    # sur valeurs corrompues (ex: {"energy": "high"}) au lieu de propager.
    energy = _safe_float(d.get("energy", 0.5), default=0.5, field_name="energy")
    energy = max(0.0, min(1.0, energy))

    # ── relationships ─────────────────────────────────────────────────────────
    raw_rels = d.get("relationships", {})
    relationships: dict[str, ViewerRelationship] = {}
    if isinstance(raw_rels, dict):
        for subject, rel_data in raw_rels.items():
            if isinstance(rel_data, dict):
                relationships[subject] = _relationship_from_dict(subject, rel_data)

    return PersonaState(
        mood_arc=mood_arc,
        energy=energy,
        relationships=relationships,
    )


# ── Helpers privés ────────────────────────────────────────────────────────────


def _entry_to_dict(entry: MoodArcEntry) -> dict:
    """Sérialise une MoodArcEntry en dict."""
    # Normalise en UTC avant sérialisation
    since = entry.since
    if since.tzinfo is None:
        since = since.replace(tzinfo=timezone.utc)
    return {
        "state": entry.state,
        "since": since.isoformat(),
        "reason": entry.reason,
    }


def _entry_from_dict(d: dict) -> MoodArcEntry:
    """Reconstruit une MoodArcEntry depuis un dict."""
    state = str(d.get("state", "neutral"))
    reason = str(d.get("reason", ""))
    since_raw = d.get("since", "")
    try:
        since = datetime.fromisoformat(str(since_raw))
        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        since = datetime.now(tz=timezone.utc)
    return MoodArcEntry(state=state, since=since, reason=reason)


def _relationship_to_dict(rel: ViewerRelationship) -> dict:
    """Sérialise une ViewerRelationship en dict."""
    return {
        "subject": rel.subject,
        "trust": rel.trust,
        "familiarity": rel.familiarity,
        "running_gags": list(rel.running_gags),
    }


def _relationship_from_dict(subject: str, d: dict) -> ViewerRelationship:
    """Reconstruit une ViewerRelationship depuis un dict.

    `subject` est passé explicitement (clé du dict parent) pour éviter
    la désynchronisation si la clé du dict et le champ `subject` intérieur
    diffèrent (cas de migration).
    """
    # Régression P1 review #62 : _safe_float — un viewer doc corrompu ne doit
    # pas crasher tout le persona load. Reset au défaut 0.0 du champ touché.
    trust = max(0.0, min(1.0, _safe_float(
        d.get("trust", 0.0), default=0.0,
        field_name=f"relationships[{subject}].trust",
    )))
    familiarity = max(0.0, min(1.0, _safe_float(
        d.get("familiarity", 0.0), default=0.0,
        field_name=f"relationships[{subject}].familiarity",
    )))
    raw_gags = d.get("running_gags", [])
    if isinstance(raw_gags, (list, tuple)):
        running_gags = tuple(str(g) for g in raw_gags)
    else:
        running_gags = ()
    return ViewerRelationship(
        subject=subject,
        trust=trust,
        familiarity=familiarity,
        running_gags=running_gags,
    )
