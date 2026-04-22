"""VIP voice agent — LiveKit Agents Worker (process séparé).

Lancé comme 4e service par `ops/start-shugu.ps1` via :

    python -m shugu.adapters.vip_agent dev     # foreground avec logs
    python -m shugu.adapters.vip_agent start   # production (auto-restart)

## Architecture (Phase 3a MVP)

LiveKit Agents veut que le Worker tourne dans son propre process, pas
embedded dans FastAPI — c'est le pattern officiel (crash isolation,
signal handling, multi-job concurrency). Donc on ne fait PAS de
`asyncio.create_task()` dans le lifespan FastAPI : on spawn un process
Python à côté.

Le backend FastAPI interagit avec le Worker uniquement via :
  - La LiveKit API Dispatch (`AgentDispatchService.create_dispatch`) que
    `routes/livekit_api.py` appelle quand un VIP mint un token.
  - Le `settings` sont lus depuis `ops/env/.env` par Pydantic-Settings
    (partagé avec le backend, même `USER_JWT_SECRET` etc.).

## Ce qui marche

- STT Whisper local (via `ShuguWhisperSTT` + Silero VAD)
- LLM MiniMax M2.7 via endpoint OpenAI-compat
- TTS MiniMax cloned voice (cohérent avec broadcast public)
- Greeting automatique au join du participant
- Barge-in natif LiveKit

## État Phase 1 fondation (autonomous streamer)

- ✅ **Bridge events one-way** via `VipBridgeClient` → `/internal/vip/event`
  (HTTP localhost signé). Émissions : `participant_joined`, `session_started`,
  `session_ended`. La future Régie Phase 3 subscribe au topic `vip.events`
  pour arbitrer entre VIP voice / chat public / ambient.

## TODO (Phase 2+)

- Câbler les `function_tool` qui délèguent à `BodyRouter` via
  `VipBridgeClient.invoke_tool("body.gesture", ...)`. Le backend côté
  `/internal/vip/tool` retourne déjà 501 pour `body.*` — Phase 2 branchera.

- Mémoire contextuelle : charger `vip/<username>.md` depuis la table
  `memory_facts` via `MemoryAgent.recall(subject="vip:<username>")` — Phase 2
  quand `memory_enabled=True`.

- Session log (`vip_session_log` table) — Phase 5.
"""
from __future__ import annotations

import asyncio
import time

import httpx
import structlog
from livekit import agents
from livekit.agents import Agent, AgentSession, JobContext, WorkerOptions, cli
from livekit.plugins import minimax as lk_minimax
from livekit.plugins import openai as lk_openai
from livekit.plugins import silero

from ..config import get_settings
from ..core.vip_bridge import VipEventIn
from .stt_livekit_adapter import ShuguWhisperSTT
from .stt_streaming import FasterWhisperSTT, STTSettings
from .vip_bridge_client import VipBridgeClient

log = structlog.get_logger(__name__)


VIP_SYSTEM_PROMPT = """\
Tu es Shugu, en conversation vocale privée avec un abonné VIP.
Cette conversation n'est PAS diffusée publiquement — sois plus intime,
directe, et plus personnelle que dans tes interactions publiques.

Règles :
  - Réponds en 1-2 phrases courtes. Pas de monologue.
  - Pose des questions à ton interlocuteur, intéresse-toi réellement à lui.
  - Reste dans ton personnage : tu es Shugu, pas un assistant IA.
  - Si on te demande quelque chose qui nécessiterait la régie scène
    publique, explique gentiment que tu ne contrôles pas cela depuis le
    salon VIP privé.

Tu parles français par défaut, mais tu peux t'adapter à la langue de ton
interlocuteur.
"""


async def _safe_emit(bridge: VipBridgeClient, event: VipEventIn) -> None:
    """Émet un event au backend en swallow-mode : on ne veut JAMAIS qu'un
    backend KO interrompe la conversation VIP en cours.

    Log-only sur échec. Le client fait déjà 3 retries avec backoff ; arrivé
    ici avec exception, on accepte qu'on a perdu cet event et on continue.
    """
    try:
        await bridge.emit_event(event)
    except Exception as exc:
        log.warning(
            "vip_agent.bridge_emit_failed",
            kind=event.kind, room=event.room, error=str(exc),
        )


