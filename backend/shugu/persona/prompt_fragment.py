"""Génération du fragment texte injectable dans le system prompt LLM.

Fournit `render_fragment(state, viewer_subject)` qui produit un bloc de texte
décrivant l'état adaptatif courant de Shugu, destiné à être injecté en tête
du system prompt pour contextualiser les réponses LLM.

Contenu du fragment :
    1. Mood courant (dernier MoodArcEntry) + descriptif.
    2. 2-3 transitions récentes de l'arc pour la continuité narrative.
    3. Niveau d'énergie avec label descriptif (tired / normal / energetic / sparking).
    4. Si `viewer_subject` fourni ET présent dans relationships :
       - trust / familiarity (niveau descriptif).
       - Running gags (jusqu'à MAX_GAGS_IN_FRAGMENT).

Ce module est synchrone (pas d'async, pas d'I/O).
N'importe rien de `shugu.*` externe.
"""
from __future__ import annotations

from .state import PersonaState

# Nombre maximum de running gags inclus dans le fragment.
# Valeur choisie pour ne pas polluer le context window LLM.
MAX_GAGS_IN_FRAGMENT: int = 3

# Nombre de transitions récentes à inclure dans le fragment (hors la courante).
_ARC_CONTEXT_ENTRIES: int = 2


# ── Constantes de label ───────────────────────────────────────────────────────

_ENERGY_LABELS = [
    (0.0, 0.2, "épuisée"),
    (0.2, 0.4, "fatiguée"),
    (0.4, 0.6, "détendue"),
    (0.6, 0.8, "énergique"),
    (0.8, 1.0, "électrisée"),
    (1.0, 1.01, "au max"),   # borne haute inclusive
]

_TRUST_LABELS = [
    (0.0, 0.25, "inconnue"),
    (0.25, 0.5, "familière"),
    (0.5, 0.75, "de confiance"),
    (0.75, 1.01, "très proche"),
]

_FAMILIARITY_LABELS = [
    (0.0, 0.25, "nouveau"),
    (0.25, 0.5, "régulier"),
    (0.5, 0.75, "habitué"),
    (0.75, 1.01, "fidèle"),
]


# ── API publique ──────────────────────────────────────────────────────────────


def render_fragment(
    state: PersonaState,
    viewer_subject: str | None,
) -> str:
    """Génère le fragment texte persona à injecter dans le system prompt LLM.

    Paramètres :
        state          : PersonaState courant.
        viewer_subject : clé du viewer courant ("viewer:xyz" ou "vip:alice")
                         ou None si pas de viewer spécifique (ambient/silence).

    Retourne :
        String prêt à l'injection, commençant par "[PERSONA]" pour faciliter
        le repérage dans les logs.

    Usage :
        fragment = render_fragment(state, viewer_subject="vip:alice")
        system_prompt = base_system_prompt + "\\n\\n" + fragment
    """
    lines: list[str] = ["[PERSONA]"]

    # ── Mood courant ──────────────────────────────────────────────────────────
    if state.mood_arc:
        current_mood = state.mood_arc[-1]
        lines.append(f"Mood actuel : {current_mood.state} (depuis : {current_mood.reason})")

        # Contexte récent de l'arc (transitions précédentes)
        arc_context = state.mood_arc[-(1 + _ARC_CONTEXT_ENTRIES):-1]
        if arc_context:
            history_parts = [f"{e.state} ({e.reason})" for e in arc_context]
            lines.append(f"Arc récent : {' → '.join(history_parts)} → {current_mood.state}")
    else:
        lines.append("Mood actuel : neutre")

    # ── Énergie ───────────────────────────────────────────────────────────────
    energy_label = _get_energy_label(state.energy)
    lines.append(
        f"Énergie : {energy_label} ({state.energy:.0%})"
    )

    # ── Relation viewer ───────────────────────────────────────────────────────
    if viewer_subject is not None:
        rel = state.relationships.get(viewer_subject)
        if rel is not None:
            trust_label = _get_label(rel.trust, _TRUST_LABELS)
            fam_label = _get_label(rel.familiarity, _FAMILIARITY_LABELS)
            lines.append(
                f"Viewer {viewer_subject} : {fam_label}, relation {trust_label} "
                f"(trust={rel.trust:.2f}, familiarité={rel.familiarity:.2f})"
            )
            # Running gags — tronqués à MAX_GAGS_IN_FRAGMENT
            gags = rel.running_gags[:MAX_GAGS_IN_FRAGMENT]
            if gags:
                gag_str = ", ".join(f'"{g}"' for g in gags)
                lines.append(f"Inside-jokes avec ce viewer : {gag_str}")
        else:
            lines.append(f"Viewer {viewer_subject} : premier contact (aucune relation mémorisée)")

    return "\n".join(lines)


# ── Helpers privés ────────────────────────────────────────────────────────────


def _get_energy_label(energy: float) -> str:
    """Retourne le label descriptif pour un niveau d'énergie [0.0, 1.0]."""
    return _get_label(energy, _ENERGY_LABELS)


def _get_label(value: float, table: list[tuple[float, float, str]]) -> str:
    """Recherche linéaire dans une table de (min, max_exclusive, label).

    Pour la borne haute inclusive (1.0), le dernier bucket a max=1.01.
    """
    for low, high, label in table:
        if low <= value < high:
            return label
    # Fallback — ne devrait pas arriver avec des valeurs clampées
    return table[-1][2]
