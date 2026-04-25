"""Helpers de wiring — publient sur le `TriggerBus` derrière le feature flag.

Séparés dans un module dédié pour éviter que `visitor_ws.py` / `operator_ws.py`
connaissent le bus : ils appellent `publish_chat_trigger(...)` au tail du
handler et c'est tout. Si le flag `director_enabled` est OFF, la fonction
retourne immédiatement — aucun coût, aucun side-effect.
"""
from __future__ import annotations

import logging

from ..config import Settings
from .triggers import TriggerBus, TriggerEvent, get_trigger_bus

log = logging.getLogger(__name__)


async def publish_chat_trigger(
    *,
    settings: Settings,
    sender: str,
    text: str,
    bus: TriggerBus | None = None,
) -> None:
    """Publie un event `chat` + optionnellement `vip_arrival` si VIP.

    - Gate `settings.director_enabled` : retour immédiat si OFF.
    - `settings.vip_usernames` est déjà normalisé (lower+strip) par le
      validator de Settings — on peut donc matcher un `sender.lower()`
      directement.
    - Une exception côté bus (très rare : subscriber cassé) est loguée
      en warning mais ne remonte PAS : ne jamais casser le handler chat
      principal à cause du Director.

    Le paramètre `bus` permet aux tests d'injecter un bus dédié ; en prod
    on retombe sur le singleton `get_trigger_bus()`.
    """
    if not settings.director_enabled:
        return
    target_bus = bus if bus is not None else get_trigger_bus()

    sender_lc = (sender or "").strip().lower()
    if not sender_lc:
        return

    try:
        await target_bus.publish(TriggerEvent(
            kind="chat",
            payload={"sender": sender_lc, "text": text},
        ))
        if sender_lc in set(settings.vip_usernames):
            await target_bus.publish(TriggerEvent(
                kind="vip_arrival",
                payload={"sender": sender_lc},
            ))
    except Exception as exc:
        # On log mais on ne re-raise pas : Director ne doit jamais casser
        # le chat. Phase E1 privilégie la stabilité runtime sur la
        # complétude des triggers.
        log.warning(
            "director.chat_trigger_failed",
            extra={"sender": sender_lc, "error": repr(exc)},
        )


async def publish_scene_change_trigger(
    *,
    settings: Settings,
    slug: str,
    extra: dict | None = None,
    bus: TriggerBus | None = None,
) -> None:
    """Publie un event `scene_change` si le Director est actif.

    `extra` est mergé dans le payload (useful pour relayer un config dict
    du topic `stage`). `slug` reste la clé canonique.
    """
    if not settings.director_enabled:
        return
    target_bus = bus if bus is not None else get_trigger_bus()

    payload: dict = {"slug": slug}
    if extra:
        for k, v in extra.items():
            if k != "slug":
                payload[k] = v

    try:
        await target_bus.publish(TriggerEvent(kind="scene_change", payload=payload))
    except Exception as exc:
        log.warning(
            "director.scene_change_trigger_failed",
            extra={"slug": slug, "error": repr(exc)},
        )
