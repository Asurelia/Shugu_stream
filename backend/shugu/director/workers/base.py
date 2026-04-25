"""Interface des workers déterministes du Director (Phase E3).

Chaque worker correspond à un *kind* de tag inline émis par Shugu Soul (E2) :
``[outfit:vip_fan]``, ``[vfx:confetti_gold]``, ``[anim:wave]``, ``[face:joy]``,
``[say_emotion:happy]``, ``[camera:close_up]``, ``[scene:gaming]``.

Le contrat est volontairement minimal :

- Un seul point d'entrée ``apply(tag_value, state) -> StateDelta`` ;
- Un broadcast déterministe sur le bus ``editor:broadcast`` (Phase D) ;
- Un ``StateDelta`` retourné qui encapsule la mutation à merger dans le
  `SceneStateSnapshot` côté `DirectorStateStore`.

Le LLM Soul reste l'unique âme — les workers ne sont qu'effecteurs. Aucune
logique conversationnelle, aucune décision de timing : juste exécuter le tag
parsé et mettre à jour l'état pour que le prompt suivant le voie.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from ..scene_state import SceneStateSnapshot

log = logging.getLogger(__name__)


# Sentinelle scene_id pour les broadcasts directorisés. Phase D
# `_bus_forward_loop` filtre normalement par scene_id ; les workers Director
# n'ont pas de scene UUID (le snapshot expose un slug court "main_talk", pas
# la PK `scene_drafts.id`), donc on utilise une wildcard et un bypass dédié
# côté forward loop pour les payloads `type == "scene.apply"`. Cf. ADR
# documenté en haut de `__init__.py`.
DIRECTOR_SCENE_ID_SENTINEL = "*"

# Topic Phase D réutilisé pour les broadcasts Director — c'est le même canal
# que celui utilisé par le Scene Editor WS (peer.joined, draft.update, etc.).
# Le payload `scene.apply` est différencié par son `type` côté forward loop.
EDITOR_BROADCAST_TOPIC = "editor:broadcast"


@dataclass(slots=True, frozen=True)
class StateDelta:
    """Mutation à appliquer au snapshot après l'action worker.

    `patch` est un shallow-merge dict que `DirectorStateStore.update()` sait
    consommer. Un dict vide `{}` signale "aucune mutation persistante" — utile
    pour les workers éphémères (anim, say_emotion) dont l'effet est observable
    seulement le temps du broadcast.
    """

    patch: dict = field(default_factory=dict)


class Worker(ABC):
    """Interface abstraite des workers déterministes du Director.

    Sous-classes concrètes :
    `OutfitWorker`, `VfxWorker`, `AnimWorker`, `FaceWorker`, `SayWorker`,
    `CameraWorker`, `SceneWorker`. Chacune définit son `tag_name` (clé du tag
    inline parsé : "outfit", "vfx", ...) et implémente `apply()`.

    L'`event_bus` est injecté au constructeur (DI explicite) — la factory
    `make_workers()` se charge de l'instancier avec le bus actif côté
    `app.lifespan`. Cf. `__init__.py` pour le rationale.
    """

    #: Nom du tag inline traité par ce worker (ex: "outfit", "vfx", ...).
    tag_name: str = ""

    def __init__(self, event_bus) -> None:
        # Type fluide volontairement (`shugu.core.protocols.EventBus` est un
        # Protocol, pas une classe importable circulairement ici). Le typage
        # est validé par mypy/ruff via les usages côté tests + factory.
        self._event_bus = event_bus

    @abstractmethod
    async def apply(
        self,
        tag_value: str,
        state: SceneStateSnapshot,
    ) -> StateDelta:
        """Exécute l'action correspondant au tag et retourne le delta à merger.

        Implémentations :
        - Validation du `tag_value` contre `state.assets_available[<bank>]`
          (ou whitelist hardcodée pour les workers à domaine fini : face,
          camera) — un tag invalide retourne `StateDelta()` vide + log
          warning, sans exception (le pipeline LLM ne doit pas crasher sur
          un slug halluciné).
        - Broadcast sur `editor:broadcast` avec le payload `scene.apply`.
        - Construction du `StateDelta` cohérent avec la sémantique du worker.
        """

    async def _publish(self, payload: dict) -> None:
        """Publie un envelope sur le bus pour livrer `payload` aux clients WS.

        L'enveloppe utilise le sentinel `DIRECTOR_SCENE_ID_SENTINEL` ; le
        forward loop éditeur la livre à toutes les sockets actives quand le
        payload interne est typé `scene.apply` (bypass dédié dans
        `_bus_forward_loop`).

        Une exception côté bus est swallow + log warning (même pattern que
        `wiring.publish_chat_trigger`) : un broadcast raté ne doit JAMAIS
        casser le pipeline orchestrator.
        """
        envelope = {
            "scene_id": DIRECTOR_SCENE_ID_SENTINEL,
            "origin": "director",
            "payload": payload,
        }
        try:
            await self._event_bus.publish(EDITOR_BROADCAST_TOPIC, envelope)
        except Exception as exc:
            log.warning(
                "director.worker_publish_failed",
                extra={
                    "tag": self.tag_name,
                    "payload_type": payload.get("type"),
                    "error": repr(exc),
                },
            )
