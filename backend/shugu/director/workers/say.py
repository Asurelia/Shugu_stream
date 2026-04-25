"""`SayWorker` — Phase E3 (interface partielle).

Effecteur du tag `[say_emotion:emotion]`. Phase E3 expose UNIQUEMENT le
broadcast du ton émotionnel — la synthèse TTS proprement dite (pipeline
`adapters/tts/*` + diffusion audio) reste OUT OF SCOPE et sera traitée en
Phase E4 (couplage avec l'orchestrator + ElevenLabs/Edge/MiniMax).

Le tag `[say_emotion:V]` indique au pipeline TTS futur quel ton appliquer
à la prochaine génération vocale. Le texte à dire arrive d'un autre canal
(la sortie LLM principale après strip des tags). Pour ne pas fragiliser
la pipeline existante, on broadcast juste l'émotion ici — le pipeline
TTS de E4 viendra écouter et choisir son preset voice.

Whitelist alignée sur `FaceWorker` : la cohérence ton facial / ton vocal
est l'effet recherché côté streamer.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from ..scene_state import SceneStateSnapshot
from .base import StateDelta, Worker

log = logging.getLogger(__name__)

#: Whitelist d'émotions vocales — alignée sur `FaceWorker.FACE_WHITELIST`
#: pour que les tags `[face:joy]` et `[say_emotion:joy]` aient le même set.
#: E4 enrichira potentiellement avec des nuances (`excited`, `whisper`...).
SAY_EMOTION_WHITELIST: frozenset[str] = frozenset({
    "neutral",
    "joy",
    "surprised",
    "sad",
    "angry",
    "thinking",
})


class SayWorker(Worker):
    """Tag l'émotion vocale pour le pipeline TTS — broadcast éphémère."""

    tag_name = "say_emotion"

    async def apply(
        self,
        tag_value: str,
        state: SceneStateSnapshot,
    ) -> StateDelta:
        slug = (tag_value or "").strip()
        if not slug or slug not in SAY_EMOTION_WHITELIST:
            log.warning(
                "director.worker_say_invalid",
                extra={"tag_value": tag_value, "available": sorted(SAY_EMOTION_WHITELIST)},
            )
            return StateDelta(patch={})

        await self._publish({
            "type": "scene.apply",
            "kind": "say_emotion",
            "id": slug,
            "ts": datetime.now(timezone.utc).isoformat(),
        })
        # Pas de patch : l'émotion vocale est consommée par le pipeline TTS
        # en E4 sans persister dans le snapshot.
        return StateDelta(patch={})
