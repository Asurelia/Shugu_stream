"""Workers déterministes du Director — Phase E3.

Chaque worker correspond à un *kind* de tag inline émis par Shugu Soul (E2)
et exécute l'effet correspondant via un broadcast sur `editor:broadcast`
(topic Phase D) et un patch d'état sur le `SceneStateSnapshot`.

# Architecture

```text
LLM Soul (E2)  →  parse tags inline  →  for tag in tags:
                                          worker = workers[tag.kind]
                                          delta = await worker.apply(...)
                                          await store.update(delta.patch)
```

Le bus `editor:broadcast` est déjà cross-process (Redis pub/sub Phase D)
et déjà routé vers les opérators connectés via `/ws/editor`. Phase E3 ajoute
un payload `scene.apply` que le frontend (ViewerAdapter Phase F) consomme
pour piloter le viewer 3D.

# ADR — broadcast envelope (review point E3)

Phase D `_bus_forward_loop` filtre les events par `scene_id` (le UUID de
`scene_drafts`). Les workers Director n'ont pas de scene UUID — leur
`SceneStateSnapshot.scene` est un slug court ("main_talk", "gaming"…), pas
une PK SQLAlchemy. Trois options ont été examinées :

  (a) **Sentinel `scene_id="*"` + bypass `scene.apply` dans le forward loop**
      — minimal, les workers gardent l'API spec littérale (broadcast flat).
      Choix retenu : le bypass est un seul `if` côté forward loop,
      réversible en E4 si le contrat évolue.
  (b) Topic dédié `director:broadcast` — propre mais déclare un nouveau
      topic à `DEFAULT_BROADCAST_TOPICS`, et le frontend doit ouvrir une
      seconde route WS / topic. Coût > bénéfice MVP.
  (c) Tracker le scene UUID actif dans le snapshot — invasif, casse le
      contrat E1 (`scene` reste un slug compact pour le prompt).

Cf. `routes/editor_ws.py:_bus_forward_loop` pour l'implémentation du bypass.

# ADR — DI vs static registry (review point E3)

La spec littérale exposait `ALL_WORKERS = {"outfit": OutfitWorker(), ...}`
mais les workers ont besoin d'un `EventBus` pour publier — un `OutfitWorker()`
sans dépendances n'aurait nulle part où broadcast. On expose donc une
factory `make_workers(event_bus)` qui injecte la dépendance au boot
(`app.lifespan`). Ça reste un dict `tag_name -> Worker` côté usage,
strictement compatible avec l'orchestrator E2 prévu.
"""
from __future__ import annotations

from .anim import AnimWorker
from .base import (
    DIRECTOR_SCENE_ID_SENTINEL,
    EDITOR_BROADCAST_TOPIC,
    StateDelta,
    Worker,
)
from .camera import CameraWorker
from .face import FaceWorker
from .outfit import OutfitWorker
from .say import SayWorker
from .scene import SceneWorker
from .vfx import VfxWorker

__all__ = [
    "Worker",
    "StateDelta",
    "DIRECTOR_SCENE_ID_SENTINEL",
    "EDITOR_BROADCAST_TOPIC",
    "OutfitWorker",
    "VfxWorker",
    "AnimWorker",
    "FaceWorker",
    "SayWorker",
    "CameraWorker",
    "SceneWorker",
    "make_workers",
]


def make_workers(event_bus) -> dict[str, Worker]:
    """Construit le registry `tag_name -> Worker` avec la DI du bus.

    Appelé une fois côté `app.lifespan` quand l'`EventBus` est prêt.
    L'orchestrator E2 lookup ensuite `workers[tag.kind]` pour dispatcher.

    Le typage `event_bus` reste fluide pour éviter un import circulaire
    sur `core.protocols.EventBus` qui chargerait toute la dépendance
    `core/identity.py` au boot du module workers (ralentit les tests
    qui n'instancient que des workers isolés). Les usages réels passent
    par `make_event_bus()` côté `core.event_bus_factory`.
    """
    workers = (
        OutfitWorker(event_bus=event_bus),
        VfxWorker(event_bus=event_bus),
        AnimWorker(event_bus=event_bus),
        FaceWorker(event_bus=event_bus),
        SayWorker(event_bus=event_bus),
        CameraWorker(event_bus=event_bus),
        SceneWorker(event_bus=event_bus),
    )
    return {w.tag_name: w for w in workers}
