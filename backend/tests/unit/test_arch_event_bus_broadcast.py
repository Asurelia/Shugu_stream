"""Test d'architecture : tous les topics publiés par L1/L3 sont broadcast Redis.

Régression P2 (review #45) : `world.delta` était publié par
`shugu/world/publisher.py` mais absent de `DEFAULT_BROADCAST_TOPICS` dans
`shugu/core/event_bus_factory.py`. En mode Redis multi-worker, les events
restaient intra-process → un viewer connecté à un autre worker manquait
les world deltas et drifty out-of-sync.

Le même bug existait pour `senses/bus.py` (mergé en L1.1) : il publie sur
`sense.<kind>` (kind ∈ {chat, voice, event, vision}) mais seul `sense.raw`
était broadcast.

Ce test scanne statiquement les helpers publish des layers L1 et L3 pour
extraire la liste des topics qu'ils utilisent, puis vérifie que tous sont
présents dans `DEFAULT_BROADCAST_TOPICS`. Toute future couche qui ajoute un
publisher sans mettre à jour la liste broadcast déclenchera ce test rouge.

Les topics sont déclarés explicitement ici (pas extraits par AST) parce
que :
- Les helpers publishers sont peu nombreux (~5) et stables.
- Une extraction AST devrait suivre les concaténations type
  `f"sense.{kind}"` ce qui demande de l'inférence sur les Literal — fragile.
- Le but du test est avant tout de **forcer le contributeur à mettre la
  liste à jour quand il ajoute un publisher**, pas de la dériver
  automatiquement.
"""
from __future__ import annotations

from shugu.core.event_bus_factory import DEFAULT_BROADCAST_TOPICS

# Topics produits par chaque layer du streamer IA. Mettre à jour quand un
# nouveau publisher est introduit dans senses/, world/, ou ailleurs.
LAYER_PUBLISHED_TOPICS: dict[str, set[str]] = {
    "L1 — senses/bus.publish_sense_event": {
        # SenseEvent.topic = f"sense.{kind}" pour kind ∈ SenseKind Literal.
        # Si SenseKind est étendu (cf. shugu/senses/types.py), ajouter ici.
        "sense.chat",
        "sense.voice",
        "sense.event",
        "sense.vision",
    },
    "L1 — memory/sense_publish.publish_sense_raw (legacy)": {
        # Helper antérieur déjà broadcast — on le garde dans le test pour
        # documenter qu'il est connu et couvert.
        "sense.raw",
    },
    "L3 — world/publisher.publish_world_delta": {
        "world.delta",
    },
}


def test_all_layer_published_topics_are_broadcast() -> None:
    """Chaque topic publié par L1/L3 doit être dans DEFAULT_BROADCAST_TOPICS.

    Sans cette garantie, en mode Redis multi-worker le topic reste
    intra-process et les subscribers d'autres workers ne reçoivent rien.
    """
    missing: dict[str, set[str]] = {}
    for layer, topics in LAYER_PUBLISHED_TOPICS.items():
        absent = topics - DEFAULT_BROADCAST_TOPICS
        if absent:
            missing[layer] = absent

    assert not missing, (
        "Topics publiés par un layer mais absents de DEFAULT_BROADCAST_TOPICS :\n"
        + "\n".join(
            f"  • {layer}: {sorted(topics)}"
            for layer, topics in missing.items()
        )
        + "\n\n"
        + "→ Mettre à jour `shugu/core/event_bus_factory.py::DEFAULT_BROADCAST_TOPICS`."
    )
