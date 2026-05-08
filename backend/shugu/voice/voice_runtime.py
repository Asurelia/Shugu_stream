"""Container runtime partagé entre lifespan FastAPI et worker LiveKit (D-5).

Pourquoi ce module existe
-------------------------

Le sprint integration voice↔body doit relier trois processus de vie séparés :

1. **Lifespan FastAPI** (``app.py``) — instancié au boot, vit jusqu'au shutdown.
   C'est ici qu'on construit ``app.state.director_workers`` via ``make_workers``,
   qui doit recevoir un ``audio_clock_provider`` lisant
   ``bridge.chunk_started_at_ms``.

2. **Voice worker** (``livekit_agent.entrypoint``) — invoqué par
   ``AgentServer.from_server_options(...).run()`` lancé en asyncio task au
   lifespan. Avec ``livekit-agents 1.5.5``, le default
   ``WorkerOptions.job_executor_type`` est ``THREAD`` — le worker tourne
   donc dans LE MÊME process que FastAPI. Pas besoin de Redis IPC.

3. **Job entrypoint** (par appel à ``ctx`` dans ``entrypoint``) — créé à chaque
   nouvelle session voice. C'est ici qu'on instancie le ``LiveKitPublisher``
   et l'``AudioBridge`` (ils requièrent ``ctx.room`` qui n'existe pas avant).

L'objectif : permettre au lifespan de configurer son ``audio_clock_provider``
**avant** que le bridge n'existe, sans dépendre d'un import circulaire ni d'un
mécanisme de pub/sub externe.

Solution : un container léger ``VoiceRuntimeState`` créé une fois au lifespan,
référencé par le worker via ``partial(entrypoint, voice_runtime=...)``.
L'entrypoint pose le bridge dans le container quand il l'instancie, et le
``audio_clock_provider`` lit ce container à chaque appel — race-free grâce à
l'atomicité d'une lecture/écriture single-attribute en CPython (le GIL
sérialise les ``LOAD_ATTR`` / ``STORE_ATTR`` sur un même objet).

Threading model
---------------

Le worker LiveKit étant THREAD-based (cf. ``livekit-agents`` 1.5.5 default),
les écritures sur ``VoiceRuntimeState`` se font depuis le **thread du job
LiveKit** (jobs runnent dans des worker threads, pas dans la loop FastAPI),
tandis que les lectures du ``audio_clock_provider`` se font depuis les
Workers Director sur la **loop asyncio FastAPI**. Donc lecture et écriture
sont cross-thread.

La sécurité ne vient PAS de "même event loop" : elle vient du **GIL
CPython** qui sérialise les bytecodes ``LOAD_ATTR`` et ``STORE_ATTR`` sur
un single-attribute. Une lecture concurrente avec une écriture verra soit
l'ancienne valeur soit la nouvelle — jamais un état corrompu — sans lock.

Si à terme on bascule sur ``JobExecutorType.PROCESS``, ce module devra être
remplacé par un pattern Redis/pub-sub (cf. ``docs/ops/voice-body-wiring-audit-2026-05-08.md``
§2.4 Option a) — le GIL ne traverse pas les frontières de processus, donc
les attributs Python ne seraient plus partagés. À ce moment-là, le
``audio_clock_provider`` deviendra un appel Redis ``GET`` (drift potentiel
+50 ms).

Spec : ``docs/specs/2026-05-08-voice-body-pipeline-design.md`` §3.1, §6.2.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

import structlog

if TYPE_CHECKING:
    from .audio_bridge import AudioBridge

log = structlog.get_logger(__name__)


class VoiceRuntimeState:
    """Container thread-safe pour partager l'état runtime voice entre lifespan et worker.

    Instancié une fois au lifespan (``app.py``), référencé via
    ``partial(entrypoint, voice_runtime=...)`` pour que le worker LiveKit
    puisse y poser le ``bridge`` actif. Les workers Director (face/say) lisent
    ``chunk_started_at_ms`` à chaque émission de payload pour enrichir
    ``audio_at_ms`` (synchro audio↔anim spec §7.2).

    Lifecycle :
        - Boot lifespan : ``state = VoiceRuntimeState()``  → ``bridge=None``
        - Job start     : ``state.bridge = bridge``        → bridge actif
        - Job end       : ``state.bridge = None``          → reset (autre job pourra remplacer)
        - Shutdown      : ``state.bridge = None``          → cleanup final

    Le ``bridge`` peut être réassigné (un job se termine, un autre démarre)
    sans recréer le container — les workers Director gardent la même
    référence ``audio_clock_provider`` valide pour toute la durée du process.
    """

    __slots__ = ("_bridge",)

    def __init__(self) -> None:
        """Init sans bridge actif. ``audio_clock_provider`` retournera ``None``
        tant que ``bridge`` n'est pas posé par l'entrypoint."""
        self._bridge: Optional["AudioBridge"] = None

    @property
    def bridge(self) -> Optional["AudioBridge"]:
        """Bridge audio actif (ou ``None`` si aucun job voice en cours).

        Single-attribute read en CPython → atomique sans lock.
        """
        return self._bridge

    @bridge.setter
    def bridge(self, value: Optional["AudioBridge"]) -> None:
        """Pose ou reset le bridge actif.

        Appelé par ``entrypoint`` au démarrage d'un job (set bridge) et au
        shutdown du job (reset à None). Single-attribute write en CPython →
        atomique sans lock.
        """
        previous = self._bridge
        self._bridge = value
        # Log uniquement les transitions significatives — éviter le bruit si
        # même bridge est posé deux fois (idempotence test-only).
        if (previous is None) != (value is None):
            log.info(
                "voice.runtime.bridge_changed",
                active=value is not None,
            )

    def chunk_started_at_ms(self) -> Optional[int]:
        """Provider injecté à ``make_workers(audio_clock_provider=...)``.

        Lit le ``chunk_started_at_ms`` du bridge actif. Retourne ``None`` si :
        - aucun bridge n'est posé (pas de job voice actif),
        - le bridge n'a pas encore publié de PCM,
        - une chunk vient d'être ``unpublish()`` (barge-in en cours),

        Dans tous ces cas, les workers Director (face/say) omettent ``audio_at_ms``
        du payload — comportement legacy compatible spec §6.2 (le frontend
        applique l'event immédiatement à réception).
        """
        bridge = self._bridge
        if bridge is None:
            return None
        return bridge.chunk_started_at_ms
