"""Twitch EventSub adapter — publie les chat messages Twitch sur sense.chat.

Architecture :
- ``TwitchSenseAdapter`` : classe qui reçoit des messages Twitch et les
  convertit en SenseEvent publiés sur sense.chat.
- Mode dev-mock : `feed_chat_message(username, text, ts)` — appelé directement
  par tests ou par un script CLI pour simuler du chat sans creds Twitch.
- Mode prod (futur) : `start()` ouvre une WS vers EventSub, écoute les
  events `channel.chat.message`, et appelle feed_chat_message en interne.

Décision design — split mock/prod :
La méthode publique testable est `feed_chat_message`. La méthode `start`
(prod) est un wrapper léger qui se connectera à EventSub et appellera
`feed_chat_message` à chaque event reçu. Cela permet :
- Tests TDD complets sans WebSocket Twitch.
- Activation prod = brancher start() au lifespan FastAPI quand les
  creds sont fournies.

Subject namespace : ``twitch:<username_lowercase>`` — pas de hash IP
(les usernames Twitch sont publics). Bénéfice : la mémoire L2 peut
naturellement tracker la familiarité par utilisateur Twitch.

Payload format : ``{"text": str, "platform": "twitch", "channel": str}``
Le champ ``platform`` permet au StageDirector de filtrer par source sans
parser le préfixe du subject.

Garde-fous :
- Username trimmed + lowercase pour matching cohérent.
- Text non-vide (skip + warning sur whitespace-only).
- Username vide → skip + warning (Twitch garantit username, mais defensive).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from ..core.protocols import EventBus
from ..senses.bus import publish_sense_event
from ..senses.types import SenseEvent

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TwitchSenseConfig:
    """Configuration du TwitchSenseAdapter.

    Paramètres
    ----------
    enabled :
        Feature flag opt-in. Si False, l'adapter est instancié mais inactif.
        Contrôlé via ``SHUGU_TWITCH_ENABLED`` (ou ``TWITCH_ENABLED``).
    channel :
        Slug du channel Twitch à écouter (ex: ``"mystream"``). Inclus dans
        le payload de chaque SenseEvent pour permettre le filtrage multi-canal.
        Phase 4.1 (futur) : auth credentials pour l'EventSub WS.
    """

    enabled: bool = False
    channel: str = ""


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class TwitchSenseAdapter:
    """Adapter Twitch EventSub → sense.chat.

    Convertit les messages chat Twitch en SenseEvent et les publie sur le
    topic ``sense.chat`` du bus injecté.

    Cycle de vie
    ------------
    1. ``__init__`` : injection du bus + config.
    2. ``await start()`` : Phase 4.0 = no-op avec log info (dev-mock only).
       Phase 4.1 (futur) : connexion WebSocket EventSub + subscribe.
    3. ``await feed_chat_message(username, text, ts)`` : méthode testable,
       appelée directement par les tests et (futur) par la WS EventSub.
    4. ``await stop()`` : nettoyage. Idempotent.

    Exemple d'usage (tests)
    -----------------------
    >>> config = TwitchSenseConfig(enabled=True, channel="mychan")
    >>> adapter = TwitchSenseAdapter(bus=bus, config=config)
    >>> await adapter.feed_chat_message("alice", "bonjour")
    """

    def __init__(self, *, bus: EventBus, config: TwitchSenseConfig) -> None:
        self._bus = bus
        self._config = config
        self._started: bool = False

    async def feed_chat_message(
        self,
        username: str,
        text: str,
        ts: Optional[datetime] = None,
    ) -> None:
        """Publie un message chat Twitch sur sense.chat.

        Normalisation :
        - ``username`` : trimmed + lowercase. Un username vide après normalisation
          → skip avec log warning (Twitch garantit toujours un username non-vide,
          mais cette défense évite des SenseEvent invalides si l'appelant fait
          une erreur).
        - ``text`` : trimmed. Un texte vide ou whitespace-only → skip avec log
          warning (messages inutiles à l'agent).

        Paramètres
        ----------
        username :
            Nom d'utilisateur Twitch (peut contenir des espaces en bordure ou
            des majuscules — normalisé ici).
        text :
            Contenu brut du message chat.
        ts :
            Horodatage UTC de réception. Si ``None``, utilise
            ``datetime.now(timezone.utc)`` au moment de l'appel.

        Comportement d'erreur
        ---------------------
        La publication sur le bus est best-effort via `publish_sense_event`
        (qui swallow les exceptions bus et log un warning). Cette méthode
        ne re-raise jamais en cas d'erreur bus.
        """
        username_clean = username.strip().lower()
        if not username_clean:
            log.warning(
                "twitch.feed_chat_message.skip_empty_username text_preview=%r",
                text[:50],
            )
            return

        text_clean = text.strip()
        if not text_clean:
            log.warning(
                "twitch.feed_chat_message.skip_empty_text username=%r",
                username_clean,
            )
            return

        event_ts = ts if ts is not None else datetime.now(timezone.utc)

        event = SenseEvent(
            kind="chat",
            subject=f"twitch:{username_clean}",
            payload={
                "text": text,  # text brut (non-stripped) — cohérent avec visitor_ws.py
                "platform": "twitch",
                "channel": self._config.channel,
            },
            ts=event_ts,
        )

        await publish_sense_event(self._bus, event)

    async def start(self) -> None:
        """Démarre l'adapter Twitch.

        Phase 4.0 (dev-mock only) :
            Log un message INFO contenant ``"dev_mock_only"`` et retourne
            immédiatement. Aucune connexion WebSocket n'est ouverte.
            Cette méthode existe pour garantir la symétrie API avec le
            wiring lifespan FastAPI futur.

        Phase 4.1 (futur, hors scope) :
            Connexion WebSocket EventSub + subscribe ``channel.chat.message``
            + appel ``feed_chat_message`` pour chaque event reçu.

        La méthode est idempotente : plusieurs appels consécutifs n'ont
        pas d'effet additionnel (le flag ``_started`` est vérifié).
        """
        if self._started:
            log.debug("twitch.start.already_started channel=%r", self._config.channel)
            return

        self._started = True
        log.info(
            "twitch.start dev_mock_only channel=%r — "
            "Phase 4.0: aucune connexion EventSub. "
            "Utiliser feed_chat_message() directement pour les tests.",
            self._config.channel,
        )

    async def stop(self) -> None:
        """Arrête l'adapter Twitch.

        Phase 4.0 : réinitialise le flag ``_started``. Idempotent — peut
        être appelé plusieurs fois sans effet ni exception.

        Phase 4.1 (futur) : ferme la connexion WebSocket EventSub proprement.
        """
        if not self._started:
            log.debug("twitch.stop.already_stopped channel=%r", self._config.channel)
            return
        self._started = False
        log.debug("twitch.stop channel=%r", self._config.channel)


__all__ = ["TwitchSenseAdapter", "TwitchSenseConfig"]
