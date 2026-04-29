"""PersonaState — état adaptatif persistant : mood arc + énergie + relations viewers.

Définit la structure du persona state (dataclasses frozen) et les opérations
de mise à jour pures (fonctions renvoyant un nouvel état sans muter l'existant).
La persistance est entièrement déléguée à `MemoryService.persona_get/persona_set`.

Structure :
    PersonaState.mood_arc     : historique chronologique des transitions de mood
    PersonaState.energy       : niveau d'énergie courant [0.0, 1.0]
    PersonaState.relationships: map subject → ViewerRelationship (MappingProxyType)

Design :
    - frozen=True + slots=True : hashable, pas de mutation silencieuse.
    - MappingProxyType pour `relationships` : lecture seule côté consommers.
    - Cap `MAX_ARC_LEN` sur mood_arc : protège contre unbounded growth en DB.
    - Toutes les fonctions sont pures (entrée → sortie, pas d'effet de bord).
    - Les datetimes DOIVENT être timezone-aware (UTC) ; les naïfs sont rejetés.

Ce module n'importe rien de `shugu.*` — c'est une feuille pure.
"""
from __future__ import annotations

import types
from dataclasses import dataclass
from datetime import datetime
from typing import Mapping

# Nombre maximum d'entrées conservées dans mood_arc.
# Valeur choisie pour couvrir ~2h de stream à une transition / 2 min.
MAX_ARC_LEN: int = 60


# ── Structures de données ────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class MoodArcEntry:
    """Une transition de mood horodatée avec sa raison.

    Attributs :
        state  : label du mood (ex: "neutral", "happy", "frustrated").
        since  : horodatage UTC de la transition (timezone-aware obligatoire).
        reason : contexte lisible (ex: "viewer:alice_arrived", "silence_30s").

    Usage :
        entry = MoodArcEntry(state="happy", since=datetime.now(tz=timezone.utc),
                             reason="viewer:alice_arrived")
    """

    state: str
    since: datetime
    reason: str


@dataclass(frozen=True, slots=True)
class ViewerRelationship:
    """Relation persistante entre Shugu et un viewer spécifique.

    Attributs :
        subject     : clé identifiant le viewer ("viewer:<ip_hash>" ou "vip:<username>").
        trust       : confiance accumulée [0.0, 1.0] — gagnée par interactions positives.
        familiarity : familiarité [0.0, 1.0] — augmente avec le volume de messages.
        running_gags: tuple de phrases inside-jokes propres à ce viewer.

    Usage :
        rel = ViewerRelationship(
            subject="vip:alice",
            trust=0.6,
            familiarity=0.8,
            running_gags=("les patates", "café matcha"),
        )
    """

    subject: str
    trust: float
    familiarity: float
    running_gags: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PersonaState:
    """État adaptatif global de Shugu, persistent cross-sessions.

    Attributs :
        mood_arc      : tuple chronologique de MoodArcEntry (max MAX_ARC_LEN).
        energy        : niveau d'énergie courant [0.0, 1.0].
        relationships : mapping sujet → ViewerRelationship, wrappé en
                        MappingProxyType pour garantir l'immutabilité en lecture.

    Invariants :
        - mood_arc est un tuple (immuable).
        - relationships est toujours un MappingProxyType (pas un dict mutable).
        - energy est dans [0.0, 1.0].

    Usage :
        state = PersonaState(
            mood_arc=(MoodArcEntry("neutral", datetime.now(tz=timezone.utc), "init"),),
            energy=0.5,
            relationships={},
        )
    """

    mood_arc: tuple[MoodArcEntry, ...]
    energy: float
    relationships: Mapping[str, ViewerRelationship]

    def __post_init__(self) -> None:
        """Coerce les types mutables passés par le caller en types immutables.

        - dict → MappingProxyType pour relationships.
        - list → tuple pour mood_arc.
        Cela permet au caller de passer un dict ou une liste sans wrapper manuellement,
        tout en garantissant l'immutabilité interne.
        """
        # Coercion de relationships vers MappingProxyType
        if not isinstance(self.relationships, types.MappingProxyType):
            object.__setattr__(
                self, "relationships",
                types.MappingProxyType(dict(self.relationships)),
            )
        # Coercion de mood_arc vers tuple (si liste passée)
        if not isinstance(self.mood_arc, tuple):
            object.__setattr__(self, "mood_arc", tuple(self.mood_arc))


# ── Fonctions pures ──────────────────────────────────────────────────────────