async def _entrypoint(ctx: JobContext) -> None:
    """Appelé par le Worker pour chaque room où un VIP se connecte.

    Flow Phase 1 :
    1. Connecter à la room LiveKit.
    2. Attendre le participant (timeout 60s).
    3. Émettre `participant_joined` au backend (bridge HTTP).
    4. Setup STT/LLM/TTS + Agent + AgentSession.
    5. Émettre `session_started` après `session.start()`.
    6. Générer le greeting initial.
    7. **Finally** : émettre `session_ended` + close httpx client, quel que
       soit le chemin (timeout, exception, disconnect normal).

    Les émissions bridge sont en mode swallow-on-error — si le backend est
    down, le VIP peut continuer à parler avec Shugu, on loggue simplement.
    """
    settings = get_settings()

    # Client HTTP pour le bridge backend. Une instance par room — on la
    # referme en finally pour éviter les sockets orphelins sur long run.
    http_for_bridge = httpx.AsyncClient()
    bridge = VipBridgeClient(
        base_url=settings.vip_internal_url,
        secret=settings.vip_internal_secret,
        http=http_for_bridge,
    )

    await ctx.connect()
    room_name = ctx.room.name
    vip_username = "unknown"
    log.info("vip_agent.room_connected", room=room_name)

    try:
        try:
            participant = await ctx.wait_for_participant(timeout=60.0)
        except asyncio.TimeoutError:
            log.warning("vip_agent.no_participant_timeout", room=room_name)
            return

        vip_username = participant.identity or "unknown"
        log.info("vip_agent.participant_joined", room=room_name, user=vip_username)

        # Notify backend : `vip.events` topic → la Régie Phase 3 pourra
        # arbitrer entre VIP voice / chat public / ambient.
        await _safe_emit(bridge, VipEventIn(
            kind="participant_joined",
            room=room_name,
            user=vip_username,
            ts_ns=time.time_ns(),
        ))

        whisper = FasterWhisperSTT(STTSettings(
            model_name=settings.stt_model,
            compute_type=settings.stt_compute_type,
            device=settings.stt_device,
            language=settings.stt_language,
        ))

        vad = silero.VAD.load()

        session = AgentSession(
            vad=vad,
            stt=agents.stt.StreamAdapter(
                stt=ShuguWhisperSTT(whisper, language=settings.stt_language),
                vad=vad,
            ),
            llm=lk_openai.LLM(
                api_key=settings.minimax_api_key,
                base_url=settings.minimax_base_url,
                model=settings.minimax_model,
            ),
            tts=lk_minimax.TTS(
                api_key=settings.minimax_api_key,
                voice_id=settings.minimax_voice_id,
                model=settings.minimax_tts_model,
            ),
        )

        agent = Agent(instructions=VIP_SYSTEM_PROMPT)

        await session.start(room=ctx.room, agent=agent)
        log.info("vip_agent.session_started", room=room_name, user=vip_username)
        await _safe_emit(bridge, VipEventIn(
            kind="session_started",
            room=room_name,
            user=vip_username,
            ts_ns=time.time_ns(),
        ))

        # Greeting : le LLM compose une phrase d'accueil, le TTS la joue.
        await session.generate_reply(
            instructions=f"Dis bonjour à {vip_username} chaleureusement en UNE phrase. "
                         "Puis pose-lui une question ouverte pour qu'il se lance.",
        )
    finally:
        # `session_ended` est TOUJOURS émis — même sur timeout/exception/disconnect.
        # Permet à la Régie Phase 3 de savoir que la room est dispo pour
        # re-balance les priorités (ex: faire remonter l'ambient au tier idle).
        await _safe_emit(bridge, VipEventIn(
            kind="session_ended",
            room=room_name,
            user=vip_username,
            ts_ns=time.time_ns(),
        ))
        await http_for_bridge.aclose()


def _build_worker_options() -> WorkerOptions:
    """`agent_name` est important : notre Worker n'accepte QUE les dispatches
    explicites envoyés par `routes/livekit_api.py`. Sans ça, le Worker
    prendrait TOUTES les rooms de l'account LiveKit automatiquement.
    """
    return WorkerOptions(
        entrypoint_fnc=_entrypoint,
        agent_name="shugu-vip",
    )


if __name__ == "__main__":
    # `cli.run_app(opts)` lit LIVEKIT_URL/API_KEY/API_SECRET depuis env,
    # se connecte au serveur, et tourne en boucle jusqu'à Ctrl+C.
    # Lu depuis .env car Pydantic-Settings charge déjà les vars globales.
    settings = get_settings()
    import os
    if settings.livekit_url:
        os.environ.setdefault("LIVEKIT_URL", settings.livekit_url)
    if settings.livekit_api_key:
        os.environ.setdefault("LIVEKIT_API_KEY", settings.livekit_api_key)
    if settings.livekit_api_secret:
        os.environ.setdefault("LIVEKIT_API_SECRET", settings.livekit_api_secret)

    cli.run_app(_build_worker_options())