def transition_mood(
    state: PersonaState,
    *,
    new_state: str,
    reason: str,
    now: datetime,
) -> PersonaState:
    """Ajoute une transition de mood en fin d'arc et applique le cap MAX_ARC_LEN.

    Paramètres :
        state     : état source (non muté).
        new_state : label du nouveau mood (ex: "happy", "frustrated").
        reason    : raison lisible de la transition.
        now       : horodatage UTC de la transition (doit être timezone-aware).

    Retourne un nouveau PersonaState avec l'entrée ajoutée.

    Lève :
        ValueError : si `now` est un datetime naïf (sans tzinfo).

    Usage :
        s1 = transition_mood(s0, new_state="happy",
                             reason="viewer:alice_arrived",
                             now=datetime.now(tz=timezone.utc))
    """
    if now.tzinfo is None:
        raise ValueError(
            f"transition_mood: `now` doit être timezone-aware (tzinfo != None), "
            f"reçu : {now!r}. Utiliser datetime.now(tz=timezone.utc)."
        )
    new_entry = MoodArcEntry(state=new_state, since=now, reason=reason)
    # Ajout en fin d'arc + cap pour éviter unbounded growth dans la DB JSONB.
    new_arc = (*state.mood_arc, new_entry)[-MAX_ARC_LEN:]
    return PersonaState(
        mood_arc=new_arc,
        energy=state.energy,
        relationships=state.relationships,
    )


def update_energy(state: PersonaState, *, delta: float) -> PersonaState:
    """Applique un delta d'énergie et clampe le résultat à [0.0, 1.0].

    Paramètres :
        state : état source (non muté).
        delta : variation signée (positif = gain, négatif = perte).

    Retourne un nouveau PersonaState avec energy mise à jour.

    Usage :
        s_tired   = update_energy(s0, delta=-0.3)
        s_energic = update_energy(s0, delta=+0.2)
    """
    new_energy = max(0.0, min(1.0, state.energy + delta))
    return PersonaState(
        mood_arc=state.mood_arc,
        energy=new_energy,
        relationships=state.relationships,
    )


def remember_viewer(
    state: PersonaState,
    *,
    subject: str,
    trust_delta: float = 0.05,
    familiarity_delta: float = 0.1,
) -> PersonaState:
    """Crée ou met à jour la relation avec un viewer, en clampant à [0.0, 1.0].

    Si le viewer est inconnu, crée une ViewerRelationship avec trust=trust_delta
    et familiarity=familiarity_delta (partant de 0). S'il existe déjà, applique
    les deltas incrémentaux.

    Paramètres :
        state             : état source (non muté).
        subject           : clé du viewer (ex: "viewer:abc123", "vip:alice").
        trust_delta       : incrément de confiance (défaut 0.05).
        familiarity_delta : incrément de familiarité (défaut 0.1).

    Retourne un nouveau PersonaState avec la relation mise à jour.

    Usage :
        s1 = remember_viewer(s0, subject="viewer:abc123", trust_delta=0.1)
    """
    existing = state.relationships.get(subject)
    if existing is None:
        new_rel = ViewerRelationship(
            subject=subject,
            trust=max(0.0, min(1.0, trust_delta)),
            familiarity=max(0.0, min(1.0, familiarity_delta)),
            running_gags=(),
        )
    else:
        new_rel = ViewerRelationship(
            subject=subject,
            trust=max(0.0, min(1.0, existing.trust + trust_delta)),
            familiarity=max(0.0, min(1.0, existing.familiarity + familiarity_delta)),
            running_gags=existing.running_gags,
        )
    new_relationships = {**dict(state.relationships), subject: new_rel}
    return PersonaState(
        mood_arc=state.mood_arc,
        energy=state.energy,
        relationships=new_relationships,
    )


def add_running_gag(
    state: PersonaState,
    *,
    subject: str,
    gag: str,
) -> PersonaState:
    """Ajoute un running gag au viewer indiqué si le gag n'existe pas déjà.

    Si le viewer n'existe pas encore dans relationships, il est créé avec des
    valeurs par défaut (trust=0.0, familiarity=0.0).

    Paramètres :
        state   : état source (non muté).
        subject : clé du viewer (ex: "vip:alice").
        gag     : phrase / inside-joke à mémoriser.

    Retourne un nouveau PersonaState. Si le gag est un doublon, retourne l'état
    tel quel (idempotent).

    Usage :
        s1 = add_running_gag(s0, subject="vip:alice", gag="les patates")
    """
    existing = state.relationships.get(subject)
    if existing is None:
        existing = ViewerRelationship(
            subject=subject,
            trust=0.0,
            familiarity=0.0,
            running_gags=(),
        )
    # Déduplication : on n'ajoute pas si déjà présent
    if gag in existing.running_gags:
        return state
    new_rel = ViewerRelationship(
        subject=subject,
        trust=existing.trust,
        familiarity=existing.familiarity,
        running_gags=(*existing.running_gags, gag),
    )
    new_relationships = {**dict(state.relationships), subject: new_rel}
    return PersonaState(
        mood_arc=state.mood_arc,
        energy=state.energy,
        relationships=new_relationships,
    )
